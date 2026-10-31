"""Account-bound RAM snapshots, validated against Trakt activity on every use."""
import asyncio
from collections import OrderedDict
from datetime import datetime
import hashlib
import json
import time

from errors import TraktError, json_data

MAX_SNAPSHOT_AGE = 900
MAX_PERSONAL_BYTES = 16 * 1024 * 1024


class PersonalSnapshots:
    def __init__(self, client):
        self.client = client
        self.lock = asyncio.Lock()
        self.entries = OrderedDict()
        self.identity = None
        self.hits = self.misses = 0

    async def _identity(self):
        token = await self.client.auth.access_token()
        return hashlib.sha256((self.client.headers['trakt-api-key'] + ':' + token).encode()).hexdigest()

    async def _activity(self):
        data = json_data(await self.client.get('/sync/last_activities', personal=True))
        stamp = data.get('all') if isinstance(data, dict) else None
        try:
            parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError()
        except (AttributeError, ValueError, TypeError):
            raise TraktError('Trakt activity timestamps are missing or invalid. Freshness cannot be verified.') from None
        return stamp

    async def load(self, path):
        async with self.lock:
            identity = await self._identity()
            if identity != self.identity:
                self.entries.clear()
                self.identity = identity
            stamp = await self._activity()
            entry = self.entries.get(path)
            if entry and entry[0] == stamp and time.monotonic() - entry[2] < MAX_SNAPSHOT_AGE:
                if await self._identity() != identity:
                    raise TraktError('Trakt authorization changed during the request. Retry.')
                self.hits += 1
                self.entries.move_to_end(path)
                return json.loads(entry[1]), stamp
            self.misses += 1
            items = await self.client._all_items_live(path, extended=path != '/sync/watched/movies')
            after = await self._activity()
            if after != stamp or await self._identity() != identity:
                raise TraktError('Trakt data or authorization changed during sync. Retry for a consistent snapshot.')
            body = json.dumps(items, separators=(',', ':')).encode()
            self.entries.pop(path, None)
            if len(body) <= MAX_PERSONAL_BYTES:
                self.entries[path] = (stamp, body, time.monotonic())
                while sum(len(entry[1]) for entry in self.entries.values()) > MAX_PERSONAL_BYTES:
                    self.entries.popitem(last=False)
            return items, stamp

    async def clear(self):
        async with self.lock:
            self.entries.clear()
            self.identity = None

    def status(self):
        return {'enabled': True, 'scope': 'account_bound_ram', 'entries': len(self.entries),
                'response_bytes': sum(len(e[1]) for e in self.entries.values()),
                'hits': self.hits, 'misses': self.misses, 'validation': 'trakt:/sync/last_activities'}
