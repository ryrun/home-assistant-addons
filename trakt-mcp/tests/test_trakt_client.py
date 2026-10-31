import httpx
import pytest

from errors import TraktError
from trakt_client import TraktClient


class FakeAuth:
    def __init__(self):
        self.calls = []
    async def access_token(self, rejected_token=None):
        self.calls.append(rejected_token)
        return 'new' if rejected_token else 'old'


def movie(identifier, **kwargs):
    return dict(ids={'trakt': identifier}, title=f'Movie {identifier}', year=2024,
                genres=['mystery'], rating=8, **kwargs)


@pytest.mark.asyncio
async def test_server_capped_pagination_and_complete_exclusions():
    def handler(request):
        page = int(request.url.params['page'])
        if '/watched/' in request.url.path:
            return httpx.Response(200, json=[{'movie': movie(page)}], headers={
                'X-Pagination-Page-Count': '2', 'X-Pagination-Page': str(page),
                'X-Pagination-Limit': '1', 'X-Pagination-Item-Count': '2'})
        assert request.url.params['ratings'] == '70-100'
        assert request.url.params['genres'] == 'mystery'
        return httpx.Response(200, json=[movie(1), movie(2), movie(3)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id')
        result = await client.candidates(['mystery'], 2020, 2025, 7)
        assert [m['ids']['trakt'] for m in result['items']] == [3]


@pytest.mark.asyncio
async def test_unpaginated_watched_and_watchlist_filters():
    def handler(request):
        if 'watchlist' in request.url.path:
            assert request.url.params['years'] == '2024'
            assert request.url.params['genres'] == 'mystery'
        return httpx.Response(200, json=[{'movie': movie(n)} for n in range(5)],
                              headers={'X-Pagination-Page-Count': '1'} if 'watchlist' in request.url.path else {})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id')
        result = await client.watched(2, 2)
        assert len(result['items']) == 2 and result['next_page'] == 3
        assert len(await client.all_items('/sync/watched/movies')) == 5
        await client.watchlist(year=2024, genres=['mystery'])


@pytest.mark.asyncio
async def test_401_refresh_retry():
    def handler(request):
        return httpx.Response(401) if request.headers['Authorization'] == 'Bearer old' else httpx.Response(200, json=[])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = FakeAuth()
        await TraktClient(http, auth, 'id').watched()
        assert auth.calls == [None, 'old']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
async def test_errors_do_not_leak_bodies(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, text='supersecret'))) as http:
        with pytest.raises(TraktError) as error:
            await TraktClient(http, FakeAuth(), 'id').details('123')
        assert 'supersecret' not in str(error.value)


@pytest.mark.asyncio
async def test_timeout_sanitized_and_invalid_path_blocked():
    def handler(request):
        raise httpx.ReadTimeout('supersecret', request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id')
        with pytest.raises(TraktError, match='Zeitüberschreitung'):
            await client.details('123')
        with pytest.raises(TraktError, match='Film-ID'):
            await client.details('../oauth')


@pytest.mark.asyncio
async def test_incomplete_exclusion_fails_closed():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{'movie': {'ids': {}}}]))) as http:
        with pytest.raises(TraktError, match='Ausschluss'):
            await TraktClient(http, FakeAuth(), 'id').candidates()


@pytest.mark.asyncio
async def test_related_candidates_and_people_use_correct_endpoints():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/people'):
            return httpx.Response(200, json={'crew': {'directing': [{'jobs': ['Director'], 'person': {'name': 'Example'}}]}})
        if '/watched/' in request.url.path:
            return httpx.Response(200, json=[{'movie': movie(1)}])
        assert 'years' not in request.url.params  # Related endpoint supports no genre/year filters.
        return httpx.Response(200, json=[movie(1), movie(2), {**movie(3), 'year': 1990}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id')
        result = await client.candidates(['mystery'], 2020, source='related', seed_movie_id='123')
        assert result['source'] == 'trakt:/movies/123/related'
        assert [m['ids']['trakt'] for m in result['items']] == [2]
        assert (await client.people('123'))['items'][0]['jobs'] == ['Director']
        assert paths[-1] == '/movies/123/people'
        with pytest.raises(TraktError, match='seed_movie_id'):
            await client.candidates(source='related')


@pytest.mark.asyncio
async def test_trending_unwraps_movies():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{'watchers': 42, 'movie': movie(5)}]))) as http:
        result = await TraktClient(http, FakeAuth(), 'id').candidates(source='trending', exclude_watched=False)
        assert result['items'][0]['ids']['trakt'] == 5
        assert result['source'] == 'trakt:/movies/trending'


@pytest.mark.asyncio
async def test_retry_transient_get_but_never_retry_rate_limit():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await TraktClient(http, FakeAuth(), 'id').details('123')
        assert len(calls) == 2
    calls.clear()
    def limited(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '60'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(limited)) as http:
        client = TraktClient(http, FakeAuth(), 'id')
        for _ in range(2):
            with pytest.raises(TraktError, match='60'):
                await client.details('123')
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_pagination_mismatch_fails_instead_of_incomplete_exclusion():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{'movie': movie(1)}], headers={
        'X-Pagination-Page': '1', 'X-Pagination-Page-Count': '2'}))) as http:
        with pytest.raises(TraktError, match='Pagination'):
            await TraktClient(http, FakeAuth(), 'id').candidates()


@pytest.mark.asyncio
async def test_redirect_is_rejected():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'Location': 'https://evil.example'}))) as http:
        with pytest.raises(TraktError):
            await TraktClient(http, FakeAuth(), 'id').details('123')


@pytest.mark.asyncio
async def test_changed_personal_list_is_not_treated_as_complete():
    def handler(request):
        page = int(request.url.params['page'])
        return httpx.Response(200, json=[{'movie': movie(page)}], headers={
            'X-Pagination-Page': str(page), 'X-Pagination-Page-Count': '2',
            'X-Pagination-Item-Count': str(page + 1)})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TraktError, match='geändert'):
            await TraktClient(http, FakeAuth(), 'id').candidates()


@pytest.mark.asyncio
async def test_explicit_favorites_are_personal_paginated_and_not_cached(tmp_path):
    from cache import PublicCache
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == '/users/me/favorites/movies/rank'
        assert request.headers['Authorization'] == 'Bearer old'
        return httpx.Response(200, json=[{'rank': 1, 'movie': movie(7)}], headers={
            'X-Pagination-Page': '1', 'X-Pagination-Page-Count': '2', 'X-Pagination-Limit': '1'})
    cache = PublicCache(tmp_path / 'cache.sqlite3')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id', cache)
        for _ in range(2):
            result = await client.favorites(limit=1)
            assert result['items'][0]['rank'] == 1
            assert result['next_page'] == 2
        assert len(requests) == 2
        assert (await cache.status())['entries'] == 0


@pytest.mark.asyncio
async def test_person_filmography_preserves_jobs_and_characters():
    payload = {'cast': [{'movie': movie(1), 'characters': ['Lead']}],
               'crew': {'directing': [{'movie': movie(2), 'jobs': ['Director']}]}}
    def handler(request):
        assert request.url.path == '/people/example-person/movies'
        assert 'Authorization' not in request.headers
        assert request.url.params['extended'] == 'full'
        return httpx.Response(200, json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id')
        assert (await client.person_movies('example-person'))['total_items'] == 2
        with pytest.raises(TraktError):
            await client.person_movies('../oauth')


@pytest.mark.asyncio
async def test_personal_recommendations_preserve_rank_exclude_and_remove_other_user_notes(tmp_path):
    from cache import PublicCache
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == 'GET'
        assert request.headers['Authorization'] == 'Bearer old'
        if request.url.path == '/recommendations/movies':
            assert request.url.params['ignore_watchlisted'] == 'true'
            return httpx.Response(200, json=[movie(3), movie(1), movie(2),
                {**movie(4), 'favorited_by': [{'notes': 'private-other-user'}]}, movie(3)])
        if '/watched/' in request.url.path:
            return httpx.Response(200, json=[{'movie': movie(1)}])
        assert 'watchlist' in request.url.path
        return httpx.Response(200, json=[{'movie': movie(2)}], headers={'X-Pagination-Page-Count': '1'})
    cache = PublicCache(tmp_path / 'cache.sqlite3')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id', cache)
        result = await client.recommendations(10, exclude_watchlist=True)
        assert [m['ids']['trakt'] for m in result['items']] == [3, 4]
        assert 'private-other-user' not in str(result)
        assert result['candidates_received'] == 5
        assert (await cache.status())['entries'] == 0
