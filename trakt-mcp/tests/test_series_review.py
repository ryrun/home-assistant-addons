import asyncio

import httpx
import pytest

from errors import TraktError
from library import LibraryReader
from metrics import Metrics
from server import safe_tool
from test_library import paginated, show
from test_trakt_client import FakeAuth
from trakt_client import TraktClient


@pytest.mark.asyncio
@pytest.mark.parametrize('method,args', [
    ('up_next', ()), ('history', ()), ('list_items', ('my-list',)),
    ('collection', ('movies',)), ('collection', ('episodes',)), ('playback', ()),
])
async def test_paged_personal_endpoints_never_claim_completeness_without_headers(method, args):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{'show': show()}]))) as http:
        with pytest.raises(TraktError, match='Pagination metadata missing'):
            await getattr(LibraryReader(TraktClient(http, FakeAuth(), 'id')), method)(*args)


@pytest.mark.parametrize('items,page,pages,size,total', [
    ([1], 1, 1, 2, 2), ([1, 2], 1, 1, 2, 4),
    ([], 2, 2, 2, 4), ([1, 2, 3], 1, 2, 2, 3),
])
def test_inconsistent_pagination_does_not_hide_missing_items(items, page, pages, size, total):
    response = httpx.Response(200, json=items, headers={
        'X-Pagination-Page': str(page), 'X-Pagination-Page-Count': str(pages),
        'X-Pagination-Limit': str(size), 'X-Pagination-Item-Count': str(total),
    })
    with pytest.raises(TraktError, match='pagination|Pagination'):
        TraktClient._decode_page(response, page, 100)


def test_partial_headers_are_not_misread_as_a_complete_unpaginated_array():
    response = httpx.Response(200, json=[1], headers={'X-Pagination-Page': '1', 'X-Pagination-Item-Count': '10'})
    with pytest.raises(TraktError, match='Incomplete Trakt pagination'):
        TraktClient._decode_page(response, 1, 10)


@pytest.mark.parametrize('pages,size', [(0, 0), (0, 50), (1, 50)])
def test_legitimate_empty_pagination_is_preserved(pages, size):
    response = httpx.Response(200, json=[], headers={'X-Pagination-Page-Count': str(pages),
                              'X-Pagination-Limit': str(size), 'X-Pagination-Item-Count': '0'})
    result = TraktClient._decode_page(response, 1, 50)
    assert result['items'] == [] and result['next_page'] is None


@pytest.mark.asyncio
async def test_changed_activity_rejects_series_recommendations_after_exclusions():
    checks = 0
    def handler(request):
        nonlocal checks
        if request.url.path == '/sync/last_activities':
            checks += 1
            return httpx.Response(200, json={'all': f'2026-01-01T00:00:0{checks}Z'})
        if request.url.path == '/recommendations/shows':
            return httpx.Response(200, json=[show()])
        return paginated([])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TraktError, match='activity changed'):
            await LibraryReader(TraktClient(http, FakeAuth(), 'id')).show_recommendations()
    assert checks == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('stamp', [None, 'private-malformed-timestamp', '2026-01-01T00:00:00'])
async def test_unverifiable_activity_fails_without_echoing_upstream_values(stamp):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'all': stamp}))) as http:
        with pytest.raises(TraktError, match='activity timestamp') as error:
            await LibraryReader(TraktClient(http, FakeAuth(), 'id')).show_recommendations()
    assert 'private-' not in str(error.value)


@pytest.mark.asyncio
async def test_shared_tool_slots_bound_parallel_handlers_and_survive_cancellation():
    slots = asyncio.Semaphore(2)
    entered = asyncio.Event()
    release = asyncio.Event()
    active = maximum = started = 0
    async def first():
        nonlocal active, maximum, started
        active += 1
        started += 1
        maximum = max(maximum, active)
        if started == 2:
            entered.set()
        try:
            await release.wait()
            return {'ok': True}
        finally:
            active -= 1
    async def second():
        return await first()
    metrics = Metrics()
    functions = [safe_tool(first, slots=slots, metrics=metrics), safe_tool(second, slots=slots, metrics=metrics)]
    tasks = [asyncio.create_task(functions[n % 2]()) for n in range(8)]
    await asyncio.wait_for(entered.wait(), 1)
    assert started == 2 and active == 2
    tasks[-1].cancel()
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert maximum == 2 and started == 7
    assert sum(isinstance(value, asyncio.CancelledError) for value in results) == 1
    assert metrics.snapshot()['tools']['active'] == 0
    assert await functions[0]() == {'ok': True}  # No leaked permit after cancellation.


@pytest.mark.asyncio
async def test_tool_timeout_includes_queue_wait(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError
    timeout = asyncio.timeout
    monkeypatch.setattr('server.asyncio.timeout', lambda _: timeout(0.01))
    called = False
    async def function():
        nonlocal called
        called = True
    metrics = Metrics()
    with pytest.raises(ToolError, match='timed out'):
        await safe_tool(function, slots=asyncio.Semaphore(0), metrics=metrics)()
    assert not called
    assert metrics.snapshot()['tools']['active'] == 0
    assert metrics.snapshot()['tools']['errors'] == 1


def test_pagination_mismatch_reports_only_numeric_diagnostics():
    response = httpx.Response(200, json=[{'title': 'private-title'}], headers={
        'X-Pagination-Page': '1', 'X-Pagination-Page-Count': '2',
        'X-Pagination-Limit': '50', 'X-Pagination-Item-Count': '60',
    })
    with pytest.raises(TraktError) as error:
        TraktClient._decode_page(response, 1, 50)
    message = str(error.value)
    for detail in ('page=1', 'page_count=2', 'upstream_limit=50',
                   'total_items=60', 'received_items=1', 'requested_limit=50'):
        assert detail in message
    assert 'private-title' not in message
