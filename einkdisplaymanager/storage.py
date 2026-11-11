"""Small transactional metadata store; immutable file contents live beside SQLite."""

import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from media import atomic_write


def new_id():
    return secrets.token_hex(5)


class Store:
    def __init__(self, root, quota_mb=1024):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.files = self.root / 'media'
        self.files.mkdir(exist_ok=True, mode=0o700)
        self.quota = quota_mb * 1024 * 1024
        self.db = sqlite3.connect(self.root / 'manager.sqlite3')
        os.chmod(self.root / 'manager.sqlite3', 0o600)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, doc TEXT NOT NULL, PRIMARY KEY(kind,id))')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError('Database version is newer than this add-on; restore a compatible version.')
        self.db.execute('PRAGMA user_version=1')
        self.db.commit()
        self.cleanup()

    def all(self, kind):
        return [json.loads(row[0]) for row in self.db.execute('SELECT doc FROM records WHERE kind=? ORDER BY rowid', (kind,))]

    def get(self, kind, identifier):
        if not isinstance(identifier, str):
            raise KeyError('Item not found.')
        row = self.db.execute('SELECT doc FROM records WHERE kind=? AND id=?', (kind, identifier)).fetchone()
        if row is None:
            raise KeyError('Item not found.')
        return json.loads(row[0])

    def save(self, kind, doc):
        with self.db:
            self.db.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET doc=excluded.doc',
                            (kind, doc['id'], json.dumps(doc, separators=(',', ':'), allow_nan=False)))

    def delete(self, kind, identifier):
        self.get(kind, identifier)
        with self.db:
            self.db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, identifier))

    def usage(self):
        return sum(f.stat().st_size for f in self.files.iterdir() if f.is_file())

    def put_file(self, data, suffix):
        from media import digest
        path = self.files / (digest(data) + suffix)
        if not path.exists():
            if self.usage() + len(data) > self.quota:
                raise ValueError('Storage limit reached. Delete unused images or increase storage_limit_mb.')
            atomic_write(path, data)
        return path.name

    def path(self, name):
        path = self.files / name
        if path.parent != self.files or not path.is_file():
            raise KeyError('Image file is unavailable.')
        return path

    def cleanup(self):
        """Remove crash leftovers only; named variants are always retained."""
        referenced = {v[key] for kind in ('asset', 'variant') for v in self.all(kind)
                      for key in ('file', 'thumbnail')}
        for path in self.files.iterdir():
            if path.is_file() and path.name not in referenced:
                path.unlink()

    def new_asset(self, metadata, name, data, thumb):
        existing = next((a for a in self.all('asset') if a['hash'] == metadata['hash']), None)
        if existing:
            return existing, True
        doc = dict(metadata, id=new_id(), name=name, created_at=time.time(),
                   file=self.put_file(data, '.original'), thumbnail=self.put_file(thumb, '.jpg'))
        self.save('asset', doc)
        return doc, False

    def close(self):
        self.db.close()
