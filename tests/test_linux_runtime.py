"""Portable environment contracts plus native process-lock behavior."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

import linux_runtime


def test_linux_configures_qt_autoplay_without_disabling_sandbox(monkeypatch):
    monkeypatch.setattr(linux_runtime.sys, 'platform', 'linux')
    for key in ('PYWEBVIEW_GUI', 'QT_API', 'QTWEBENGINE_CHROMIUM_FLAGS'):
        monkeypatch.delenv(key, raising=False)
    linux_runtime.configure_environment()
    assert os.environ['QT_API'] == 'pyqt6'
    assert os.environ['PYWEBVIEW_GUI'] == 'qt'
    assert '--autoplay-policy=no-user-gesture-required' in os.environ['QTWEBENGINE_CHROMIUM_FLAGS']
    assert '--no-sandbox' not in os.environ['QTWEBENGINE_CHROMIUM_FLAGS']
    assert 'QTWEBENGINE_DISABLE_SANDBOX' not in os.environ


def test_existing_qt_flags_and_explicit_autoplay_policy_are_preserved(monkeypatch):
    monkeypatch.setattr(linux_runtime.sys, 'platform', 'linux')
    monkeypatch.setenv('QTWEBENGINE_CHROMIUM_FLAGS', '--lang=ru --autoplay-policy=user-gesture-required')
    linux_runtime.configure_environment()
    assert os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] == '--lang=ru --autoplay-policy=user-gesture-required'


@pytest.mark.skipif(sys.platform != 'linux', reason='POSIX flock must be verified on Linux')
def test_profile_lock_excludes_processes_and_keeps_inode_after_release(tmp_path):
    path = tmp_path / 'profile' / 'instance.lock'
    first = linux_runtime.InstanceLock(path)
    assert first.acquire()
    inode = path.stat().st_ino
    command = [sys.executable, '-c',
               'from linux_runtime import InstanceLock; import sys; '
               'lock=InstanceLock(sys.argv[1]); sys.exit(0 if lock.acquire() else 4)', str(path)]
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], timeout=10)
    assert result.returncode == 4
    first.release()
    second = linux_runtime.InstanceLock(path)
    assert second.acquire()
    second.release()
    assert path.stat().st_ino == inode
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux O_NOFOLLOW is required')
def test_lock_rejects_symlink_without_modifying_target(tmp_path):
    target = tmp_path / 'target'
    target.write_text('preserve')
    link = tmp_path / 'link'
    link.symlink_to(target)
    with pytest.raises(OSError):
        linux_runtime.InstanceLock(link).acquire()
    assert target.read_text() == 'preserve'


def test_native_validator_refuses_to_claim_linux_on_windows():
    if sys.platform == 'linux':
        pytest.skip('Non-Linux refusal is a host-specific contract')
    result = subprocess.run([sys.executable, 'tools/validate_linux.py', '--output', 'reports/should-not-exist'],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'Native validation requires Linux' in result.stderr
