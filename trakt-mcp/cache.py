"""Bounded public SQLite cache. Reads never perform housekeeping writes."""
import asyncio
from contextlib import closing
import json
import os
import sqlite3
import threading
import time

import httpx

MAX_ENTRIES = 256
MAX_BYTES = 16 * 1024 * 1024
MAX_ENTRY_BYTES = 512 * 1024


class PublicCache:
    def __init__(self, path, ttl=3600, clock=time.time):
        self.path, self.ttl, self.clock = path, ttl, clock
        self.lock = threading.Lock()
        self.hits = self.misses = 0
        self.generation = 0
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        path.chmod(0o600)
        try:
            self._run('init')
        except sqlite3.DatabaseError:
            # Public data is disposable. Keep one private backup for inspection.
            os.replace(path, path.with_suffix('.corrupt'))
            fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
            self._run('init')

    def _run(self, operation, key=None, response=None, ttl=None, generation=None):
        with self.lock, closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            if operation == 'init':
                db.execute('CREATE TABLE IF NOT EXISTS responses '
                           '(key TEXT PRIMARY KEY, stored REAL, body BLOB, headers TEXT, expires REAL)')
                columns = {r[1] for r in db.execute('PRAGMA table_info(responses)')}
                if 'expires' not in columns:
                    db.execute('ALTER TABLE responses ADD COLUMN expires REAL')
                    db.execute('UPDATE responses SET expires = stored + ?', (self.ttl,))
                db.execute('CREATE INDEX IF NOT EXISTS cache_expiry ON responses(expires)')
                return
            now = self.clock()
            if operation == 'get':
                row = db.execute('SELECT body, headers FROM responses WHERE key = ? '
                                 'AND expires > ? AND stored <= ? AND stored > ?',
                                 (key, now, now, now - self.ttl)).fetchone()
                if row:
                    try:
                        json.loads(row[0])
                        headers = json.loads(row[1])
                        result = httpx.Response(200, content=row[0], headers=headers)
                    except (ValueError, TypeError):
                        db.execute('DELETE FROM responses WHERE key = ?', (key,))
                    else:
                        self.hits += 1
                        return result
                self.misses += 1
            elif operation == 'set':
                if generation is not None and generation != self.generation:
                    return
                body = response.content
                lifetime = min(self.ttl, self.ttl if ttl is None else ttl)
                if len(body) > MAX_ENTRY_BYTES or lifetime <= 0:
                    return
                json.loads(body)
                db.execute('DELETE FROM responses WHERE expires <= ?', (now,))
                headers = {k: v for k, v in response.headers.items() if k.startswith('x-pagination-')}
                db.execute('INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)',
                           (key, now, body, json.dumps(headers), now + lifetime))
                while True:
                    count, size = db.execute('SELECT COUNT(*), COALESCE(SUM(LENGTH(body)), 0) FROM responses').fetchone()
                    if count <= MAX_ENTRIES and size <= MAX_BYTES:
                        break
                    db.execute('DELETE FROM responses WHERE key = '
                               '(SELECT key FROM responses ORDER BY stored, key LIMIT 1)')
            elif operation == 'clear':
                self.generation += 1
                db.execute('DELETE FROM responses')
            elif operation == 'status':
                count, size = db.execute('SELECT COUNT(*), COALESCE(SUM(LENGTH(body)), 0) '
                                         'FROM responses WHERE expires > ?', (now,)).fetchone()
                return {'enabled': self.ttl > 0, 'ttl_seconds': self.ttl, 'entries': count,
                        'response_bytes': size, 'hits': self.hits, 'misses': self.misses,
                        'scope': 'public_metadata_only'}

    async def get(self, key):
        return await asyncio.to_thread(self._run, 'get', key)

    async def put(self, key, response, ttl=None, generation=None):
        await asyncio.to_thread(self._run, 'set', key, response, ttl, generation)

    async def clear(self):
        await asyncio.to_thread(self._run, 'clear')

    async def status(self):
        return await asyncio.to_thread(self._run, 'status')
