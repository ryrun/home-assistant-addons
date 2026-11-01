import asyncio
import json
import time

import httpx
import pytest

from auth import Auth, AUTH_URL
from errors import TraktError


def tokens(access='private-access', refresh='private-refresh', expired=False):
    return dict(access_token=access, refresh_token=refresh, created_at=int(time.time()) - (1000 if expired else 0), expires_in=500)


@pytest.mark.asyncio
async def test_device_flow_keeps_secrets_private_and_handles_interval(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(AUTH_URL)
        if request.url.path.endswith('/code'):
            return httpx.Response(200, json=dict(device_code='private-device', user_code='ABCD', verification_url='https://auth.trakt.tv/activate', expires_in=600, interval=5))
        return httpx.Response(200, json=tokens())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = Auth(http, 'id', 'secret', tmp_path / 'oauth.json')
        assert 'private-device' not in json.dumps(await auth.start())
        assert (await auth.poll())['status'] == 'pending'
        assert len(calls) == 1
        auth.pending['next_poll'] = 0
        assert await auth.poll() == {'status': 'authorized'}
        assert auth.path.stat().st_mode & 0o777 == 0o600
        assert Auth(http, 'id', 'secret', auth.path).tokens == auth.tokens
        assert auth.pending is None


@pytest.mark.asyncio
@pytest.mark.parametrize('client_secret', ['', 'secret'])
async def test_parallel_refresh_rotates_only_once(tmp_path, client_secret):
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.01)
        expected = {
            'client_id': 'id', 'refresh_token': 'private-refresh',
            'grant_type': 'refresh_token', 'redirect_uri': 'http://localhost',
        }
        if client_secret:
            expected['client_secret'] = client_secret
        assert json.loads(request.content) == expected
        return httpx.Response(200, json=tokens('new', 'rotated'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = Auth(http, 'id', client_secret, tmp_path / 'oauth.json')
        auth._save(tokens(expired=True))
        assert await asyncio.gather(*(auth.access_token() for _ in range(8))) == ['new'] * 8
        assert len(calls) == 1
        assert json.loads(auth.path.read_text())['refresh_token'] == 'rotated'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [404, 409, 410, 418, 429, 400])
async def test_device_statuses(tmp_path, status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as http:
        auth = Auth(http, 'id', '', tmp_path / 'oauth.json')
        auth.pending = dict(code='private', expires=time.monotonic() + 100, next_poll=0, interval=5)
        if status in (400, 429):
            result = await auth.poll()
            assert result['retry_after_seconds'] == (10 if status == 429 else 5)
        else:
            with pytest.raises(TraktError):
                await auth.poll()
            assert auth.pending is None


@pytest.mark.asyncio
async def test_invalid_refresh_requires_new_login(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={'error': 'invalid_grant', 'error_description': 'secret-leak'}))) as http:
        auth = Auth(http, 'id', '', tmp_path / 'oauth.json')
        auth._save(tokens(expired=True))
        with pytest.raises(TraktError, match='authorization expired'):
            await auth.access_token()
        assert not auth.path.exists()


@pytest.mark.asyncio
async def test_rotated_tokens_survive_disk_write_failure_in_memory(tmp_path, monkeypatch):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=tokens('new', 'rotated')))) as http:
        auth = Auth(http, 'id', '', tmp_path / 'oauth.json')
        auth._save(tokens(expired=True))
        with monkeypatch.context() as patch:
            patch.setattr('auth.os.replace', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
            with pytest.raises(OSError):
                await auth.access_token()
        assert auth.tokens['refresh_token'] == 'rotated'
        assert await auth.access_token() == 'new'
        assert json.loads(auth.path.read_text())['refresh_token'] == 'rotated'


def test_corrupt_token_file_allows_reauthorization(tmp_path, caplog):
    path = tmp_path / 'oauth.json'
    path.write_text('{broken-secret')
    auth = Auth(None, 'id', '', path)
    assert auth.tokens is None
    assert 'Restart Trakt authorization' in caplog.text
    assert 'broken-secret' not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['refresh', 'start'])
async def test_oauth_rate_limit_blocks_repeated_requests_and_preserves_tokens(tmp_path, operation):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '120'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = Auth(http, 'id', '', tmp_path / 'oauth.json')
        auth._save(tokens(expired=True))
        original = auth.path.read_bytes()
        invoke = auth.access_token if operation == 'refresh' else auth.start
        with pytest.raises(TraktError):
            await invoke()
        with pytest.raises(TraktError, match='OAuth rate limit active'):
            await invoke()
        assert len(calls) == 1
        assert auth.path.read_bytes() == original
        assert auth.tokens is not None
        auth.rate_limit_until = 0
        with pytest.raises(TraktError):
            await invoke()
        assert len(calls) == 2
