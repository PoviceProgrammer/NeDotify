"""WinAPI / security / elevation fixes (audit B1: BUG-001/018/019/027/028/
039/040/044/045/048).

Everything here is hermetic: the registry, console codepage output, the taskkill
runs, ShellExecuteW and the raw Popen call are faked or fed canned bytes; no
real process, UAC prompt or system mutation ever runs. Message assertions match
the user-facing Russian text only on stable substrings.
"""

import ctypes
import os
import struct
import sys
import time
from types import SimpleNamespace

import pytest

import services.zapret_service as m
from services.zapret_service import ZapretService


# ─── fixtures & fakes ────────────────────────────────────────────────────────


def _pe_bytes():
    """Minimal valid-PE-shaped content so the binary gates pass."""
    body = m._PE_MIN_SIZE + 64
    out = bytearray(b"MZ" + b"\x00" * 0x3A)
    out += struct.pack("<I", 0x40)
    out += b"\x00" * (0x40 - len(out))
    out += b"PE\0\0" + struct.pack("<H", 0x8664)
    out += b"\x00" * (body - len(out))
    return bytes(out)


class CallRecorder:
    """Records taskkill / ShellExecuteW invocations."""

    def __init__(self, result=33, action=None):
        self.calls = []
        self.result = result
        self.action = action

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.action:
            self.action()
        return self.result


@pytest.fixture
def svc(tmp_path, redirect_home, monkeypatch):
    """ZapretService with its system touchpoints faked out.

    The scans are patched on the INSTANCE (not the class) so individual tests
    can restore the real implementation with monkeypatch.delattr — the wmic
    test needs the real _scan_pids_with to run.
    """
    service = ZapretService()
    monkeypatch.setattr(service, "app_dir", str(tmp_path / "zapret"), raising=False)
    monkeypatch.setattr(service, "pid_file",
                        os.path.join(str(tmp_path / "zapret"), "run.pid"), raising=False)
    monkeypatch.setattr(service, "cmd_file",
                        os.path.join(str(tmp_path / "zapret"), "run.cmd"), raising=False)
    os.makedirs(service.app_dir, exist_ok=True)
    monkeypatch.setattr(m, "_global_zapret_guard_acquire", lambda *a, **k: None)
    monkeypatch.setattr(m, "_global_zapret_guard_release", lambda handle: None)
    monkeypatch.setattr(service, "_classify_running_winws", lambda: (None, None))
    monkeypatch.setattr(service, "find_binary", lambda p=None: "C:\\fake\\winws.exe")
    monkeypatch.setattr(service, "_get_pending_update", lambda: "")
    monkeypatch.setattr(service, "_scan_pids_with", lambda sig: [])
    monkeypatch.setattr(service, "_scan_all_winws_pids", lambda: [])
    service._launch_confirm_window = 0.0
    # Real elevated launches wait 5s for PID discovery — shrink for tests.
    service._elevation_scan_window = 0.05
    return service


def _write_pe(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(_pe_bytes())
    return path


# ─── BUG-001: elevation only from verified installation roots ────────────────


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry/UAC gate")
class TestProtectedElevationPath:
    def test_verified_install_location_allows_elevation(self, tmp_path, monkeypatch):
        install_root = tmp_path / "install"
        exe = _write_pe(str(install_root / "bin" / "winws.exe"))
        monkeypatch.setattr(m, "_query_registry_install_location",
                            lambda: str(install_root))
        monkeypatch.setattr(sys, "executable", str(install_root / "NeDotify.exe"))
        assert m._protected_elevation_path(exe) is True

    def test_downloaded_bundle_without_registry_stays_denied(self, svc, monkeypatch):
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        monkeypatch.setattr(m, "_query_registry_install_location", lambda: None)
        assert m._protected_elevation_path(exe) is False

    def test_forged_install_location_not_hosting_the_app_is_denied(self, tmp_path, monkeypatch):
        """A rogue HKCU entry must not vouch for binaries outside the real
        installation: the running NeDotify itself must live inside the
        verified root."""
        install_root = tmp_path / "install"
        exe = _write_pe(str(install_root / "bin" / "winws.exe"))
        monkeypatch.setattr(m, "_query_registry_install_location",
                            lambda: str(install_root))
        monkeypatch.setattr(sys, "executable", str(tmp_path / "elsewhere" / "NeDotify.exe"))
        assert m._protected_elevation_path(exe) is False

    def test_binary_failing_validation_inside_install_location_is_denied(self, tmp_path, monkeypatch):
        install_root = tmp_path / "install"
        exe = _write_pe(str(install_root / "bin" / "winws.exe"))
        with open(exe, "wb") as f:
            f.write(b"garbage not a pe image" * 16)
        monkeypatch.setattr(m, "_query_registry_install_location",
                            lambda: str(install_root))
        monkeypatch.setattr(sys, "executable", str(install_root / "NeDotify.exe"))
        assert m._protected_elevation_path(exe) is False

    def test_sibling_directory_of_install_location_is_denied(self, tmp_path, monkeypatch):
        install_root = tmp_path / "install"
        exe = _write_pe(str(tmp_path / "installEvil" / "winws.exe"))
        monkeypatch.setattr(m, "_query_registry_install_location",
                            lambda: str(install_root))
        monkeypatch.setattr(sys, "executable", str(install_root / "NeDotify.exe"))
        assert m._protected_elevation_path(exe) is False

    def test_program_files_branch_still_works(self, tmp_path, monkeypatch):
        pf = tmp_path / "Program Files"
        exe = _write_pe(str(pf / "Zapret" / "winws.exe"))
        known = {0x0026: str(pf), 0x002A: str(tmp_path / "Program Files (x86)")}

        def fake_shgetfolderpath(hwnd, csidl, token, flags, buf):
            buf.value = known[csidl]
            return 0

        monkeypatch.setattr(ctypes, "windll", SimpleNamespace(
            shell32=SimpleNamespace(SHGetFolderPathW=fake_shgetfolderpath)))
        assert m._protected_elevation_path(exe) is True

    def test_program_files_sibling_is_denied(self, tmp_path, monkeypatch):
        pf = tmp_path / "Program Files"
        exe = _write_pe(str(tmp_path / "Program FilesEvil" / "winws.exe"))
        known = {0x0026: str(pf), 0x002A: str(tmp_path / "Program Files (x86)")}

        def fake_shgetfolderpath(hwnd, csidl, token, flags, buf):
            buf.value = known[csidl]
            return 0

        monkeypatch.setattr(ctypes, "windll", SimpleNamespace(
            shell32=SimpleNamespace(SHGetFolderPathW=fake_shgetfolderpath)))
        assert m._protected_elevation_path(exe) is False

    def test_ancestor_install_location_forgery_is_denied(self, tmp_path, monkeypatch):
        """A rogue HKCU entry pointing at an ANCESTOR of the real install dir
        (e.g. the user profile) must not bless a winws.exe planted next to the
        real installation: the accepted root is EXACTLY the directory of the
        running executable, not any superset of it."""
        real_install = tmp_path / "real"
        exe = _write_pe(str(tmp_path / "evil" / "winws.exe"))
        monkeypatch.setattr(m, "_query_registry_install_location",
                            lambda: str(tmp_path))
        monkeypatch.setattr(sys, "executable", str(real_install / "NeDotify.exe"))
        assert m._protected_elevation_path(exe) is False

    def test_registry_query_expands_reg_expand_sz(self, monkeypatch):
        monkeypatch.setenv("NEDOTIFY_TEST_INSTALL", r"C:\Apps\NeDotify")

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU", HKEY_LOCAL_MACHINE="HKLM",
            KEY_WOW64_64KEY=0x0100, KEY_WOW64_32KEY=0x0200,
            KEY_READ=0x20019, REG_EXPAND_SZ=2,
            OpenKey=lambda hive, subkey, reserved=0, access=0: FakeKey(),
            QueryValueEx=lambda key, name: (r"%NEDOTIFY_TEST_INSTALL%", 2),
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
        assert m._query_registry_install_location() == r"C:\Apps\NeDotify"

    def test_registry_query_falls_back_to_32bit_view(self, monkeypatch):
        """A redirected (WOW64) uninstall entry must still be found: the
        64-bit view is tried first, then the 32-bit view."""
        seen_access = []

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def open_key(hive, subkey, reserved=0, access=0):
            seen_access.append(access)
            if access & 0x0100:  # 64-bit view: entry not there
                raise OSError("not found")
            return FakeKey()

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU", HKEY_LOCAL_MACHINE="HKLM",
            KEY_WOW64_64KEY=0x0100, KEY_WOW64_32KEY=0x0200,
            KEY_READ=0x20019, REG_EXPAND_SZ=2,
            OpenKey=open_key,
            QueryValueEx=lambda key, name: (r"C:\Apps\NeDotify", 1),
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
        assert m._query_registry_install_location() == r"C:\Apps\NeDotify"
        assert any(a & 0x0200 for a in seen_access)

    def test_registry_query_reads_hkcu_and_falls_back_to_none(self, monkeypatch):
        opened = []

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def open_key(hive, subkey, reserved=0, access=0):
            opened.append((hive, subkey))
            if hive == "HKCU":
                return FakeKey()
            raise OSError("not found")

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU", HKEY_LOCAL_MACHINE="HKLM",
            KEY_WOW64_64KEY=0x0100, KEY_WOW64_32KEY=0x0200,
            KEY_READ=0x20019, REG_EXPAND_SZ=2,
            OpenKey=open_key,
            QueryValueEx=lambda key, name: (r"C:\Apps\NeDotify", "REG_SZ"),
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
        assert m._query_registry_install_location() == r"C:\Apps\NeDotify"
        assert opened[0][0] == "HKCU"

    def test_registry_query_returns_none_when_key_missing(self, monkeypatch):
        def open_key(hive, subkey, reserved=0, access=0):
            raise OSError("not found")

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU", HKEY_LOCAL_MACHINE="HKLM",
            KEY_WOW64_64KEY=0x0100, KEY_WOW64_32KEY=0x0200,
            KEY_READ=0x20019, REG_EXPAND_SZ=2,
            OpenKey=open_key, QueryValueEx=lambda key, name: ("", "REG_SZ"),
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
        assert m._query_registry_install_location() is None

    def test_launch_elevated_denies_bundle_with_reinstall_hint(self, svc, monkeypatch):
        """BUG-001: the denial for the downloaded bundle must point at
        reinstalling/updating the app, not at an unreachable Program Files."""
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        monkeypatch.setattr(m, "_query_registry_install_location", lambda: None)
        recorder = CallRecorder(result=33)
        monkeypatch.setattr(svc, "_shell_execute_elevated", recorder)
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is False
        assert "Переустановите" in msg
        assert svc.app_dir in msg
        assert recorder.calls == []  # never reached ShellExecuteW

    def test_launch_elevated_accepts_verified_install(self, svc, tmp_path, monkeypatch):
        install_root = tmp_path / "install"
        exe = _write_pe(str(install_root / "bin" / "winws.exe"))
        # Mimic the installed layout: the app's binary root IS the install dir.
        monkeypatch.setattr(svc, "base_dir", str(install_root), raising=False)
        monkeypatch.setattr(m, "_query_registry_install_location",
                            lambda: str(install_root))
        monkeypatch.setattr(sys, "executable", str(install_root / "NeDotify.exe"))
        monkeypatch.setattr(svc, "_shell_execute_elevated", CallRecorder(result=42))
        monkeypatch.setattr(svc, "_read_pidfile", lambda: None)
        monkeypatch.setattr(svc, "_pid_alive", lambda pid: True)
        monkeypatch.setattr(svc, "_is_our_winws_process", lambda pid, sig="", signature_verified=False: True)
        monkeypatch.setattr(svc, "_scan_pids_with", lambda sig: [1234])
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True
        assert "Zapret активен" in msg


# ─── BUG-018: wmic UTF-16LE console output ───────────────────────────────────


class TestConsoleDecoding:
    def test_utf16le_with_bom(self):
        raw = "Node,CommandLine,ProcessId\r\nPC,\"cmd here\",4321\r\n".encode("utf-16")
        assert "ProcessId" in m._decode_console_bytes(raw)
        assert "\x00" not in m._decode_console_bytes(raw)

    def test_utf16le_without_bom(self):
        raw = "ProcessId 4321".encode("utf-16-le")
        assert "4321" in m._decode_console_bytes(raw)

    def test_utf8_passthrough(self):
        assert m._decode_console_bytes("plain ascii".encode("utf-8")) == "plain ascii"

    def test_cp866_oem_output(self):
        raw = "Ошибка доступа".encode("cp866")
        assert "Ошибка доступа" == m._decode_console_bytes(raw).strip()

    def test_empty(self):
        assert m._decode_console_bytes(b"") == ""

    def test_wmic_branch_finds_pid_from_utf16_output(self, svc, monkeypatch):
        """The whole point of BUG-018: on a live wmic system (Win10) the fast
        scan branch must actually return the PID — utf-8 decoding made it
        permanently empty."""
        monkeypatch.delattr(svc, "_scan_pids_with")  # restore the real scan
        csv_text = ('Node,CommandLine,ProcessId\r\n'
                    'PC,"C:\\zapret\\winws.exe --wf-tcp=80,443 SIGMARK",4321\r\n')
        monkeypatch.setattr(m.subprocess, "check_output",
                            lambda *a, **k: csv_text.encode("utf-16"))
        monkeypatch.setattr(svc, "_pid_alive", lambda pid: True)
        monkeypatch.setattr(svc, "_is_winws_process", lambda pid: True)
        assert svc._scan_pids_with("SIGMARK") == [4321]

    def test_wmic_branch_ignores_non_matching_cmdline(self, svc, monkeypatch):
        monkeypatch.delattr(svc, "_scan_pids_with")  # restore the real scan
        csv_text = ('Node,CommandLine,ProcessId\r\n'
                    'PC,"C:\\zapret\\winws.exe --other",4321\r\n')
        monkeypatch.setattr(m.subprocess, "check_output",
                            lambda *a, **k: csv_text.encode("utf-16"))
        monkeypatch.setattr(svc, "_pid_alive", lambda pid: True)
        monkeypatch.setattr(svc, "_is_winws_process", lambda pid: True)
        assert svc._scan_pids_with("SIGMARK") == []


# ─── BUG-019: log decoding across codepages ──────────────────────────────────


class TestLogDecoding:
    def test_cp866_log_is_readable(self, svc):
        with open(svc.log_file, "wb") as f:
            f.write("Отказано в доступе.\r\nВторая строка.\r\n".encode("cp866"))
        tail = svc._read_log_tail()
        assert any("Отказано в доступе." in line for line in tail)
        assert "\ufffd" not in " ".join(tail)

    def test_utf8_log_is_readable(self, svc):
        with open(svc.log_file, "wb") as f:
            f.write("plain error line\r\n".encode("utf-8"))
        assert svc._read_log_tail() == ["plain error line"]

    def test_utf16_log_is_readable(self, svc):
        with open(svc.log_file, "wb") as f:
            f.write("unicode log line\r\n".encode("utf-16"))
        assert svc._read_log_tail() == ["unicode log line"]

    def test_offset_reads_only_appended_content(self, svc):
        with open(svc.log_file, "wb") as f:
            f.write(b"OLD SESSION Access is denied\r\n")
        offset = os.path.getsize(svc.log_file)
        with open(svc.log_file, "ab") as f:
            f.write(b"new run line 1\r\nnew run line 2\r\n")
        tail = svc._read_log_tail(offset=offset)
        assert tail == ["new run line 1", "new run line 2"]

    def test_offset_zero_reads_everything(self, svc):
        with open(svc.log_file, "wb") as f:
            f.write(b"first\r\nsecond\r\n")
        assert svc._read_log_tail(offset=0) == ["first", "second"]


# ─── BUG-027: anchored crash-analysis patterns ───────────────────────────────


class TestCrashAnalysis:
    @pytest.mark.parametrize("line", [
        "WinDivertOpen: error 5",
        "WinDivertOpen failed, winerror 5",
        "[ERROR] Access is denied.",
        "permission denied for driver",
        "The requested operation requires elevation",
        "This operation requires administrator",
        "err=5 while opening device",
        "недостаточно прав для запуска драйвера",
        "Отказано в доступе.",
        "Требуются права администратора",
    ])
    def test_elevation_true_positives(self, svc, line):
        assert svc._looks_like_elevation_needed([line]) is True

    @pytest.mark.parametrize("line", [
        "loaded module C:\\Users\\Admin\\some.dll",  # BUG-027 false positive
        "user Admin started the session",
        "opening C:\\Program Files\\Administrator Tools\\x.exe",
        "failed with error 50",
        "exit code 500 reported",
        "host administered check failed",
    ])
    def test_admin_path_and_loose_numbers_are_not_elevation(self, svc, line):
        assert svc._looks_like_elevation_needed([line]) is False

    def test_error_5_word_boundary(self, svc):
        assert svc._looks_like_elevation_needed(["error 5 occurred"]) is True
        assert svc._looks_like_elevation_needed(["error 50 occurred"]) is False

    def test_admin_path_crash_gets_the_generic_diagnosis(self, svc):
        msg = svc._analyze_crash(["cannot load C:\\Users\\Admin\\winws.dll, error 50"])
        assert "UAC" not in msg
        assert "краш" in msg

    def test_windivert_busy_diagnosis(self, svc):
        assert "занят" in svc._analyze_crash(["windivert driver is busy"])
        assert "занят" in svc._analyze_crash(["драйвер WinDivert занят"])
        msg = svc._analyze_crash(["WinDivertOpen failed"])
        assert "Не удалось загрузить драйвер WinDivert" in msg

    def test_windivert_access_denied_is_elevation(self, svc):
        msg = svc._analyze_crash(["WinDivertOpen: Access is denied."])
        assert "администратора" in msg

    def test_bare_access_denied_phrase_in_a_path_is_not_elevation(self, svc):
        """BUG-027 review: 'Access Denied' inside a path must not diagnose UAC
        (FormatMessage always writes 'Access is denied', so the bare variant
        adds no real coverage)."""
        assert svc._looks_like_elevation_needed(
            ["opening C:\\Access Denied Files\\x.dll failed, error 50"]) is False

    def test_administrator_account_path_is_not_elevation(self, svc):
        """BUG-027 review: the built-in Russian account IS named
        «Администратор», so a bare «администратор» matched user-profile paths;
        only rights-context phrases must match."""
        assert svc._looks_like_elevation_needed(
            ["cannot load C:\\Users\\Администратор\\winws.dll, error 50"]) is False
        assert svc._looks_like_elevation_needed(["запуск от имени администратора"]) is True
        assert svc._looks_like_elevation_needed(["нет прав администратора"]) is True
        assert svc._looks_like_elevation_needed(
            ["Требуются права администратора"]) is True


# ─── BUG-028: elevated launch appends to the log ─────────────────────────────


def _setup_allowed_elevation(svc, monkeypatch, exe):
    monkeypatch.setattr(m, "_protected_elevation_path", lambda path: True)
    monkeypatch.setattr(svc, "_read_pidfile", lambda: None)
    monkeypatch.setattr(svc, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(svc, "_scan_pids_with", lambda sig: [])
    monkeypatch.setattr(svc, "_scan_all_winws_pids", lambda: [])
    monkeypatch.setattr(svc, "_shell_execute_elevated", CallRecorder(result=42))
    return exe


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GetSystemDirectoryW")
class TestElevatedLogRedirect:
    def test_cmd_params_append_instead_of_truncate(self, svc, monkeypatch):
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True  # BUG-040 warning-success (see below)
        recorder = svc._shell_execute_elevated
        assert len(recorder.calls) == 1
        comspec, cmd_params, cwd = recorder.calls[0][0]
        assert comspec.endswith("cmd.exe")
        assert os.path.dirname(exe) == cwd
        assert f'>> "{svc.log_file}" 2>&1"' in cmd_params
        assert f'> "{svc.log_file}"' not in cmd_params.replace(f'>> "{svc.log_file}"', "")

    def test_oversized_log_is_rotated_before_elevated_launch(self, svc, monkeypatch):
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        with open(svc.log_file, "wb") as f:
            f.write(b"x" * (1024 * 1024 + 1))
        svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert os.path.exists(svc.log_file + ".old")
        assert not os.path.exists(svc.log_file)

    def test_crash_appended_after_offset_still_fails_the_launch(self, svc, monkeypatch):
        """A previous session's log must not mask (or fake) this run's crash."""
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        with open(svc.log_file, "wb") as f:
            f.write(b"old session noise Access is denied\r\n")

        def append_crash(*args, **kwargs):
            with open(svc.log_file, "ab") as f:
                f.write("WinDivertOpen: error 5\r\n".encode("cp866"))
            return 42

        monkeypatch.setattr(svc, "_shell_execute_elevated", CallRecorder(result=42, action=append_crash))
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is False
        assert "администратора" in msg

    def test_healthy_previous_log_does_not_fake_a_crash(self, svc, monkeypatch):
        """The BUG-028 + BUG-040 pair: append mode keeps the old log, so the
        warning-success decision must judge only what THIS run appended."""
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        with open(svc.log_file, "wb") as f:
            f.write(b"old session Access is denied\r\n")
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True
        assert "не удалось определить его PID" in msg


# ─── BUG-040: PID discovery failure is a warning, not a fake failure ─────────


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GetSystemDirectoryW")
class TestElevatedPidDiscovery:
    def test_pid_found_reports_active(self, svc, monkeypatch):
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        real_read_pidfile = svc._read_pidfile  # real bound method, pre-patch
        _setup_allowed_elevation(svc, monkeypatch, exe)
        monkeypatch.setattr(svc, "_scan_pids_with", lambda sig: [777])
        monkeypatch.setattr(svc, "_pid_alive", lambda pid: True)
        monkeypatch.setattr(svc, "_is_our_winws_process", lambda pid, sig="", signature_verified=False: True)
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True
        assert "Zapret активен" in msg
        # The discovered PID is recorded for a later stop() — real pidfile read.
        assert real_read_pidfile() == 777

    def test_existing_pidfile_pid_reports_active(self, svc, monkeypatch):
        """The post-loop fallback: the PID becomes attributable only after the
        scan window has closed."""
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        started = time.monotonic()

        def ours_after_window(pid, sig="", signature_verified=False):
            # Detachable only past the (0.05s) scan window + one loop sleep.
            return time.monotonic() - started > 0.15

        monkeypatch.setattr(svc, "_pid_alive", lambda pid: True)
        monkeypatch.setattr(svc, "_is_our_winws_process", ours_after_window)
        monkeypatch.setattr(svc, "_read_pidfile", lambda: 999)
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True
        assert "ранее запущен" in msg

    def test_empty_log_reports_warning_success_not_failure(self, svc, monkeypatch):
        """BUG-040: the old path claimed «не запустился» and invited an
        immediate relaunch — a second elevated winws over the live one."""
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True
        assert "не удалось определить его PID" in msg
        assert "не запустился" not in msg


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GetSystemDirectoryW")
class TestElevatedPidPresumption:
    """BUG-040 review: a warning-success used to leave is_running() False, so
    the status panel showed «отключен» right after a successful toggle and a
    repeated start() could not see the probable first instance."""

    def test_warning_success_reports_running_until_stopped(self, svc, monkeypatch):
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True
        assert svc._elevation_pid_unknown is True
        assert svc.is_running() is True

        stopped, _ = svc.stop()
        assert stopped is True
        assert svc._elevation_pid_unknown is False
        assert svc.is_running() is False

    def test_positive_pid_discovery_clears_the_presumption(self, svc, monkeypatch):
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        monkeypatch.setattr(svc, "_scan_pids_with", lambda sig: [777])
        monkeypatch.setattr(svc, "_pid_alive", lambda pid: True)
        monkeypatch.setattr(svc, "_is_our_winws_process", lambda pid, sig="", signature_verified=False: True)
        ok, msg = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True
        assert svc._elevation_pid_unknown is False

    def test_build_status_reports_the_unknown_pid_state(self, svc, monkeypatch):
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        _setup_allowed_elevation(svc, monkeypatch, exe)
        monkeypatch.setattr(m, "check_internet", lambda timeout=1.5: True)
        ok, _ = svc._launch_elevated(exe, "--wf-tcp=80,443")
        assert ok is True
        svc._build_status()
        status = svc._status_cache
        assert status["running"] is True
        assert "PID не определён" in status["message"]


# ─── BUG-039: taskkill filters by the actual image name ──────────────────────


class TestKillPid:
    def test_zapret_exe_is_stopped_with_its_own_name(self, svc, monkeypatch):
        state = {"alive": True, "commands": []}

        def fake_run(cmd, **kwargs):
            state["commands"].append(cmd)
            state["alive"] = False

        monkeypatch.setattr(svc, "_pid_alive", lambda pid: state["alive"])
        monkeypatch.setattr(svc, "_is_winws_process", lambda pid: True)
        monkeypatch.setattr(svc, "_get_process_exe_path", lambda pid: "C:\\zapret\\zapret.exe")
        monkeypatch.setattr(m.subprocess, "run", fake_run)
        assert svc._kill_pid(1234) is True
        assert state["commands"], "taskkill must have run"
        for cmd in state["commands"]:
            assert "IMAGENAME eq zapret.exe" in cmd
            assert "/PID 1234" in cmd
            assert "winws*" not in cmd

    def test_filter_is_dropped_when_the_path_is_unreadable(self, svc, monkeypatch):
        """Elevated process with an unreadable exe path AND no tasklist name:
        the PID was already verified by _is_winws_process, so /PID alone is a
        last resort (PID-reuse TOCTOU is documented in _kill_pid)."""
        state = {"alive": True, "commands": []}

        def fake_run(cmd, **kwargs):
            state["commands"].append(cmd)
            state["alive"] = False

        monkeypatch.setattr(svc, "_pid_alive", lambda pid: state["alive"])
        monkeypatch.setattr(svc, "_is_winws_process", lambda pid: True)
        monkeypatch.setattr(svc, "_get_process_exe_path", lambda pid: None)
        monkeypatch.setattr(svc, "_tasklist_image_name", lambda pid: None)
        monkeypatch.setattr(m.subprocess, "run", fake_run)
        assert svc._kill_pid(1234) is True
        assert state["commands"][0] == "taskkill /PID 1234"

    def test_tasklist_name_fallback_qualifies_the_filter(self, svc, monkeypatch):
        """BUG-039 hardening: when ctypes cannot read the exe path, the image
        name from tasklist still qualifies /FI instead of dropping it."""
        state = {"alive": True, "commands": []}

        def fake_run(cmd, **kwargs):
            state["commands"].append(cmd)
            state["alive"] = False

        monkeypatch.setattr(svc, "_pid_alive", lambda pid: state["alive"])
        monkeypatch.setattr(svc, "_is_winws_process", lambda pid: True)
        monkeypatch.setattr(svc, "_get_process_exe_path", lambda pid: None)
        monkeypatch.setattr(svc, "_tasklist_image_name", lambda pid: "zapret.exe")
        monkeypatch.setattr(m.subprocess, "run", fake_run)
        assert svc._kill_pid(1234) is True
        assert "IMAGENAME eq zapret.exe" in state["commands"][0]

    def test_tasklist_image_name_parses_csv_and_rejects_foreign(self, svc, monkeypatch):
        monkeypatch.setattr(
            m.subprocess, "check_output",
            lambda *a, **k: '"zapret.exe","1234","Console","1"\r\n'.encode("utf-8"))
        assert svc._tasklist_image_name(1234) == "zapret.exe"
        monkeypatch.setattr(
            m.subprocess, "check_output",
            lambda *a, **k: '"explorer.exe","1234","Console","1"\r\n'.encode("utf-8"))
        assert svc._tasklist_image_name(1234) is None

    def test_non_integer_pid_is_rejected(self, svc, monkeypatch):
        recorder = CallRecorder()
        monkeypatch.setattr(m.subprocess, "run", recorder)
        monkeypatch.setattr(svc, "_pid_alive", lambda pid: True)
        assert svc._kill_pid("1234; del /q C:\\") is False  # type/value garbage
        assert recorder.calls == []

    def test_foreign_image_process_is_never_killed(self, svc, monkeypatch):
        recorder = CallRecorder()
        monkeypatch.setattr(m.subprocess, "run", recorder)
        monkeypatch.setattr(svc, "_pid_alive", lambda pid: True)
        monkeypatch.setattr(svc, "_is_winws_process", lambda pid: False)
        assert svc._kill_pid(1234) is False
        assert recorder.calls == []


# ─── BUG-044: ctypes hygiene in the liveness helpers ─────────────────────────


class FakeFunc:
    """Callable that accepts argtypes/restype assignment like a ctypes func."""

    def __init__(self, fn):
        self._fn = fn
        self.argtypes = None
        self.restype = None

    def __call__(self, *args, **kwargs):
        return self._fn(*args, **kwargs)


class FakeKernel32:
    """kernel32 stand-in that records prototypes and answers canned errors."""

    def __init__(self, open_result, last_error, exit_code=None, get_exit_success=True):
        self.open_result = open_result
        self.last_error = last_error
        self.exit_code = exit_code
        self.get_exit_success = get_exit_success
        self.open_calls = []
        self.closed = []
        self.OpenProcess = FakeFunc(self._open_process)
        self.GetExitCodeProcess = FakeFunc(self._get_exit_code)
        self.CloseHandle = FakeFunc(self._close_handle)

    def _open_process(self, access, inherit, pid):
        self.open_calls.append((access, inherit, pid))
        return self.open_result

    def _get_exit_code(self, handle, ref):
        if self.exit_code is not None and ref is not None:
            ref._obj.value = self.exit_code
        return self.get_exit_success

    def _close_handle(self, handle):
        self.closed.append(handle)
        return True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows liveness probe")
class TestCtypesHygiene:
    def _patch_kernel32(self, monkeypatch, fake):
        created = []

        def fake_windll(name, **kwargs):
            created.append((name, kwargs))
            return fake

        monkeypatch.setattr(ctypes, "WinDLL", fake_windll)
        monkeypatch.setattr(ctypes, "get_last_error", lambda: fake.last_error)
        return created

    def test_access_denied_means_alive_and_uses_get_last_error(self, monkeypatch):
        fake = FakeKernel32(open_result=0, last_error=5)
        created = self._patch_kernel32(monkeypatch, fake)
        svc = ZapretService()
        assert svc._pid_alive(4242) is True
        # BUG-044: use_last_error=True, prototypes installed, get_last_error used.
        assert created and created[0][1].get("use_last_error") is True
        assert fake.OpenProcess.argtypes is not None
        assert fake.GetExitCodeProcess.argtypes is not None
        assert fake.CloseHandle.argtypes is not None
        assert fake.open_calls[0][2] == 4242

    def test_other_error_means_dead(self, monkeypatch):
        fake = FakeKernel32(open_result=0, last_error=87)
        self._patch_kernel32(monkeypatch, fake)
        svc = ZapretService()
        assert svc._pid_alive(4242) is False

    def test_still_active_exit_code_means_alive(self, monkeypatch):
        fake = FakeKernel32(open_result=1234, last_error=0, exit_code=259)
        self._patch_kernel32(monkeypatch, fake)
        svc = ZapretService()
        assert svc._pid_alive(4242) is True
        assert fake.closed == [1234]

    def test_exited_exit_code_means_dead(self, monkeypatch):
        fake = FakeKernel32(open_result=1234, last_error=0, exit_code=0)
        self._patch_kernel32(monkeypatch, fake)
        svc = ZapretService()
        assert svc._pid_alive(4242) is False

    def test_ctypes_failure_never_falls_back_to_os_kill(self, monkeypatch):
        """The os.kill probe is POSIX-only: on Windows (Python < 3.14) it
        would TerminateProcess the target instead of probing it."""
        def boom(*args, **kwargs):
            raise RuntimeError("kernel32 unavailable")

        monkeypatch.setattr(ctypes, "WinDLL", boom)
        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
        svc = ZapretService()
        assert svc._pid_alive(4242) is False
        assert killed == []

    def test_is_winws_process_sets_prototypes(self, monkeypatch):
        fake = FakeKernel32(open_result=0, last_error=87)
        self._patch_kernel32(monkeypatch, fake)
        svc = ZapretService()
        assert svc._is_winws_process(4242) is False
        assert fake.OpenProcess.argtypes is not None

    def test_get_process_exe_path_sets_prototypes(self, monkeypatch):
        fake = FakeKernel32(open_result=0, last_error=87)
        self._patch_kernel32(monkeypatch, fake)
        svc = ZapretService()
        assert svc._get_process_exe_path(4242) is None
        assert fake.OpenProcess.argtypes is not None


# ─── BUG-045: a missing/AV-blocked binary is not an elevation request ────────


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive-letter path rules")
class TestLaunchOSError:
    def _launch(self, svc, monkeypatch, popen):
        exe = _write_pe(os.path.join(svc.app_dir, "winws.exe"))
        monkeypatch.setattr(m.subprocess, "Popen", popen)
        return svc._launch(exe, "--wf-tcp=80,443"), exe

    def test_file_not_found_is_reported_as_av_block(self, svc, monkeypatch):
        def popen(*args, **kwargs):
            raise FileNotFoundError(2, "The system cannot find the file specified")

        (kind, proc, msg), exe = self._launch(svc, monkeypatch, popen)
        assert kind == "failed"
        assert "антивирусом" in msg
        assert "разрешённому" not in msg

    def test_removed_binary_does_not_go_elevated(self, svc, monkeypatch):
        """AV quarantines the file between validation and Popen: isfile()
        turns False, the launch must fail honestly instead of asking UAC."""
        real_isfile = os.path.isfile
        gone = {"flag": False}

        def fake_isfile(path):
            if gone["flag"] and str(path) == str(os.path.join(svc.app_dir, "winws.exe")):
                return False
            return real_isfile(path)

        def popen(*args, **kwargs):
            gone["flag"] = True
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr(os.path, "isfile", fake_isfile)
        (kind, proc, msg), exe = self._launch(svc, monkeypatch, popen)
        assert kind == "failed"
        assert "антивирусом" in msg

    def test_permission_error_with_present_file_still_goes_elevated(self, svc, monkeypatch):
        """A manually raised PermissionError(740) (errno=740) keeps requesting
        UAC; the REAL Python 3.14 shape is covered below."""
        def popen(*args, **kwargs):
            raise PermissionError(740, "The requested operation requires elevation")

        (kind, proc, msg), exe = self._launch(svc, monkeypatch, popen)
        assert kind == "elevate"

    def test_real_winerror_740_oserror_goes_elevated(self, svc, monkeypatch):
        """Empirically verified on Python 3.14.7 (Win11, ru-RU): CreateProcess
        on a requireAdministrator exe raises a PLAIN OSError with winerror=740
        and errno=22 — NOT PermissionError. The gate must read the winerror."""
        def popen(*args, **kwargs):
            raise OSError(22, "Запрошенная операция требует повышения", None, 740, None)

        (kind, proc, msg), exe = self._launch(svc, monkeypatch, popen)
        assert kind == "elevate"

    def test_access_denied_with_present_file_fails_without_uac(self, svc, monkeypatch):
        """winerror 5 (AV quarantine / file-ACL lock) with the file still in
        place must fail honestly instead of flashing a UAC dialog that fails
        again inside the elevated cmd.exe."""
        def popen(*args, **kwargs):
            raise OSError(13, "Отказано в доступе", None, 5, None)

        (kind, proc, msg), exe = self._launch(svc, monkeypatch, popen)
        assert kind == "failed"
        assert "не удалось запустить" in msg.lower()
        assert "антивирус" in msg.lower()


# ─── BUG-048: dead owner HWND never reaches ShellExecuteW ────────────────────


class _NativeCall:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class TestOwnerWindowValidation:
    def _service_with_fake_user32(self, monkeypatch, alive, hwnd=0x1234):
        state = SimpleNamespace(hwnd=hwnd, visible=False, minimized=False,
                                alive=alive, result=42, calls=[])
        recorder = CallRecorder(result=42)
        state.recorder = recorder

        def execute(*args):
            state.calls.append(args)
            return state.result

        user32 = SimpleNamespace(
            IsWindowVisible=lambda hwnd: state.visible,
            IsIconic=lambda hwnd: state.minimized,
            IsWindow=lambda hwnd: state.alive,
            ShowWindowAsync=_NativeCall(lambda hwnd, mode: None),
        )
        shell32 = SimpleNamespace(ShellExecuteW=_NativeCall(execute))
        monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32, shell32=shell32))
        service = ZapretService()
        service._set_elevation_window(lambda: state.hwnd)
        return service, state

    def test_dead_owner_window_is_dropped(self, monkeypatch):
        service, state = self._service_with_fake_user32(monkeypatch, alive=False)
        service._shell_execute_elevated("cmd.exe", "/c winws.exe", "C:\\zapret")
        assert state.calls[0][0] is None

    def test_live_owner_window_is_kept(self, monkeypatch):
        service, state = self._service_with_fake_user32(monkeypatch, alive=True, hwnd=0x1234)
        service._shell_execute_elevated("cmd.exe", "/c winws.exe", "C:\\zapret")
        owner = state.calls[0][0]
        assert owner is not None
        assert owner.value == 0x1234


# ─── BUG-049: docstring accuracy (regression guard) ──────────────────────────


def test_launch_elevated_docstring_does_not_claim_direct_pidfile_write():
    """BUG-049: the elevated child's PID is discovered by scanning; the
    docstring must not describe a direct run.pid write mechanism."""
    doc = ZapretService._launch_elevated.__doc__ or ""
    assert "writes its PID directly" not in doc
    assert "scanning" in doc


# ─── BUG-019 review: bounded log reads (offset protection intact) ────────────


class TestLogReadWindow:
    def test_windowed_tail_cannot_leak_previous_session(self, svc, monkeypatch):
        """With a tiny window the read starts past the offset but never below
        it: old-session content stays out of this run's diagnosis."""
        monkeypatch.setattr(m, "_LOG_READ_WINDOW_BYTES", 64)
        with open(svc.log_file, "wb") as f:
            f.write(b"OLD Access is denied " + b"x" * 200 + b"\r\n")
        offset = os.path.getsize(svc.log_file)
        with open(svc.log_file, "ab") as f:
            f.write((b"n" * 30 + b"\r\n") * 4)
        tail = svc._read_log_tail(offset=offset)
        assert tail
        assert all("Access is denied" not in line for line in tail)

    def test_large_log_tail_still_decodes(self, svc):
        """Default window: a multi-hundred-KB log is read as its tail."""
        with open(svc.log_file, "wb") as f:
            f.write(b"padding\r\n" * 20000)  # ~180 KB, all ASCII
        f = open(svc.log_file, "ab")
        with f:
            f.write("Отказано в доступе.\r\n".encode("cp866"))
        tail = svc._read_log_tail()
        assert any("Отказано в доступе." in line for line in tail)


# ─── BUG-001 installer half: frozen builds must scan the install dir ─────────


def test_frozen_build_uses_install_dir_not_meipass(tmp_path, monkeypatch):
    """In the onefile layout sys._MEIPASS is a throwaway extraction dir the
    installer can never place files into; find_binary() must scan the folder
    holding NeDotify.exe so an installer-shipped {app}\\zapret bundle is
    discoverable (and elevation-eligible)."""
    app_dir = tmp_path / "app"
    bundled = _write_pe(str(app_dir / "zapret" / "winws.exe"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "NeDotify.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    service = ZapretService()
    assert os.path.normcase(service.base_dir) == os.path.normcase(str(app_dir))
    assert os.path.normcase(service.find_binary() or "") == os.path.normcase(bundled)


def test_dev_build_keeps_repo_root_as_base_dir():
    service = ZapretService()
    if getattr(sys, "frozen", False):
        pytest.skip("running inside a frozen build")
    expected = os.path.dirname(os.path.dirname(os.path.abspath(m.__file__)))
    assert service.base_dir == getattr(sys, "_MEIPASS", expected)
