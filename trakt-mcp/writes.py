"""Run bounded Trakt writes and keep enough state for conditional undo."""
import asyncio
from collections import OrderedDict
import hashlib
import json
import logging
import os
import tempfile
import secrets
import time
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from errors import TraktError, json_data
from http_utils import bounded_request, retry_after
from trakt_client import API_URL

Id = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
Action = Literal['create_list', 'append_list', 'set_list_note', 'reorder_list',
                 'add_watchlist', 'set_rating', 'add_favorites', 'add_collection', 'add_history']
GROUP = {
    'create_list': 'list', 'append_list': 'list', 'set_list_note': 'list',
    'reorder_list': 'list', 'add_watchlist': 'watchlist', 'set_rating': 'ratings',
    'add_favorites': 'favorites', 'add_collection': 'collection', 'add_history': 'history',
}
PERMISSIONS = tuple(dict.fromkeys(GROUP.values()))
SYNC_PATH = {'add_watchlist': 'watchlist', 'set_rating': 'ratings', 'add_favorites': 'favorites',
             'add_collection': 'collection', 'add_history': 'history'}


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Action
    movie_ids: list[Id] = Field(default_factory=list, max_length=20)
    show_ids: list[Id] = Field(default_factory=list, max_length=20)
    episode_ids: list[Id] = Field(default_factory=list, max_length=20)
    list_id: Id | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    list_item_id: Id | None = None
    notes: str | None = Field(default=None, max_length=500)
    rank: list[Id] | None = Field(default=None, min_length=1, max_length=1000)
    rating: Annotated[int, Field(strict=True, ge=1, le=10)] | None = None

    def request_data(self):
        data = self.model_dump(exclude_none=True, exclude_defaults=True)
        action = self.action
        required = {
            'create_list': {'name'}, 'append_list': {'list_id'},
            'set_list_note': {'list_id', 'list_item_id', 'notes'},
            'reorder_list': {'list_id', 'rank'}, 'set_rating': {'rating'},
        }.get(action, set())
        media = {'movie_ids', 'show_ids', 'episode_ids'}
        if action in ('set_list_note', 'reorder_list'):
            media = set()
        elif action in ('add_history', 'add_collection'):
            media = {'movie_ids', 'episode_ids'}
        elif action != 'set_rating':
            media = {'movie_ids', 'show_ids'}
        if not required <= data.keys() or data.keys() - required - media - {'action'}:
            raise TraktError('Unexpected or missing parameters for this write action.')
        if media and not media.intersection(data):
            raise TraktError('Supply at least one Trakt media ID.')
        if sum(len(data.get(key, [])) for key in media) > 20:
            raise TraktError('Supply at most 20 media entries per call.')
        if self.name is not None and (not self.name.strip() or not self.name.isprintable()):
            raise TraktError('Use a nonempty printable list name.')
        if self.rank and len(set(self.rank)) != len(self.rank):
            raise TraktError('Rank must contain distinct list item IDs.')
        for key in media.intersection(data):
            data[key] = list(dict.fromkeys(data[key]))
        return data


def payload(data):
    result = {}
    for field, kind in (('movie_ids', 'movies'), ('show_ids', 'shows'), ('episode_ids', 'episodes')):
        if field in data:
            result[kind] = [{'ids': {'trakt': value}, **({'rating': data['rating']} if 'rating' in data else {})}
                            for value in data[field]]
    return result


class WritePermissions:
    """Persist the administrator's choices for the next add-on startup."""

    def __init__(self, path):
        self.path = path
        self.saved = dict.fromkeys(PERMISSIONS, False)
        try:
            with path.open('rb') as file:
                self.saved = self.validate(json.loads(file.read(1024)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logging.getLogger('trakt_mcp').warning('Stored write permissions are invalid. All writes are disabled.')
        self.active = self.saved.copy()

    @staticmethod
    def validate(data):
        if (not isinstance(data, dict) or set(data) != set(PERMISSIONS)
                or any(type(enabled) is not bool for enabled in data.values())):
            raise ValueError('Expected six boolean write permissions.')
        return {name: data[name] for name in PERMISSIONS}

    def save(self, data):
        updated = self.validate(data)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False) as file:
            temporary = self.path.with_name(os.path.basename(file.name))
            try:
                json.dump(updated, file)
                file.flush()
                os.fsync(file.fileno())
                file.close()
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
        self.saved = updated

    def status(self):
        return {'active': self.active, 'saved': self.saved, 'restart_required': self.active != self.saved}


class TraktWrites:
    def __init__(self, client, enabled):
        self.client = client
        self.enabled = enabled
        self.records = OrderedDict()
        self.lock = asyncio.Lock()
        self.next_write = 0

    async def identity(self):
        token = await self.client.auth.access_token()
        return hashlib.sha256(token.encode()).digest(), token

    async def private_list(self, list_id):
        path = f'/users/me/lists/{list_id}'
        data = json_data(await self.client.get(path, personal=True))
        if (not isinstance(data, dict) or data.get('privacy') != 'private'
                or not isinstance(data.get('ids'), dict) or data['ids'].get('trakt') != list_id):
            raise TraktError('The target must be a private personal list in the connected account.')
        return data

    async def list_state(self, list_id):
        meta = await self.private_list(list_id)
        path = f'/users/me/lists/{list_id}/items/movie,show,season,episode/rank/asc'
        if type(meta.get('item_count')) is not int or not 0 <= meta['item_count'] <= 1000:
            raise TraktError('This operation requires a list with at most 1000 verifiable entries.')
        items = await self.client._all_items_live(path, require_pagination=True)
        rows = {}
        for item in items:
            if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] in rows:
                raise TraktError('Trakt did not return distinct list item IDs.')
            kind = item.get('type')
            media = item.get(kind) if isinstance(kind, str) else None
            ids = media.get('ids') if isinstance(media, dict) else None
            if not isinstance(ids, dict) or type(ids.get('trakt')) is not int:
                raise TraktError('Trakt did not return a list item media ID.')
            rows[item['id']] = (kind, ids['trakt'], item.get('rank'), item.get('notes'), item.get('listed_at'))
        if type(meta.get('item_count')) is not int or meta['item_count'] != len(rows):
            raise TraktError('Trakt list metadata and item count do not agree. Refresh and try again.')
        return {key: meta.get(key) for key in ('name', 'privacy', 'description', 'updated_at',
                'item_count', 'sort_by', 'sort_how', 'display_numbers', 'allow_comments', 'type')}, rows

    async def watchlist_state(self, data):
        result = {}
        for kind in ('movie', 'show'):
            wanted = set(data.get(kind + '_ids', []))
            if not wanted:
                continue
            path = f'/users/me/watchlist/{kind}s/added'
            for entry in await self.client._all_items_live(path, require_pagination=True):
                media_id = entry.get(kind, {}).get('ids', {}).get('trakt')
                if type(media_id) is not int:
                    raise TraktError('Watchlist membership could not be verified.')
                if media_id in wanted:
                    key = (kind, media_id)
                    if type(entry.get('id')) is not int or key in result:
                        raise TraktError('Watchlist item identity could not be verified.')
                    result[key] = (entry['id'], entry.get('notes'), entry.get('listed_at'), entry.get('rank'))
        return result

    async def collection_existing(self, data):
        existing = set()
        for kind in ('movie', 'episode'):
            if not data.get(kind + '_ids'):
                continue
            for entry in await self.client._all_items_live(f'/sync/collection/{kind}s', require_pagination=True):
                media_id = entry.get(kind, {}).get('ids', {}).get('trakt')
                if type(media_id) is not int:
                    raise TraktError('Collection membership could not be verified.')
                existing.add((kind, media_id))
        return existing

    def record(self, data, identity):
        key = secrets.token_urlsafe(18)
        row = {'data': data, 'identity': identity, 'state': 'running',
               'undo': 'Automatic undo is unavailable for this operation.'}
        self.records[key] = row
        if len(self.records) > 60:
            self.records.popitem(last=False)
        return key, row

    @staticmethod
    def outcome(key, row):
        return {'operation_id': key, 'state': row['state'], 'change': row['data'],
                'can_undo': row['state'] == 'completed' and 'inverse' in row,
                'undo': row['undo'], 'undo_change': row.get('undo_change'),
                'result': row.get('result')}

    def lookup(self, key, identity):
        row = self.records.get(key)
        if row is None or row['identity'] != identity:
            raise TraktError('Operation not found for the current Trakt authorization.')
        return row

    async def result(self, key):
        identity, _ = await self.identity()
        return self.outcome(key, self.lookup(key, identity))

    @staticmethod
    def review_required(row, message):
        row['state'] = 'review_required'
        row.setdefault('result', {})['message'] = message
        row['undo'] = 'Automatic undo unavailable for an unverified result.'

    async def run(self, request):
        data = request.request_data()
        if not self.enabled[GROUP[request.action]]:
            raise TraktError('This write permission is disabled.')
        async with self.lock:
            identity, _ = await self.identity()
            key, row = self.record(data, identity)
            try:
                async with asyncio.timeout(60):
                    await self.execute(row)
                row['state'] = 'completed'
            except TraktError as error:
                self.review_required(row, str(error))
            except TimeoutError:
                self.review_required(row, 'The request timed out. Check Trakt before retrying.')
            except Exception:
                self.review_required(row, 'The result could not be verified. Check Trakt before retrying.')
            finally:
                if row['state'] == 'running':
                    self.review_required(row, 'The call was interrupted. Check Trakt before retrying.')
                row.pop('before', None)
            return self.outcome(key, row)

    async def send(self, method, path, token, body):
        async with self.client.request_slots:
            if self.client.rate_limit_until > time.monotonic():
                raise TraktError('Trakt is rate limited. Review the operation before retrying.')
            await asyncio.sleep(max(0, self.next_write - time.monotonic()))
            self.next_write = time.monotonic() + 1.05
            try:
                response = await bounded_request(self.client.http, method, API_URL + path,
                    headers={**self.client.headers, 'Authorization': 'Bearer ' + token}, json=body,
                    metrics=self.client.metrics, service='trakt')
            except httpx.RequestError:
                raise TraktError('Trakt did not confirm the change. Check the target before retrying.') from None
            if response.status_code == 429:
                self.client.rate_limit_until = max(self.client.rate_limit_until,
                                                   time.monotonic() + retry_after(response.headers))
            if not 200 <= response.status_code < 300:
                raise TraktError(f'Trakt returned HTTP {response.status_code}. Check the target before retrying.')
            return {} if response.status_code == 204 else json_data(response)

    async def execute(self, row):
        data = row['data']
        action = data['action']
        before = {}
        if 'list_id' in data:
            _, before = await self.list_state(data['list_id'])
            if action == 'set_list_note' and data['list_item_id'] not in before:
                raise TraktError('The item is not in this private list.')
            if action == 'reorder_list' and set(data['rank']) != before.keys():
                raise TraktError('Supply the full list order using list item IDs.')
        elif action == 'add_watchlist':
            before = await self.watchlist_state(data)
        row['before'] = before

        existing = await self.collection_existing(data) if action == 'add_collection' else set()
        if action == 'add_watchlist':
            existing = set(before)
        identity, token = await self.identity()
        if identity != row['identity']:
            raise TraktError('Trakt authorization changed. The write was not started.')
        body = payload(data)
        list_id = data.get('list_id')
        if action == 'create_list':
            created = await self.send('POST', '/users/me/lists', token, {'name': data['name'], 'privacy': 'private'})
            list_id = created.get('ids', {}).get('trakt') if isinstance(created, dict) else None
            if type(list_id) is not int or list_id <= 0:
                raise TraktError('Trakt did not return a usable list ID. Check your lists before retrying.')
            row['result'] = {'list_id': list_id}
        skipped = {}
        if action == 'append_list':
            existing = {(value[0], value[1]) for value in row['before'].values()}
        if action in ('append_list', 'add_collection', 'add_watchlist'):
            for kind in ('movie', 'show', 'episode'):
                group = kind + 's'
                entries = body.get(group, [])
                new = [entry for entry in entries if (kind, entry['ids']['trakt']) not in existing]
                if entries:
                    skipped[group] = len(entries) - len(new)
                if new:
                    body[group] = new
                else:
                    body.pop(group, None)
            if not body:
                row['result'] = {'list_id': list_id, 'skipped_existing': skipped}
                row['undo'] = 'No entries were changed.'
                return
        path, method = f'/users/me/lists/{list_id}/items', 'POST'
        if action == 'set_list_note':
            path, method, body = f'{path}/{data["list_item_id"]}', 'PUT', {'notes': data['notes']}
        elif action == 'reorder_list':
            path, body = path + '/reorder', {'rank': data['rank']}
        elif action in SYNC_PATH:
            path = '/sync/' + SYNC_PATH[action]
        response = await self.send(method, path, token, body)
        if not isinstance(response, dict):
            raise TraktError('Trakt did not return a verifiable write result.')
        summary = {key: {kind: values[kind] if type(values[kind]) is int else len(values[kind])
                         for kind in ('movies', 'shows', 'seasons', 'episodes')
                         if kind in values and type(values[kind]) in (int, list)}
                   for key in ('added', 'updated', 'existing', 'deleted', 'not_found')
                   if isinstance(values := response.get(key), dict)}
        if action != 'set_list_note' and not summary and action != 'reorder_list':
            raise TraktError('Trakt did not return write counts. Check the target before retrying.')
        row['result'] = {'list_id': list_id, 'skipped_existing': skipped, **summary}
        if self.client.snapshots:
            await self.client.snapshots.clear()
        if any(summary.get('not_found', {}).values()):
            raise TraktError('Trakt did not find some requested entries. Review the result before retrying.')

        if GROUP[action] in ('list', 'watchlist'):
            row['undo'] = 'Automatic undo unavailable because the exact change could not be verified.'
            try:
                async with asyncio.timeout(5):
                    if action == 'add_watchlist':
                        await self.capture_watchlist_inverse(row, body)
                    else:
                        await self.capture_inverse(row, list_id)
            except (TraktError, TimeoutError):
                pass

    async def capture_watchlist_inverse(self, row, body):
        after = await self.watchlist_state(row['data'])
        before = row['before']
        expected = {(kind, entry['ids']['trakt']) for kind in ('movie', 'show')
                    for entry in body.get(kind + 's', [])}
        counts = row['result'].get('added', {})
        if (set(after) - set(before) != expected or any(after.get(k) != v for k, v in before.items())
                or any(counts.get(kind, 0) != len(items) for kind, items in body.items())):
            return
        row['inverse'] = ('POST', '/sync/watchlist/remove', body)
        row['after'] = after
        row['undo'] = 'Remove only the titles added by this operation if the selected watchlist entries are unchanged.'
        row['undo_change'] = {'action': 'remove_watchlist_entries', 'entries': body}

    async def capture_inverse(self, row, list_id):
        meta, after = await self.list_state(list_id)
        before = row['before']
        data = row['data']
        action = data['action']
        path = f'/users/me/lists/{list_id}'
        if action in ('create_list', 'append_list'):
            if any(after.get(key) != value for key, value in before.items()):
                return
            added = [value for key, value in after.items() if key not in before]
            requested = {(kind, value) for kind in ('movie', 'show') for value in data.get(kind + '_ids', [])}
            expected = requested - {(value[0], value[1]) for value in before.values()}
            counts = row['result'].get('added')
            if (not expected or {(v[0], v[1]) for v in added} != expected or len(added) != len(expected)
                    or not isinstance(counts, dict) or any(
                        counts.get(kind + 's', 0) != sum(k == kind for k, _ in expected)
                        for kind in ('movie', 'show')
                    )):
                return
            for_undo = {kind + 's': [{'ids': {'trakt': value}} for k, value in sorted(expected) if k == kind]
                        for kind in ('movie', 'show') if any(k == kind for k, _ in expected)}
            inverse = ('DELETE', path, None) if action == 'create_list' else ('POST', path + '/items/remove', for_undo)
            label = 'Delete the newly created private list' if action == 'create_list' else 'Remove only the titles added by this operation'
            undo_change = ({'action': 'delete_created_list', 'name': meta['name']}
                           if action == 'create_list' else {'action': 'remove_added_list_entries', 'entries': for_undo})
        elif action == 'set_list_note':
            item_id = data['list_item_id']
            expected = dict(before)
            old = before[item_id]
            expected[item_id] = (*old[:3], data['notes'], old[4])
            if after != expected:
                return
            inverse = ('PUT', f'{path}/items/{item_id}', {'notes': old[3]})
            label = 'Restore the previous note'
            undo_change = {'action': 'restore_list_note', 'list_item_id': item_id, 'notes': old[3]}
        else:
            if (before.keys() != after.keys() or any(after[k][:2] + after[k][3:] != v[:2] + v[3:] for k, v in before.items())
                    or any(type(v[2]) is not int for v in [*before.values(), *after.values()])):
                return
            old_rank = sorted(before, key=lambda key: before[key][2])
            if sorted(after, key=lambda key: after[key][2]) != data['rank'] or old_rank == data['rank']:
                return
            inverse = ('POST', path + '/items/reorder', {'rank': old_rank})
            label = 'Restore the previous order'
            undo_change = {'action': 'restore_list_order', 'rank': old_rank}
        if action == 'create_list' and meta.get('name') != data['name']:
            return
        row['inverse'] = inverse
        row['after'] = (meta, after)
        row['undo'] = label + ' if the list is still unchanged.'
        row['undo_change'] = {**undo_change, 'list_id': list_id}

    async def undo(self, original_key):
        async with self.lock:
            identity, _ = await self.identity()
            original = self.lookup(original_key, identity)
            if (original['state'] != 'completed' or 'inverse' not in original
                    or not self.enabled[GROUP[original['data']['action']]]):
                raise TraktError('Undo is no longer available.')
            list_id = original['result']['list_id']
            key, row = self.record(
                {'action': 'undo', 'original_operation_id': original_key, **{
                    k: v for k, v in original['undo_change'].items() if k != 'action'
                }, 'undo_action': original['undo_change']['action']},
                identity,
            )
            try:
                async with asyncio.timeout(60):
                    await self.apply_inverse(original, row, list_id)
                row['state'] = 'completed'
            except TraktError as error:
                self.review_required(row, str(error))
            except TimeoutError:
                self.review_required(row, 'Undo timed out. Check Trakt before retrying.')
            except Exception:
                self.review_required(row, 'The undo result could not be verified. Check Trakt before retrying.')
            finally:
                if row['state'] == 'running':
                    self.review_required(row, 'Undo was interrupted. Check Trakt before retrying.')
            return self.outcome(key, row)

    async def apply_inverse(self, original, row, list_id):
        if original['data']['action'] == 'add_watchlist':
            current = await self.watchlist_state(original['data'])
        else:
            current = await self.list_state(list_id)
        if current != original['after']:
            raise TraktError('The list changed after the write. Automatic undo was stopped.')
        identity, token = await self.identity()
        if identity != original['identity']:
            raise TraktError('Trakt authorization changed. Automatic undo was stopped.')
        method, path, body = original.pop('inverse')
        original.pop('undo_change', None)
        original.pop('after', None)
        original['undo'] = 'Undo was attempted. Check the operation result.'
        response = await self.send(method, path, token, body)
        row['result'] = {'list_id': list_id}
        if method == 'POST' and path.endswith('/remove'):
            expected = {kind: len(items) for kind, items in body.items()}
            actual = response.get('deleted', {}) if isinstance(response, dict) else {}
            if not isinstance(actual, dict) or any(actual.get(kind) != count for kind, count in expected.items()):
                raise TraktError('Trakt did not confirm that every item was removed. Review the list.')
        original['state'] = 'undone'
        original['undo'] = 'This operation was undone.'
        if self.client.snapshots:
            await self.client.snapshots.clear()
