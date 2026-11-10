"""Deep install/update regressions; all code, network, and process I/O is isolated.

These tests deliberately specify the desired behavior and fail on the audited
implementation. No real winws process, UAC prompt, route, or VPN is touched.
"""

import io
from pathlib import Path
import re
import struct
import zipfile

import pytest

import services.zapret_service as m


def _pe(marker=0):
    body = bytearray(m._PE_MIN_SIZE + 64)
    body[:2] = b"MZ"
    struct.pack_into("<I", body, 0x3C, 0x80)
    body[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", body, 0x84, 0x8664)
    body[-1] = marker
    return bytes(body)


def _archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr("zapret/binaries/windows-x86_64/" + name, content)
    return output.getvalue()


def _full_archive(marker=1):
    return _archive({name: _pe(marker) for name in m._REQUIRED_BUNDLE_FILES})


def _forbidden(*args, **kwargs):
    raise AssertionError("Unexpected external operation in isolated update test")


@pytest.fixture
def service(tmp_path, monkeypatch):
    service = m.ZapretService()
    base = tmp_path / "application"
    base.mkdir()
    service.base_dir = str(base)
    monkeypatch.setattr(service, "is_running", lambda: False)
    monkeypatch.setattr(service, "_download_zip", _forbidden)
    monkeypatch.setattr(service, "_shell_execute_elevated", _forbidden)
    monkeypatch.setattr(m.subprocess, "Popen", _forbidden)
    monkeypatch.setattr(service, "_scan_all_winws_pids", lambda: [])
    monkeypatch.setattr(service, "_classify_running_winws", lambda: (None, None))
    monkeypatch.setattr(m, "_global_zapret_guard_acquire", lambda *args: None)
    monkeypatch.setattr(m, "_global_zapret_guard_release", lambda *args: None)
    monkeypatch.setattr(m, "_win32_create_kill_on_close_job", lambda: None)
    monkeypatch.setattr(service, "get_latest_release_info",
                        lambda: (m.ZAPRET_VERSION, m.ZAPRET_ZIP_URL, ""))
    return service


def _provide_archive(service, monkeypatch, payload=None):
    # The real release hash is tested elsewhere. This isolates post-download
    # faults without contacting GitHub or storing executable release binaries.
    payload = payload if payload is not None else _full_archive()
    monkeypatch.setattr(service, "_download_zip", lambda *args, **kwargs: payload)
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *args: True)


def _existing_bundle(service, marker=0):
    for name in m._REQUIRED_BUNDLE_FILES:
        (Path(service.app_dir) / name).write_bytes(_pe(marker))


@pytest.mark.parametrize("missing", m._REQUIRED_BUNDLE_FILES[1:])
def test_force_update_repairs_same_version_with_missing_dependency(service, monkeypatch, missing):
    _existing_bundle(service)
    (Path(service.app_dir) / missing).unlink()
    service._write_version_info(m.ZAPRET_VERSION)
    _provide_archive(service, monkeypatch)

    ok, message = service.update_zapret(force=True)

    assert ok, message
    assert m.is_valid_windows_binary(str(Path(service.app_dir) / missing)), (
        "same-version winws.exe does not prove its DLLs and driver are installed"
    )


@pytest.mark.parametrize("operation", ["download_binaries", "update_zapret"])
def test_version_metadata_write_failure_is_reported_as_failure(service, monkeypatch, operation):
    service._write_version_info("v70.0")
    _provide_archive(service, monkeypatch)
    real_write = service._atomic_write_text

    def deny_version_write(path, text):
        if Path(path).name == "version.json":
            service._state_write_failed = True
            return False
        return real_write(path, text)

    monkeypatch.setattr(service, "_atomic_write_text", deny_version_write)
    events = []
    service.set_event_callback(lambda event, payload: events.append(event))

    ok, message = getattr(service, operation)()

    assert service.get_local_version() == "v70.0"
    assert not ok, "a failed install commit must reach the user: " + message
    assert "zapret_download_finished" not in events


@pytest.mark.parametrize("operation", ["download_binaries", "update_zapret"])
def test_empty_extraction_cannot_stamp_existing_fallback_as_new_version(service, monkeypatch, operation):
    fallback = Path(service.base_dir) / "bin" / "winws.exe"
    fallback.parent.mkdir()
    fallback.write_bytes(_pe(0))
    service._write_version_info("v70.0")
    # Fault injection: an extraction that commits no launcher must not count
    # a PREEXISTING executable in a different location as its own output.
    _provide_archive(service, monkeypatch, _archive({"empty.exe": b""}))

    ok, message = getattr(service, operation)()

    assert not ok, "no launcher was extracted: " + message
    assert service.get_local_version() == "v70.0"
    assert fallback.read_bytes() == _pe(0)


def test_mid_swap_failure_removes_new_files_from_previous_bundle(service, monkeypatch):
    destination = Path(service.app_dir)
    _existing_bundle(service)
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    real_replace = m.os.replace

    def fail_last_swap(src, dst):
        if Path(src).parent.name != ".bak" and Path(dst).name == "cygwin1.dll":
            raise PermissionError("injected locked DLL")
        return real_replace(src, dst)

    monkeypatch.setattr(m.os, "replace", fail_last_swap)
    payload = _archive({"winws.exe": _pe(1), "new-helper.exe": _pe(1),
                        "WinDivert.dll": _pe(1), "WinDivert64.sys": _pe(1), "cygwin1.dll": _pe(1)})

    with pytest.raises(PermissionError, match="injected locked DLL"):
        service._extract_zip(payload)

    after = {p.name: p.read_bytes() for p in destination.iterdir()}
    assert after == before, "transaction rollback left newly added executable code installed"


def test_rollback_failure_retains_recovery_copy(service, monkeypatch):
    destination = Path(service.app_dir)
    _existing_bundle(service)
    real_replace = m.os.replace

    def fail_swap_and_rollback(src, dst):
        if Path(src).parent.name == ".bak" or Path(dst).name == "cygwin1.dll":
            raise PermissionError("injected DLL lock followed by rollback lock")
        return real_replace(src, dst)

    monkeypatch.setattr(m.os, "replace", fail_swap_and_rollback)

    with pytest.raises(PermissionError):
        service._extract_zip(_full_archive())

    assert (destination / "winws.exe").read_bytes() == _pe(1)
    recovery = list(destination.parent.glob(".zapret_extract_*/.bak/winws.exe"))
    assert recovery and any(path.read_bytes() == _pe(0) for path in recovery), (
        "the failed rollback destroyed the only recovery copy of the old launcher"
    )


def test_pending_update_launches_binary_returned_after_install(service, monkeypatch):
    fallback = Path(service.base_dir) / "bin" / "winws.exe"
    fallback.parent.mkdir()
    fallback.write_bytes(_pe(0))
    service._write_version_info("v70.0", pending_update=m.ZAPRET_VERSION)
    _provide_archive(service, monkeypatch)
    launches = []
    monkeypatch.setattr(service, "_launch", lambda exe, args:
                        launches.append(exe) or ("failed", None, "isolated launch boundary"))

    service.start()

    updated = str(Path(service.app_dir) / "winws.exe")
    assert service.get_local_version() == m.ZAPRET_VERSION
    assert launches == [updated], "start retained the pre-update fallback executable path"


@pytest.mark.parametrize("location", ["executable", "log"])
def test_elevation_rejects_percent_expansion_in_approved_paths(service, monkeypatch, location):
    monkeypatch.setenv("NEDOTIFY_AUDIT_TEST", "expanded-path")
    executable = Path(service.app_dir) / "winws.exe"
    if location == "executable":
        executable = Path(service.app_dir) / "%NEDOTIFY_AUDIT_TEST%" / "winws.exe"
        executable.parent.mkdir()
    else:
        service.log_file = str(Path(service.logs_dir) / "%NEDOTIFY_AUDIT_TEST%.log")
    executable.write_bytes(_pe())
    assert m.validate_zapret_binary(str(executable), service.app_dir)
    # Model an approved installation location without making UAC/registry
    # changes. The second gate must preserve the very path it approved.
    monkeypatch.setattr(m, "_protected_elevation_path", lambda path: True)
    dispatches = []
    monkeypatch.setattr(service, "_shell_execute_elevated",
                        lambda *args: dispatches.append(args) or 5)

    ok, message = service._launch_elevated(str(executable), "--wf-tcp=80,443")

    assert not ok
    assert not dispatches, (
        "cmd.exe expands percent variables even inside quoted, validated paths: " + repr(dispatches)
    )


def test_elevated_command_explicitly_disables_delayed_expansion(service, monkeypatch):
    executable = Path(service.app_dir) / "winws.exe"
    executable.write_bytes(_pe())
    monkeypatch.setattr(m, "_protected_elevation_path", lambda path: True)
    dispatches = []
    monkeypatch.setattr(service, "_shell_execute_elevated",
                        lambda *args: dispatches.append(args) or 5)

    service._launch_elevated(str(executable), "--wf-tcp=80,443")

    assert len(dispatches) == 1
    command_flags = dispatches[0][1].split(" /c", 1)[0].lower().split()
    assert "/v:off" in command_flags, "valid !characters! in paths must stay literal"


def test_installer_expands_webview_bootstrap_url_and_destination():
    source = (Path(__file__).resolve().parents[1] / "installer.iss").read_text(encoding="utf-8")
    url = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
    # Inno's downloader avoids the entire shell-quoting boundary, including
    # apostrophes/percent signs in a real user's temporary directory.
    assert "WV2_BOOTSTRAP_URL = '" + url + "'" in source
    assert "DownloadTemporaryFile(WV2_BOOTSTRAP_URL, 'MicrosoftEdgeWebview2Setup.exe', '', nil)" in source
    assert "ExpandConstant('{tmp}\\MicrosoftEdgeWebview2Setup.exe')" in source
    assert 'DownloadCmd' not in source


def test_installer_blocks_or_recovers_when_required_webview_install_fails():
    source = (Path(__file__).resolve().parents[1] / "installer.iss").read_text(encoding="utf-8")
    body = source.split("function PrepareToInstall", 1)[1].split("procedure InitializeWizard", 1)[0]
    assignments = re.findall(r"\bResult\s*:=\s*('(?:''|[^'])*')", body)

    assert any(value != "''" for value in assignments), (
        "PrepareToInstall logs bootstrap failure but returns success with no required WebView2 runtime"
    )
