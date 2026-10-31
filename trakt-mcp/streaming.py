"""Read-only TMDb/JustWatch availability, without sending Trakt credentials."""
import asyncio
from datetime import datetime, timezone
import re
import sqlite3
import time
import unicodedata

import httpx

from errors import TraktError
from http_utils import bounded_request, retry_after, API_CONCURRENCY

TMDB_URL = 'https://api.themoviedb.org/3'
ATTRIBUTION = 'Streaming availability data provided by JustWatch via TMDb.'
KINDS = {'flatrate': 'subscription', 'free': 'free', 'ads': 'ads', 'rent': 'rent', 'buy': 'buy'}


def country_code(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z]{2}', value):
        raise TraktError('Land als zweistelligen ISO-Code angeben, z. B. DE.')
    return value.upper()


def service_names(values):
    if not isinstance(values, list) or len(values) > 50 or any(
        not isinstance(v, str) or not v.strip() or len(v) > 100 or any(ord(c) < 32 for c in v) for v in values
    ):
        raise TraktError('Streaming-Abos als Liste von höchstens 50 Anbieternamen angeben.')
    return list(dict.fromkeys(v.strip() for v in values))


def normalized(value):
    return unicodedata.normalize('NFKC', value).casefold().strip()


class StreamingClient:
    def __init__(self, http, trakt, token='', country='DE', services=None, provider_ids=None, cache=None, metrics=None):
        self.http, self.trakt, self.token = http, trakt, token
        self.metrics = metrics
        self.country = country_code(country)
        self.services = service_names(services or [])
        self.provider_ids = self._ids(provider_ids or [])
        self.cache = cache
        self.catalog_lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(API_CONCURRENCY)
        self.rate_limit_until = 0

    async def get(self, path, params=None):
        if not self.token:
            raise TraktError('Für Streaming-Daten tmdb_read_access_token in der HA-Konfiguration hinterlegen.')
        for attempt in range(2):
            remaining = self.rate_limit_until - time.monotonic()
            if remaining > 0:
                raise TraktError(f'TMDb-Rate-Limit aktiv. In {int(remaining) + 1} Sekunden erneut versuchen.')
            try:
                async with self.slots:
                    remaining = self.rate_limit_until - time.monotonic()
                    if remaining > 0:
                        raise TraktError(f'TMDb rate limit active. Retry in {int(remaining) + 1} seconds.')
                    response = await bounded_request(self.http, 'GET', TMDB_URL + path, params=params,
                                                   headers={'Authorization': 'Bearer ' + self.token,
                                                            'Accept': 'application/json'}, metrics=self.metrics, service='tmdb')
            except httpx.RequestError:
                if attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
                raise TraktError('Streaming-Dienst TMDb nicht erreichbar. Bitte erneut versuchen.') from None
            if response.status_code == 429:
                seconds = retry_after(response.headers)
                self.rate_limit_until = time.monotonic() + seconds
                raise TraktError(f'TMDb-Rate-Limit erreicht. In {seconds} Sekunden erneut versuchen.')
            if response.status_code in (502, 503, 504) and attempt == 0:
                await asyncio.sleep(0.25)
                continue
            if response.status_code in (401, 403):
                raise TraktError('TMDb-Zugriff abgelehnt. tmdb_read_access_token und API-Freigabe prüfen.')
            if response.status_code == 404:
                raise TraktError('Film oder Anbieterressource bei TMDb nicht gefunden.')
            if not 200 <= response.status_code < 300:
                raise TraktError('Streaming-Dienst TMDb ist vorübergehend nicht verfügbar.')
            try:
                data = response.json()
            except ValueError:
                raise TraktError('TMDb lieferte eine ungültige Antwort.') from None
            if not isinstance(data, dict):
                raise TraktError('Unerwartetes TMDb-Datenformat.')
            return data

    @staticmethod
    def _provider(item):
        if (not isinstance(item, dict) or type(item.get('provider_id')) is not int
                or not isinstance(item.get('provider_name'), str)):
            raise TraktError('Unvollständige Anbieterinformationen von TMDb.')
        return {'provider_id': item['provider_id'], 'provider_name': item['provider_name']}

    @staticmethod
    def _ids(values):
        if not isinstance(values, list) or len(values) > 50 or any(type(v) is not int or v <= 0 for v in values):
            raise TraktError('Streaming provider IDs must be a list of at most 50 positive integers.')
        return list(dict.fromkeys(values))

    async def providers(self, country=None):
        region = country_code(country if country is not None else self.country)
        key = 'tmdb:movie-providers:' + region
        async with self.catalog_lock:
            response = None
            if self.cache:
                try:
                    response = await self.cache.get(key)
                except (sqlite3.Error, OSError, ValueError):
                    pass
            if response is not None:
                data = response.json()
            else:
                generation = self.cache.generation if self.cache else None
                data = await self.get('/watch/providers/movie', {'watch_region': region, 'language': 'en-US'})
                if self.cache and isinstance(data.get('results'), list):
                    try:
                        await self.cache.put(key, httpx.Response(200, json=data), ttl=86400, generation=generation)
                    except (sqlite3.Error, OSError):
                        pass
        if not isinstance(data, dict) or not isinstance(data.get('results'), list):
            raise TraktError('Incomplete TMDb provider catalog.')
        return {'country': region, 'items': [self._provider(p) for p in data['results']],
                'configured_services': self.services, 'configured_provider_ids': self.provider_ids,
                'source': 'TMDb', 'attribution': ATTRIBUTION,
                'note': 'Prefer stable provider IDs in streaming_provider_ids. Additional channels are separate offers.'}

    async def availability(self, identifier, country=None, services=None, provider_ids=None):
        region = country_code(country if country is not None else self.country)
        selected = self.services if services is None else service_names(services)
        selected_ids = self.provider_ids if provider_ids is None else self._ids(provider_ids)
        if selected or selected_ids:
            catalog = (await self.providers(region))['items']
            names = {normalized(p['provider_name']): p['provider_id'] for p in catalog}
            ids = {p['provider_id'] for p in catalog}
            if any(normalized(name) not in names for name in selected) or any(i not in ids for i in selected_ids):
                raise TraktError('Unknown streaming provider for this country. Use trakt_get_streaming_providers to correct names or IDs.')
            selected_ids = list(set(selected_ids).union(names[normalized(name)] for name in selected))
        # Check setup before spending a Trakt request; map by ID, never by ambiguous title.
        if not self.token:
            raise TraktError('Für Streaming-Daten tmdb_read_access_token in der HA-Konfiguration hinterlegen.')
        movie = await self.trakt.details(identifier)
        tmdb_id = movie.get('ids', {}).get('tmdb') if isinstance(movie, dict) else None
        if type(tmdb_id) is not int or tmdb_id <= 0:
            raise TraktError('Für diesen Film fehlt eine gültige TMDb-ID in den Trakt-Metadaten.')
        data = await self.get(f'/movie/{tmdb_id}/watch/providers')
        results = data.get('results')
        if not isinstance(results, dict):
            raise TraktError('Unvollständige Streaming-Antwort von TMDb.')
        regional = results.get(region)
        if regional is not None and not isinstance(regional, dict):
            raise TraktError('Ungültige regionale Streaming-Antwort von TMDb.')
        regional = regional or {}
        offers = {}
        for upstream, kind in KINDS.items():
            entries = regional.get(upstream, [])
            if not isinstance(entries, list):
                raise TraktError('Ungültige Streaming-Angebote von TMDb.')
            offers[kind] = [self._provider(p) for p in entries]
        matches = [dict(p, offer_type='subscription') for p in offers['subscription']
                   if p['provider_id'] in selected_ids]
        has_data = any(offers.values())
        link = regional.get('link')
        # Return only the known TMDb listing URL, never arbitrary upstream URLs.
        if not isinstance(link, str) or not re.fullmatch(r'https://www\.themoviedb\.org/[^\s]*', link):
            link = None
        return {
            'movie': {'title': movie.get('title'), 'year': movie.get('year'), 'ids': movie['ids']},
            'country': region, 'source': 'TMDb', 'attribution': ATTRIBUTION,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'offers_found' if has_data else 'no_data',
            'offers': offers, 'configured_services': selected, 'selected_provider_ids': selected_ids, 'subscription_matches': matches,
            'available_with_configured_subscription': bool(matches) if has_data and selected_ids else None,
            'listing_url': link,
            'note': 'Anbieterstand ist keine Wiedergabegarantie. Keine Live-Prüfung deines Abos. '
                    'Anbieternamen müssen exakt passen; Zusatz-Channels sind separat. '
                    'Keine Daten bedeutet unbekannt, nicht sicher unverfügbar. Quelle JustWatch via TMDb nennen.',
        }

    async def shortlist(self, identifiers, country=None, services=None, provider_ids=None):
        if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 10:
            raise TraktError('A shortlist must contain between one and ten movie IDs.')
        identifiers = list(dict.fromkeys(identifiers))
        async def one(identifier):
            try:
                return {'movie_id': identifier, 'result': await self.availability(identifier, country, services, provider_ids)}
            except TraktError as error:
                return {'movie_id': identifier, 'error': str(error)}
            except Exception:
                return {'movie_id': identifier, 'error': 'Availability lookup failed.'}
        return {'items': await asyncio.gather(*(one(i) for i in identifiers)), 'attribution': ATTRIBUTION,
                'note': 'Per-movie errors do not establish unavailability. No playback guarantee.'}
