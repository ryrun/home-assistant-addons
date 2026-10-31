import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from server import create_app

OPTIONS = dict(trakt_client_id='test-id', mcp_auth_token='x' * 48, allowed_networks=[],
               personal_cache_enabled=False, enable_mcp_auth_tools=True)


def test_auth_gate_and_health(tmp_path):
    app = create_app(OPTIONS, tmp_path)
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        for method in ('get', 'post', 'delete'):
            assert getattr(client, method)('/mcp').status_code == 401
            assert getattr(client, method)('/mcp', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert client.post('/mcp', headers={'Authorization': 'Bearer ' + 'x' * 48, 'Origin': 'https://evil.example'}).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_real_sdk_streamable_http_handshake_and_repeated_tools(tmp_path, mode):
    calls = []
    def upstream(request):
        calls.append(request)
        assert request.method == 'GET'
        return httpx.Response(200, json={'title': 'Example', 'year': 2024, 'ids': {'trakt': 123}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_http:
        app = create_app(OPTIONS, tmp_path, upstream_http)
        # SDK's HTTP transport exercises MCP negotiation and independent HTTP requests.
        async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                      headers={'Authorization': 'Bearer ' + 'x' * 48}) as http:
            async with Client(streamable_http_client('http://testserver/mcp', http_client=http), mode=mode) as client:
                tools = (await client.list_tools()).tools
                assert len(tools) == 18
                assert all(t.output_schema is not None for t in tools)
                assert all(t.annotations.read_only_hint for t in tools if not t.name.startswith('trakt_auth') and t.name != 'trakt_clear_cache')
                for _ in range(2):
                    result = await client.call_tool('trakt_get_movie_details', {'movie_id': '123'})
                    assert not result.is_error
                    assert 'Example' in str(result)
                    assert result.structured_content['title'] == 'Example'
                bad = await client.call_tool('trakt_get_watched_movies', {'limit': 0})
                assert bad.is_error
                unauthorized = await client.call_tool('trakt_get_movie_ratings', {})
                assert unauthorized.is_error
                assert 'trakt_auth_start' in str(unauthorized)
        assert len(calls) == 1


def test_broken_public_cache_does_not_prevent_startup(tmp_path):
    (tmp_path / 'public-cache.sqlite3').write_text('corrupt-cache')
    app = create_app(OPTIONS, tmp_path)
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200


def test_host_allowlist_rejects_unconfigured_host(tmp_path):
    app = create_app({**OPTIONS, 'allowed_hosts': ['homeassistant.local:8765']}, tmp_path)
    with TestClient(app) as client:
        response = client.post('/mcp', json={}, headers={'Authorization': 'Bearer ' + 'x' * 48})
        assert response.status_code == 421


@pytest.mark.asyncio
async def test_all_new_tools_over_mcp(tmp_path):
    from auth import Auth
    from test_auth import tokens
    from test_trakt_client import movie
    requests = []
    def upstream(request):
        requests.append(request)
        assert request.method == 'GET'
        path = request.url.path
        assert request.url.host == 'api.trakt.tv'
        if path == '/users/settings':
            return httpx.Response(200, json={'user': {'email': 'private-account-email'},
                                           'account': {'token': 'private-account-token'},
                                           'browsing': {'genres': {'favorites': ['mystery']},
                                                        'watchnow': {'country': 'DE', 'favorites': ['netflix']}}})
        if path == '/movies/123/ratings':
            return httpx.Response(200, json={'trakt': {'rating': 8.1, 'votes': 100},
                                           'imdb': {'rating': 8.3, 'votes': 200}})
        if path == '/movies/123':
            return httpx.Response(200, json={**movie(123), 'ids': {'trakt': 123, 'tmdb': 456}})
        if path.startswith('/people/'):
            return httpx.Response(200, json={'cast': [], 'crew': {'directing': [{'movie': movie(3), 'jobs': ['Director']}]}})
        if 'favorites' in path:
            return httpx.Response(200, json=[{'rank': 1, 'movie': movie(3)}], headers={'X-Pagination-Page-Count': '1'})
        if path == '/recommendations/movies':
            return httpx.Response(200, json=[movie(3)])
        if path == '/sync/watched/movies':
            return httpx.Response(200, json=[])
        pytest.fail('Unexpected request path: ' + path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_http:
        Auth(upstream_http, OPTIONS['trakt_client_id'], '', tmp_path / 'oauth.json')._save(tokens())
        app = create_app(OPTIONS, tmp_path, upstream_http)
        async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer ' + 'x' * 48}
        ) as http:
            async with Client(streamable_http_client('http://testserver/mcp', http_client=http)) as client:
                for tool, arguments in (
                    ('trakt_get_user_preferences', {}),
                    ('trakt_get_favorite_movies', {}),
                    ('trakt_get_person_movies', {'person_id': 'director'}),
                    ('trakt_get_personal_recommendations', {}),
                    ('trakt_get_movie_ratings_summary', {'movie_id': '123'}),
                ):
                    result = await client.call_tool(tool, arguments)
                    assert not result.is_error, str(result)
                    assert 'private-access' not in str(result)
                    assert 'private-account-' not in str(result)
                    if tool == 'trakt_get_user_preferences':
                        assert result.structured_content['genres']['favorites'] == ['mystery']
                    if tool == 'trakt_get_movie_ratings_summary':
                        assert result.structured_content['ratings']['imdb']['rating'] == 8.3
