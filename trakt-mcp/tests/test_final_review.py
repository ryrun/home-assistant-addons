import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from auth import Auth
from cache import PublicCache
from errors import TraktError
from server import create_app
from test_auth import tokens
from test_trakt_client import FakeAuth, movie
from trakt_client import TraktClient


@pytest.mark.parametrize('option,value', [
    ('mcp_auth_token', 'x'*40+'\0'), ('mcp_auth_token', 'x'*513),
    ('trakt_client_id', 'bad\nclient'), ('authorize_trakt', 'false'),
    ('enable_mcp_auth_tools', 'false'), ('allowed_networks', '192.168.0.0/16'),
])
def test_invalid_configuration_is_rejected_without_echoing_values(tmp_path, option, value):
    with pytest.raises(TraktError) as error:
        create_app({'trakt_client_id': 'id', 'mcp_auth_token': 'x'*48, option: value}, tmp_path)
    assert value not in str(error.value)


def test_tokens_are_bound_to_the_configured_application(tmp_path):
    path = tmp_path/'oauth.json'
    auth = Auth(None, 'first-app', '', path)
    auth._save(tokens())
    assert Auth(None, 'first-app', '', path).tokens
    assert Auth(None, 'other-app', '', path).tokens is None
    assert path.exists()  # Retain for restoration if configuration was changed accidentally.
    assert 'client_id_hash' in json.loads(path.read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'verification_url': 'https://evil.example/activate'},
    {'verification_url': 'https://auth.trakt.tv/\nactivate'},
    {'interval': -1}, {'expires_in': 0}, {'user_code': '<script>'},
])
async def test_invalid_device_data_never_reaches_clients(tmp_path, change):
    payload = dict(device_code='private-device-code', user_code='ABCD', interval=5,
                   expires_in=600, verification_url='https://auth.trakt.tv/activate') | change
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        auth = Auth(http, 'id', '', tmp_path/'oauth.json')
        with pytest.raises(TraktError) as error:
            await auth.start()
        assert auth.pending is None
        assert 'private-device-code' not in str(error.value)
        assert 'evil.example' not in str(error.value)


@pytest.mark.asyncio
async def test_clear_cache_prevents_an_inflight_lookup_from_repopulating(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def handler(request):
        calls.append(request)
        started.set()
        await release.wait()
        return httpx.Response(200, json={'title': 'Example'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        cache = PublicCache(tmp_path/'cache.sqlite3')
        client = TraktClient(http, FakeAuth(), 'id', cache)
        pending = asyncio.create_task(client.details('1'))
        await started.wait()
        await cache.clear()
        release.set()
        await pending
        assert (await cache.status())['entries'] == 0
        await client.details('1')
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_compound_preferences_reject_account_change_with_identical_timestamps():
    auth = FakeAuth()
    client = TraktClient(None, auth, 'id', personal_cache=True)
    stamp = '2026-10-31T00:00:00Z'
    async def ratings_then_favorites(path):
        if 'ratings' in path:
            client.snapshots.identity = 'first-account'
            return [{'movie': movie(1), 'rating': 10}], stamp
        client.snapshots.identity = 'other-account'
        return [{'movie': movie(2)}], stamp
    client.snapshots.load = AsyncMock(side_effect=ratings_then_favorites)
    with pytest.raises(TraktError, match='changed during lookup'):
        await client.preference_data()


@pytest.mark.asyncio
async def test_full_personal_list_rejects_missing_pagination_headers():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{'movie': movie(1)}]))) as http:
        with pytest.raises(TraktError, match='completeness'):
            await TraktClient(http, FakeAuth(), 'id').all_items('/users/me/watchlist/movies/added')
