"""F5 regressions in core/proxy.py: UNC paths (M1) and token masking in logs (M28)."""
import logging
import os

import pytest

from core import proxy as proxy_module
from tests.test_proxy_harness import PROXY_TOKEN, nedotify_home, app_core, offline_handler  # noqa: F401


@pytest.mark.parametrize('raw', [
    '\\\\attacker\\share\\song.mp3',
    '//attacker/share/song.mp3',
    'file://attacker/share/song.mp3',
    'file:////attacker/share/song.mp3',
])
def test_unc_and_file_host_paths_refused_before_fs_access(raw, nedotify_home, app_core, monkeypatch):
    calls = []
    monkeypatch.setattr(proxy_module.os.path, 'isfile', lambda p: calls.append(('isfile', p)) or True)
    monkeypatch.setattr(proxy_module.os.path, 'realpath', lambda p: calls.append(('realpath', p)) or p)
    assert proxy_module._safe_stream_local_path(raw, app_core.db) == ''
    assert calls == []


def test_drive_less_path_refused_before_fs_access(nedotify_home, app_core, monkeypatch):
    calls = []
    monkeypatch.setattr(proxy_module.os.path, 'isfile', lambda p: calls.append(p) or True)
    assert proxy_module._safe_stream_local_path('\\rooted\\song.mp3', app_core.db) == ''
    assert calls == []


def test_managed_local_file_still_served(nedotify_home, app_core):
    path = os.path.join(nedotify_home, 'streams', 'ok.mp3')
    with open(path, 'wb') as fh:
        fh.write(b'ID3' + b'x' * 16)
    assert proxy_module._safe_stream_local_path(path, app_core.db) == os.path.realpath(path)


def test_log_message_masks_query_token(nedotify_home, app_core, caplog):
    handler = offline_handler(app_core)
    with caplog.at_level(logging.DEBUG, logger=proxy_module.__name__):
        handler.log_message('"%s" %s %s', f'GET /api/stream?url=x&k={PROXY_TOKEN}&auth_token={PROXY_TOKEN} HTTP/1.1', '200', '-')
    text = '\n'.join(r.getMessage() for r in caplog.records)
    assert PROXY_TOKEN not in text
    assert 'k=***' in text and 'auth_token=***' in text
