"""Zapret update-channel fixes (audit C1: BUG-004/008/010/016/029/032/038).

Everything is hermetic: GitHub fetches, downloads and process scans are
stubbed, the machine-guard mutex and the launcher are faked; no real network
call ever runs. Message assertions match stable substrings of the user-facing
Russian texts.

Covered contracts:
- BUG-004: a pending update this build cannot install is cleared instead of
  sticking forever; the auto-updater never writes pending for an
  uninstallable release; a failed pending-apply in start() is retried at most
  once per 24 h.
- BUG-008: update_zapret aborts BEFORE extraction when stop() fails — files
  of a running winws.exe must never be replaced.
- BUG-010: a failed GitHub check carries an ``error``, never masquerades as
  "у вас последняя версия".
- BUG-016: a broken version.json with a working binary announces nothing and
  is never "repaired" with version:''.
- BUG-029: release tags compare numerically (v72.9 < v72.13).
- BUG-032: _extract_zip is transactional — a failure on any file leaves
  app_dir untouched, a failure mid-swap is rolled back.
- BUG-038: the start()-path download reports its phases through the event
  hook.
"""

import io
import os
import struct
import threading
import time
import types
import zipfile

import pytest

import services.zapret_service as m
from services.zapret_service import ZapretService, ZAPRET_VERSION, ZAPRET_ZIP_URL


# ─── fixtures & fakes ────────────────────────────────────────────────────────


def _pe_bytes():
    """Minimal valid-PE-shaped content that passes is_valid_windows_binary."""
    body = m._PE_MIN_SIZE + 64
    out = bytearray(b"MZ" + b"\x00" * 0x3A)
    out += struct.pack("<I", 0x40)
    out += b"\x00" * (0x40 - len(out))
    out += b"PE\0\0" + struct.pack("<H", 0x8664)
    out += b"\x00" * (body - len(out))
    return bytes(out)


class FakeProc:
    """Popen stand-in: alive until `crash()` is called (the lifecycle watcher
    parks in wait(), so it must not return early)."""

    def __init__(self, pid=5555):
        self.pid = pid
        self.handle = 0
        self.returncode = None
        self._dead = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self._dead.wait()
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self._dead.set()

    def crash(self, code):
        self.returncode = code
        self._dead.set()


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """ZapretService with its state files pointed into a throwaway dir."""
    service = ZapretService()
    service.app_dir = str(tmp_path / "zapret")
    service.pid_file = os.path.join(service.app_dir, "run.pid")
    service.cmd_file = os.path.join(service.app_dir, "run.cmd")
    os.makedirs(service.app_dir, exist_ok=True)
    return service


def _healthy_binary(svc):
    """A real winws.exe in app_dir that passes the integrity gate."""
    path = os.path.join(svc.app_dir, "winws.exe")
    with open(path, "wb") as f:
        f.write(_pe_bytes())
    return path


def _patch_find_binary(svc, monkeypatch, path=None):
    monkeypatch.setattr(ZapretService, "find_binary",
                        lambda self, p=None: path if path is not None else _healthy_binary(svc))


def _release(tag, url):
    return lambda self: (tag, url, "")


def _release_error(message):
    return lambda self: (None, None, message)


def _autoupdate_settings(enabled=True):
    return types.SimpleNamespace(
        get=lambda cat, key, default=None:
            enabled if (cat, key) == ("zapret", "autoupdate") else default)


def _start_hermetic(svc, monkeypatch, launch_result=None):
    """Stub the launch path so start() reaches its decisions without any real
    process, scan, guard mutex or UAC."""
    monkeypatch.setattr(m, "_global_zapret_guard_acquire", lambda *a, **k: None)
    monkeypatch.setattr(m, "_global_zapret_guard_release", lambda handle: None)
    monkeypatch.setattr(ZapretService, "_classify_running_winws", lambda self: (None, None))
    monkeypatch.setattr(ZapretService, "_scan_pids_with", lambda self, sig: [])
    monkeypatch.setattr(ZapretService, "_scan_all_winws_pids", lambda self: [])
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args:
                        launch_result if launch_result is not None
                        else ("started", FakeProc(), "ok"))
    svc._launch_confirm_window = 0.0


def _write_zip(entries):
    """Build an in-memory zapret-shaped archive {archive_name: content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


# ─── BUG-029: numeric release-tag comparison ─────────────────────────────────


def test_v72_9_is_not_newer_than_v72_13():
    """The regression: string comparison announced the OLDER release."""
    assert m._version_is_newer("v72.9", "v72.13") == (False, False)


def test_v72_13_is_newer_than_v72_9():
    assert m._version_is_newer("v72.13", "v72.9") == (True, False)


def test_equal_and_padded_tags_are_not_newer():
    assert m._version_is_newer("v72.13", "v72.13") == (False, False)
    assert m._version_is_newer("72.13", "v72.13") == (False, False)
    assert m._version_is_newer("v72.13.1", "v72.13") == (True, False)
    assert m._version_is_newer("v72.13", "v72.13.0") == (False, False)


def test_unparseable_tags_degrade_conservatively():
    assert m._version_is_newer("v72.13-rc1", "v72.13") == (True, True)
    assert m._version_is_newer("v72.13", "beta") == (True, True)
    assert m._version_is_newer("beta", "beta") == (False, True)


def test_nothing_installed_means_the_latest_is_newer():
    assert m._version_is_newer("v72.13", "") == (True, False)


def test_check_announces_no_update_for_an_older_release(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    svc._write_version_info("v72.13")
    monkeypatch.setattr(ZapretService, "get_latest_release_info", _release(
        "v72.9", "https://github.com/bol-van/zapret/releases/download/v72.9/zapret-v72.9.zip"))
    res = svc.check_for_updates()
    assert res["update_available"] is False
    assert res["error"] == ""


# ─── BUG-010: a network failure is not "у вас последняя версия" ──────────────


def test_check_reports_a_fetch_failure_as_an_error(svc, monkeypatch):
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release_error("Не удалось связаться с GitHub: timeout"))
    res = svc.check_for_updates()
    assert res["error"], "the UI needs a reason to show 'check failed'"
    assert res["update_available"] is False
    assert res["latest_version"] == ""


def test_update_reports_a_fetch_failure_honestly(svc, monkeypatch):
    extract_calls = []
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release_error("no net"))
    monkeypatch.setattr(ZapretService, "_extract_zip",
                        lambda self, zb: extract_calls.append(1))
    ok, msg = svc.update_zapret()
    assert ok is False
    assert msg
    assert extract_calls == []


def test_auto_update_treats_no_network_as_no_completed_check(svc, monkeypatch):
    """A skipped check must not be recorded as done, and must not disturb the
    recorded version."""
    svc._write_version_info("v72.13")
    svc.settings = _autoupdate_settings(True)
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release_error("network down"))
    svc._auto_update_once()
    meta = svc._read_version_meta()
    assert meta.get("version") == "v72.13"
    assert "last_check" not in meta, "a failed check is not a completed check"


# ─── BUG-016: broken version.json with a working binary ─────────────────────


def test_broken_version_json_with_a_working_binary_announces_nothing(svc, monkeypatch):
    """A truncated version.json reads as version '' — with a healthy binary on
    disk that is missing metadata, not a missing install."""
    with open(os.path.join(svc.app_dir, "version.json"), "w", encoding="utf-8") as f:
        f.write('{"version": "v72.13", "last_')
    binary = _healthy_binary(svc)
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: binary)
    monkeypatch.setattr(ZapretService, "get_latest_release_info", _release(
        "v72.14", "https://github.com/bol-van/zapret/releases/download/v72.14/zapret-v72.14.zip"))
    res = svc.check_for_updates()
    assert res["update_available"] is False, "phantom update announcement"
    assert res["version_unknown"] is True


def test_auto_update_never_writes_an_empty_version_over_broken_metadata(svc, monkeypatch):
    with open(os.path.join(svc.app_dir, "version.json"), "w", encoding="utf-8") as f:
        f.write('{"ver')
    _patch_find_binary(svc, monkeypatch)
    svc.settings = _autoupdate_settings(True)
    monkeypatch.setattr(ZapretService, "get_latest_release_info", _release(
        "v72.14", "https://github.com/bol-van/zapret/releases/download/v72.14/zapret-v72.14.zip"))
    svc._auto_update_once()
    meta = svc._read_version_meta()
    assert "version" not in meta, "the auto-updater must not fabricate version:''"
    assert "pending_update" not in meta


def test_metadata_updates_preserve_the_recorded_version(svc):
    svc._write_version_info("v72.13")
    svc._update_version_meta(last_check=123.0)
    assert svc.get_local_version() == "v72.13"
    assert svc._read_version_meta()["last_check"] == 123.0
    assert not os.path.exists(os.path.join(svc.app_dir, "version.json.tmp"))


# ─── BUG-004a: a refused update clears the pending marker ────────────────────


def test_refusing_an_uninstallable_release_clears_pending(svc, monkeypatch):
    svc._write_version_info("v72.13", pending_update="v72.14")
    monkeypatch.setattr(ZapretService, "get_latest_release_info", _release(
        "v72.14", "https://github.com/bol-van/zapret/releases/download/v72.14/zapret-v72.14.zip"))
    extract_calls = []
    monkeypatch.setattr(ZapretService, "_extract_zip",
                        lambda self, zb: extract_calls.append(1))
    ok, msg = svc.update_zapret()
    assert ok is False
    assert "SHA-256" in msg
    assert extract_calls == []
    assert svc._get_pending_update() == "", "the pending marker must not stick forever"


def test_stale_pending_is_dropped_when_the_release_is_already_installed(svc, monkeypatch):
    """A pending whose tag is already on disk used to make every start() pay a
    GitHub call for a guaranteed no-op."""
    binary = _healthy_binary(svc)
    svc._write_version_info(ZAPRET_VERSION, pending_update=ZAPRET_VERSION)
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: binary)
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    ok, msg = svc.update_zapret()
    assert ok is True
    assert svc._get_pending_update() == ""


def test_successful_update_drops_the_pending_marker(svc, monkeypatch):
    svc._write_version_info("v70.0", pending_update=ZAPRET_VERSION)
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(ZapretService, "_download_zip",
                        lambda self, url, timeout=40.0:
                        _write_zip({"zapret/x86_64/winws.exe": _pe_bytes()}))
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a, **k: True)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    ok, msg = svc.update_zapret()
    assert ok is True
    assert svc._get_pending_update() == ""
    assert svc.get_local_version() == ZAPRET_VERSION
    with open(os.path.join(svc.app_dir, "winws.exe"), "rb") as f:
        assert f.read() == _pe_bytes()


# ─── BUG-004b: announcements distinguish installable from manual ────────────


def test_check_distinguishes_installable_from_manual_update(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    svc._write_version_info("v72.13")

    monkeypatch.setattr(ZapretService, "get_latest_release_info", _release(
        "v72.14", "https://github.com/bol-van/zapret/releases/download/v72.14/zapret-v72.14.zip"))
    res = svc.check_for_updates()
    assert res["update_available"] is True
    assert res["auto_installable"] is False
    assert res["manual_update_required"] is True

    # An OLDER installed build with the pinned newest release: installable.
    svc._write_version_info("v70.0")
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    res = svc.check_for_updates()
    assert res["update_available"] is True
    assert res["auto_installable"] is True
    assert res["manual_update_required"] is False


def test_pinned_release_of_the_installed_version_is_not_an_update(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    svc._write_version_info("v72.13")
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    res = svc.check_for_updates()
    assert res["update_available"] is False
    assert res["auto_installable"] is True
    assert res["manual_update_required"] is False


def test_auto_update_never_schedules_an_uninstallable_release(svc, monkeypatch):
    svc._write_version_info("v72.13")
    svc.settings = _autoupdate_settings(True)
    update_calls = []
    monkeypatch.setattr(ZapretService, "update_zapret",
                        lambda self, force=False: update_calls.append(1) or (True, "ok"))
    monkeypatch.setattr(ZapretService, "get_latest_release_info", _release(
        "v72.14", "https://github.com/bol-van/zapret/releases/download/v72.14/zapret-v72.14.zip"))
    svc._auto_update_once()
    assert svc._get_pending_update() == "", "pending for an uninstallable release deadlocks the channel"
    assert update_calls == []


def test_auto_update_marks_pending_only_for_an_installable_release(svc, monkeypatch):
    svc._write_version_info("v70.0")
    svc.settings = _autoupdate_settings(True)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: True)
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    svc._auto_update_once()
    assert svc._get_pending_update() == ZAPRET_VERSION


def test_status_message_for_an_uninstallable_pending_promises_nothing(svc, monkeypatch):
    """BUG-004: the status must not promise "применится при следующем запуске"
    for a release the updater can never install."""
    binary = _healthy_binary(svc)
    svc._write_version_info("v72.13", pending_update="v72.14")
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: binary)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: True)
    monkeypatch.setattr(m, "check_internet", lambda timeout=1.5: True)
    svc._build_status()
    message = svc._status_cache["message"]
    assert "обновите приложение" in message

    svc._write_version_info("v72.13", pending_update=ZAPRET_VERSION)
    svc._build_status()
    message = svc._status_cache["message"]
    assert "применится при следующем запуске" in message


# ─── BUG-004в: a failed pending-apply is not retried on every start ──────────


def test_failed_pending_apply_is_rate_limited_to_once_per_day(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    _start_hermetic(svc, monkeypatch)
    svc._write_version_info("v72.13", pending_update=ZAPRET_VERSION)

    update_calls = []

    def failing_update(self, force=False):
        update_calls.append(1)
        return False, "Не удалось связаться с GitHub"

    monkeypatch.setattr(ZapretService, "update_zapret", failing_update)

    ok1, _ = svc.start()
    assert update_calls == [1], "the first start should attempt the pending apply"
    assert ok1 is True, "a failed pending apply must not block the launch"

    ok2, _ = svc.start()
    assert len(update_calls) == 1, "the failed pending apply must not retry on the next start"

    # After 24 h the retry is allowed again.
    svc._update_version_meta(pending_failed_at=time.time() - 90000)
    svc.start()
    assert len(update_calls) == 2


def test_successful_pending_apply_leaves_no_retry_debt(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    _start_hermetic(svc, monkeypatch)
    svc._write_version_info("v72.13", pending_update=ZAPRET_VERSION)

    update_calls = []

    def resolving_update(self, force=False):
        update_calls.append(1)
        self._clear_pending_update()
        return True, "Zapret успешно обновлен!"

    monkeypatch.setattr(ZapretService, "update_zapret", resolving_update)

    assert svc.start()[0] is True
    assert len(update_calls) == 1
    svc.start()
    svc.start()
    assert len(update_calls) == 1, "a resolved pending must not trigger more GitHub calls"


# ─── BUG-008: update must not unpack over a running winws ────────────────────


def test_update_aborts_before_extraction_when_stop_fails(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    svc._write_version_info("v70.0")
    monkeypatch.setattr(ZapretService, "is_running", lambda self: True)
    monkeypatch.setattr(ZapretService, "stop",
                        lambda self: (False, "Не удалось остановить процесс Zapret (PID 123)"))
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    monkeypatch.setattr(ZapretService, "_download_zip",
                        lambda self, url, timeout=40.0: b"zip")
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a, **k: True)
    extract_calls = []
    monkeypatch.setattr(ZapretService, "_extract_zip",
                        lambda self, zb: extract_calls.append(1))

    ok, msg = svc.update_zapret()
    assert ok is False
    assert extract_calls == [], "extraction over a live process must never start"
    assert "останов" in msg and "работающего процесса" in msg


def test_update_stops_before_extraction_and_restarts_after(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    _healthy_binary(svc)  # the old bundle that gets replaced
    svc._write_version_info("v70.0", pending_update=ZAPRET_VERSION)
    order = []

    monkeypatch.setattr(ZapretService, "is_running", lambda self: True)
    monkeypatch.setattr(ZapretService, "stop",
                        lambda self: order.append("stop") or (True, "Zapret остановлен"))
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    monkeypatch.setattr(ZapretService, "_download_zip",
                        lambda self, url, timeout=40.0:
                        _write_zip({"zapret/x86_64/winws.exe": _pe_bytes()}))
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a, **k: True)
    real_replace = os.replace

    def replace(src, dst):
        if dst.endswith("winws.exe"):
            order.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.setattr(ZapretService, "start",
                        lambda self, **kw: order.append("restart") or (True, "ok"))

    ok, msg = svc.update_zapret()
    assert ok is True
    assert order == ["stop", "replace", "restart"], "stop must precede the swap"
    assert svc.get_local_version() == ZAPRET_VERSION
    assert svc._get_pending_update() == ""


def test_failed_extraction_after_a_stop_restores_the_bypass(svc, monkeypatch):
    """The update stopped the bypass, then extraction failed: the previous
    bundle is intact (transactional extraction), so Zapret is restarted."""
    _patch_find_binary(svc, monkeypatch)
    svc._write_version_info("v70.0")
    monkeypatch.setattr(ZapretService, "is_running", lambda self: True)
    monkeypatch.setattr(ZapretService, "stop",
                        lambda self: (True, "Zapret остановлен"))
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    monkeypatch.setattr(ZapretService, "_download_zip",
                        lambda self, url, timeout=40.0: b"zip")
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a, **k: True)
    monkeypatch.setattr(ZapretService, "_extract_zip",
                        lambda self, zb: (_ for _ in ()).throw(ValueError("битый файл")))
    restarted = []
    monkeypatch.setattr(ZapretService, "start",
                        lambda self, **kw: restarted.append(1) or (True, "ok"))
    monkeypatch.setattr(m.time, "sleep", lambda s: None)

    ok, msg = svc.update_zapret()
    assert ok is False
    assert restarted == [1], "a stopped bypass must not stay off after a failed update"
    assert "перезапущен" in msg


# ─── BUG-032: transactional extraction ───────────────────────────────────────


def _extract_tmp_dirs(svc):
    parent = os.path.dirname(svc.app_dir)
    return [n for n in os.listdir(parent) if n.startswith(".zapret_extract_")]


def test_failure_on_the_second_file_leaves_app_dir_untouched(svc):
    target = os.path.join(svc.app_dir, "winws.exe")
    with open(target, "wb") as f:
        f.write(b"OLD-CONTENT")
    good = _pe_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zapret/x86_64/winws.exe", good)          # valid
        z.writestr("zapret/x86_64/cygwin1.dll", b"\x00" * 16)  # invalid PE

    with pytest.raises(ValueError):
        svc._extract_zip(buf.getvalue())

    with open(target, "rb") as f:
        assert f.read() == b"OLD-CONTENT", "the first file must not be swapped in"
    assert sorted(os.listdir(svc.app_dir)) == ["winws.exe"]
    assert _extract_tmp_dirs(svc) == [], "the temp dir must be cleaned up"


def test_a_mid_swap_failure_is_rolled_back(svc, monkeypatch):
    """os.replace failing on the second target (a locked exe) must restore the
    first one instead of leaving a mixture of old and new binaries."""
    old_winws = _pe_bytes()
    old_dll = _pe_bytes()[:-1] + b"\x01"
    with open(os.path.join(svc.app_dir, "winws.exe"), "wb") as f:
        f.write(old_winws)
    with open(os.path.join(svc.app_dir, "cygwin1.dll"), "wb") as f:
        f.write(old_dll)

    real_replace = os.replace

    def failing_replace(src, dst):
        if os.path.basename(dst) == "cygwin1.dll":
            raise PermissionError(32, "файл занят другим процессом")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    new_winws = _pe_bytes()[:-1] + b"\x02"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zapret/x86_64/winws.exe", new_winws)
        z.writestr("zapret/x86_64/cygwin1.dll", _pe_bytes())

    with pytest.raises(PermissionError):
        svc._extract_zip(buf.getvalue())

    with open(os.path.join(svc.app_dir, "winws.exe"), "rb") as f:
        assert f.read() == old_winws, "the already-moved file must be rolled back"
    with open(os.path.join(svc.app_dir, "cygwin1.dll"), "rb") as f:
        assert f.read() == old_dll
    assert sorted(os.listdir(svc.app_dir)) == ["cygwin1.dll", "winws.exe"]
    assert _extract_tmp_dirs(svc) == []


def test_successful_extract_swaps_every_valid_file(svc):
    payload = _pe_bytes()
    dll = _pe_bytes()[:-1] + b"\x03"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zapret/x86_64/bin/winws.exe", payload)
        z.writestr("zapret/x86_64/bin/cygwin1.dll", dll)
        z.writestr("zapret/README.txt", b"docs are not binaries")
        z.writestr("zapret/x86_64/bin/empty.exe", b"")  # skipped, not an error
    svc._extract_zip(buf.getvalue())

    with open(os.path.join(svc.app_dir, "winws.exe"), "rb") as f:
        assert f.read() == payload
    assert os.path.isfile(os.path.join(svc.app_dir, "cygwin1.dll"))
    assert not os.path.isfile(os.path.join(svc.app_dir, "empty.exe"))
    assert not os.path.isfile(os.path.join(svc.app_dir, "README.txt"))
    assert sorted(os.listdir(svc.app_dir)) == ["cygwin1.dll", "winws.exe"]
    assert _extract_tmp_dirs(svc) == []


def test_an_archive_without_usable_binaries_touches_nothing(svc):
    target = os.path.join(svc.app_dir, "winws.exe")
    with open(target, "wb") as f:
        f.write(b"OLD")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zapret/x86_64/winws.exe", b"")  # 0-byte entries are skipped
    svc._extract_zip(buf.getvalue())
    with open(target, "rb") as f:
        assert f.read() == b"OLD"
    assert _extract_tmp_dirs(svc) == []


# ─── BUG-038: the start()-path download reports its phases ───────────────────


def _collect_events(svc):
    events = []
    svc.set_event_callback(lambda name, payload=None:
                           events.append((name, dict(payload or {}))))
    return events


def test_download_reports_started_and_finished_through_the_hook(svc, monkeypatch):
    binary = _healthy_binary(svc)
    events = _collect_events(svc)
    zip_bytes = _write_zip({"zapret/x86_64/winws.exe": _pe_bytes()})
    monkeypatch.setattr(ZapretService, "_download_zip",
                        lambda self, url, timeout=30.0: zip_bytes)
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a, **k: True)
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: binary)

    ok, msg = svc.download_binaries()
    assert ok is True
    names = [name for name, _ in events]
    assert names[0] == "zapret_download_started"
    assert "zapret_download_finished" in names
    assert all(payload.get("message") for _, payload in events), "every phase carries a message"


def test_download_failure_reports_a_failed_event_with_the_reason(svc, monkeypatch):
    events = _collect_events(svc)

    def boom(self, url, timeout=30.0):
        raise OSError("сеть недоступна")

    monkeypatch.setattr(ZapretService, "_download_zip", boom)

    ok, msg = svc.download_binaries()
    assert ok is False
    assert events, "a silent download is what made the toggle look hung"
    assert events[-1][0] == "zapret_download_failed"
    assert events[-1][1].get("message")
    assert "сеть недоступна" in msg


def test_start_emits_download_events_when_the_binary_is_missing(svc, monkeypatch):
    """start() on a fresh install downloads synchronously (BUG-038) — the user
    must see the phases, and the launch must still succeed."""
    path = os.path.join(svc.app_dir, "winws.exe")
    calls = []

    def find(self, p=None):
        calls.append(1)
        return path if len(calls) >= 2 else None  # first look: nothing installed

    monkeypatch.setattr(ZapretService, "find_binary", find)
    _start_hermetic(svc, monkeypatch)

    events = _collect_events(svc)
    zip_bytes = _write_zip({"zapret/x86_64/winws.exe": _pe_bytes()})
    monkeypatch.setattr(ZapretService, "_download_zip",
                        lambda self, url, timeout=30.0: zip_bytes)
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a, **k: True)

    ok, msg = svc.start()
    assert ok is True
    names = [name for name, _ in events]
    assert "zapret_download_started" in names
    assert "zapret_download_finished" in names


def test_start_reports_the_download_reason_when_it_fails(svc, monkeypatch):
    path = os.path.join(svc.app_dir, "winws.exe")
    calls = []

    def find(self, p=None):
        calls.append(1)
        return path if len(calls) >= 2 else None

    monkeypatch.setattr(ZapretService, "find_binary", find)
    _start_hermetic(svc, monkeypatch)
    launched = []
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or ("started", FakeProc(), "ok"))
    monkeypatch.setattr(ZapretService, "download_binaries",
                        lambda self: (False, "Ошибка загрузки Zapret: нет сети"))

    ok, msg = svc.start()
    assert ok is False
    assert "нет сети" in msg, "the download failure must reach the user"
    assert launched == []


# ─── C2 review: BUG-008 residual — a failed restart after a successful ───────
# ─── update must not read as a plain success ─────────────────────────────────


def _patch_successful_update_core(svc, monkeypatch):
    """update_zapret reaches the swap+version rewrite with everything stubbed."""
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))
    monkeypatch.setattr(ZapretService, "is_running", lambda self: True)
    monkeypatch.setattr(ZapretService, "stop",
                        lambda self: (True, "Zapret остановлен"))
    monkeypatch.setattr(ZapretService, "_download_zip",
                        lambda self, url, timeout=40.0:
                        _write_zip({"zapret/x86_64/winws.exe": _pe_bytes()}))
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a, **k: True)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)


def test_update_reports_a_failed_restart_honestly(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    _healthy_binary(svc)
    svc._write_version_info("v70.0")
    _patch_successful_update_core(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "start",
                        lambda self, **kw: (False, "UAC отклонён"))

    ok, msg = svc.update_zapret()
    assert ok is True, "the binaries ARE updated"
    assert svc.get_local_version() == ZAPRET_VERSION
    assert "не удалось" in msg and "включите его повторно" in msg, \
        "a failed restart must not read as a plain success"


def test_update_survives_a_raising_restart(svc, monkeypatch):
    _patch_find_binary(svc, monkeypatch)
    _healthy_binary(svc)
    svc._write_version_info("v70.0")
    _patch_successful_update_core(svc, monkeypatch)

    def raising_start(self, **kw):
        raise RuntimeError("state machine exploded")

    monkeypatch.setattr(ZapretService, "start", raising_start)

    ok, msg = svc.update_zapret()
    assert ok is True, "a restart bug must not undo the recorded update"
    assert "включите его повторно" in msg


# ─── C2 review: BUG-004 residual — a cancelled start must not apply the ──────
# ─── pending update (and must not bounce a newer command's process) ──────────


def test_cancelled_start_skips_the_pending_apply(svc, monkeypatch):
    _start_hermetic(svc, monkeypatch)
    binary = _healthy_binary(svc)
    svc._write_version_info("v72.13", pending_update=ZAPRET_VERSION)
    update_calls = []
    monkeypatch.setattr(ZapretService, "update_zapret",
                        lambda self, force=False: update_calls.append(1) or (True, "ok"))

    find_calls = []

    def find(self, p=None):
        find_calls.append(1)
        if len(find_calls) == 1:
            # A stop()/start() arrives while the binary is being resolved.
            with svc._lock:
                svc._generation += 1
        return binary

    monkeypatch.setattr(ZapretService, "find_binary", find)

    ok, msg = svc.start()
    assert ok is False
    assert "отменён" in msg
    assert update_calls == [], "a cancelled start must not pay the GitHub round-trip"


# ─── C2 review: BUG-004 residual — the auto-update cycle is serialized ───────
# ─── against update_zapret on version.json ───────────────────────────────────


def test_auto_update_waits_for_an_in_flight_update(svc, monkeypatch):
    """The pending/last_check writes are read-modify-write transactions on
    version.json; they must never interleave with update_zapret's rewrite."""
    svc._write_version_info("v70.0")
    svc.settings = _autoupdate_settings(True)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: True)
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release(ZAPRET_VERSION, ZAPRET_ZIP_URL))

    svc._update_lock.acquire()
    done = threading.Event()
    result = {}

    def run():
        svc._auto_update_once()
        result["pending"] = svc._get_pending_update()
        done.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert not done.wait(1.5), "the auto-update must wait for the in-flight update"
        assert svc._get_pending_update() == "", "no pending write under a held update lock"
    finally:
        svc._update_lock.release()
    assert done.wait(5)
    assert result.get("pending") == ZAPRET_VERSION
    worker.join(1)


# ─── C2 review: BUG-010 hardening — a failed check asserts nothing ───────────


def test_failed_check_publishes_no_latest_version(svc, monkeypatch):
    """With version metadata present, the error payload used to echo the
    CURRENT version as ``latest_version`` — an assertion the failed check
    never verified."""
    svc._write_version_info("v72.13")
    monkeypatch.setattr(ZapretService, "get_latest_release_info",
                        _release_error("Не удалось связаться с GitHub: timeout"))
    res = svc.check_for_updates()
    assert res["error"]
    assert res["latest_version"] == ""
    assert res["download_url"] == ""
    assert res["update_available"] is False


# ─── C2 review: BUG-017 gate on the update paths ─────────────────────────────


def test_update_and_download_refuse_when_storage_is_unavailable(svc):
    svc._storage_unavailable = True
    ok, msg = svc.update_zapret()
    assert ok is False
    assert "недоступен" in msg

    ok2, msg2 = svc.download_binaries()
    assert ok2 is False
    assert "недоступен" in msg2
    assert not os.path.exists(os.path.join(svc.app_dir, "winws.exe"))
