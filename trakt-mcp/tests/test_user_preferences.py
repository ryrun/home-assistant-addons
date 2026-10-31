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
from server import create_app
from test_auth import tokens
from test_trakt_client import FakeAuth
from trakt_client import TraktClient


@pytest.mark.asyncio
async def test_preferences_are_live_authenticated_and_exclude_unrelated_account_data(tmp_path):
    payload = {
        'user': {'email': 'private-email', 'dob': 'private-birthday'},
        'account': {'token': 'private-token', 'share_code': 'private-share-code'},
        'connections': {'future_credentials': 'private-credentials'},
        'browsing': {
            'genres': {'favorites': ['mystery'], 'disliked': ['horror'], 'future': 'private-value'},
            'watchnow': {'country': 'de', 'favorites': ['netflix'], 'only_favorites': False,
                         'future_secret': 'private-secret'},
            'comments': {'blocked_uids': ['private-id']},
        },
    }
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == 'GET'
        assert request.url.path == '/users/settings'
        assert dict(request.url.params) == {'extended': 'browsing'}
        assert request.headers['Authorization'] == 'Bearer old'
        return httpx.Response(200, json=payload)
    cache = PublicCache(tmp_path / 'public.sqlite3')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TraktClient(http, FakeAuth(), 'id', cache, personal_cache=True)
        first = await client.user_preferences()
        assert first['genres'] == {'favorites': ['mystery'], 'disliked': ['horror']}
        assert first['streaming'] == {'country': 'DE', 'favorite_sources': ['netflix'], 'only_favorites': False}
        payload['browsing']['genres']['favorites'] = ['science-fiction']
        assert (await client.user_preferences())['genres']['favorites'] == ['science-fiction']
        assert len(calls) == 2
        assert (await cache.status())['entries'] == 0
        assert client.snapshots.status()['entries'] == 0
        assert 'private-' not in json.dumps(first)
        assert 'private-' not in cache.path.read_bytes().decode(errors='ignore')


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'browsing': None}, {'browsing': {'genres': None, 'watchnow': None}}])
async def test_missing_settings_are_unknown_not_invented(payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        result = await TraktClient(http, FakeAuth(), 'id').user_preferences()
    assert result['genres'] == {'favorites': None, 'disliked': None}
    assert result['streaming'] == {'country': None, 'favorite_sources': None, 'only_favorites': None}


@pytest.mark.asyncio
async def test_empty_selections_and_false_remain_explicit():
    payload = {'browsing': {'genres': {'favorites': [], 'disliked': []},
                            'watchnow': {'country': '', 'favorites': [], 'only_favorites': False}}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        result = await TraktClient(http, FakeAuth(), 'id').user_preferences()
    assert result['genres'] == {'favorites': [], 'disliked': []}
    assert result['streaming'] == {'country': None, 'favorite_sources': [], 'only_favorites': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    [], {'browsing': []}, {'browsing': {'genres': []}},
    {'browsing': {'genres': {'favorites': 'private-value'}}},
    {'browsing': {'genres': {'disliked': [123]}}},
    {'browsing': {'watchnow': {'favorites': ['private-value\n']}}},
    {'browsing': {'watchnow': {'favorites': ['x' * 257]}}},
    {'browsing': {'watchnow': {'country': 'private-value'}}},
    {'browsing': {'watchnow': {'only_favorites': 1}}},
])
async def test_invalid_preferences_fail_without_echoing_response_values(payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
        with pytest.raises(TraktError) as error:
            await TraktClient(http, FakeAuth(), 'id').user_preferences()
    assert 'private-value' not in str(error.value)


@pytest.mark.asyncio
async def test_preferences_reject_authorization_change_during_request():
    auth = FakeAuth()
    auth.access_token = AsyncMock(side_effect=['first-account', 'first-account', 'other-account'])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as http:
        with pytest.raises(TraktError, match='authorization changed'):
            await TraktClient(http, auth, 'id').user_preferences()


@pytest.mark.asyncio
async def test_preferences_over_mcp_without_private_logs(tmp_path, caplog):
    caplog.set_level('INFO', logger='trakt_mcp')
    def handler(request):
        assert request.url.host == 'api.trakt.tv'
        assert request.url.path == '/users/settings'
        assert request.headers['Authorization'] == 'Bearer private-access'
        return httpx.Response(200, json={'account': {'token': 'private-account-token'},
                                       'browsing': {'genres': {'favorites': ['mystery']},
                                                    'watchnow': {'country': 'DE', 'favorites': ['netflix']}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        Auth(upstream, 'id', '', tmp_path / 'oauth.json')._save(tokens())
        app = create_app({'trakt_client_id': 'id', 'mcp_auth_token': 'x' * 48}, tmp_path, upstream)
        async with app.app.router.lifespan_context(app.app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={'Authorization': 'Bearer ' + 'x' * 48}
        ) as http:
            async with Client(streamable_http_client('http://testserver/mcp', http_client=http)) as client:
                result = await client.call_tool('trakt_get_user_preferences', {})
                assert not result.is_error
                assert result.structured_content['genres']['favorites'] == ['mystery']
                assert result.structured_content['streaming']['favorite_sources'] == ['netflix']
                assert 'private-' not in str(result)
                status = await client.call_tool('trakt_get_status', {})
                assert status.structured_content['streaming_availability_supported'] is False
    assert 'trakt_get_user_preferences' in caplog.text
    assert 'private-' not in caplog.text
    assert 'netflix' not in caplog.text and 'mystery' not in caplog.text
