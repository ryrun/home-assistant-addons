import asyncio
import sqlite3
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.testclient import TestClient

from auth import Auth
from cache import PublicCache
from errors import TraktError
from http_utils import bounded_request
from security import client_allowed, parse_networks
from server import create_app
from streaming import StreamingClient
from test_auth import tokens
from test_trakt_client import FakeAuth, movie
from trakt_client import TraktClient


@pytest.mark.asyncio
@pytest.mark.parametrize('error', ['invalid_client', 'invalid_request', 'unknown'])
async def test_oauth_configuration_errors_keep_tokens(tmp_path, error):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={'error': error}))) as http:
        auth = Auth(http, 'id', '', tmp_path / 'oauth.json')
        auth._save(tokens(expired=True))
        with pytest.raises(TraktError, match='retained'):
            await auth.access_token()
        assert auth.tokens and auth.path.exists()


@pytest.mark.asyncio
async def test_invalid_cached_body_refetches(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'title': 'OK'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        cache = PublicCache(tmp_path / 'cache.sqlite3')
        client = TraktClient(http, FakeAuth(), 'id', cache)
        await client.details('123')
        with sqlite3.connect(cache.path) as db:
            db.execute('UPDATE responses SET body = ?', (b'{broken',))
        assert (await client.details('123'))['title'] == 'OK'
        assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('service', ['trakt', 'tmdb'])
async def test_waiting_request_obeys_new_cooldown(service):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path.endswith('/1'):
            started.set()
            await release.wait()
            return httpx.Response(429, headers={'Retry-After': '7200'})
        return httpx.Response(200, json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id') if service == 'trakt' else StreamingClient(http, None, 'token')
        if service == 'trakt':
            client.request_slots = asyncio.Semaphore(1)
        else:
            client.slots = asyncio.Semaphore(1)
        first = asyncio.create_task(client.get('/1'))
        await started.wait()
        second = asyncio.create_task(client.get('/2'))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert all(isinstance(result, TraktError) for result in results)
        assert len(calls) == 1
        assert client.rate_limit_until - time.monotonic() > 7100


@pytest.mark.asyncio
async def test_device_retry_after_is_respected(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={'Retry-After': '300'}))) as http:
        auth = Auth(http, 'id', '', tmp_path / 'oauth.json')
        auth.pending = dict(code='private', expires=time.monotonic() + 1000, next_poll=0, interval=5)
        assert (await auth.poll())['retry_after_seconds'] == 300


@pytest.mark.asyncio
async def test_upstream_body_limit_applies_to_actual_bytes():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x' * 100))) as http:
        with pytest.raises(TraktError, match='size limit'):
            await bounded_request(http, 'GET', 'https://example.test/data', max_bytes=50)


def test_network_filter_handles_ipv4_ipv6_and_untrusted_headers():
    networks = parse_networks(['192.168.0.0/16', 'fc00::/7'])
    assert client_allowed(('192.168.1.2', 10), networks)
    assert client_allowed(('::ffff:192.168.1.2', 10), networks)
    assert client_allowed(('fd00::1', 10), networks)
    assert not client_allowed(('8.8.8.8', 10), networks)
    with TestClient(create_app({'trakt_client_id': 'id', 'mcp_auth_token': 'x'*48,
                                'allowed_networks': ['192.168.0.0/16']}, http=AsyncMock()),
                    client=('8.8.8.8', 10)) as client:
        assert client.post('/mcp', headers={'Authorization': 'Bearer '+'x'*48,
                                          'X-Forwarded-For': '192.168.1.2'}).status_code == 403
        assert client.get('/health').status_code == 200


@pytest.mark.asyncio
async def test_personal_snapshots_invalidate_and_do_not_survive_account_change():
    stamp = ['2026-10-31T00:00:00Z']
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == '/sync/last_activities':
            return httpx.Response(200, json={'all': stamp[0]})
        return httpx.Response(200, json=[{'movie': movie(n)} for n in range(300)])
    auth = FakeAuth()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, auth, 'id', personal_cache=True)
        await client.watched(1)
        await client.watched(2)
        assert calls.count('/sync/watched/movies') == 1
        stamp[0] = '2026-10-31T01:00:00Z'
        await client.watched()
        assert calls.count('/sync/watched/movies') == 2
        auth.access_token = AsyncMock(return_value='other-account-token')
        await client.watched()
        assert calls.count('/sync/watched/movies') == 3


@pytest.mark.asyncio
async def test_personal_cache_never_serves_stale_data_when_activity_fails():
    fail = [False]
    def handler(request):
        if request.url.path == '/sync/last_activities':
            return httpx.Response(403) if fail[0] else httpx.Response(200, json={'all': '2026-10-31T00:00:00Z'})
        return httpx.Response(200, json=[])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id', personal_cache=True)
        await client.watched()
        fail[0] = True
        with pytest.raises(TraktError):
            await client.watched()


@pytest.mark.asyncio
async def test_shortlist_returns_per_movie_errors_and_deduplicates():
    client = StreamingClient(None, None)
    client.availability = AsyncMock(side_effect=[{'status': 'offers_found'}, TraktError('Not found')])
    result = await client.shortlist(['1', '1', '2'])
    assert len(result['items']) == 2
    assert result['items'][1]['error'] == 'Not found'
    assert client.availability.await_count == 2


@pytest.mark.asyncio
async def test_preference_data_has_totals_and_explicit_truncation():
    client = TraktClient(None, None, 'id')
    client._all_items_live = AsyncMock(side_effect=[
        [{'movie': movie(1), 'rating': 10}, {'movie': movie(2), 'rating': 9}, {'movie': movie(3), 'rating': 1}],
        [{'movie': movie(4)}]])
    result = await client.preference_data(limit=1)
    assert result['totals']['ratings'] == 3
    assert result['selection_truncated'] and result['source_lists_complete']
    assert result['high_ratings'][0]['rating'] == 10


@pytest.mark.asyncio
async def test_provider_ids_work_and_unknown_names_do_not_look_unavailable(tmp_path):
    def handler(request):
        if request.url.path.endswith('/watch/providers/movie'):
            return httpx.Response(200, json={'results': [{'provider_id': 8, 'provider_name': 'Netflix'}]})
        return httpx.Response(200, json={'results': {'DE': {'flatrate': [{'provider_id': 8, 'provider_name': 'Netflix'}]}}})
    trakt = AsyncMock()
    trakt.details.return_value = {'title': 'Example', 'ids': {'tmdb': 1}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = StreamingClient(http, trakt, 'token', provider_ids=[8], cache=PublicCache(tmp_path/'cache.sqlite3'))
        assert (await client.availability('1'))['available_with_configured_subscription'] is True
        with pytest.raises(TraktError, match='Unknown streaming provider'):
            await client.availability('1', services=['Netfliix'])
        assert (await client.cache.status())['hits'] >= 1


def test_privilege_drop_prepares_only_known_files(tmp_path, monkeypatch):
    from security import drop_privileges, RUNTIME_UID
    import security
    (tmp_path/'oauth.json').write_text('{}')
    operations = []
    monkeypatch.setattr(security.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(security.os, 'chown', lambda path, uid, gid: operations.append(('chown', str(path), uid)))
    monkeypatch.setattr(security.os, 'setgroups', lambda value: operations.append(('groups', value)))
    monkeypatch.setattr(security.os, 'setgid', lambda value: operations.append(('gid', value)))
    monkeypatch.setattr(security.os, 'setuid', lambda value: operations.append(('uid', value)))
    drop_privileges(tmp_path)
    assert operations[-1] == ('uid', RUNTIME_UID)
    assert (tmp_path/'oauth.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_fresh_snapshot_rejects_change_during_initial_load():
    count = [0]
    def handler(request):
        if request.url.path == '/sync/last_activities':
            count[0] += 1
            return httpx.Response(200, json={'all': f'2026-10-31T0{count[0]}:00:00Z'})
        return httpx.Response(200, json=[])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id', personal_cache=True)
        with pytest.raises(TraktError, match='changed during sync'):
            await client.watched()
        assert not client.snapshots.entries


@pytest.mark.asyncio
async def test_cache_uses_short_trending_lifetime_and_reads_do_not_write(tmp_path):
    now = [1000]
    cache = PublicCache(tmp_path/'cache.sqlite3', ttl=3600, clock=lambda: now[0])
    await cache.put('trending', httpx.Response(200, json=[]), ttl=300)
    await cache.put('details', httpx.Response(200, json={}))
    now[0] += 301
    assert await cache.get('trending') is None
    assert await cache.get('details') is not None
    with sqlite3.connect(cache.path) as db:
        # Expired entries remain on disk until the next write; get/status do not clean them.
        assert db.execute('SELECT COUNT(*) FROM responses').fetchone()[0] == 2


@pytest.mark.asyncio
async def test_default_tool_surface_disables_authorization(tmp_path):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    app = create_app({'trakt_client_id': 'id', 'mcp_auth_token': 'x'*48}, tmp_path)
    async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer '+'x'*48}
    ) as http:
        async with Client(streamable_http_client('http://testserver/mcp', http_client=http)) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert len(names) == 18
            assert 'trakt_auth_start' not in names and 'trakt_auth_poll' not in names
            assert 'trakt_get_preference_data' in names
            assert 'trakt_get_user_preferences' in names
