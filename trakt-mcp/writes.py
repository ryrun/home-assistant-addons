"""Prepare bounded Trakt changes and execute them only through HA ingress."""
import asyncio
from collections import OrderedDict
import hashlib
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
OPTIONS = {group: f'enable_{group}_writes' for group in dict.fromkeys(GROUP.values())}
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
            raise TraktError('Approve at most 20 media entries at a time.')
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


class WriteQueue:
    def __init__(self, client, options):
        self.client = client
        self.enabled = {group: options.get(option, False) for group, option in OPTIONS.items()}
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

    async def prepare(self, request):
        data = request.request_data()
        if not self.enabled[GROUP[request.action]]:
            raise TraktError('This write permission is disabled in the add-on configuration.')
        identity, _ = await self.identity()
        target, items = None, {}
        if request.action == 'add_watchlist':
            items = await self.watchlist_state(data)
        if request.list_id is not None:
            target, items = await self.list_state(request.list_id)
            if request.action == 'set_list_note' and request.list_item_id not in items:
                raise TraktError('The item is not in this list.')
            if request.action == 'reorder_list' and set(request.rank) != items.keys():
                raise TraktError('Supply the full list order using list item IDs.')
        titles = []
        for kind in ('movie', 'show'):
            for media_id in data.get(kind + '_ids', []):
                detail = json_data(await self.client.get(f'/{kind}s/{media_id}'))
                if not isinstance(detail, dict) or detail.get('ids', {}).get('trakt') != media_id:
                    raise TraktError('Trakt did not confirm the requested title ID.')
                titles.append({'type': kind, 'id': media_id, 'title': detail.get('title'), 'year': detail.get('year')})
        if identity != (await self.identity())[0]:
            raise TraktError('Trakt authorization changed. Prepare the action again.')
        now = time.monotonic()
        if sum(r['state'] == 'pending' and r['expires'] > now for r in self.records.values()) >= 20:
            raise TraktError('Too many pending approvals. Review them in Home Assistant.')
        while len(self.records) >= 60:
            oldest = next((key for key, row in self.records.items()
                           if row['state'] not in ('pending', 'running') or
                           (row['state'] == 'pending' and row['expires'] <= now)), None)
            if oldest is None:
                raise TraktError('Approval queue is full.')
            del self.records[oldest]
        key = secrets.token_urlsafe(18)
        self.records[key] = {'at': time.time(), 'data': data, 'identity': identity, 'expires': now + 600,
                             'state': 'pending', 'titles': titles, 'approval': secrets.token_urlsafe(32),
                             'target': target.get('name') if target else None,
                             'before': items,
                             'undo': 'Conditional undo may be available after verification.' if GROUP[request.action] in ('list', 'watchlist')
                                     else 'Automatic undo unavailable. Review the change in Trakt.',
                             'updated_at': target.get('updated_at') if target else None}
        return {'operation_id': key, 'state': 'pending', 'proposal': data,
                'target': self.records[key]['target'], 'titles': titles,
                'visibility': 'private' if GROUP[request.action] == 'list' else None, 'undo': self.records[key]['undo'],
                'message': 'Review and confirm this exact operation in the Home Assistant add-on dashboard.'}

    def public(self, *, dashboard=False):
        now = time.monotonic()
        result = []
        for key, row in reversed(self.records.items()):
            state = 'expired' if row['state'] == 'pending' and row['expires'] <= now else row['state']
            item = {'operation_id': key, 'state': state, 'proposal': row['data'], 'at': row['at'],
                    'can_undo': state == 'completed' and 'inverse' in row, 'titles': row.get('titles', []),
                    'target': row['target'], 'visibility': 'private' if 'list_id' in row['data'] and row['data']['list_id'] is not None
                    or row['data']['action'] == 'create_list' else None, 'undo': row['undo'], 'result': row.get('result')}
            if dashboard and state == 'pending':
                item['approval'] = row['approval']
            result.append(item)
        return result

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

    async def approve(self, key, proof, decision="approve"):
        async with self.lock:
            row = self.records.get(key)
            if (row is None or row['state'] != 'pending' or row['expires'] <= time.monotonic()
                    or not secrets.compare_digest(row['approval'], proof)):
                raise TraktError('Approval is invalid, expired or already used.')
            if decision == 'decline':
                row['state'] = 'declined'
                return {'state': 'declined'}
            row['state'] = 'running'
            try:
                async with asyncio.timeout(60):
                    if row['data']['action'] == 'undo':
                        await self.undo(row)
                    else:
                        await self.execute(row)
                row['state'] = 'completed'
            except (TraktError, TimeoutError) as error:
                row['state'] = 'review_required'
                row.setdefault('result', {})['message'] = str(error) if isinstance(error, TraktError) else (
                    'The request timed out. Check Trakt before retrying.')
                row['undo'] = 'Automatic undo unavailable for an unverified result.'
            except Exception:
                row['state'] = 'review_required'
                row.setdefault('result', {})['message'] = 'The result could not be verified. Check Trakt before retrying.'
                row['undo'] = 'Automatic undo unavailable for an unverified result.'
            finally:
                if row['state'] == 'running':
                    row['state'] = 'review_required'
            return {'state': row['state'], 'result': row.get('result')}

    async def execute(self, row):
        data = row['data']
        action = data['action']
        if not self.enabled[GROUP[action]]:
            raise TraktError('This write permission is disabled.')
        if 'list_id' in data:
            target, items = await self.list_state(data['list_id'])
            if (target.get('name') != row['target'] or target.get('updated_at') != row['updated_at']
                    or items != row['before']):
                raise TraktError('The list changed after preview. Prepare the action again.')
        existing = await self.collection_existing(data) if action == 'add_collection' else set()
        if action == 'add_watchlist':
            current = await self.watchlist_state(data)
            if current != row['before']:
                raise TraktError('The selected watchlist entries changed after preview. Prepare the action again.')
            existing = set(current)
        identity, token = await self.identity()
        if identity != row['identity']:
            raise TraktError('Trakt authorization changed. Prepare the action again.')
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
        elif action == 'set_list_note':
            item_id = data['list_item_id']
            expected = dict(before)
            old = before[item_id]
            expected[item_id] = (*old[:3], data['notes'], old[4])
            if after != expected:
                return
            inverse = ('PUT', f'{path}/items/{item_id}', {'notes': old[3]})
            label = 'Restore the previous note'
        else:
            if (before.keys() != after.keys() or any(after[k][:2] + after[k][3:] != v[:2] + v[3:] for k, v in before.items())
                    or any(type(v[2]) is not int for v in [*before.values(), *after.values()])):
                return
            old_rank = sorted(before, key=lambda key: before[key][2])
            if sorted(after, key=lambda key: after[key][2]) != data['rank'] or old_rank == data['rank']:
                return
            inverse = ('POST', path + '/items/reorder', {'rank': old_rank})
            label = 'Restore the previous order'
        if action == 'create_list' and meta.get('name') != data['name']:
            return
        row['inverse'] = inverse
        row['after'] = (meta, after)
        row['undo'] = label + ' if the list is still unchanged.'

    def stage_undo(self, key):
        row = self.records.get(key)
        if (row is None or row['state'] != 'completed' or 'inverse' not in row
                or not self.enabled[GROUP[row['data']['action']]] or len(self.records) >= 60):
            raise TraktError('Undo is not available.')
        undo_key = secrets.token_urlsafe(18)
        self.records[undo_key] = {
            'at': time.time(), 'data': {'action': 'undo', 'original_operation_id': key,
                'list_id': row['result']['list_id'], 'change': row['undo'],
                'original_selection': row['data']},
            'target': row['target'] or row['data'].get('name'), 'identity': row['identity'],
            'titles': row.get('titles', []),
            'state': 'pending', 'expires': time.monotonic() + 600,
            'approval': secrets.token_urlsafe(32), 'undo': 'Automatic redo unavailable.',
        }
        return {'operation_id': undo_key, 'state': 'pending'}

    async def undo(self, row):
        original = self.records.get(row['data']['original_operation_id'])
        if (original is None or original['state'] != 'completed' or 'inverse' not in original
                or not self.enabled[GROUP[original['data']['action']]]):
            raise TraktError('Undo is no longer available.')
        if original['data']['action'] == 'add_watchlist':
            current = await self.watchlist_state(original['data'])
        else:
            current = await self.list_state(row['data']['list_id'])
        if current != original['after']:
            raise TraktError('The list changed after the write. Automatic undo was stopped.')
        identity, token = await self.identity()
        if identity != row['identity']:
            raise TraktError('Trakt authorization changed. Automatic undo was stopped.')
        method, path, body = original.pop('inverse')
        original['undo'] = 'Undo was attempted. Check the operation result.'
        response = await self.send(method, path, token, body)
        row['result'] = {'list_id': row['data']['list_id']}
        if method == 'POST' and path.endswith('/remove'):
            expected = {kind: len(items) for kind, items in body.items()}
            actual = response.get('deleted', {}) if isinstance(response, dict) else {}
            if not isinstance(actual, dict) or any(actual.get(kind) != count for kind, count in expected.items()):
                raise TraktError('Trakt did not confirm that every item was removed. Review the list.')
        original['state'] = 'undone'
        if self.client.snapshots:
            await self.client.snapshots.clear()
