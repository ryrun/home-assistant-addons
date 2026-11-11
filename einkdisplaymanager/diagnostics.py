"""Bounded device events and live server-side transfer progress, without request secrets."""

import copy
import time

LIMIT = 100
DETAILS = {'http_status', 'bytes_written', 'total_bytes', 'duration_seconds',
           'error_code', 'entry_id', 'asset_id', 'variant_id', 'mime_type'}


class Diagnostics:
    def __init__(self, store):
        self.store = store
        self.active = {}
        for record in self.store.all('diagnostics'):
            transfer = record.get('last_transfer', {})
            if transfer.get('status') in ('preparing', 'sending'):
                transfer.pop('elapsed_seconds', None)
                transfer.pop('duration_seconds', None)
                transfer.update(status='interrupted', error_code='restart', ended_at=time.time(), progress_known=False)
                self.store.save('diagnostics', record)
                self.event(record['id'], 'image_interrupted',
                           'The add-on restarted during a transfer. Receipt and final byte count are unknown.',
                           error_code='restart')

    def record(self, identifier):
        try:
            return self.store.get('diagnostics', identifier)
        except KeyError:
            return {'id': identifier, 'events': [], 'last_transfer': {'status': 'idle'}}

    def event(self, identifier, event, message, **details):
        record = self.record(identifier)
        entries = record['events']
        sequence = entries[-1]['id'] + 1 if entries else 1
        entries.append({'id': sequence, 'at': time.time(), 'event': event, 'message': message,
                        **{key: value for key, value in details.items() if key in DETAILS}})
        record['events'] = entries[-LIMIT:]
        self.store.save('diagnostics', record)

    def transfer(self, identifier):
        if identifier in self.active:
            active = self.active[identifier]
            result = {key: value for key, value in active.items() if not key.startswith('_')}
            result['elapsed_seconds'] = round(max(0, time.monotonic() - active['_monotonic']), 2)
            return result
        return copy.deepcopy(self.record(identifier)['last_transfer'])

    def running(self, identifier):
        return identifier in self.active

    def start(self, identifier, total_bytes, entry_id, asset_id, mime_type):
        transfer = {'status': 'preparing', 'started_at': time.time(), '_monotonic': time.monotonic(),
                    'bytes_written': 0, 'total_bytes': total_bytes, 'entry_id': entry_id,
                    'asset_id': asset_id, 'mime_type': mime_type, 'progress_known': True}
        self.active[identifier] = transfer
        record = self.record(identifier)
        record['last_transfer'] = self.transfer(identifier)
        self.store.save('diagnostics', record)
        self.event(identifier, 'image_started', 'Frame image request started.',
                   total_bytes=total_bytes, entry_id=entry_id, asset_id=asset_id, mime_type=mime_type)

    def update(self, identifier, *, total_bytes=None, bytes_written=None):
        transfer = self.active[identifier]
        transfer['status'] = 'sending'
        if total_bytes is not None:
            transfer['total_bytes'] = total_bytes
        if bytes_written is not None:
            transfer['bytes_written'] = bytes_written

    def finish(self, identifier, status, message, *, http_status=None, error_code=None):
        if not self.running(identifier):
            return
        transfer = self.transfer(identifier)
        transfer.update(status=status, ended_at=time.time(), duration_seconds=transfer.pop('elapsed_seconds'),
                        http_status=http_status, error_code=error_code)
        record = self.record(identifier)
        record['last_transfer'] = transfer
        self.store.save('diagnostics', record)
        del self.active[identifier]
        self.event(identifier, 'image_' + status, message, http_status=http_status, error_code=error_code,
                   bytes_written=transfer['bytes_written'], total_bytes=transfer['total_bytes'],
                   duration_seconds=transfer['duration_seconds'], entry_id=transfer['entry_id'])

    def view(self, identifier):
        return {'transfer': self.transfer(identifier), 'events': self.record(identifier)['events']}

    def remove(self, identifier):
        self.active.pop(identifier, None)
        try:
            self.store.delete('diagnostics', identifier)
        except KeyError:
            pass
