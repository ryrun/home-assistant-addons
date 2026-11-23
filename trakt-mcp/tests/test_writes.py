import json

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from auth import Auth
from server import create_app
from test_auth import tokens
from test_dashboard import OPTIONS, INGRESS
from test_library import paginated, show


@pytest.mark.asyncio
async def test_mcp_proposal_requires_dashboard_approval_and_create_undo(tmp_path):
    mutations = []
    items = []

    def upstream(request):
        path = request.url.path
        if request.method == 'GET':
            if path == '/shows/7':
                return httpx.Response(200, json=show(7))
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
        app = create_app({**OPTIONS, 'enable_list_writes': True}, tmp_path, backend)
        async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer '+OPTIONS['mcp_auth_token']}
        ) as mcp_http, httpx.AsyncClient(transport=httpx.ASGITransport(app=app.dashboard, client=INGRESS),
                                       base_url='http://ingress') as dashboard:
            async with Client(streamable_http_client('http://testserver/mcp', http_client=mcp_http)) as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                assert tools['trakt_prepare_write'].annotations.read_only_hint is False
                disabled = await client.call_tool('trakt_prepare_write', {
                    'change': {'action': 'add_watchlist', 'show_ids': [7]}})
                assert disabled.is_error
                result = await client.call_tool('trakt_prepare_write', {
                    'change': {'action': 'create_list', 'name': 'Film night', 'show_ids': [7]}})
                assert not result.is_error, result
                proposal = result.structured_content
                assert proposal['state'] == 'pending' and 'approval' not in proposal
                assert not mutations
                operation = (await dashboard.get('/api/stats')).json()['write_operations'][0]
                key = proposal['operation_id']
                blocked = await mcp_http.post('http://testserver/api/review', json={
                    'operation_id': key, 'approval': operation['approval'], 'decision': 'approve'})
                assert blocked.status_code == 404
                bad = await dashboard.post('/api/review', json={
                    'operation_id': key, 'approval': 'invalid', 'decision': 'approve'})
                assert bad.status_code == 409 and not mutations
                approval = {'operation_id': key, 'approval': operation['approval'], 'decision': 'approve'}
                done = await dashboard.post('/api/review', json=approval)
                assert done.json()['state'] == 'completed'
                assert len(mutations) == 2
                assert (await dashboard.post('/api/review', json=approval)).status_code == 409
                status = await client.call_tool('trakt_get_write_result', {'operation_id': key})
                assert status.structured_content['can_undo']
                staged = await dashboard.post('/api/review', json={'operation_id': key, 'decision': 'stage_undo'})
                assert staged.json()['state'] == 'pending' and len(mutations) == 2
                undo = (await dashboard.get('/api/stats')).json()['write_operations'][0]
                # A later edit must invalidate the automatic inverse.
                items[0]['notes'] = 'new note'
                refused = await dashboard.post('/api/review', json={
                    'operation_id': undo['operation_id'], 'approval': undo['approval'], 'decision': 'approve'})
                assert refused.json()['state'] == 'review_required'
                assert len(mutations) == 2
                del items[0]['notes']
                await dashboard.post('/api/review', json={'operation_id': key, 'decision': 'stage_undo'})
                undo = (await dashboard.get('/api/stats')).json()['write_operations'][0]
                done = await dashboard.post('/api/review', json={
                    'operation_id': undo['operation_id'], 'approval': undo['approval'], 'decision': 'approve'})
                assert done.json()['state'] == 'completed'
                assert mutations[-1] == ('DELETE', '/users/me/lists/42')


@pytest.mark.asyncio
async def test_watchlist_undo_removes_only_verified_additions():
    from test_trakt_client import FakeAuth
    from trakt_client import TraktClient
    from writes import WriteQueue, WriteRequest

    existing = {'id': 110, 'type': 'show', 'show': show(1)}
    new = {'id': 120, 'type': 'show', 'show': show(2)}
    items = [existing]
    sent = []

    def upstream(request):
        if request.method == 'GET':
            if request.url.path.startswith('/shows/'):
                return httpx.Response(200, json=show(int(request.url.path.rsplit('/', 1)[1])))
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
        queue = WriteQueue(TraktClient(http, FakeAuth(), 'id'), {'enable_watchlist_writes': True})
        proposal = await queue.prepare(WriteRequest(action='add_watchlist', show_ids=[1, 2]))
        operation = queue.public(dashboard=True)[0]
        result = await queue.approve(proposal['operation_id'], operation['approval'])
        assert result['result']['skipped_existing'] == {'shows': 1}
        assert queue.public()[0]['can_undo']
        queue.stage_undo(proposal['operation_id'])
        undo = queue.public(dashboard=True)[0]
        assert (await queue.approve(undo['operation_id'], undo['approval']))['state'] == 'completed'
        assert items == [existing]
        assert sent == ['/sync/watchlist', '/sync/watchlist/remove']


@pytest.mark.asyncio
async def test_partial_create_keeps_list_id_and_does_not_retry():
    from test_trakt_client import FakeAuth
    from trakt_client import TraktClient
    from writes import WriteQueue, WriteRequest

    sent = []

    def upstream(request):
        if request.method == 'GET':
            return httpx.Response(200, json=show(7))
        sent.append(request.url.path)
        if len(sent) == 1:
            return httpx.Response(201, json={'ids': {'trakt': 42}})
        raise httpx.ReadTimeout('private upstream exception')

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
        queue = WriteQueue(TraktClient(http, FakeAuth(), 'id'), {'enable_list_writes': True})
        proposal = await queue.prepare(WriteRequest(action='create_list', name='Night', show_ids=[7]))
        result = await queue.approve(proposal['operation_id'], queue.public(dashboard=True)[0]['approval'])
        assert result['state'] == 'review_required'
        assert result['result']['list_id'] == 42
        assert not queue.public()[0]['can_undo']
        assert 'private upstream exception' not in str(result)
        assert sent == ['/users/me/lists', '/users/me/lists/42/items']
