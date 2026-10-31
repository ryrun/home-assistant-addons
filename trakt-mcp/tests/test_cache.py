import asyncio

import httpx
import pytest

from cache import PublicCache
from errors import TraktError
from trakt_client import TraktClient
from test_trakt_client import FakeAuth


@pytest.mark.asyncio
async def test_cache_persistence_ttl_and_pagination_headers(tmp_path):
    now = [1000]
    path = tmp_path / 'cache.sqlite3'
    cache = PublicCache(path, ttl=30, clock=lambda: now[0])
    response = httpx.Response(200, json=[{'id': 42}], headers={
        'X-Pagination-Page-Count': '3', 'Authorization': 'never-store-this'})
    await cache.put('key', response)
    reopened = PublicCache(path, ttl=30, clock=lambda: now[0])
    result = await reopened.get('key')
    assert result.json() == [{'id': 42}]
    assert result.headers['X-Pagination-Page-Count'] == '3'
    assert 'authorization' not in result.headers
    assert path.stat().st_mode & 0o777 == 0o600
    now[0] += 31
    assert await reopened.get('key') is None


@pytest.mark.asyncio
async def test_cache_bounded_and_manual_clear(tmp_path, monkeypatch):
    monkeypatch.setattr('cache.MAX_ENTRIES', 2)
    monkeypatch.setattr('cache.MAX_BYTES', 50)
    cache = PublicCache(tmp_path / 'cache.sqlite3')
    for n in range(4):
        await cache.put(str(n), httpx.Response(200, json={'id': n}))
    assert (await cache.status())['entries'] == 2
    await cache.clear()
    assert (await cache.status())['entries'] == 0
    await cache.put('oversized', httpx.Response(200, json={'large': 'x' * 100}))
    assert await cache.get('oversized') is None


@pytest.mark.asyncio
async def test_concurrent_public_requests_coalesce_but_personal_lists_stay_fresh(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=[])
    cache = PublicCache(tmp_path / 'cache.sqlite3')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id', cache)
        await asyncio.gather(*(client.details('123') for _ in range(5)))
        assert len(calls) == 1
        await client.watched()
        await client.watched()
        assert len(calls) == 3
        assert (await cache.status())['entries'] == 1
        await cache.clear()
        await client.details('123')
        assert len(calls) == 4


@pytest.mark.asyncio
async def test_upstream_errors_are_not_cached(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(404) if len(calls) == 1 else httpx.Response(200, json={'title': 'OK'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id', PublicCache(tmp_path / 'cache.sqlite3'))
        with pytest.raises(TraktError):
            await client.details('123')
        assert (await client.details('123'))['title'] == 'OK'
