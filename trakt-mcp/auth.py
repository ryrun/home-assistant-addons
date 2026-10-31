"""Device authorization and atomic, private storage of rotating OAuth tokens."""
import asyncio
import json
import hashlib
import re
from urllib.parse import urlsplit
import math
import logging
import os
from pathlib import Path
import tempfile
import time
import sys

import httpx

from errors import TraktError, check_response, json_data
from http_utils import bounded_request, retry_after

AUTH_URL = 'https://auth.trakt.tv/oauth'


class Auth:
    def __init__(self, http: httpx.AsyncClient, client_id: str, client_secret: str, path: Path, metrics=None):
        self.http, self.client_id, self.client_secret = http, client_id, client_secret
        self.path = path
        self.metrics = metrics
        self.lock = asyncio.Lock()
        self.pending = None
        self.tokens = None
        self._needs_save = False
        try:
            path.chmod(0o600)
            saved = json.loads(path.read_text())
            self.tokens = self._validate(saved)
            if saved.get('client_id_hash', self._client_hash()) != self._client_hash():
                self.tokens = None
                logging.getLogger('trakt_mcp').warning('Trakt client ID changed. Authorize the configured application again; old token file retained.')
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError):
            self.tokens = None
            logging.getLogger('trakt_mcp').warning('Token-Datei ungültig. Trakt-Anmeldung über die Add-on-Konfiguration erneut starten.')

    def _client_hash(self):
        return hashlib.sha256(self.client_id.encode()).hexdigest()

    @staticmethod
    def _validate(data):
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and 1 <= len(data[k]) <= 4096 and all(33 <= ord(c) <= 126 for c in data[k]) for k in ('access_token', 'refresh_token')):
            raise ValueError('Invalid tokens')
        if not all(type(data.get(k)) in (int, float) and math.isfinite(data[k]) and data[k] >= 0 for k in ('created_at', 'expires_in')):
            raise ValueError('Invalid expiration')
        if data['expires_in'] <= 0:
            raise ValueError('Invalid expiration')
        return {k: data[k] for k in ('access_token', 'refresh_token', 'created_at', 'expires_in')}

    def _save(self, data):
        try:
            tokens = self._validate(data)
        except (ValueError, TypeError):
            raise TraktError('Trakt lieferte unvollständige Anmeldedaten.') from None
        # Keep rotated tokens in memory even if disk persistence fails. Retry saving
        # before the next authenticated request, instead of reusing an invalid refresh token.
        self.tokens = tokens
        self._needs_save = True
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.oauth-')
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump({**tokens, 'client_id_hash': self._client_hash()}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            if sys.platform.startswith('linux'):
                directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            self._needs_save = False
        finally:
            if os.path.exists(name):
                os.unlink(name)

    async def _post(self, endpoint, payload):
        try:
            return await bounded_request(self.http, 'POST', AUTH_URL + endpoint, json=payload, max_bytes=65536, metrics=self.metrics, service='oauth',
                                         expected_statuses=(400,) if endpoint == '/device/token' else ())
        except httpx.RequestError:
            raise TraktError('Trakt-Anmeldedienst nicht erreichbar. Bitte erneut versuchen.') from None

    async def start(self):
        async with self.lock:
            response = await self._post('/device/code', {'client_id': self.client_id})
            check_response(response)
            data = json_data(response)
            try:
                if not isinstance(data, dict):
                    raise ValueError()
                if not isinstance(data['verification_url'], str) or any(not 33 <= ord(c) <= 126 for c in data['verification_url']):
                    raise ValueError()
                url = urlsplit(data['verification_url'])
                if (url.scheme != 'https' or url.netloc not in ('auth.trakt.tv', 'trakt.tv')
                        or url.path.rstrip('/') != '/activate' or url.query or url.fragment):
                    raise ValueError()
                if (not isinstance(data['device_code'], str) or not 1 <= len(data['device_code']) <= 4096
                        or any(not 33 <= ord(c) <= 126 for c in data['device_code'])
                        or not isinstance(data['user_code'], str)
                        or not re.fullmatch(r'[A-Za-z0-9-]{1,32}', data['user_code'])
                        or type(data['interval']) is not int or not 1 <= data['interval'] <= 3600
                        or type(data['expires_in']) is not int or not data['interval'] <= data['expires_in'] <= 86400):
                    raise ValueError()
                self.pending = {
                    'code': data['device_code'], 'interval': data['interval'],
                    'expires': time.monotonic() + data['expires_in'],
                    'next_poll': time.monotonic() + data['interval'],
                }
                return {k: data[k] for k in ('user_code', 'verification_url', 'expires_in', 'interval')}
            except (KeyError, TypeError, ValueError):
                self.pending = None
                raise TraktError('Trakt lieferte unvollständige Gerätecodes.') from None

    async def poll(self):
        async with self.lock:
            pending = self.pending
            if not pending or time.monotonic() >= pending['expires']:
                self.pending = None
                raise TraktError('Keine laufende Anmeldung. Bitte trakt_auth_start aufrufen.')
            wait = pending['next_poll'] - time.monotonic()
            if wait > 0:
                return {'status': 'pending', 'retry_after_seconds': max(1, int(wait) + 1)}
            payload = {'code': pending['code'], 'client_id': self.client_id}
            if self.client_secret:
                payload['client_secret'] = self.client_secret
            pending['next_poll'] = time.monotonic() + pending['interval']
            response = await self._post('/device/token', payload)
            if response.status_code in (400, 429):
                if response.status_code == 429:
                    pending['interval'] = max(pending['interval'] + 5, retry_after(response.headers, pending['interval'] + 5))
                    pending['next_poll'] = time.monotonic() + pending['interval']
                return {'status': 'pending', 'retry_after_seconds': pending['interval']}
            if response.status_code in (404, 409, 410, 418):
                self.pending = None
                raise TraktError('Geräteanmeldung abgelehnt, abgelaufen oder bereits verwendet. Bitte neu starten.')
            check_response(response)
            self._save(json_data(response))
            self.pending = None
            return {'status': 'authorized'}

    async def access_token(self, rejected_token=None):
        async with self.lock:
            if not self.tokens:
                raise TraktError('Trakt is not connected. Authorize through Home Assistant, or trakt_auth_start if enabled.')
            if self._needs_save:
                self._save(self.tokens)
            tokens = self.tokens
            if tokens['created_at'] + tokens['expires_in'] > time.time() + 120 and (
                rejected_token is None or rejected_token != tokens['access_token']
            ):
                return tokens['access_token']
            payload = {'client_id': self.client_id, 'refresh_token': tokens['refresh_token'], 'grant_type': 'refresh_token',
                       'redirect_uri': 'http://localhost'}
            if self.client_secret:
                payload['client_secret'] = self.client_secret
            response = await self._post('/token', payload)
            if response.status_code in (400, 401):
                try:
                    error = response.json().get('error')
                except (ValueError, AttributeError):
                    error = None
                if error == 'invalid_grant':
                    self.tokens = None
                    self.path.unlink(missing_ok=True)
                    raise TraktError('Trakt authorization expired. Authorize again through Home Assistant or MCP.')
                raise TraktError('Trakt token refresh rejected. Check client configuration; saved tokens were retained.')
            check_response(response)
            self._save(json_data(response))
            return self.tokens['access_token']
