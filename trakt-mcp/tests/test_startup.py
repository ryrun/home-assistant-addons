import json
import os
from unittest.mock import Mock

import pytest

import server


@pytest.fixture
def startup(tmp_path, monkeypatch):
    options = tmp_path / 'options.json'
    monkeypatch.setenv('TRAKT_OPTIONS_FILE', str(options))
    monkeypatch.setenv('TRAKT_DATA_DIR', str(tmp_path))
    prepare = Mock()
    monkeypatch.setattr(server, 'drop_privileges', prepare)
    previous_mask = os.umask(0o077)
    yield options, prepare
    os.umask(previous_mask)


@pytest.mark.parametrize('changes,expected', [
    ({'mcp_auth_token': 'private-short'}, 'mcp_auth_token must contain 32–512'),
    ({'trakt_client_id': ''}, 'trakt_client_id must contain'),
    ({'trakt_client_secret': None}, 'trakt_client_secret must be a string'),
    ({'log_level': 'private-invalid-level'}, 'log_level must be'),
    ({'allowed_networks': ['private-invalid-network']}, 'valid CIDR'),
])
def test_configuration_errors_are_actionable_before_storage_changes(startup, caplog, changes, expected):
    options, prepare = startup
    options.write_text(json.dumps({'trakt_client_id': 'private-client-id', 'mcp_auth_token': 'private-mcp-password-' * 3,
                                  'trakt_client_secret': '', **changes}))
    with pytest.raises(SystemExit) as error:
        server.main()
    assert error.value.code == 1
    prepare.assert_not_called()
    assert 'validating configuration' in caplog.text
    assert expected in caplog.text
    assert 'private-' not in caplog.text


def test_invalid_json_reports_position_without_contents(startup, caplog):
    options, prepare = startup
    options.write_text('{"private-token": "private-secret", broken}')
    with pytest.raises(SystemExit):
        server.main()
    prepare.assert_not_called()
    assert 'reading options' in caplog.text
    assert 'invalid JSON (line 1, column' in caplog.text
    assert 'private-' not in caplog.text


def test_missing_options_file_reports_error_without_path(startup, caplog):
    with pytest.raises(SystemExit):
        server.main()
    assert 'reading options: FileNotFoundError (errno=2' in caplog.text
    assert str(startup[0]) not in caplog.text


@pytest.mark.parametrize('stage,kind', [('storage', PermissionError), ('initialization', TypeError)])
def test_unexpected_startup_errors_report_stage_without_raw_exception(startup, caplog, monkeypatch, stage, kind):
    options, prepare = startup
    options.write_text(json.dumps({'trakt_client_id': 'id', 'mcp_auth_token': 'x' * 48,
                                  'trakt_client_secret': ''}))
    def fail(*args):
        if kind is PermissionError:
            raise PermissionError(1, 'private-secret', '/private-token-file')
        raise TypeError('private-secret')
    if stage == 'storage':
        prepare.side_effect = fail
    else:
        monkeypatch.setattr(server, 'create_app', fail)
    with pytest.raises(SystemExit):
        server.main()
    assert ('preparing persistent storage and runtime user' if stage == 'storage' else 'initializing MCP server') in caplog.text
    assert kind.__name__ in caplog.text
    assert 'test_startup.py:' in caplog.text
    assert 'errno=1' in caplog.text if stage == 'storage' else 'errno=None' in caplog.text
    assert 'private-' not in caplog.text
    assert 'Traceback' not in caplog.text
