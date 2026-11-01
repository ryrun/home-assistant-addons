import logging
from unittest.mock import AsyncMock

import pytest

from setup_flow import authorize_from_home_assistant


@pytest.mark.asyncio
async def test_home_assistant_setup_logs_only_user_code(caplog):
    auth = AsyncMock()
    auth.start.return_value = dict(user_code='ABCD-1234', expires_in=600,
                                  device_code='private-device', access_token='private-access')
    auth.poll.return_value = {'status': 'authorized'}
    with caplog.at_level(logging.INFO):
        await authorize_from_home_assistant(auth)
    assert 'ABCD-1234' in caplog.text
    assert 'connected successfully' in caplog.text
    assert 'private-' not in caplog.text


@pytest.mark.asyncio
async def test_setup_unexpected_errors_do_not_leak_secrets(caplog):
    auth = AsyncMock()
    auth.start.side_effect = RuntimeError('private-access')
    await authorize_from_home_assistant(auth)
    assert 'failed' in caplog.text
    assert 'private-access' not in caplog.text
