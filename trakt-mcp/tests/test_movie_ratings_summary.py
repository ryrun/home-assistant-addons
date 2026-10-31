import json
import sqlite3

import httpx
import pytest
from starlette.testclient import TestClient

from cache import PublicCache
from errors import TraktError
from server import create_app
from trakt_client import TraktClient


@pytest.mark.asyncio
async def test_external_scores_are_fetched_only_from_trakt_and_cached(tmp_path):
    calls = []
    payload = {
        'trakt': {'rating': 8.12345, 'votes': 100, 'distribution': {'8': 100}},
        'imdb': {'rating': 8.4, 'votes': 200, 'link': 'https://www.imdb.com/title/tt123'},
        'rotten_tomatoes': {'rating': 94, 'user_rating': 82, 'state': 'fresh'},
        'metascore': {'rating': 0}, 'letterboxd': {'rating': 4.2},
        'mal': {'rating': None, 'votes': 0}, 'tmdb': None,
        'unexpected': 'do-not-return',
    }
    def handler(request):
        calls.append(request)
        assert request.method == 'GET' and request.url.host == 'api.trakt.tv'
        assert request.url.path == '/movies/123/ratings'
        assert dict(request.url.params) == {'extended': 'all'}
        assert 'Authorization' not in request.headers
        return httpx.Response(200, json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, None, 'id', PublicCache(tmp_path / 'cache.sqlite3'))
        first = await client.ratings_summary('123')
        assert first == await client.ratings_summary('123')
    assert len(calls) == 1
    assert first['ratings']['trakt']['rating'] == 8.12345
    assert first['ratings']['rotten_tomatoes']['rating'] == 94
    assert first['ratings']['rotten_tomatoes']['user_rating'] == 82
    assert first['ratings']['metascore']['rating'] == 0
    assert first['ratings']['mal']['rating'] is None
    assert first['ratings']['tmdb'] is None
    assert first['ratings']['imdb']['link'] == payload['imdb']['link']
    assert first['scales']['letterboxd'] == 5 and first['scales']['rotten_tomatoes'] == 100
    assert 'do-not-return' not in json.dumps(first)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'rating': 7.5, 'votes': 10}, {'trakt': {'rating': 7.5, 'votes': 10}}])
async def test_missing_external_ratings_remain_unknown(payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        result = await TraktClient(http, None, 'id').ratings_summary('movie-slug')
    assert all(result['ratings'][source] is None for source in ('imdb', 'rotten_tomatoes', 'metascore', 'letterboxd', 'mal', 'tmdb'))
    if payload:
        assert result['ratings']['trakt']['rating'] == 7.5
    else:
        assert result['ratings']['trakt'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [[], {'imdb': 'private-malformed-response'}])
async def test_invalid_ratings_are_rejected_without_raw_values(payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        with pytest.raises(TraktError, match='Invalid Trakt movie ratings response') as error:
            await TraktClient(http, None, 'id').ratings_summary('123')
    assert 'private-' not in str(error.value)


@pytest.mark.asyncio
async def test_invalid_ratings_identifier_does_not_make_a_request():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('Unexpected request'))) as http:
        with pytest.raises(TraktError):
            await TraktClient(http, None, 'id').ratings_summary('../oauth/token')


@pytest.mark.asyncio
async def test_cache_upgrade_removes_provider_catalogs_and_preserves_trakt_metadata(tmp_path):
    path = tmp_path / 'cache.sqlite3'
    cache = PublicCache(path)
    await cache.put('tmdb:movie-providers:DE', httpx.Response(200, json={'old': True}))
    await cache.put('trakt-public-movie', httpx.Response(200, json={'title': 'Example'}))
    cache = PublicCache(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT key FROM responses').fetchall() == [('trakt-public-movie',)]
    assert await cache.get('trakt-public-movie') is not None


def test_legacy_streaming_options_are_ignored_and_monitor_is_trakt_only(tmp_path):
    options = {'trakt_client_id': 'id', 'mcp_auth_token': 'x' * 48,
               'tmdb_read_access_token': 'private-obsolete-token', 'streaming_country': 'obsolete',
               'streaming_services': ['old-service'], 'streaming_provider_ids': [999]}
    app = create_app(options, tmp_path)
    with TestClient(app.dashboard, client=('172.30.32.2', 1234)) as client:
        data = client.get('/api/stats')
        assert set(data.json()['metrics']['upstreams']) == {'trakt', 'oauth'}
        assert set(data.json()['cooldowns']) == {'trakt', 'oauth'}
        assert 'streaming_configured' not in data.json()
        assert 'private-' not in data.text
        page = client.get('/').text
        assert 'TMDb' not in page and 'Streaming lookup' not in page
