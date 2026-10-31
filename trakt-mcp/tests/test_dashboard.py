import time

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from metrics import Metrics
from server import create_app

OPTIONS = {'trakt_client_id': 'private-client-id', 'mcp_auth_token': 'private-mcp-token-'+'x'*40,
           'trakt_client_secret': 'private-client-secret',
           'personal_cache_enabled': False}
INGRESS = ('172.30.32.2', 12345)


@pytest.mark.parametrize('peer', [('127.0.0.1', 1), ('192.168.1.2', 1), ('8.8.8.8', 1), ('testclient', 1)])
def test_dashboard_rejects_non_supervisor_peers_and_spoofed_headers(tmp_path, peer):
    app = create_app(OPTIONS, tmp_path)
    with TestClient(app.dashboard, client=peer) as client:
        for path in ('/', '/api/stats', '/assets/status.js', '/assets/status.css'):
            response = client.get(path, headers={'X-Forwarded-For': '172.30.32.2',
                                               'X-Ingress-Path': '/api/hassio_ingress/fake/',
                                               'Authorization': 'Bearer '+OPTIONS['mcp_auth_token']})
            assert response.status_code == 403


def test_ingress_read_only_assets_headers_and_no_secrets(tmp_path):
    app = create_app(OPTIONS, tmp_path)
    app.metrics.ready = True
    with TestClient(app.dashboard, client=INGRESS) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert './assets/status.js' in page.text
        assert page.headers['Cache-Control'] == 'no-store'
        assert "frame-ancestors 'self'" in page.headers['Content-Security-Policy']
        assert client.get('/assets/status.js').status_code == 200
        assert client.get('/assets/status.css').status_code == 200
        response = client.get('/api/stats')
        assert response.json()['metrics']['ready']
        assert response.json()['metrics']['tools']['calls'] == 0
        assert 'private-' not in response.text
        assert client.post('/api/stats').status_code == 405
        assert client.get('/mcp').status_code == 404
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        assert client.get('/api/stats').status_code in (401, 403)
        assert client.get('/api/stats', headers={'Authorization': 'Bearer '+OPTIONS['mcp_auth_token']}).status_code == 404


@pytest.mark.asyncio
async def test_statistics_count_actual_calls_and_cached_responses_without_upstream_polling(tmp_path):
    requests = []
    def upstream(request):
        requests.append(request)
        if request.url.path == '/movies/404':
            return httpx.Response(404, text='private-upstream-body')
        return httpx.Response(200, json={'title': 'private-movie-title', 'ids': {'trakt': 1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_http:
        app = create_app(OPTIONS, tmp_path, upstream_http)
        async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer '+OPTIONS['mcp_auth_token']}
        ) as http:
            async with Client(streamable_http_client('http://testserver/mcp', http_client=http)) as client:
                await client.call_tool('trakt_get_movie_details', {'movie_id': '1'})
                await client.call_tool('trakt_get_movie_details', {'movie_id': '1'})
                result = await client.call_tool('trakt_get_movie_details', {'movie_id': '404'})
                assert result.is_error
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.dashboard, client=INGRESS),
                                          base_url='http://ingress') as dashboard:
                for _ in range(2):
                    response = await dashboard.get('/api/stats')
                    data = response.json()
                    assert data['metrics']['tools']['calls'] == 3
                    assert data['metrics']['tools']['errors'] == 1
                    assert data['metrics']['tools']['active'] == 0
                    assert data['metrics']['upstreams']['trakt']['requests'] == 2
                    assert data['metrics']['upstreams']['trakt']['errors'] == 1
                    assert data['public_cache']['hits'] == 1
                    assert 'private-' not in response.text
                assert len(requests) == 2


def test_metrics_are_bounded_and_record_expected_oauth_pending():
    metrics = Metrics()
    for _ in range(600):
        start = metrics.begin_tool('trakt_get_movie_details')
        metrics.finish_tool('trakt_get_movie_details', start, 'ok')
        metrics.record_upstream('oauth', time.monotonic(), 400, 10, expected=True)
    data = metrics.snapshot()
    assert data['tools']['calls'] == 600
    assert data['tools']['samples'] == 512
    assert len(data['recent']) == 30
    assert data['per_tool'][0]['samples'] == 128
    assert data['upstreams']['oauth']['errors'] == 0
    assert data['upstreams']['oauth']['statuses']['400'] == 600
    assert data['process']['memory_bytes'] > 0
    assert Metrics().snapshot()['tools']['calls'] == 0
