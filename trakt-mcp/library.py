"""Read-only series and personal library operations, sharing the Trakt HTTP client."""
from datetime import date, datetime, time, timezone
import re

from errors import TraktError, json_data
from trakt_client import consistent_account

MEDIA_FIELDS = ('movie', 'show', 'season', 'episode')
ITEM_FIELDS = ('id', 'rank', 'listed_at', 'watched_at', 'rated_at', 'rating', 'plays',
               'last_watched_at', 'last_collected_at', 'collected_at', 'updated_at',
               'hidden_at', 'paused_at', 'progress', 'action', 'type', 'notes', 'metadata')
LIST_FIELDS = ('name', 'description', 'privacy', 'type', 'display_numbers', 'allow_comments',
               'sort_by', 'sort_how', 'created_at', 'updated_at', 'item_count', 'comment_count', 'likes', 'ids')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,199}', value):
        raise TraktError('Use a valid Trakt ID, IMDb ID, or slug.')
    return value


def choice(value, allowed):
    if value not in allowed:
        raise TraktError('Unsupported media type or option.')
    return value


def positive(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 100000:
        raise TraktError('Invalid season, episode, or pagination number.')
    return value


def iso_date(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError()
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise TraktError('Use a valid date in YYYY-MM-DD format.') from None


def date_range(start, end, *, timestamps=False):
    def parse(value, last):
        if value is None:
            return None
        if not timestamps:
            return iso_date(value)
        try:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                parsed = datetime.combine(date.fromisoformat(value), time.max if last else time.min, timezone.utc)
            else:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError()
            return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        except (ValueError, TypeError, AttributeError):
            raise TraktError('Use YYYY-MM-DD or an ISO datetime with a timezone.') from None
    start, end = parse(start, False), parse(end, True)
    if start is not None and end is not None:
        a = datetime.fromisoformat(start.replace('Z', '+00:00')) if timestamps else start
        b = datetime.fromisoformat(end.replace('Z', '+00:00')) if timestamps else end
        if a > b:
            raise TraktError('The start of the date range must not be after its end.')
    return {k: v for k, v in (('start_at', start), ('end_at', end)) if v is not None}


def object_data(response):
    data = json_data(response)
    if not isinstance(data, dict):
        raise TraktError('Trakt returned an invalid object response.')
    return data


def compact(item):
    if not isinstance(item, dict):
        raise TraktError('Trakt returned an invalid library item.')
    return {k: item[k] for k in (*ITEM_FIELDS, *MEDIA_FIELDS) if k in item}


def local_page(items, page, limit):
    positive(page, 1)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise TraktError('limit must be between 1 and 100.')
    total = len(items)
    return {'items': items[(page - 1) * limit:page * limit], 'page': page, 'limit': limit,
            'total_items': total, 'page_count': (total + limit - 1) // limit,
            'next_page': page + 1 if page * limit < total else None}


class LibraryReader:
    def __init__(self, client):
        self.client, self.auth = client, client.auth

    async def _page(self, path, page=1, limit=50, params=None, *, personal=False,
                    paginated=True, extended=True, projector=None, require_pagination=False):
        positive(page, 1)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise TraktError('limit must be between 1 and 100.')
        query = {**({'extended': 'full'} if extended else {}), **(params or {})}
        if paginated:
            query.update(page=page, limit=limit)
        response = await self.client.get(path, query, personal=personal)
        if personal:
            self.client._check_personal_pagination(response, path)
        if require_pagination and 'X-Pagination-Page-Count' not in response.headers:
            raise TraktError('Pagination metadata missing; completeness cannot be verified for this endpoint.')
        result = self.client._decode_page(response, page, limit)
        if len(result['items']) > limit:
            raise TraktError('Trakt returned more items than the requested page limit.')
        if projector:
            result['items'] = [projector(item) for item in result['items']]
        return {**result, 'source': 'trakt:' + path,
                'freshness': {'validation': 'live_request' if personal else 'public_cache_policy'}}

    async def search_shows(self, query, year=None, limit=10):
        params = {'query': query}
        if year is not None:
            params['years'] = str(year)
        return await self._page('/search/show', limit=limit, params=params)

    async def show_details(self, show_id):
        return object_data(await self.client.get('/shows/' + identifier(show_id), {'extended': 'full'}))

    async def seasons(self, show_id, page=1, limit=50):
        return await self._page('/shows/' + identifier(show_id) + '/seasons', page, limit, paginated=False)

    async def season_episodes(self, show_id, season, page=1, limit=50):
        path = f'/shows/{identifier(show_id)}/seasons/{positive(season)}'
        return await self._page(path, page, limit, paginated=False)

    async def episode_details(self, show_id, season, episode):
        path = f'/shows/{identifier(show_id)}/seasons/{positive(season)}/episodes/{positive(episode, 1)}'
        return object_data(await self.client.get(path, {'extended': 'full'}))

    async def season_details(self, show_id, season):
        path = f'/shows/{identifier(show_id)}/seasons/{positive(season)}/info'
        return object_data(await self.client.get(path, {'extended': 'full'}))

    async def show_ratings(self, show_id, season=None, episode=None):
        path = '/shows/' + identifier(show_id)
        if episode is not None and season is None:
            raise TraktError('Provide season when requesting episode ratings.')
        if season is not None:
            path += '/seasons/' + str(positive(season))
        if episode is not None:
            path += '/episodes/' + str(positive(episode, 1))
        return self.client.format_ratings(object_data(await self.client.get(path + '/ratings', {'extended': 'all'})), path)

    async def related_shows(self, show_id, page=1, limit=10):
        return await self._page('/shows/' + identifier(show_id) + '/related', page, limit)

    async def show_people(self, show_id, limit=50, offset=0):
        data = object_data(await self.client.get('/shows/' + identifier(show_id) + '/people'))
        entries = [dict(item, department='cast') for item in data.get('cast') or []]
        for department, items in (data.get('crew') or {}).items():
            entries.extend(dict(item, department=department) for item in items)
        return {'items': entries[offset:offset + limit], 'total_items': len(entries), 'offset': offset,
                'limit': limit, 'next_offset': offset + limit if offset + limit < len(entries) else None}

    async def next_scheduled_episode(self, show_id):
        path = '/shows/' + identifier(show_id) + '/next_episode'
        response = await self.client.get(path, {'extended': 'full'})
        return {'episode': None if response.status_code == 204 else object_data(response), 'source': 'trakt:' + path,
                'note': 'Next scheduled episode, not the next unwatched episode for this user. Null means none returned.'}

    @consistent_account
    async def show_progress(self, show_id, season=None, page=1, limit=100, specials=False,
                            include_hidden=False, count_specials=True):
        path = '/shows/' + identifier(show_id) + '/progress/watched'
        if season is not None:
            positive(season)
        data = object_data(await self.client.get(path, {'specials': str(specials).lower(),
                           'hidden': str(include_hidden).lower(), 'count_specials': str(count_specials).lower()}, personal=True))
        seasons = data.get('seasons')
        if not isinstance(seasons, list):
            raise TraktError('Trakt returned invalid show progress.')
        episodes, summaries = [], []
        for entry in seasons:
            if not isinstance(entry, dict) or not isinstance(entry.get('episodes'), list) or type(entry.get('number')) is not int:
                raise TraktError('Trakt returned invalid season progress.')
            summaries.append({k: entry[k] for k in ('number', 'title', 'aired', 'completed') if k in entry})
            if season is None or entry['number'] == season:
                for episode in entry['episodes']:
                    if not isinstance(episode, dict):
                        raise TraktError('Trakt returned invalid episode progress.')
                    episodes.append({**{k: episode[k] for k in ('number', 'completed', 'last_watched_at') if k in episode},
                                     'season': entry['number']})
        summary = {k: data[k] for k in ('aired', 'completed', 'last_watched_at', 'reset_at', 'next_episode', 'last_episode') if k in data}
        return {**local_page(episodes, page, limit), 'summary': summary, 'season_summaries': summaries[:100],
                'season_summaries_truncated': len(summaries) > 100, 'selected_season': season,
                'specials_included': specials, 'hidden_included': include_hidden,
                'count_specials': count_specials,
                'source': 'trakt:' + path, 'cached': False,
                'note': 'Progress counts aired episodes only. next_episode is personal unwatched progress, not an airing calendar. '
                        'Respect reset_at for rewatches. Hidden and special seasons depend on the requested flags.'}

    @consistent_account
    async def up_next(self, page=1, limit=50):
        return await self._page('/sync/progress/up_next', page, limit, personal=True, projector=compact, require_pagination=True)

    @consistent_account
    async def watched_shows(self, page=1, limit=50):
        return await self._page('/sync/watched/shows', page, limit, personal=True, paginated=False,
                                extended=False, projector=compact)

    @consistent_account
    async def personal_ratings(self, media_type, page=1, limit=50):
        choice(media_type, ('movies', 'shows', 'seasons', 'episodes'))
        return await self._page('/sync/ratings/' + media_type, page, limit, personal=True, projector=compact)

    @consistent_account
    async def show_watchlist(self, page=1, limit=50):
        return await self._page('/users/me/watchlist/shows/added', page, limit, personal=True, projector=compact)

    @consistent_account
    async def favorite_shows(self, page=1, limit=50):
        return await self._page('/users/me/favorites/shows/rank', page, limit, personal=True, projector=compact)

    @consistent_account
    async def history(self, media_type='all', page=1, limit=50, start_at=None, end_at=None, item_id=None):
        choice(media_type, ('all', 'movies', 'shows', 'episodes'))
        path = '/users/me/history' + ('' if media_type == 'all' else '/' + media_type)
        if item_id is not None:
            if media_type == 'all':
                raise TraktError('Select a media type when providing item_id.')
            path += '/' + identifier(item_id)
        return await self._page(path, page, limit, date_range(start_at, end_at, timestamps=True), personal=True,
                                projector=compact, require_pagination=True)

    @consistent_account
    async def lists(self, page=1, limit=50):
        def project(item):
            if not isinstance(item, dict):
                raise TraktError('Trakt returned invalid list metadata.')
            return {k: item[k] for k in LIST_FIELDS if k in item}
        return await self._page('/users/me/lists', page, limit, personal=True, extended=False, projector=project)

    @consistent_account
    async def list_items(self, list_id, media_type='all', page=1, limit=50):
        choice(media_type, ('all', 'movie', 'show', 'season', 'episode'))
        suffix = 'movie,show,season,episode' if media_type == 'all' else media_type
        return await self._page(f'/users/me/lists/{identifier(list_id)}/items/{suffix}', page, limit,
                                personal=True, projector=compact, require_pagination=True)

    @consistent_account
    async def hidden(self, section='recommendations', media_type=None, page=1, limit=50):
        choice(section, ('recommendations', 'calendar', 'progress_watched', 'progress_collected', 'dropped'))
        params = {}
        if media_type is not None:
            params['type'] = choice(media_type, ('movie', 'show', 'season'))
        result = await self._page('/users/hidden/' + section, page, limit, params, personal=True, projector=compact)
        result['note'] = 'Hidden/dropped status is section-specific and is not automatically a dislike.'
        return result

    async def calendar(self, kind='shows', start_date=None, days=7, target='my', page=1, limit=50):
        if target == 'my':
            return await self._personal_calendar(kind, start_date, days, target, page, limit)
        return await self._calendar(kind, start_date, days, target, page, limit)

    @consistent_account
    async def _personal_calendar(self, *args):
        return await self._calendar(*args)

    async def _calendar(self, kind, start_date, days, target, page, limit):
        choice(target, ('my', 'all'))
        suffix = {'shows': 'shows', 'movies': 'movies', 'new_shows': 'shows/new',
                  'premieres': 'shows/premieres', 'finales': 'shows/finales'}.get(kind)
        if suffix is None or type(days) is not int or not 1 <= days <= 31:
            raise TraktError('Select a supported calendar and a window of 1–31 days.')
        start = iso_date(start_date) if start_date is not None else datetime.now(timezone.utc).date().isoformat()
        path = f'/calendars/{target}/{suffix}/{start}/{days}'
        result = await self._page(path, page, limit, personal=target == 'my', paginated=False,
                                  projector=lambda item: {k: item[k] for k in ('first_aired', 'released', 'movie', 'show', 'episode') if k in item})
        result.update(start_date=start, days=days, timezone='UTC', target=target,
                      note='Release/airing dates, not streaming provider availability. Global calendars may be curated and incomplete.')
        return result

    @consistent_account
    async def stats(self):
        path = '/users/me/stats'
        response = await self.client.get(path, personal=True)
        if response.status_code == 204:
            return {'available': False, 'stats': None, 'source': 'trakt:' + path,
                    'note': 'Trakt returned no precomputed stats. This endpoint requires available VIP statistics; no zeros were inferred.'}
        data = object_data(response)
        stats = {k: data[k] for k in ('lists', 'total_minutes', 'total_plays') if k in data}
        groups = {name: ('ratings', 'comments', 'watched', 'collected', 'plays', 'minutes')
                  for name in ('seasons', 'shows', 'movies', 'episodes')}
        groups.update(ratings=('total', 'distribution'), progress=('started', 'finished', 'dropped'))
        for name, fields in groups.items():
            if name in data:
                if not isinstance(data[name], dict):
                    raise TraktError('Trakt returned invalid account statistics.')
                stats[name] = {key: data[name][key] for key in fields if key in data[name]}
        return {'available': True, 'stats': stats, 'source': 'trakt:' + path,
                'note': 'Trakt precomputed account statistics; minutes are watch-time totals, not remaining episode runtime.'}

    @consistent_account
    async def collection(self, media_type='movies', page=1, limit=50):
        choice(media_type, ('movies', 'shows', 'episodes'))
        result = await self._page('/sync/collection/' + media_type, page, limit, personal=True,
                                  projector=compact, require_pagination=media_type != 'shows')
        result['note'] = 'Items recorded in your Trakt collection, not proof of current ownership, access or streaming availability. '
        if media_type == 'shows':
            result['note'] += 'Show entries omit nested episode collections; use media_type=episodes for individual episodes.'
        return result

    @consistent_account
    async def playback(self, media_type='all', page=1, limit=50, start_date=None, end_date=None):
        choice(media_type, ('all', 'movies', 'episodes'))
        path = '/sync/playback' + ('' if media_type == 'all' else '/' + media_type)
        result = await self._page(path, page, limit, date_range(start_date, end_date), personal=True,
                                  projector=compact, require_pagination=True)
        result['note'] = 'Paused playback positions reported to Trakt by compatible players. Empty data does not prove that nothing was started.'
        return result

    @consistent_account
    async def show_recommendations(self, limit=10, exclude_started=True, exclude_watchlist=False, exclude_hidden=True):
        activity_before = await self._activity() if (exclude_started or exclude_watchlist or exclude_hidden) else None
        data = json_data(await self.client.get('/recommendations/shows',
            {'limit': 100, 'extended': 'full', 'ignore_watchlisted': str(exclude_watchlist).lower()}, personal=True))
        if not isinstance(data, list):
            raise TraktError('Trakt returned invalid show recommendations.')
        excluded = set()
        paths = []
        if exclude_started:
            paths.append('/sync/watched/shows')
        if exclude_watchlist:
            paths.append('/users/me/watchlist/shows/added')
        if exclude_hidden:
            paths.extend(('/users/hidden/recommendations', '/users/hidden/dropped'))
        for path in paths:
            for item in await self.client._all_items_live(path):
                if 'season' in item or item.get('type') == 'season':
                    continue
                show = item.get('show') or {}
                value = show.get('ids', {}).get('trakt')
                if value is None:
                    # A movie/season hidden from recommendations is not a hidden show.
                    if 'show' not in item and ('movie' in item or 'season' in item):
                        continue
                    raise TraktError('Missing Trakt show ID; reliable exclusion is not possible.')
                excluded.add(value)
        selected, seen = [], set()
        for rank, show in enumerate(data, 1):
            if not isinstance(show, dict):
                raise TraktError('Trakt returned an invalid show recommendation.')
            value = show.get('ids', {}).get('trakt')
            if value is None:
                raise TraktError('Missing Trakt show ID in recommendations.')
            if value not in excluded and value not in seen:
                seen.add(value)
                selected.append({**{k: v for k, v in show.items() if k not in ('favorited_by', 'recommended_by')}, 'recommendation_rank': rank})
        if activity_before is not None and activity_before != await self._activity():
            raise TraktError('Trakt activity changed during series recommendations. Retry for consistent exclusions.')
        return {'items': selected[:limit], 'candidates_received': len(data), 'available_after_exclusions': len(selected),
                'selection_truncated': len(selected) > limit, 'source': 'trakt:/recommendations/shows',
                'excluded_started': exclude_started, 'excluded_watchlist': exclude_watchlist, 'excluded_hidden': exclude_hidden,
                'note': 'Trakt personal order preserved. At most 100 upstream candidates; fewer may remain after exclusions.'}

    async def _activity(self):
        data = object_data(await self.client.get('/sync/last_activities', personal=True))
        stamp = data.get('all')
        try:
            parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError()
        except (AttributeError, ValueError, TypeError):
            raise TraktError('Trakt activity timestamp is missing or invalid; exclusions cannot be verified.') from None
        return stamp
