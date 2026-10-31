import json
from unittest.mock import AsyncMock

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from auth import Auth
from cache import PublicCache
from errors import TraktError
from library import LibraryReader, date_range
from server import create_app
from test_auth import tokens
from test_trakt_client import FakeAuth
from trakt_client import TraktClient
from version import VERSION


def show(value=1):
    return {'title': f'Show {value}', 'year': 2024, 'ids': {'trakt': value}, 'genres': ['mystery']}


def paginated(payload, *, page=1, pages=1, total=None):
    return httpx.Response(200, json=payload, headers={
        'X-Pagination-Page': str(page), 'X-Pagination-Page-Count': str(pages),
        'X-Pagination-Limit': str(len(payload) or 1),
        'X-Pagination-Item-Count': str(total if total is not None else len(payload)),
    })


def progress():
    return {'aired': 3, 'completed': 1, 'reset_at': '2026-01-01T00:00:00Z',
            'next_episode': {'season': 1, 'number': 2},
            'last_episode': {'season': 1, 'number': 1},
            'seasons': [{'number': 1, 'aired': 3, 'completed': 1,
                         'episodes': [{'number': n, 'completed': n == 1} for n in (1, 2, 3)]}]}


TOOLS = [
    ('trakt_search_shows', {'query': 'example'}, '/search/show', False),
    ('trakt_get_show_details', {'show_id': 'example'}, '/shows/example', False),
    ('trakt_get_show_seasons', {'show_id': 'example'}, '/shows/example/seasons', False),
    ('trakt_get_season_details', {'show_id': 'example', 'season': 1}, '/shows/example/seasons/1/info', False),
    ('trakt_get_season_episodes', {'show_id': 'example', 'season': 1}, '/shows/example/seasons/1', False),
    ('trakt_get_episode_details', {'show_id': 'example', 'season': 1, 'episode': 2}, '/shows/example/seasons/1/episodes/2', False),
    ('trakt_get_show_progress', {'show_id': 'example', 'limit': 2}, '/shows/example/progress/watched', True),
    ('trakt_get_up_next', {}, '/sync/progress/up_next', True),
    ('trakt_get_next_scheduled_episode', {'show_id': 'example'}, '/shows/example/next_episode', False),
    ('trakt_get_watched_shows', {}, '/sync/watched/shows', True),
    ('trakt_get_personal_ratings', {'media_type': 'seasons'}, '/sync/ratings/seasons', True),
    ('trakt_get_show_watchlist', {}, '/users/me/watchlist/shows/added', True),
    ('trakt_get_favorite_shows', {}, '/users/me/favorites/shows/rank', True),
    ('trakt_get_show_ratings_summary', {'show_id': 'example'}, '/shows/example/ratings', False),
    ('trakt_get_related_shows', {'show_id': 'example'}, '/shows/example/related', False),
    ('trakt_get_show_people', {'show_id': 'example'}, '/shows/example/people', False),
    ('trakt_get_show_recommendations', {'exclude_started': False, 'exclude_hidden': False}, '/recommendations/shows', True),
    ('trakt_get_history', {'media_type': 'episodes', 'start_at': '2026-01-01', 'end_at': '2026-01-02'}, '/users/me/history/episodes', True),
    ('trakt_get_lists', {}, '/users/me/lists', True),
    ('trakt_get_list_items', {'list_id': 'my-list'}, '/users/me/lists/my-list/items/movie,show,season,episode', True),
    ('trakt_get_hidden_items', {}, '/users/hidden/recommendations', True),
    ('trakt_get_calendar', {'start_date': '2026-01-01'}, '/calendars/my/shows/2026-01-01/7', True),
    ('trakt_get_user_stats', {}, '/users/me/stats', True),
    ('trakt_get_collection', {'media_type': 'episodes'}, '/sync/collection/episodes', True),
    ('trakt_get_playback', {'media_type': 'episodes'}, '/sync/playback/episodes', True),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_every_library_tool_over_real_mcp_is_read_only_and_uses_trakt_only(tmp_path, mode, caplog):
    expected = None
    def upstream(request):
        assert request.method == 'GET' and request.url.host == 'api.trakt.tv'
        assert request.url.path == expected[2]
        assert ('Authorization' in request.headers) == expected[3]
        path = request.url.path
        if path.endswith('/progress/watched'):
            return httpx.Response(200, json=progress())
        if path.endswith('/next_episode'):
            return httpx.Response(204)
        if path.endswith('/people'):
            return httpx.Response(200, json={'cast': [], 'crew': {'directing': [{'person': {'name': 'Director'}, 'jobs': ['Director']}]}})
        if path.endswith('/ratings'):
            return httpx.Response(200, json={'imdb': {'rating': 8, 'votes': 50}})
        if path == '/users/me/stats':
            return httpx.Response(200, json={'movies': {'watched': 10, 'minutes': 1000}, 'total_minutes': 1000,
                                           'network': {'friends': 5}, 'account': {'token': 'private-secret'}})
        if path == '/users/me/lists':
            return httpx.Response(200, json=[{'name': 'My list', 'ids': {'trakt': 5}, 'share_link': 'private-share',
                                            'user': {'email': 'private-email'}}])
        if path == '/recommendations/shows':
            return httpx.Response(200, json=[{**show(), 'favorited_by': [{'notes': 'private-other-note'}],
                                             'recommended_by': [{'notes': 'private-other-note'}]}])
        if path == '/shows/example' or path.endswith('/info') or '/episodes/2' in path:
            return httpx.Response(200, json={**show(), 'status': 'ended'})
        item = {'show': show(), 'rating': 9, 'rated_at': '2026-01-01T00:00:00Z',
                'notes': 'my-note', 'progress': {'next_episode': {'season': 1, 'number': 2}}}
        if expected[3]:
            item['user'] = {'email': 'private-email'}
        return paginated([item])
    caplog.set_level('INFO', logger='trakt_mcp')
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as backend:
        Auth(backend, 'id', '', tmp_path / 'oauth.json')._save(tokens())
        app = create_app({'trakt_client_id': 'id', 'mcp_auth_token': 'x'*48}, tmp_path, backend)
        async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer '+'x'*48}
        ) as http:
            async with Client(streamable_http_client('http://testserver/mcp', http_client=http), mode=mode) as client:
                tools = {t.name: t for t in (await client.list_tools()).tools}
                for expected in TOOLS:
                    name, arguments, _, _ = expected
                    assert tools[name].annotations.read_only_hint is True
                    assert tools[name].output_schema is not None
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error, (name, str(result))
                    assert result.structured_content is not None
                    assert 'private-' not in str(result), name
                    if name == 'trakt_get_up_next':
                        assert result.structured_content['items'][0]['progress']['next_episode']['number'] == 2
                    if name == 'trakt_get_lists':
                        assert result.structured_content['items'][0]['ids']['trakt'] == 5
                    if name == 'trakt_get_list_items':
                        assert result.structured_content['items'][0]['notes'] == 'my-note'
                status = await client.call_tool('trakt_get_status', {})
                assert status.structured_content['server_version'] == VERSION
                assert status.structured_content['personal_cache']['entries'] == 0
    assert 'private-' not in caplog.text and 'my-note' not in caplog.text


@pytest.mark.asyncio
async def test_progress_paginates_episode_status_without_changing_whole_show_totals():
    calls = []
    def handler(request):
        calls.append(request)
        assert dict(request.url.params) == {'specials': 'true', 'hidden': 'true', 'count_specials': 'false'}
        return httpx.Response(200, json=progress())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        library = LibraryReader(TraktClient(http, FakeAuth(), 'id'))
        result = await library.show_progress('example', season=1, page=2, limit=2,
                                             specials=True, include_hidden=True, count_specials=False)
    assert [e['number'] for e in result['items']] == [3]
    assert result['items'][0]['season'] == 1
    assert result['summary']['completed'] == 1 and result['summary']['aired'] == 3
    assert result['summary']['next_episode'] == {'season': 1, 'number': 2}
    assert result['summary']['reset_at'] == '2026-01-01T00:00:00Z'
    assert result['next_page'] is None and result['total_items'] == 3
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_personal_pages_bypass_disk_cache_and_preserve_history_and_notes(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == '/users/me/history/movies/123'
        assert request.url.params['start_at'] == '2026-01-01T00:00:00Z'
        assert request.url.params['end_at'] == '2026-01-02T23:59:59.999999Z'
        return paginated([{'id': len(calls), 'action': 'scrobble', 'watched_at': '2026-01-01T12:00:00Z',
                            'movie': {'ids': {'trakt': 123}}}], pages=2, total=2)
    cache = PublicCache(tmp_path / 'public.sqlite3')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        library = LibraryReader(TraktClient(http, FakeAuth(), 'id', cache, personal_cache=True))
        for expected_id in (1, 2):
            result = await library.history('movies', limit=1, start_at='2026-01-01', end_at='2026-01-02', item_id='123')
            assert result['items'][0]['id'] == expected_id and result['next_page'] == 2
            assert result['items'][0]['action'] == 'scrobble'
        assert (await cache.status())['entries'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 204])
async def test_vip_stats_distinguish_missing_from_zero(status):
    payload = {'movies': {'watched': 0}, 'total_minutes': 0}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload) if status == 200 else httpx.Response(204))) as http:
        result = await LibraryReader(TraktClient(http, FakeAuth(), 'id')).stats()
    assert result['available'] == (status == 200)
    assert result['stats'] == payload if status == 200 else result['stats'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,args', [
    ('show_details', ('../oauth',)), ('season_episodes', ('example', -1)),
    ('episode_details', ('example', 1, 0)), ('show_ratings', ('example', None, 2)),
    ('list_items', ('../settings',)), ('hidden', ('comments',)),
    ('personal_ratings', ('../history',)), ('playback', ('shows',)),
    ('collection', ('../settings',)), ('calendar', ('shows', '2026-02-30')),
    ('calendar', ('shows', '2026-01-01', 32)),
    ('history', ('all', 1, 10, None, None, '123')),
])
async def test_invalid_identifiers_options_and_dates_never_reach_trakt(operation, args):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('Unexpected HTTP request'))) as http:
        library = LibraryReader(TraktClient(http, FakeAuth(), 'id'))
        with pytest.raises(TraktError):
            await getattr(library, operation)(*args)


def test_date_ranges_use_utc_and_reject_invalid_or_reversed_ranges():
    assert date_range('2026-01-01T02:00:00+02:00', '2026-01-01T00:00:00.1Z', timestamps=True) == {
        'start_at': '2026-01-01T00:00:00Z', 'end_at': '2026-01-01T00:00:00.100000Z'}
    for start, end in [('2026-02-02', '2026-02-01'), ('2026-02-30', None), ('2026-01-01T00:00:00', None)]:
        with pytest.raises(TraktError):
            date_range(start, end, timestamps=True)


@pytest.mark.asyncio
async def test_show_recommendations_exclude_started_watchlisted_hidden_and_dropped_and_keep_rank():
    def handler(request):
        path = request.url.path
        if path == '/recommendations/shows':
            return httpx.Response(200, json=[{**show(n), 'favorited_by': [{'notes': 'private-note'}],
                                             'recommended_by': [{'notes': 'private-note'}]} for n in range(1, 7)])
        mapping = {'/sync/watched/shows': 1, '/users/me/watchlist/shows/added': 2,
                   '/users/hidden/recommendations': 3, '/users/hidden/dropped': 4}
        return paginated([{'show': show(mapping[path])}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await LibraryReader(TraktClient(http, FakeAuth(), 'id')).show_recommendations(limit=1, exclude_watchlist=True)
    assert [item['ids']['trakt'] for item in result['items']] == [5]
    assert result['items'][0]['recommendation_rank'] == 5
    assert result['selection_truncated'] and result['available_after_exclusions'] == 2
    assert 'private-note' not in json.dumps(result)


@pytest.mark.asyncio
async def test_hidden_exclusion_fails_closed_when_pagination_is_missing():
    def handler(request):
        return httpx.Response(200, json=[show()] if '/recommendations/shows' in request.url.path else [])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TraktError, match='Pagination metadata missing'):
            await LibraryReader(TraktClient(http, FakeAuth(), 'id')).show_recommendations(exclude_started=False)


@pytest.mark.asyncio
async def test_private_library_results_reject_account_switch():
    auth = FakeAuth()
    auth.access_token = AsyncMock(side_effect=['one', 'one', 'two'])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))) as http:
        with pytest.raises(TraktError, match='authorization changed'):
            await LibraryReader(TraktClient(http, auth, 'id')).lists()


@pytest.mark.asyncio
async def test_progress_keeps_late_seasons_reachable_after_summary_truncation():
    data = progress()
    data['seasons'] = [{'number': n, 'episodes': [{'number': 1, 'completed': False}]} for n in range(1, 106)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))) as http:
        result = await LibraryReader(TraktClient(http, FakeAuth(), 'id')).show_progress('example', season=105)
    assert result['season_summaries_truncated'] and len(result['season_summaries']) == 100
    assert result['items'] == [{'season': 105, 'number': 1, 'completed': False}]


@pytest.mark.asyncio
async def test_global_calendar_needs_no_account_and_preserves_utc_dates():
    def handler(request):
        assert 'Authorization' not in request.headers
        assert request.url.path == '/calendars/all/shows/premieres/2026-01-01/7'
        assert 'page' not in request.url.params and 'limit' not in request.url.params
        return httpx.Response(200, json=[{'first_aired': '2026-01-01T23:30:00Z', 'show': show(), 'episode': {'number': 1}}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = FakeAuth()
        auth.access_token = AsyncMock(side_effect=TraktError('Not connected'))
        result = await LibraryReader(TraktClient(http, auth, 'id')).calendar('premieres', '2026-01-01', target='all')
    assert result['timezone'] == 'UTC' and result['items'][0]['first_aired'] == '2026-01-01T23:30:00Z'
    auth.access_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_upstream_cannot_expand_requested_output_limit():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: paginated([{'show': show(1)}, {'show': show(2)}]))) as http:
        with pytest.raises(TraktError, match='more items than'):
            await LibraryReader(TraktClient(http, FakeAuth(), 'id')).up_next(limit=1)


@pytest.mark.asyncio
async def test_hidden_read_and_exclusion_walk_multiple_pages():
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == '/recommendations/shows':
            return httpx.Response(200, json=[show(1), show(2), show(3)])
        if request.url.path.endswith('/dropped'):
            return paginated([])
        page = int(request.url.params['page'])
        return paginated([{'show': show(page)}], page=page, pages=2, total=2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await LibraryReader(TraktClient(http, FakeAuth(), 'id')).show_recommendations(exclude_started=False)
    assert [entry['ids']['trakt'] for entry in result['items']] == [3]
    assert sum(request.url.path.endswith('/recommendations') for request in calls) == 2


@pytest.mark.asyncio
async def test_sdk_rejects_bad_library_parameters_before_http(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('Unexpected HTTP request'))) as backend:
        Auth(backend, 'id', '', tmp_path/'oauth.json')._save(tokens())
        app = create_app({'trakt_client_id': 'id', 'mcp_auth_token': 'x'*48}, tmp_path, backend)
        async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer '+'x'*48}
        ) as http:
            async with Client(streamable_http_client('http://testserver/mcp', http_client=http)) as client:
                for name, arguments in [
                    ('trakt_get_calendar', {'days': 32}),
                    ('trakt_get_episode_details', {'show_id': 'example', 'season': -1, 'episode': 1}),
                    ('trakt_get_history', {'media_type': '../settings'}),
                    ('trakt_get_personal_ratings', {'media_type': 'users'}),
                    ('trakt_get_show_progress', {'show_id': '../settings'}),
                    ('trakt_get_collection', {'limit': 101}),
                ]:
                    result = await client.call_tool(name, arguments)
                    assert result.is_error, name


@pytest.mark.asyncio
@pytest.mark.parametrize('season,episode,suffix', [
    (None, None, ''), (0, None, '/seasons/0'), (1, 2, '/seasons/1/episodes/2'),
])
async def test_series_season_and_episode_scores_use_the_correct_public_endpoint(season, episode, suffix):
    def handler(request):
        assert request.url.path == '/shows/example' + suffix + '/ratings'
        assert request.url.params['extended'] == 'all'
        assert 'Authorization' not in request.headers
        return httpx.Response(200, json={'rating': 7.5, 'votes': 10,
                                       'rotten_tomatoes': {'rating': 90, 'user_rating': 80}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await LibraryReader(TraktClient(http, None, 'id')).show_ratings('example', season, episode)
    assert result['ratings']['trakt']['rating'] == 7.5
    assert result['ratings']['rotten_tomatoes'] == {'rating': 90, 'user_rating': 80}
    assert result['scales']['rotten_tomatoes'] == 100


@pytest.mark.asyncio
async def test_watched_show_aggregates_are_locally_paged_without_nested_history():
    def handler(request):
        assert request.url.path == '/sync/watched/shows'
        assert 'page' not in request.url.params and 'extended' not in request.url.params
        return httpx.Response(200, json=[{'show': show(n), 'plays': 5, 'last_watched_at': '2026-01-01T00:00:00Z',
                                         'seasons': [{'episodes': [{'number': 1}]}]} for n in range(3)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await LibraryReader(TraktClient(http, FakeAuth(), 'id')).watched_shows(page=2, limit=2)
    assert result['total_items'] == 3 and result['next_page'] is None
    assert result['items'] == [{'show': show(2), 'plays': 5, 'last_watched_at': '2026-01-01T00:00:00Z'}]
