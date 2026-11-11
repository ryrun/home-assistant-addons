import pytest
from aiohttp.test_utils import TestClient, TestServer
from server import Manager


@pytest.fixture
async def system(tmp_path):
    manager = Manager(tmp_path, dev=True)
    admin_app, device_app = manager.apps()
    async with TestClient(TestServer(admin_app)) as admin, TestClient(TestServer(device_app)) as frames:
        csrf = (await (await admin.get('/api/state')).json())['csrf']
        admin.session.headers['X-Eink-CSRF'] = csrf
        await admin.put('/api/settings', json={'base_url': 'http://192.168.1.10:8098'})
        yield manager, admin, frames
    manager.store.close()

