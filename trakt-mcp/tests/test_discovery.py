"""Read-only discovery behavior, private boundaries and real MCP schemas."""
import json

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from auth import Auth
from cache import PublicCache
from discovery import SmartLists, SmartListFilters, RecommendationFilters
from errors import TraktError
from library import LibraryReader
from server import create_app
from test_auth import tokens
from test_library import paginated, show
from test_trakt_client import FakeAuth
from trakt_client import TraktClient


@pytest.mark.parametrize('values', [
    {'ratings': '101-'}, {'ratings': '80-70'}, {'runtimes': '-'}, {'years': '2026.5-'},
    {'imdb_ratings': '10.1-'}, {'metascores': '-101'}, {'parental_violence': '0-4'},
    {'genres': ['../private']}, {'people': ['x,y']}, {'genres': []},
    {'watchnow_country': 'DE'}, {'released_within_days': 0}, {'unknown': 'value'},
])
def test_invalid_filter_values_are_rejected(values):
    with pytest.raises(ValidationError):
        SmartListFilters(**values)


def test_smart_query_preserves_range_scales_and_exclusions():
    filters = SmartListFilters(genres=['mystery', '-horror'], ratings='70-100', imdb_ratings='7.5-',
        runtimes='-120', people=['steven-spielberg'], people_role='directing',
        people_operator='and', watchnow=['favorites', '-netflix'], watchnow_country='de', ignore_watched=True)
    assert filters.query() == {'genres': 'mystery,-horror', 'ratings': '70-100', 'imdb_ratings': '7.5-',
        'runtimes': '-120', 'people': 'steven-spielberg', 'people_role': 'directing',
        'people_operator': 'and', 'watchnow': 'favorites,-netflix', 'watchnow_country': 'de', 'ignore_watched': 'true'}
    with pytest.raises(TraktError, match='awards is required'):
        SmartListFilters(award_won=True).query()


@pytest.mark.asyncio
async def test_private_smart_lists_are_live_and_never_enter_public_cache(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == 'GET' and request.url.host == 'api.trakt.tv'
        assert request.headers['Authorization'] == 'Bearer old'
        if request.url.path == '/smart-lists/my-list':
            return httpx.Response(200, json={'name': 'My list', 'source': 'watchlist', 'media_type': 'movies',
                'ids': {'trakt': 4, 'slug': 'my-list', 'private': 'private-secret'},
                'filters': {'ratings': [70, 100], 'genres': ['mystery'], 'token': 'private-secret'},
                'user': {'email': 'private-secret'}, 'share_link': 'private-secret'})
        assert request.url.path == '/smart-lists/my-list/items/shows/imdb_rating/desc'
        assert request.url.params['genres'] == 'mystery,-horror'
        assert request.url.params['page'] == '2' and request.url.params['limit'] == '1'
        return paginated([{'rank': 2, 'show': show(2), 'user': {'token': 'private-secret'}}], page=2, pages=2, total=2)
    cache = PublicCache(tmp_path/'public.sqlite3', 3600)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        reader = SmartLists(TraktClient(http, FakeAuth(), 'id', cache=cache))
        for _ in range(2):
            definition = await reader.definition('my-list')
            result = await reader.items('my-list', 'shows', 'imdb_rating', 'desc', 2, 1,
                                       SmartListFilters(genres=['mystery', '-horror']))
            assert 'private-secret' not in json.dumps([definition, result])
            assert result['items'][0]['rank'] == 2 and result['next_page'] is None
            assert definition['filters'] == {'ratings': [70, 100], 'genres': ['mystery']}
            assert definition['source'] == 'watchlist'
        assert len(calls) == 4
        assert (await cache.status())['entries'] == 0


@pytest.mark.asyncio
async def test_templates_cached_and_personal_previews_never_claim_results(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert 'Authorization' not in request.headers
        assert request.url.path == '/smart-lists/templates'
        return httpx.Response(200, json=[
            {'id': 'public', 'personal': False, 'total': 10, 'filters': {},
             'items': [{'movie': {'title': str(n)}, 'type': 'movie'} for n in range(4)]},
            {'id': 'personal', 'personal': True, 'filters': {}, 'total': 100,
             'items': [{'movie': {'title': 'private-secret'}}], 'user': 'private-secret'},
        ])
    cache = PublicCache(tmp_path/'public.sqlite3', 3600)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        reader = SmartLists(TraktClient(http, None, 'id', cache=cache))
        result = await reader.templates()
        assert len(result['items'][0]['items']) == 3
        assert result['items'][0]['preview_truncated'] is True
        assert result['items'][1]['items'] == [] and result['items'][1]['total'] is None
        assert 'private-secret' not in json.dumps(result)
        await reader.templates()
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['movie', 'show'])
async def test_personal_recommendations_forward_filters_and_keep_exclusions(kind):
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer old'
        assert request.url.params['theme'] == 'christmas'
        assert request.url.params['watch_window'] == '90'
        assert request.url.params['ratings'] == '70-100'
        return httpx.Response(200, json=[
            {**show(1), 'ending': 'concluded', 'favorited_by': ['private-secret']},
            {**show(2), 'ending': 'open'}, {**show(3), 'ending': None},
        ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id')
        filters = RecommendationFilters(theme='christmas', watch_window=90, ratings='70-100')
        if kind == 'movie':
            result = await client.recommendations(exclude_watched=False, filters=filters)
            assert len(result['items']) == 3
        else:
            result = await LibraryReader(client).show_recommendations(exclude_started=False, exclude_hidden=False,
                filters=filters, ending='concluded')
            assert [v['ids']['trakt'] for v in result['items']] == [1]
        assert result['requested_filters']['watch_window'] == 90
        assert 'private-secret' not in json.dumps(result)


@pytest.mark.asyncio
async def test_smart_list_rejects_unverifiable_pagination_and_bad_path():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        reader = SmartLists(TraktClient(http, FakeAuth(), 'id'))
        with pytest.raises(TraktError):
            await reader.definition('../users/settings')
        assert not calls
        with pytest.raises(TraktError, match='Pagination metadata missing'):
            await reader.items('my-list')


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_discovery_tools_real_mcp_nested_schemas_and_read_only_annotations(tmp_path, mode):
    def handler(request):
        assert request.method == 'GET' and request.url.host == 'api.trakt.tv'
        if request.url.path == '/smart-lists/templates':
            return httpx.Response(200, json=[])
        if request.url.path == '/smart-lists/my-list':
            return httpx.Response(200, json={'name': 'My list', 'filters': {}})
        if request.url.path.startswith('/recommendations/'):
            assert request.url.params['genres'] == 'mystery'
            return httpx.Response(200, json=[show()])
        assert request.url.params['ratings'] == '70-100'
        return paginated([{'type': 'show', 'show': show()}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as backend:
        Auth(backend, 'id', '', tmp_path/'oauth.json')._save(tokens())
        app = create_app({'trakt_client_id': 'id', 'mcp_auth_token': 'x'*48}, tmp_path, backend)
        async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer '+'x'*48}
        ) as http:
            async with Client(streamable_http_client('http://testserver/mcp', http_client=http), mode=mode) as client:
                tools = {t.name: t for t in (await client.list_tools()).tools}
                arguments = {
                    'trakt_get_smart_list': {'list_id': 'my-list'},
                    'trakt_get_smart_list_items': {'list_id': 'my-list', 'filters': {'ratings': '70-100'}},
                    'trakt_get_smart_list_templates': {},
                    'trakt_get_personal_recommendations': {'exclude_watched': False, 'filters': {'genres': ['mystery']}},
                    'trakt_get_show_recommendations': {'exclude_started': False, 'exclude_hidden': False,
                                                       'filters': {'genres': ['mystery']}},
                }
                for name, args in arguments.items():
                    assert tools[name].annotations.read_only_hint is True
                    result = await client.call_tool(name, args)
                    assert not result.is_error, str(result)
                    assert result.structured_content is not None
                bad = await client.call_tool('trakt_get_smart_list_items',
                    {'list_id': 'my-list', 'filters': {'ratings': '101-', 'unknown': 'value'}})
                assert bad.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404])
async def test_smart_list_permission_errors_are_not_empty_successes(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(status, json={'error': 'private-secret'})
    )) as http:
        with pytest.raises(TraktError) as error:
            await SmartLists(TraktClient(http, FakeAuth(), 'id')).items('my-list',
                filters=SmartListFilters(watchnow=['favorites']))
        assert 'private-secret' not in str(error.value)


@pytest.mark.asyncio
async def test_smart_list_rejects_account_change_during_read():
    class ChangingAuth:
        token = 'old'
        async def access_token(self, rejected_token=None):
            return self.token
    auth = ChangingAuth()
    def handler(request):
        auth.token = 'new'
        return httpx.Response(200, json={'name': 'List', 'filters': {}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TraktError, match='authorization changed'):
            await SmartLists(TraktClient(http, auth, 'id')).definition('my-list')


@pytest.mark.asyncio
async def test_show_details_preserve_unknown_or_concluded_ending():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={**show(), 'status': 'canceled', 'ending': None})
    )) as http:
        result = await LibraryReader(TraktClient(http, None, 'id')).show_details('example')
        assert result['status'] == 'canceled' and result['ending'] is None
