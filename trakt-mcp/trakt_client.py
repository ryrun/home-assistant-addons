"""Read-only Trakt API v2 client. OAuth POSTs live separately in auth.py."""
import asyncio
from functools import wraps
import json
import logging
import re
import time
import sqlite3

import httpx

from errors import TraktError, check_response, json_data
from http_utils import bounded_request, retry_after, API_CONCURRENCY
from personal_cache import PersonalSnapshots

API_URL = 'https://api.trakt.tv'
MAX_PAGES = 200


def movie_id(value):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]{0,199}', value):
        raise TraktError('Film-ID muss eine Trakt-ID, IMDb-ID oder ein Trakt-Slug sein.')
    return value


def genres_value(genres):
    if genres and (len(genres) > 20 or any(not re.fullmatch(r'[a-z][a-z-]{0,49}', g) for g in genres)):
        raise TraktError('Genres als Trakt-Slugs angeben, z. B. science-fiction.')
    return ','.join(genres or [])


def consistent_account(function):
    @wraps(function)
    async def wrapped(self, *args, **kwargs):
        identity = await self.auth.access_token() if self.auth is not None else None
        result = await function(self, *args, **kwargs)
        if identity is not None and identity != await self.auth.access_token():
            raise TraktError('Trakt authorization changed during the operation. Retry.')
        return result
    return wrapped


class TraktClient:
    def __init__(self, http, auth, client_id, cache=None, personal_cache=False, metrics=None):
        self.http, self.auth = http, auth
        self.metrics = metrics
        self.headers = {'trakt-api-version': '2', 'trakt-api-key': client_id,
                        'User-Agent': 'HomeAssistant-TraktMCP/0.2.0'}
        self.cache = cache
        self.snapshots = PersonalSnapshots(self) if personal_cache else None
        self.cache_locks = [asyncio.Lock() for _ in range(32)]
        self.request_slots = asyncio.Semaphore(API_CONCURRENCY)
        self.rate_limit_until = 0

    async def get(self, path, params=None, personal=False):
        if personal or self.cache is None or self.cache.ttl == 0:
            return await self._fetch(path, params, personal)
        key = json.dumps([path, sorted((params or {}).items())], separators=(',', ':'))
        # Fixed-size lock stripes coalesce concurrent identical public requests.
        async with self.cache_locks[hash(key) % len(self.cache_locks)]:
            try:
                cached = await self.cache.get(key)
            except (sqlite3.Error, OSError, ValueError):
                cached = None
                logging.getLogger('trakt_mcp').warning('Öffentlicher Cache nicht lesbar; frage Trakt direkt ab.')
            if cached is not None:
                return cached
            generation = self.cache.generation
            response = await self._fetch(path, params, personal=False)
            json_data(response)  # Never cache malformed JSON or upstream errors.
            try:
                await self.cache.put(key, response, ttl=300 if path.endswith('/trending') else None, generation=generation)
            except (sqlite3.Error, OSError):
                logging.getLogger('trakt_mcp').warning('Öffentlicher Cache nicht beschreibbar.')
            return response

    async def _fetch(self, path, params=None, personal=False):
        headers = dict(self.headers)
        if personal:
            headers['Authorization'] = 'Bearer ' + await self.auth.access_token()
        async def request():
            for attempt in range(2):
                remaining = self.rate_limit_until - time.monotonic()
                if remaining > 0:
                    raise TraktError(f'Trakt-Rate-Limit aktiv. In {int(remaining) + 1} Sekunden erneut versuchen.')
                try:
                    async with self.request_slots:
                        remaining = self.rate_limit_until - time.monotonic()
                        if remaining > 0:
                            raise TraktError(f'Trakt rate limit active. Retry in {int(remaining) + 1} seconds.')
                        response = await bounded_request(self.http, 'GET', API_URL + path, params=params, headers=headers,
                                                         metrics=self.metrics, service='trakt')
                except httpx.RequestError:
                    if attempt == 0:
                        await asyncio.sleep(0.25)
                        continue
                    raise TraktError('Trakt nicht erreichbar oder Zeitüberschreitung. Bitte erneut versuchen.') from None
                if response.status_code == 429:
                    seconds = retry_after(response.headers)
                    self.rate_limit_until = time.monotonic() + seconds
                    raise TraktError(f'Trakt-Rate-Limit erreicht. In {seconds} Sekunden erneut versuchen.')
                if response.status_code in (502, 503, 504) and attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
                return response
        response = await request()
        if response.status_code == 401 and personal:
            rejected = headers['Authorization'][7:]
            headers['Authorization'] = 'Bearer ' + await self.auth.access_token(rejected)
            response = await request()
        check_response(response)
        return response

    async def page(self, path, page=1, limit=100, params=None, personal=False):
        response = await self.get(path, {**(params or {}), 'page': page, 'limit': limit, 'extended': 'full'}, personal)
        if personal:
            self._check_personal_pagination(response, path)
        return self._decode_page(response, page, limit)

    @staticmethod
    def _check_personal_pagination(response, path):
        if any(segment in path for segment in ('/watchlist/', '/favorites/')) and 'X-Pagination-Page-Count' not in response.headers:
            raise TraktError('Pagination metadata missing from a personal list; completeness cannot be verified.')

    @staticmethod
    def _decode_page(response, page, limit, full=False):
        items = json_data(response)
        if not isinstance(items, list):
            raise TraktError('Unerwartetes Trakt-Datenformat.')
        try:
            # Non-paginated endpoints (notably sync/watched) return the entire dataset.
            pages = int(response.headers.get('X-Pagination-Page-Count', 1))
            current = int(response.headers.get('X-Pagination-Page', page))
            size = int(response.headers.get('X-Pagination-Limit', limit))
            total = int(response.headers.get('X-Pagination-Item-Count', len(items)))
        except ValueError:
            raise TraktError('Ungültige Trakt-Pagination.') from None
        if current != page or pages < 0 or total < 0 or size < 0 or (items and (size == 0 or pages == 0)):
            raise TraktError('Inkonsistente Trakt-Pagination; vollständige Ergebnisse nicht sichergestellt.')
        if not items and page < pages:
            raise TraktError('Leere Trakt-Seite vor Listenende; vollständige Ergebnisse nicht sichergestellt.')
        if 'X-Pagination-Page-Count' not in response.headers:
            total = len(items)
            pages = 1 if full else (total + limit - 1) // limit
            if not full:
                items = items[(page - 1) * limit:page * limit]
        return {'items': items, 'page': current, 'page_count': pages, 'limit': size,
                'total_items': total, 'next_page': page + 1 if page < pages else None}

    async def all_items(self, path):
        if self.snapshots:
            items, _ = await self.snapshots.load(path)
            return items
        return await self._all_items_live(path)

    async def _all_items_live(self, path, extended=False):
        items = []
        expected_total = None
        transferred = 0
        for page in range(1, MAX_PAGES + 1):
            response = await self.get(path, {'page': page, 'limit': 100, **({'extended': 'full'} if extended else {})}, personal=True)
            self._check_personal_pagination(response, path)
            transferred += len(response.content)
            if transferred > 16 * 1024 * 1024:
                raise TraktError('Personal sync exceeds the 16 MiB transfer budget. Narrow the request or disable full-list operations.')
            result = self._decode_page(response, page, 100, full=True)
            if 'X-Pagination-Item-Count' in response.headers:
                if expected_total is not None and result['total_items'] != expected_total:
                    raise TraktError('Persönliche Liste während des Abrufs geändert. Bitte erneut versuchen.')
                expected_total = result['total_items']
            items.extend(result['items'])
            if result['next_page'] is None:
                if expected_total is not None and len(items) != expected_total:
                    raise TraktError('Persönliche Liste unvollständig. Bitte erneut versuchen.')
                return items
        raise TraktError('Persönliche Liste überschreitet das Sicherheitslimit; Ausschluss wäre unvollständig.')

    async def personal_page(self, path, page, limit, year=None, genres=None):
        if not self.snapshots:
            params = {}
            if year is not None:
                params['years'] = str(year)
            if genres:
                params['genres'] = genres_value(genres)
            return await self.page(path, page, limit, params, personal=True)
        genres_value(genres)
        items, stamp = await self.snapshots.load(path)
        if year is not None or genres:
            items = [item for item in items if
                     (year is None or item.get('movie', {}).get('year') == year) and
                     (not genres or set(genres).intersection(item.get('movie', {}).get('genres') or []))]
        total = len(items)
        pages = (total + limit - 1) // limit
        return {'items': items[(page - 1) * limit:page * limit], 'page': page, 'limit': limit,
                'page_count': pages, 'total_items': total, 'next_page': page + 1 if page < pages else None,
                'freshness': {'validation': 'trakt:/sync/last_activities', 'activity_at': stamp}}

    async def watched(self, page=1, limit=100):
        return await self.personal_page('/sync/watched/movies', page, limit)

    async def ratings(self, page=1, limit=100):
        return await self.personal_page('/sync/ratings/movies', page, limit)

    async def watchlist(self, page=1, limit=100, year=None, genres=None):
        return await self.personal_page('/users/me/watchlist/movies/added', page, limit, year, genres)

    async def search(self, query, year=None, limit=10):
        params = {'query': query}
        if year is not None:
            params['years'] = str(year)
        return await self.page('/search/movie', limit=limit, params=params)

    async def details(self, identifier):
        return json_data(await self.get('/movies/' + movie_id(identifier), {'extended': 'full'}))

    async def ratings_summary(self, identifier):
        identifier = movie_id(identifier)
        data = json_data(await self.get('/movies/' + identifier + '/ratings', {'extended': 'all'}))
        if not isinstance(data, dict):
            raise TraktError('Invalid Trakt movie ratings response.')
        sources = {}
        fields = ('rating', 'votes', 'link', 'distribution', 'user_rating', 'state', 'user_state')
        for name in ('trakt', 'imdb', 'metascore', 'rotten_tomatoes', 'letterboxd', 'mal', 'tmdb'):
            value = data.get(name)
            if name == 'trakt' and value is None and any(k in data for k in ('rating', 'votes', 'distribution')):
                value = {k: data[k] for k in ('rating', 'votes', 'distribution') if k in data}
            if value is not None and not isinstance(value, dict):
                raise TraktError('Invalid Trakt movie ratings response.')
            sources[name] = {k: value[k] for k in fields if k in value} if value is not None else None
        return {'movie_id': identifier, 'ratings': sources,
                'scales': {'trakt': 10, 'imdb': 10, 'metascore': 100, 'rotten_tomatoes': 100,
                           'letterboxd': 5, 'mal': 10, 'tmdb': 10},
                'source': 'trakt:/movies/' + identifier + '/ratings?extended=all',
                'note': 'Community/external scores supplied by Trakt, not your personal ratings. '
                        'Original scales are preserved; Rotten Tomatoes rating is critics and user_rating is audience. '
                        'Missing/null values are unknown, not zero. No external rating sites are queried.'}

    async def people(self, identifier, limit=50, offset=0):
        data = json_data(await self.get('/movies/' + movie_id(identifier) + '/people'))
        if not isinstance(data, dict):
            raise TraktError('Invalid movie credits response.')
        entries = [dict(item, department='cast') for item in data.get('cast') or []]
        for department, items in (data.get('crew') or {}).items():
            entries.extend(dict(item, department=department) for item in items)
        return {'items': entries[offset:offset + limit], 'total_items': len(entries), 'offset': offset,
                'limit': limit, 'next_offset': offset + limit if offset + limit < len(entries) else None}

    async def related(self, identifier, page=1, limit=10):
        return await self.page('/movies/' + movie_id(identifier) + '/related', page, limit)

    async def favorites(self, page=1, limit=100):
        return await self.personal_page('/users/me/favorites/movies/rank', page, limit)

    @consistent_account
    async def user_preferences(self):
        """Allowlist explicit preferences; never expose or cache full account settings."""
        data = json_data(await self.get('/users/settings', {'extended': 'browsing'}, personal=True))
        def section(value):
            if value is None:
                return {}
            if not isinstance(value, dict):
                raise TraktError('Invalid Trakt preference settings response.')
            return value
        browsing = section(section(data).get('browsing'))
        genres = section(browsing.get('genres'))
        streaming = section(browsing.get('watchnow'))

        def strings(value, genre=False):
            if value is None:
                return None
            if not isinstance(value, list) or len(value) > 100 or any(
                not isinstance(v, str) or not v.strip() or len(v) > 256
                or any(ord(c) < 32 or ord(c) == 127 for c in v)
                or (genre and not re.fullmatch(r'[a-z][a-z-]{0,49}', v)) for v in value
            ):
                raise TraktError('Invalid Trakt preference settings response.')
            return list(dict.fromkeys(value))

        country = streaming.get('country')
        if country == '':
            country = None
        if country is not None and (not isinstance(country, str) or not re.fullmatch(r'[A-Za-z]{2}', country)):
            raise TraktError('Invalid Trakt streaming country in preference settings.')
        only_favorites = streaming.get('only_favorites')
        if only_favorites is not None and type(only_favorites) is not bool:
            raise TraktError('Invalid Trakt streaming preference settings.')
        return {
            'genres': {'favorites': strings(genres.get('favorites'), genre=True),
                       'disliked': strings(genres.get('disliked'), genre=True)},
            'streaming': {'country': country.upper() if country else None,
                          'favorite_sources': strings(streaming.get('favorites')),
                          'only_favorites': only_favorites},
            'source': 'trakt:/users/settings?extended=browsing',
            'note': 'Explicit user settings, not inferred preferences. Null means not provided; an empty list means no selections. '
                    'Streaming source identifiers are Trakt values, not verified subscriptions. '
                    'These settings do not establish movie availability and do not provide streaming offer lookups.',
        }

    async def person_movies(self, identifier, limit=50, offset=0):
        data = json_data(await self.get('/people/' + movie_id(identifier) + '/movies', {'extended': 'full'}))
        if not isinstance(data, dict):
            raise TraktError('Invalid person credits response.')
        credits = []
        for item in data.get('cast') or []:
            credits.append(dict(item, department='cast'))
        for department, items in (data.get('crew') or {}).items():
            credits.extend(dict(item, department=department) for item in items)
        return {'items': credits[offset:offset + limit], 'total_items': len(credits), 'offset': offset,
                'limit': limit, 'next_offset': offset + limit if offset + limit < len(credits) else None}

    @consistent_account
    async def preference_data(self, limit=10):
        if self.snapshots:
            ratings, stamp = await self.snapshots.load('/sync/ratings/movies')
            identity = self.snapshots.identity
            favorites, favorite_stamp = await self.snapshots.load('/users/me/favorites/movies/rank')
            if stamp != favorite_stamp or identity != self.snapshots.identity:
                raise TraktError('Trakt preferences changed during lookup. Retry.')
        else:
            ratings = await self._all_items_live('/sync/ratings/movies', extended=True)
            favorites = await self._all_items_live('/users/me/favorites/movies/rank', extended=True)
        high = sorted((r for r in ratings if isinstance(r.get('rating'), int) and r['rating'] >= 8),
                      key=lambda r: r['rating'], reverse=True)
        low = sorted((r for r in ratings if isinstance(r.get('rating'), int) and r['rating'] <= 4),
                     key=lambda r: r['rating'])
        def compact(item):
            movie = item.get('movie') or {}
            return {**{k: item[k] for k in ('rating', 'rated_at', 'rank') if k in item},
                    'movie': {k: movie[k] for k in ('title', 'year', 'ids', 'genres') if k in movie}}
        return {'high_ratings': [compact(r) for r in high[:limit]],
                'low_ratings': [compact(r) for r in low[:limit]],
                'favorites': [compact(r) for r in favorites[:limit]],
                'totals': {'ratings': len(ratings), 'high_ratings': len(high),
                           'low_ratings': len(low), 'favorites': len(favorites)},
                'limit_per_group': limit, 'source_lists_complete': True,
                'selection_truncated': any(len(group) > limit for group in (high, low, favorites)),
                'note': 'Factual selection only: high >= 8, low <= 4. Interpret preferences in the assistant.'}

    @consistent_account
    async def recommendations(self, limit=10, exclude_watched=True, exclude_watchlist=False):
        # This endpoint uses limit, not standard page-based pagination. Fetch up to
        # its documented maximum and apply fresh local exclusions before truncation.
        response = await self.get('/recommendations/movies',
                                  {'limit': 100, 'extended': 'full',
                                   'ignore_watchlisted': str(exclude_watchlist).lower()}, personal=True)
        movies = json_data(response)
        if not isinstance(movies, list):
            raise TraktError('Unerwartetes Format persönlicher Trakt-Empfehlungen.')
        excluded = set()
        for enabled, path in ((exclude_watched, '/sync/watched/movies'),
                              (exclude_watchlist, '/users/me/watchlist/movies/added')):
            if enabled:
                for item in await self.all_items(path):
                    identifier = item.get('movie', {}).get('ids', {}).get('trakt')
                    if identifier is None:
                        raise TraktError('Persönliche Film-ID fehlt; zuverlässiger Ausschluss nicht möglich.')
                    excluded.add(identifier)
        items, seen = [], set()
        for movie in movies:
            identifier = movie.get('ids', {}).get('trakt') if isinstance(movie, dict) else None
            if identifier is None:
                raise TraktError('Film-ID in persönlicher Trakt-Empfehlung fehlt.')
            if identifier in excluded or identifier in seen:
                continue
            seen.add(identifier)
            # Other users' favorited_by/recommended_by notes are unnecessary here.
            items.append({k: v for k, v in movie.items() if k not in ('favorited_by', 'recommended_by')})
        return {'items': items[:limit], 'source': 'trakt:/recommendations/movies',
                'candidates_received': len(movies), 'eligible_candidates': len(items),
                'exclude_watched': exclude_watched, 'exclude_watchlist': exclude_watchlist,
                'note': 'Persönliche Trakt-Rangfolge, kein Garant für Gefallen oder Streaming-Verfügbarkeit. '
                        'Es werden höchstens 100 Trakt-Kandidaten geprüft; nach Ausschlüssen sind weniger Ergebnisse möglich.'}

    async def candidates(self, genres=None, year_from=None, year_to=None, min_rating=None,
                         limit=10, exclude_watched=True, exclude_watchlist=False,
                         source='popular', seed_movie_id=None):
        if year_from is not None and year_to is not None and year_from > year_to:
            raise TraktError('year_from darf nicht größer als year_to sein.')
        if source not in ('popular', 'trending', 'related'):
            raise TraktError('Unbekannte Kandidatenquelle.')
        if source == 'related' and not seed_movie_id:
            raise TraktError('Für ähnliche Kandidaten seed_movie_id angeben.')
        path = '/movies/' + movie_id(seed_movie_id) + '/related' if source == 'related' else '/movies/' + source
        params = {}
        if genres:
            params['genres'] = genres_value(genres)
        if year_from is not None or year_to is not None:
            params['years'] = f'{year_from or 1800}-{year_to or 9999}'
        if min_rating is not None:
            params['ratings'] = f'{min_rating * 10:g}-100'
        identity = await self.auth.access_token() if exclude_watched or exclude_watchlist else None
        excluded = set()
        for enabled, exclusion_path in ((exclude_watched, '/sync/watched/movies'),
                              (exclude_watchlist, '/users/me/watchlist/movies/added')):
            if enabled:
                for item in await self.all_items(exclusion_path):
                    identifier = item.get('movie', {}).get('ids', {}).get('trakt')
                    if identifier is None:
                        raise TraktError('Persönliche Film-ID fehlt; zuverlässiger Ausschluss nicht möglich.')
                    excluded.add(identifier)
        matches, seen = [], set()
        next_page = None
        for page in range(1, 11):
            result = await self.page(path, page, 100, {} if source == 'related' else params)
            next_page = result['next_page']
            for item in result['items']:
                movie = item.get('movie', {}) if source == 'trending' else item
                identifier = movie.get('ids', {}).get('trakt')
                if identifier is None or identifier in excluded or identifier in seen:
                    continue
                seen.add(identifier)
                # Apply filters locally too: never accept missing metadata as a match.
                year, rating = movie.get('year'), movie.get('rating')
                if year_from is not None and (year is None or year < year_from):
                    continue
                if year_to is not None and (year is None or year > year_to):
                    continue
                if min_rating is not None and (rating is None or rating < min_rating):
                    continue
                if genres and not set(genres).intersection(movie.get('genres') or []):
                    continue
                matches.append(movie)
                if len(matches) == limit:
                    break
            if len(matches) == limit or next_page is None:
                break
        if identity is not None and identity != await self.auth.access_token():
            raise TraktError('Trakt authorization changed during candidate lookup. Retry.')
        return {'items': matches, 'source': 'trakt:' + path, 'pages_scanned': page,
                'scan_limit_reached': page == 10 and next_page is not None and len(matches) < limit,
                'exclude_watched': exclude_watched, 'exclude_watchlist': exclude_watchlist,
                'note': 'Kandidatenquelle ist keine persönliche Rangfolge. Genres werden mit ODER verknüpft.'}
