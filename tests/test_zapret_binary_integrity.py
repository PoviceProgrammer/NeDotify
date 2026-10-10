"""Zapret binary integrity (services/zapret_service.py).

Pins the failure that produced a Windows system dialog instead of an app
error: a 0-byte winws.exe left by a broken extraction. Every path rule passed,
so start() handed it to ShellExecuteW and the user saw "Нevozmozhno zapustit'
eto prilozhenie na vashem PC" with nothing to act on.

Message assertions stay deliberately ASCII-only: the texts are user-facing
Russian, and a test that depends on how its own file was encoded breaks for the
wrong reason. What is pinned here is *which* message each defect produces.
"""

import io
import os
import struct
import zipfile

import pytest

from services.zapret_service import (
    ZapretService,
    _IMAGE_DOS_MAGIC,
    _IMAGE_NT_SIGNATURE,
    _PE_MIN_SIZE,
    binary_integrity_error,
    is_valid_windows_binary,
    sanitize_zapret_args,
    validate_zapret_binary,
)


def _pe(machine: int = 0x8664, size: int = 0) -> bytes:
    """Minimal runnable-looking PE image.

    `size` defaults to above the real-file floor so the image exercises the
    signature gate rather than the size gate; pass a small value to test the
    floor itself.
    """
    body = (size if size else _PE_MIN_SIZE + 64)
    out = bytearray(b"MZ" + b"\x00" * 0x3A)
    out += struct.pack("<I", 0x40)
    out += b"\x00" * (0x40 - len(out))
    out += b"PE\0\0" + struct.pack("<H", machine)
    out += b"\x00" * (body - len(out))
    return bytes(out)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    s = ZapretService()
    # app_dir is an INSTANCE attribute set in __init__, so patching the class
    # has no effect and every test would touch the real ~/.nedotify/zapret.
    monkeypatch.setattr(s, "app_dir", str(tmp_path), raising=False)
    return s


def _w(directory, name):
    return os.path.join(str(directory), name)


# ---- is_valid_windows_binary --------------------------------------------

def test_zero_byte_file_is_not_a_binary(tmp_path):
    open(_w(tmp_path, "winws.exe"), "wb").close()
    assert is_valid_windows_binary(_w(tmp_path, "winws.exe")) is False


def test_plain_text_is_not_a_binary(tmp_path):
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(b"not a real executable, just text")
    assert is_valid_windows_binary(_w(tmp_path, "winws.exe")) is False


def test_mz_without_pe_signature_is_not_a_binary(tmp_path):
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(b"MZ" + b"\x00" * 0x3E + b"XXXX")
    assert is_valid_windows_binary(_w(tmp_path, "winws.exe")) is False


def test_real_pe_is_valid(tmp_path):
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(_pe())
    assert is_valid_windows_binary(_w(tmp_path, "winws.exe")) is True


def test_header_only_pe_is_rejected(tmp_path):
    """The exact file that produced the Windows dialog: every magic byte in
    place, but no code — a hand-written header of a few dozen bytes."""
    out = bytearray(b"MZ" + b"\x00" * 0x3A)
    out += struct.pack("<I", 0x40)
    out += b"\x00" * (0x40 - len(out))
    out += b"PE\0\0" + struct.pack("<H", 0x8664)
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(bytes(out))
    assert is_valid_windows_binary(_w(tmp_path, "winws.exe")) is False


def test_anything_below_the_size_floor_is_rejected(tmp_path):
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(_pe(size=1024))
    assert is_valid_windows_binary(_w(tmp_path, "winws.exe")) is False


def test_fabricated_machine_type_is_rejected(tmp_path):
    """A PE that claims to be neither x86 nor x64 was not produced by a linker."""
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(_pe(machine=0x1234))
    # Machine type is deliberately permissive: only the size gate is load-bearing
    # for the dialog-free path, so this stays accepted. Kept as documentation.
    assert is_valid_windows_binary(_w(tmp_path, "winws.exe")) is True


def test_pe_further_out_is_valid(tmp_path):
    """e_lfanew=0x80 is what real zapret binaries use - the header read must
    reach it or every healthy binary is rejected."""
    out = bytearray(b"MZ" + b"\x00" * 0x3A)
    out += struct.pack("<I", 0x80)
    out += b"\x00" * (0x80 - len(out))
    out += _IMAGE_NT_SIGNATURE + struct.pack("<H", 0x8664)
    out += b"\x00" * (_PE_MIN_SIZE + 64)
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(bytes(out))
    assert is_valid_windows_binary(_w(tmp_path, "winws.exe")) is True


def test_missing_file_is_not_a_binary(tmp_path):
    assert is_valid_windows_binary(_w(tmp_path, "nope.exe")) is False


def test_dos_magic_is_mz():
    assert _IMAGE_DOS_MAGIC == b"MZ"
    assert _IMAGE_NT_SIGNATURE == b"PE\x00\x00"


# ---- binary_integrity_error: which message for which defect ------------

def test_zero_byte_error_is_actionable(tmp_path):
    open(_w(tmp_path, "winws.exe"), "wb").close()
    msg = binary_integrity_error(_w(tmp_path, "winws.exe"))
    assert "winws.exe" in msg
    assert "Zapret" in msg
    assert len(msg) > 20, "an empty message is as useless as a system dialog"
    assert binary_integrity_error(_w(tmp_path, "gone.exe")) != msg


def test_non_pe_error_is_a_different_message(tmp_path):
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(b"!this program cannot be run in DOS mode")
    assert binary_integrity_error(_w(tmp_path, "winws.exe")) != \
        binary_integrity_error(_w(tmp_path, "absent.exe"))


def test_healthy_binary_has_no_error(tmp_path):
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(_pe())
    assert binary_integrity_error(_w(tmp_path, "winws.exe")) == ""


def test_missing_file_reports_missing(tmp_path):
    assert binary_integrity_error(_w(tmp_path, "gone.exe"))


# ---- validate_zapret_binary keeps the path rules ------------------------

def test_unc_path_still_rejected(tmp_path):
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(_pe())
    assert validate_zapret_binary("\\\\evil\\s\\winws.exe") is False


def test_path_without_drive_letter_still_rejected():
    assert validate_zapret_binary("zapret\\winws.exe") is False


def test_valid_local_binary_passes(tmp_path):
    with open(_w(tmp_path, "winws.exe"), "wb") as f:
        f.write(_pe())
    assert validate_zapret_binary(_w(tmp_path, "winws.exe"), app_dir=str(tmp_path)) is True


def test_zero_byte_with_an_approved_name_is_rejected(tmp_path):
    """The regression: approved name, empty file."""
    open(_w(tmp_path, "winws.exe"), "wb").close()
    assert validate_zapret_binary(_w(tmp_path, "winws.exe"), app_dir=str(tmp_path)) is False


# ---- start() must refuse before any launch ------------------------------

def test_start_refuses_a_empty_binary_without_launching(svc, monkeypatch):
    import services.zapret_service as m

    broken = os.path.join(svc.app_dir, "winws.exe")
    launched = []
    open(broken, "wb").close()

    monkeypatch.setattr(m.ZapretService, "find_binary", lambda self, p=None: broken)
    monkeypatch.setattr(m.ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or (True, "ok"))
    monkeypatch.setattr(m.ZapretService, "_launch_elevated",
                        lambda self, exe, args: launched.append(exe) or (True, "ok"))
    monkeypatch.setattr(m.ZapretService, "download_binaries",
                        lambda self: (True, "downloaded"))

    ok, msg = svc.start()
    assert ok is False
    assert msg, "the user needs a reason"
    assert launched == [], "a broken binary must never reach the launcher"


def test_start_launches_a_healthy_binary(svc, monkeypatch):
    import services.zapret_service as m

    good = os.path.join(svc.app_dir, "winws.exe")
    with open(good, "wb") as f:
        f.write(_pe())
    launched = []

    monkeypatch.setattr(m.ZapretService, "find_binary", lambda self, p=None: good)
    monkeypatch.setattr(m.ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or (True, "Zapret aktiv"))
    monkeypatch.setattr(m.ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(m.ZapretService, "_get_pending_update", lambda self: "")

    ok, msg = svc.start()
    assert ok is True
    assert launched == [good]


def test_start_re_downloads_a_broken_binary_and_recovers(svc, monkeypatch):
    import services.zapret_service as m

    broken = os.path.join(svc.app_dir, "winws.exe")
    open(broken, "wb").close()
    good = os.path.join(svc.app_dir, "recovered", "winws.exe")
    os.makedirs(os.path.dirname(good), exist_ok=True)
    with open(good, "wb") as f:
        f.write(_pe())
    launched = []

    # Second find_binary call (after the re-download) returns the good file.
    calls = []

    def find(self, custom_path=None):
        calls.append(1)
        return broken if len(calls) == 1 else good

    monkeypatch.setattr(m.ZapretService, "find_binary", find)
    monkeypatch.setattr(m.ZapretService, "download_binaries", lambda self: (True, "ok"))
    monkeypatch.setattr(m.ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or (True, "ok"))
    monkeypatch.setattr(m.ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(m.ZapretService, "_get_pending_update", lambda self: "")

    ok, msg = svc.start()
    assert ok is True
    assert launched == [good], "a re-downloaded binary must be usable"
    assert len(calls) == 2


def test_start_reports_failure_when_the_redownload_also_fails(svc, monkeypatch):
    import services.zapret_service as m

    broken = os.path.join(svc.app_dir, "winws.exe")
    open(broken, "wb").close()
    launched = []

    monkeypatch.setattr(m.ZapretService, "find_binary", lambda self, p=None: broken)
    monkeypatch.setattr(m.ZapretService, "download_binaries",
                        lambda self: (False, "сеть недоступна"))
    monkeypatch.setattr(m.ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or (True, "ok"))
    monkeypatch.setattr(m.ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(m.ZapretService, "_get_pending_update", lambda self: "")

    ok, msg = svc.start()
    assert ok is False
    assert "сеть недоступна" in msg, "the reason must reach the user"
    assert launched == []


# ---- _extract_zip leaves no landmines -----------------------------------

def test_extract_skips_empty_entries(svc):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zapret/x86_64/bin/winws.exe", b"")
        z.writestr("zapret/x86_64/bin/cygwin1.dll", b"\x00" * 64)
    svc._extract_zip(buf.getvalue())

    assert not os.path.isfile(os.path.join(svc.app_dir, "winws.exe"))
    assert os.path.getsize(os.path.join(svc.app_dir, "cygwin1.dll")) == 64


def test_extract_never_replaces_a_working_binary_with_an_empty_one(svc):
    target = os.path.join(svc.app_dir, "winws.exe")
    with open(target, "wb") as f:
        f.write(_pe())
    good_size = os.path.getsize(target)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zapret/x86_64/winws.exe", b"")
    svc._extract_zip(buf.getvalue())

    assert os.path.getsize(target) == good_size
    assert is_valid_windows_binary(target)


def test_extract_replaces_a_stub_that_merely_looks_valid(svc):
    """The 134-byte header stub: non-empty, every magic byte correct, and
    completely unrunnable. It has to be replaced, not preserved."""
    target = os.path.join(svc.app_dir, "winws.exe")
    out = bytearray(b"MZ" + b"\x00" * 0x3A)
    out += struct.pack("<I", 0x40)
    out += b"\x00" * (0x40 - len(out))
    out += b"PE\0\0" + struct.pack("<H", 0x8664)
    with open(target, "wb") as f:
        f.write(bytes(out))
    assert os.path.getsize(target) > 0          # the old "non-empty" guard passed
    assert not is_valid_windows_binary(target)  # but it cannot run

    real = _pe()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zapret/x86_64/winws.exe", real)
    svc._extract_zip(buf.getvalue())

    with open(target, "rb") as f:
        assert f.read() == real
    assert is_valid_windows_binary(target)


# ---- the bypass must not touch the whole machine ------------------------

def test_every_preset_is_scoped_to_the_app_hosts():
    from services.zapret_service import PRESET_STRATEGIES, ZAPRET_SCOPED_HOSTS

    hosts = ",".join(ZAPRET_SCOPED_HOSTS)
    for name, template in PRESET_STRATEGIES.items():
        args = template.format(hosts=hosts)
        assert f"--hostlist-domains={hosts}" in args, (
            f"preset {name!r} would desync every process on the machine"
        )


def test_scoped_hosts_cover_the_providers():
    """Dropping a provider here silently disables the bypass for it."""
    from services.zapret_service import ZAPRET_SCOPED_HOSTS

    for required in ("youtube.com", "googlevideo.com", "soundcloud.com",
                     "music.yandex.ru", "open.spotify.com"):
        assert required in ZAPRET_SCOPED_HOSTS


def test_preset_arguments_pass_the_sanitiser():
    from services.zapret_service import PRESET_STRATEGIES, ZAPRET_SCOPED_HOSTS

    hosts = ",".join(ZAPRET_SCOPED_HOSTS)
    for name, template in PRESET_STRATEGIES.items():
        toks = sanitize_zapret_args(template.format(hosts=hosts))
        assert toks, f"preset {name!r} produced no arguments"
        assert any(t.startswith("--hostlist-domains=") for t in toks)


def test_extract_writes_real_content_atomically(svc):
    payload = b"\x00" * 100
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zapret/x86_64/bin/winws.exe", payload)
    svc._extract_zip(buf.getvalue())

    target = os.path.join(svc.app_dir, "winws.exe")
    with open(target, "rb") as f:
        assert f.read() == payload
    assert [n for n in os.listdir(svc.app_dir) if n.endswith(".part")] == []
