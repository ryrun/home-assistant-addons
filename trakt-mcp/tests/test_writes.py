import json

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from contextlib import asynccontextmanager

from auth import Auth
from server import create_app
from test_auth import tokens
from test_dashboard import OPTIONS, INGRESS
from test_library import paginated, show
from test_trakt_client import FakeAuth
from trakt_client import TraktClient
from writes import PERMISSIONS, TraktWrites, WriteRequest


@asynccontextmanager
async def mcp_client(app):
    async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer '+OPTIONS['mcp_auth_token']}
    ) as http, Client(streamable_http_client('http://testserver/mcp', http_client=http)) as client:
        yield client


@pytest.mark.asyncio
async def test_dashboard_saves_categories_and_mcp_executes_writes_and_undo(tmp_path):
    mutations = []
    items = []

    def upstream(request):
        path = request.url.path
        if request.method == 'GET':
            if path == '/users/me/lists/42':
                return httpx.Response(200, json={'name': 'Film night', 'privacy': 'private',
                    'ids': {'trakt': 42}, 'item_count': len(items), 'updated_at': '2026-01-01T00:00:00Z'})
            assert path == '/users/me/lists/42/items/movie,show,season,episode/rank/asc'
            return paginated(items)
        mutations.append((request.method, path))
        if request.method == 'DELETE':
            assert path == '/users/me/lists/42'
            return httpx.Response(204)
        if path == '/users/me/lists':
            assert json.loads(request.content) == {'name': 'Film night', 'privacy': 'private'}
            return httpx.Response(201, json={'ids': {'trakt': 42}})
        assert path == '/users/me/lists/42/items'
        assert json.loads(request.content) == {'shows': [{'ids': {'trakt': 7}}]}
        items.append({'id': 555, 'type': 'show', 'show': show(7), 'rank': 1})
        return httpx.Response(201, json={'added': {'shows': 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as backend:
        Auth(backend, OPTIONS['trakt_client_id'], '', tmp_path/'oauth.json')._save(tokens())
        saved = {category: category == 'list' for category in PERMISSIONS}
        app = create_app({**OPTIONS, 'enable_list_writes': True}, tmp_path, backend)
        async with mcp_client(app) as client, httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.dashboard, client=INGRESS), base_url='http://ingress'
        ) as dashboard:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert 'trakt_create_private_list' not in tools
            assert 'trakt_undo_write' not in tools
            stats = (await dashboard.get('/api/stats')).json()
            assert not any(stats['write_permissions']['active'].values())
            assert (await dashboard.post('/api/review', json={})).status_code == 404
            invalid = await dashboard.put('/api/write-permissions', json={'list': True})
            assert invalid.status_code == 400
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app.dashboard, client=('192.168.1.2', 1)),
                base_url='http://direct',
            ) as direct:
                assert (await direct.put('/api/write-permissions', json=saved)).status_code == 403
            settings = await dashboard.put('/api/write-permissions', json=saved)
            assert settings.json()['saved'] == saved
            assert settings.json()['restart_required']
            assert 'trakt_create_private_list' not in {t.name for t in (await client.list_tools()).tools}
            blocked = await client.call_tool('trakt_create_private_list', {'name': 'Film night', 'show_ids': [7]})
            assert blocked.is_error and not mutations
        assert (tmp_path/'write-permissions.json').stat().st_mode & 0o777 == 0o600

        app = create_app(OPTIONS, tmp_path, backend)
        async with mcp_client(app) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert 'trakt_prepare_write' not in tools
            assert 'trakt_add_to_watchlist' not in tools
            create = tools['trakt_create_private_list']
            assert create.annotations.read_only_hint is False
            assert create.annotations.destructive_hint is False
            assert create.annotations.idempotent_hint is False
            assert 'wait for explicit user confirmation' in create.description
            assert tools['trakt_set_list_note'].annotations.destructive_hint is True
            assert tools['trakt_undo_write'].annotations.destructive_hint is True

            result = await client.call_tool('trakt_create_private_list', {'name': 'Film night', 'show_ids': [7]})
            assert not result.is_error, result
            assert result.structured_content['state'] == 'completed'
            key = result.structured_content['operation_id']
            assert len(mutations) == 2
            status = await client.call_tool('trakt_get_write_result', {'operation_id': key})
            assert status.structured_content['can_undo']
            assert status.structured_content['undo_change'] == {
                'action': 'delete_created_list', 'name': 'Film night', 'list_id': 42,
            }
            items[0]['notes'] = 'new note'
            refused = await client.call_tool('trakt_undo_write', {'operation_id': key})
            assert refused.is_error and refused.structured_content['state'] == 'review_required'
            assert len(mutations) == 2
            del items[0]['notes']
            undone = await client.call_tool('trakt_undo_write', {'operation_id': key})
            assert not undone.is_error
            assert mutations[-1] == ('DELETE', '/users/me/lists/42')
            duplicate = await client.call_tool('trakt_undo_write', {'operation_id': key})
            assert duplicate.is_error and len(mutations) == 3


@pytest.mark.asyncio
async def test_watchlist_undo_removes_only_verified_additions():
    existing = {'id': 110, 'type': 'show', 'show': show(1)}
    new = {'id': 120, 'type': 'show', 'show': show(2)}
    items = [existing]
    sent = []

    def upstream(request):
        if request.method == 'GET':
            assert request.url.path == '/users/me/watchlist/shows/added'
            return paginated(items)
        assert json.loads(request.content) == {'shows': [{'ids': {'trakt': 2}}]}
        sent.append(request.url.path)
        if request.url.path.endswith('/remove'):
            items.remove(new)
            return httpx.Response(200, json={'deleted': {'shows': 1}})
        items.append(new)
        return httpx.Response(201, json={'added': {'shows': 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
        writes = TraktWrites(TraktClient(http, FakeAuth(), 'id'), {'watchlist': True})
        result = await writes.run(WriteRequest(action='add_watchlist', show_ids=[1, 2]))
        assert result['result']['skipped_existing'] == {'shows': 1}
        assert result['can_undo']
        assert result['undo_change']['entries'] == {'shows': [{'ids': {'trakt': 2}}]}
        assert (await writes.undo(result['operation_id']))['state'] == 'completed'
        assert items == [existing]
        assert sent == ['/sync/watchlist', '/sync/watchlist/remove']


@pytest.mark.asyncio
async def test_partial_create_keeps_list_id_and_does_not_retry():
    sent = []

    def upstream(request):
        sent.append(request.url.path)
        if len(sent) == 1:
            return httpx.Response(201, json={'ids': {'trakt': 42}})
        raise httpx.ReadTimeout('private upstream exception')

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
        writes = TraktWrites(TraktClient(http, FakeAuth(), 'id'), {'list': True})
        result = await writes.run(WriteRequest(action='create_list', name='Night', show_ids=[7]))
        assert result['state'] == 'review_required'
        assert result['result']['list_id'] == 42
        assert not result['can_undo']
        assert 'private upstream exception' not in str(result)
        assert sent == ['/users/me/lists', '/users/me/lists/42/items']


@pytest.mark.asyncio
async def test_rating_permission_only_publishes_rating_and_readback(tmp_path):
    requests = []

    def upstream(request):
        assert request.method == 'POST' and request.url.path == '/sync/ratings'
        requests.append(json.loads(request.content))
        return httpx.Response(201, json={'added': {'movies': 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as backend:
        Auth(backend, OPTIONS['trakt_client_id'], '', tmp_path/'oauth.json')._save(tokens())
        (tmp_path/'write-permissions.json').write_text(json.dumps({key: key == 'ratings' for key in PERMISSIONS}))
        app = create_app(OPTIONS, tmp_path, backend)
        async with mcp_client(app) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert {'trakt_set_rating', 'trakt_get_write_result'} <= tools
            assert {'trakt_create_private_list', 'trakt_add_to_history', 'trakt_undo_write'}.isdisjoint(tools)
            invalid = await client.call_tool('trakt_set_rating', {'rating': 11, 'movie_ids': [7]})
            assert invalid.is_error and not requests
            result = await client.call_tool('trakt_set_rating', {'rating': 8, 'movie_ids': [7]})
            assert not result.is_error
            assert not result.structured_content['can_undo']
            assert requests == [{'movies': [{'ids': {'trakt': 7}, 'rating': 8}]}]
