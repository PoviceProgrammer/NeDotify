"""
NeDotify - Zapret (DPI Bypass) Service
Launches and manages winws / zapret background process for Windows to bypass DPI blocks.

Phase 2 reliability contract:
- Z-2: pidfile-based identity (~/.nedotify/zapret/run.pid + run.cmd signature).
        Elevated-launch PID is discovered via `wmic` cmdline signature match;
        stop() kills ONLY our own PID (taskkill /PID), never /IM.
- Z-3: winws stderr is captured to ~/.nedotify/logs/zapret.log and crash analysis
        maps log contents to user-facing messages.
- Z-4: check_internet uses TCP-connect (port 443) across several hosts.
- Z-5: process liveness via saved PID (OpenProcess); status is cached (2.5s TTL)
        and refreshed in background, so get_status() never blocks the UI.
- Z-7/8: the state lock is only held around process state transitions;
        download/update work outside the lock but is serialized by a dedicated
        _update_lock (no concurrent downloads/updates of the same binaries);
        autoupdate defaults to OFF and, when enabled, a running winws is never
        restarted (update applies on next launch). start() on an already-running
        winws with different arguments restarts it with the new strategy.

Audit-v2 lifecycle contract (A1):
- State machine: STOPPED -> STARTING -> RUNNING -> STOPPING -> STOPPED with a
  generation counter. Every start()/stop() bumps the generation; a start whose
  generation is stale (a newer stop or start arrived meanwhile) never launches.
  This arbitrates autostart vs toggle vs cleanup (audit BUG-002/003/024).
- Lock scope: self._lock covers fast state mutations only. UAC (ShellExecuteW),
  PID scans and binary downloads run OUTSIDE the lock (BUG-007).
- Ownership: a process counts as "ours" via strict exe-path prefixes
  (os.sep-terminated), or — only when the path is
  unreadable — a pidfile record carrying our instance uid AND the recorded
  process creation time (anti PID-reuse, BUG-005/047).
- State files (run.pid, run.cmd, version.json) are written atomically
  (tmp + os.replace); write failures are logged as warnings and surfaced in
  stop()'s message instead of silently pretending everything stopped
  (BUG-014/015).
- A non-elevated child is bound to a kill-on-close Job Object so winws can
  never outlive NeDotify; an elevated (ShellExecuteW) child cannot be assigned
  — documented limitation (BUG-023).
- start() confirms the child survived a short window before reporting success
  and reports later crashes through the event hook (BUG-025).

Audit-v2 update-channel contract (C1):
- A release is auto-installable only when it is exactly the pinned one this
  build carries a trusted SHA-256 for. Newer releases are still ANNOUNCED
  (check_for_updates exposes auto_installable / manual_update_required), but
  the auto-updater never writes a pending marker for an uninstallable release
  and update_zapret clears any stale pending when it refuses one (BUG-004).
- update_zapret aborts BEFORE extraction when the running winws cannot be
  stopped, and _extract_zip is transactional (unpack+validate into a temp
  dir, then swap with rollback) (BUG-008/032).
- A failed GitHub check is reported as an error, never as "у вас последняя
  версия" (BUG-010); a broken version.json with a working binary announces
  nothing and is repaired only by a real install (BUG-016).
- Release tags compare numerically, falling back to conservative
  "difference = update" with an unknown-format flag (BUG-029).
- The start()-path auto-download reports its phases through the event hook
  ('zapret_download_started'/'zapret_download_finished'/
  'zapret_download_failed'); cancellation stays with the generation counter
  (BUG-038).
"""

import csv
import io
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Dict, Any, Tuple, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

ZAPRET_VERSION = "v72.13"
ZAPRET_ZIP_URL = f"https://github.com/bol-van/zapret/releases/download/{ZAPRET_VERSION}/zapret-{ZAPRET_VERSION}.zip"
# SHA-256 of the pinned release archive, verified before extraction.
# If it ever mismatches, the bundle is refused (no extraction, no launch).
ZAPRET_ZIP_SHA256 = "c493e33a0dc4eba23a8686efdaba55f59755ad6ade3564aebd9d13f4c65e2e0c"
_REQUIRED_BUNDLE_FILES = ("winws.exe", "WinDivert.dll", "WinDivert64.sys", "cygwin1.dll")


def _verify_zip_sha256(zip_bytes: bytes, expected_sha256: str = ZAPRET_ZIP_SHA256) -> bool:
    """Constant-time SHA-256 check of a downloaded zip archive."""
    import hashlib
    import hmac
    if not expected_sha256:
        return False
    digest = hashlib.sha256(zip_bytes).hexdigest()
    return hmac.compare_digest(digest, expected_sha256)


# ─── release-tag comparison (audit C1: BUG-029) ───
# String equality used to be the whole version logic: "v72.9" != "v72.13"
# announced an older release as an update. Tags are now parsed numerically.
_VERSION_TAG_RE = re.compile(r'^[vV]?(\d+(?:\.\d+)*)$')


def _parse_version_tag(tag: str) -> Optional[Tuple[int, ...]]:
    """Parse a release tag into a comparable numeric tuple.

    Understands the format zapret actually ships ('v72.13') plus plain and
    longer numeric forms ('72.13', 'v72.13.2'). Anything else (release
    candidates, dates, prose) returns None — the caller falls back to the
    conservative "differences mean an update" rule."""
    if not tag:
        return None
    match = _VERSION_TAG_RE.match(tag.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _version_is_newer(latest_tag: str, current_tag: str) -> Tuple[bool, bool]:
    """Numeric tag comparison (BUG-029). Returns ``(is_newer, unknown_format)``.

    ``unknown_format`` is set when a tag could not be parsed into numbers; the
    comparison then degrades conservatively to "any difference is an update"
    — silently swallowing a real update would be worse than announcing one
    that needs a manual look. An empty current tag means nothing is installed,
    so the latest release is by definition newer (and the format IS known)."""
    latest = _parse_version_tag(latest_tag)
    current = _parse_version_tag(current_tag)
    if not current_tag:
        # Nothing installed: any existing release is "newer" by definition.
        return bool(latest_tag), False
    if latest is None or current is None:
        return latest_tag != current_tag, True
    # 72.13 == 72.13.0: pad the shorter tuple with zeros.
    width = max(len(latest), len(current))
    latest += (0,) * (width - len(latest))
    current += (0,) * (width - len(current))
    return latest > current, False

# Hosts this app actually talks to. Zapret is a machine-wide WinDivert driver:
# with a bare `--filter-tcp=80,443` it rewrites packets for every process on
# the box, so a browser, a game and the OS updater all get DPI-desync they
# never asked for. Pinning the hostlist keeps the bypass on the services the
# player streams from. WinDivert has no process filter here (upstream zapret
# exposes `--pid` only for the WinDivert layer, and `--pidfile` only writes
# winws's own pid), so host scoping is the precision available.
#
# Kept in sync with the providers actually wired into the code (BUG-011):
#   core/proxy.py::YOUTUBE_HOSTS and ::SOUNDCLOUD_HOSTS — scdn.co IS a
#     SoundCloud CDN domain there (credentials are attached to it);
#   services/deezer_service.py — api.deezer.com catalogue/search;
#   services/playlist_import_service.py — deezer.com / www.deezer.com /
#     link.deezer.com playlist import;
#   services/vk_service.py — vk.com / www.vk.com / vkvideo.ru direct links.
# winws hostlist matching is suffix-based (a domain matches its subdomains),
# so deezer.com also covers link.deezer.com; the redundant www./api. entries
# follow the established explicit style of this list (www.youtube.com,
# i.ytimg.com). Deezer cover art hosts (cdns-preview-*.dzcdn.net) are NOT
# pinned on purpose: those hostnames arrive inside API payloads, never from
# provider code. Add a host here when a new provider is added.
ZAPRET_SCOPED_HOSTS = (
    "youtube.com", "youtu.be", "googlevideo.com", "ytimg.com",
    "i.ytimg.com", "www.youtube.com",
    # music.youtube.com is where /youtubei/v1/search actually lands: pinning
    # only youtube.com left the search endpoint unbypassed and it timed out.
    "music.youtube.com", "m.youtube.com", "s.youtube.com",
    "soundcloud.com", "api-v2.soundcloud.com", "sndcdn.com", "soundcloud.cloud",
    # scdn.co: a SoundCloud CDN domain per core/proxy.py::SOUNDCLOUD_HOSTS —
    # without it the desync missed exactly the hosts the proxy credentials go to.
    "scdn.co",
    # Deezer: catalogue/search endpoint plus the base domain covering the
    # playlist-import link hosts (BUG-011).
    "deezer.com", "api.deezer.com",
    # VK Music direct links (services/vk_service.py) (BUG-011).
    "vk.com", "www.vk.com", "vkvideo.ru",
    "open.spotify.com", "spotify.com",
    # SpotifyService actually searches the iTunes metadata catalogue.
    "itunes.apple.com",
    "music.yandex.ru", "storage.yandex.net",
    "ws.audioscrobbler.com", "last.fm",
)

PRESET_STRATEGIES = {
    # `--hostlist-domains` narrows the desync to the app's own providers. The
    # old `--filter-tcp=80,443` on its own means "every TCP packet in the
    # machine", which is what made Zapret affect the whole system.
    #
    # Coverage facts verified against the PINNED winws v72.13 (bol-van/zapret
    # tag v72.13: docs/readme.en.md, docs/windows.en.md, nfq/params.c,
    # nfq/nfqws.c, nfq/desync.c — BUG-012):
    # - IPv6 IS covered by every preset: the WinDivert filter defaults to both
    #   L3 protocols (nfqws.c: `wf_ipv4 = true, wf_ipv6 = true`) and each
    #   desync profile defaults to `filter_ipv4 = filter_ipv6 = true`
    #   (params.c::dp_init). There is NO `--wf-ipv6` option in v72.13 — the
    #   L3 filter is `--wf-l3=ipv4|ipv6` / `--filter-l3=ipv4|ipv6`.
    # - UDP/QUIC is NOT covered by the four original presets: inside a
    #   desync profile, setting `--filter-tcp` without `--filter-udp` DENIES
    #   UDP (documented semantics), and `--wf-tcp` keeps the driver to TCP.
    #   QUIC (UDP 443) therefore goes around these strategies entirely.
    # - The `tcp_udp` preset adds a second desync profile (`--new`) for UDP
    #   443 using the exact shape of the official v72.13 example
    #   (readme.en.md: `--filter-udp=443 --dpi-desync=fake
    #   --dpi-desync-repeats=6 <HOSTLIST>`). QUIC Initial packets are
    #   recognized and their hostname extracted, so --hostlist-domains
    #   applies to QUIC too. Success rate is documented as ~50-75%; that is
    #   why it ships as a separate opt-in strategy, not a change to the four
    #   presets users already run.
    "youtube_discord": "--wf-tcp=80,443 --filter-tcp=80,443 --hostlist-domains={hosts} --dpi-desync=fake,split2 --dpi-desync-split-pos=1 --dpi-desync-repeats=6 --dpi-desync-fooling=badseq",
    "standard": "--wf-tcp=80,443 --filter-tcp=80,443 --hostlist-domains={hosts} --dpi-desync=fake,split2 --dpi-desync-split-pos=1 --dpi-desync-repeats=4 --dpi-desync-fooling=badseq",
    "aggressive": "--wf-tcp=80,443 --filter-tcp=80,443 --hostlist-domains={hosts} --dpi-desync=disorder2 --dpi-desync-split-pos=1 --dpi-desync-fooling=badseq",
    "multisplit": "--wf-tcp=80,443 --filter-tcp=80,443 --hostlist-domains={hosts} --dpi-desync=fake,multisplit --dpi-desync-split-pos=1,5 --dpi-desync-repeats=6 --dpi-desync-fooling=badseq",
    # BUG-012: TCP (80/443) + QUIC/UDP (443). Profile 1 handles TCP exactly
    # like `standard`; profile 2 (after --new) handles UDP 443 QUIC Initials.
    # Name is honest: no Discord, no IPv6 claims — see the mode label in
    # ui/web_new_v2/index.html.
    "tcp_udp": "--wf-tcp=80,443 --wf-udp=443 --filter-tcp=80,443 --hostlist-domains={hosts} --dpi-desync=fake,split2 --dpi-desync-split-pos=1 --dpi-desync-repeats=4 --dpi-desync-fooling=badseq --new --filter-udp=443 --hostlist-domains={hosts} --dpi-desync=fake --dpi-desync-repeats=6",
}

# Security: winws arguments reach an ELEVATED process, so every token is validated
# against this grammar before it is ever passed to ShellExecuteW. Anything outside
# it (quotes, semicolons, ampersands, backticks, pipes, redirects) is rejected.
_ALLOWED_ARG_RE = re.compile(r'^--[A-Za-z0-9][A-Za-z0-9\-]*(=[A-Za-z0-9,.:_/\-\\ ]*)?$')

# Option allowlist. Every entry is verified against the PINNED winws v72.13
# (docs/readme.en.md + docs/windows.en.md at tag v72.13, BUG-012):
#   --wf-l3 / --filter-l3  — the real L3 filter options ('ipv4|ipv6', comma
#     separated). NOTE: v72.13 has NO --wf-ipv6; both L3 protocols are already
#     filtered by default, these options only narrow it.
#   --wf-udp / --filter-udp — UDP port filters, required for QUIC handling.
# Deliberately NOT accepted: --hostlist/--ipset (file-backed, unvalidatable
# content), --dpi-desync-fake-* (binary payloads), anything not needed here.
_ALLOWED_ZAPRET_OPTIONS = frozenset({
    '--wf-tcp', '--wf-udp', '--wf-l3', '--filter-tcp', '--filter-udp', '--filter-l3',
    '--hostlist-domains', '--dpi-desync', '--dpi-desync-split-pos',
    '--dpi-desync-repeats', '--dpi-desync-fooling', '--dpi-desync-ttl',
    '--dpi-desync-autottl', '--dpi-desync-cutoff', '--new',
})


def _split_winws_args(raw_args: str) -> List[str]:
    """Split winws arguments on whitespace, honoring simple quote grouping.

    BUG-030: the previous shlex.split(raw_args, posix=True) treated
    backslashes as escape characters and silently ERASED them before the
    allowlist ever saw the token — '--hostlist-domains=a\\b' arrived as
    'ab'. Windows command lines do not use backslash escaping (the C runtime
    escapes only a quote), so arguments are split by hand instead:

    - tokens separate on ASCII whitespace outside quotes;
    - a quoted section ("..." or '...') keeps its content VERBATIM including
      every backslash; the quote characters themselves are stripped;
    - quotes may open and close mid-token;
    - an unclosed quote raises ValueError — silently gluing the rest of the
      line into one token could merge two arguments into one.

    This splitter is a convenience only: every token it returns is still
    validated against _ALLOWED_ARG_RE and _ALLOWED_ZAPRET_OPTIONS by
    sanitize_zapret_args, so no quoting trick can smuggle a metacharacter
    through.
    """
    tokens: List[str] = []
    buf: List[str] = []
    quote: Optional[str] = None
    for ch in raw_args:
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in ('"', "'"):
            quote = ch
        elif ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if quote is not None:
        raise ValueError("незакрытая кавычка в аргументах")
    if buf:
        tokens.append("".join(buf))
    return tokens


def sanitize_zapret_args(raw_args: str) -> List[str]:
    """Split and validate winws arguments. Raises ValueError on anything unsafe.

    Returns the validated token list. Callers must pass this list to Popen or
    join it with subprocess.list2cmdline — never interpolate raw_args into a shell
    or PowerShell command string.

    BUG-030: tokens are produced by _split_winws_args (backslash-preserving)
    instead of shlex.split(posix=True), which silently deleted backslashes.
    The security boundary is unchanged: EVERY token must pass the grammar
    regex and the option allowlist below.
    """
    if not raw_args:
        return []
    try:
        tokens = _split_winws_args(raw_args)
    except ValueError as exc:
        raise ValueError(f"Не удалось разобрать аргументы: {exc}") from exc
    if not tokens:
        # Non-empty input that collapses into nothing. Handing winws an empty
        # argument list would desync every TCP 80/443 connection on the
        # machine with default settings — refuse instead.
        raise ValueError("Не удалось разобрать аргументы: не осталось ни одного аргумента")
    for tok in tokens:
        if not _ALLOWED_ARG_RE.match(tok):
            raise ValueError(f"Недопустимый аргумент Zapret: {tok!r}")
        option = tok.split('=', 1)[0]
        if option not in _ALLOWED_ZAPRET_OPTIONS:
            raise ValueError(f"Неподдерживаемый аргумент Zapret: {option}")
    return tokens

# Only these executable names may ever be launched, elevated or not.
_ALLOWED_BINARY_NAMES = frozenset({"winws.exe", "zapret.exe", "winws"})

# ─── lifecycle state machine (audit A1: BUG-002/003/024) ───
_STATE_STOPPED = "stopped"
_STATE_STARTING = "starting"
_STATE_RUNNING = "running"
_STATE_STOPPING = "stopping"

_START_CANCELLED_MSG = "Запуск Zapret отменён: поступила более новая команда"

# Machine-wide guard (BUG-043): fast user switching gives every Windows
# account its own NeDotify instance and its own ~/.nedotify state, so the
# per-user single-instance mutex in main.py cannot stop two accounts from
# each launching a machine-wide WinDivert filter. This named mutex serializes
# the start/stop transitions across the whole machine. Held only around the
# launch decision and the kill batch, never across downloads or UAC.
_GLOBAL_ZAPRET_GUARD_MUTEX = r"Global\NeDotify_Zapret_Guard"
_GLOBAL_ZAPRET_GUARD_TIMEOUT_MS = 10000


def _global_zapret_guard_acquire(timeout_ms: int = _GLOBAL_ZAPRET_GUARD_TIMEOUT_MS):
    """Acquire the machine-wide Zapret guard mutex.

    Returns the mutex handle, or None when the guard is unavailable or another
    holder did not release it within *timeout_ms* (best-effort: single-user
    safety does not depend on it — the in-process state lock and the ownership
    checks do). WAIT_ABANDONED is accepted: the previous holder died mid-
    transition and the pre-launch scan is what actually catches its orphan.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.CreateMutexW(None, False, _GLOBAL_ZAPRET_GUARD_MUTEX)
        if not handle:
            logger.debug("Zapret guard mutex creation failed", exc_info=True)
            return None
        wait = kernel32.WaitForSingleObject(handle, max(0, int(timeout_ms)))
        if wait in (0, 0x00000080):  # WAIT_OBJECT_0, WAIT_ABANDONED
            return handle
        logger.warning("Another NeDotify instance holds the Zapret guard; giving up after %.1fs",
                       timeout_ms / 1000.0)
        kernel32.CloseHandle(handle)
        return None
    except Exception:
        logger.debug("Zapret guard acquire failed", exc_info=True)
        return None


def _global_zapret_guard_release(handle) -> None:
    if not handle:
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
    except Exception:
        logger.debug("Zapret guard release failed", exc_info=True)


# ─── Job Object (BUG-023): winws must never outlive NeDotify ───
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


def _win32_create_kill_on_close_job():
    """Create a Job Object that kills every assigned process when its last
    handle closes — i.e. when NeDotify dies, cleanly or by crashing.

    Returns the job handle, or None when jobs are unavailable (non-Windows,
    ctypes failure). The handle MUST stay open for the child's lifetime:
    closing it is what triggers the kill.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
                job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        logger.debug("Job Object creation failed", exc_info=True)
        return None


def _win32_assign_process_to_job(job, process_handle) -> bool:
    """Assign an already-created process handle to the kill-on-close job."""
    if not job or not process_handle or sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        return bool(kernel32.AssignProcessToJobObject(int(job), int(process_handle)))
    except Exception:
        logger.debug("AssignProcessToJobObject failed", exc_info=True)
        return False


def _win32_close_handle(handle) -> None:
    if not handle or sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(int(handle))
    except Exception:
        logger.debug("Job handle close failed", exc_info=True)

# A real binary must not be confused with a 0-byte file left behind by a broken
# download: Windows answers the latter with the system dialog "Невозможно
# запустить это приложение на вашем ПК. Чтобы найти версию для вашего
# компьютера, обратитесь к издателю приложения". Both checks are cheap reads of
# the first 64 bytes, so they run on every launch, elevated or not.
_IMAGE_DOS_MAGIC = b"MZ"
_IMAGE_NT_SIGNATURE = b"PE\0\0"
_PE_MACHINE_AMD64 = 0x8664
# A PE whose only content is a header cannot run, and every byte of it is
# correct — the defect is size, not signature. 4 KiB sits far below every
# binary in the zapret bundle (the smallest, killall.exe, is 23 KB) and far
# above the 134-byte header stub that produced the Windows dialog above. Do not
# raise this toward the real minimum: 32 KiB rejected a genuine killall.exe.
_PE_MIN_SIZE = 4 * 1024


def _read_header(path: str, size: int = 0x400) -> bytes:
    """Best-effort read of the first *size* bytes; b'' when unreadable.

    0x400 by design: `e_lfanew` sits at 0x3C and points at the NT header, and
    real zapret binaries place it at 0x80 — beyond a 64-byte read. A short read
    makes the signature check fail for every genuine image, so the validation
    would refuse to launch a perfectly healthy winws.exe.
    """
    try:
        with open(path, "rb") as f:
            return f.read(size)
    except OSError:
        return b""


def is_valid_windows_binary(path: str) -> bool:
    """True when *path* looks like a runnable Windows executable or module.

    Three gates, each catching a distinct way a broken install reaches the
    launcher:

    1. Size — a header-only PE has every magic byte in the right place and
       still cannot run; the floor is 4 KiB, far below the smallest real binary
       in the bundle (killall.exe at 23 KB). Raising it toward that minimum is
       how a genuine binary gets rejected.
    2. MZ header + 'PE\\0\\0' at e_lfanew — proves the file is a PE image at all.
    3. Machine type — 0x8664 (x64) or a real nonzero stamp. zapret ships x64;
       an unmapped stamp means the header was fabricated rather than linked.

    The signature tests keep `validate_zapret_binary()` honest about the
    failure mode that produces a system dialog instead of an error code. The
    machine type is only checked when it can be read (some strip tools leave
    the optional header short) — a 32-bit image is still a genuine zapret
    binary, so it is not a launch-blocking defect here.
    """
    if not path or not os.path.isfile(path):
        return False
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= 0:
        return False
    # Not a signature check on purpose: an empty PE (header only, no code) has
    # every magic byte in the right place and still cannot run. 32 KiB is far
    # below any zapret binary (smallest is killall.exe at 23 KB) and far above
    # anything a truncated download or a test fixture can produce.
    if size < _PE_MIN_SIZE:
        return False
    head = _read_header(path)
    if len(head) < 0x40 or head[:2] != _IMAGE_DOS_MAGIC:
        return False
    e_lfanew = int.from_bytes(head[0x3C:0x40], "little")
    # The offset must be past the DOS header and fit in what was read. Real
    # zapret binaries use 0x80, but linkers place the NT header as far as
    # 0x400 out, so the bound matches the read size rather than 0x200.
    if not 0x40 <= e_lfanew <= 0x3F0 or e_lfanew + 6 > len(head):
        return False
    if head[e_lfanew:e_lfanew + 4] != _IMAGE_NT_SIGNATURE:
        return False
    machine = int.from_bytes(head[e_lfanew + 4:e_lfanew + 6], "little")
    # 0x0000 shows up in images built without a machine stamp; accept anything
    # that carries the NT signature rather than rejecting a working binary.
    return machine in (0x014c, _PE_MACHINE_AMD64, 0xAA64)


def binary_integrity_error(path: str) -> str:
    """Why *path* cannot be launched, or '' when it looks like a real binary.

    Returns a user-facing Russian message so the caller can hand it straight to
    the UI — the user must never be left with a Windows dialog as the only
    explanation of what went wrong.
    """
    if not path or not os.path.isfile(path):
        return "Файл winws.exe не найден."
    try:
        size = os.path.getsize(path)
    except OSError:
        return "Не удалось прочитать файл winws.exe."
    if size <= 0:
        return (
            f"winws.exe повреждён (0 байт). Удалите папку "
            f"{path.rsplit(os.sep, 1)[0] or path} и повторите включение Zapret."
        )
    if not is_valid_windows_binary(path):
        return (
            f"winws.exe повреждён (не является исполняемым файлом Windows). "
            f"Удалите папку {path.rsplit(os.sep, 1)[0] or path} и повторите включение Zapret."
        )
    return ""


def validate_zapret_binary(path: str, app_dir: Optional[str] = None,
                          extra_roots: Optional[Sequence[str]] = None) -> bool:
    """True only for an existing local winws image with an approved name.

    Rejects UNC/network paths and paths without a drive letter. When roots are
    given (``app_dir`` plus ``extra_roots``), the file must live inside one of
    them - that is what keeps an arbitrary path out of an elevated launch.
    `extra_roots` exists because the shipped layout has two legitimate roots:
    ~/.nedotify/zapret (downloaded binaries) and the application directory
    itself (repo checkout in dev, sys._MEIPASS in the frozen build), where
    find_binary() also looks for bin/winws.exe.

    The image check is what keeps this honest about the one defect that ends in
    a Windows dialog instead of an error code: a 0-byte winws.exe left behind by
    a failed extraction satisfies every path rule above, yet ShellExecuteW
    answers it with «Невозможно запустить это приложение на вашем ПК».
    """
    if not path:
        return False
    if path.startswith(("\\\\", "//")) or not re.match(r'^[A-Za-z]:[\\/]', path):
        return False
    try:
        if not os.path.isfile(path):
            return False
    except OSError:
        return False
    roots = [r for r in ([app_dir] if app_dir else []) + list(extra_roots or []) if r]
    if roots:
        norm = os.path.normcase(os.path.realpath(path))
        for root in roots:
            base = os.path.normcase(os.path.realpath(root))
            try:
                if os.path.commonpath([norm, base]) == base:
                    break
            except ValueError:
                continue  # different drive
        else:
            return False
    if os.path.basename(path).lower() not in _ALLOWED_BINARY_NAMES:
        return False
    return is_valid_windows_binary(path)


# installer.iss AppId (Inno Setup, installer.iss:7). Inno Setup registers the
# installed application under this uninstall key with an InstallLocation value
# pointing at the real installation directory ({app}, by default
# {localappdata}\Programs\NeDotify — see installer.iss DefaultDirName).
# BUG-001: the elevation gate used to accept only Program Files, which no
# default install ever reaches, so elevation was structurally dead. The
# installer-verified InstallLocation is now an accepted elevation root.
_INNO_UNINSTALL_SUBKEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{8F56F2A1-90E1-4A0A-AB89-24A326E6D371}_is1"
)


def _query_registry_install_location():
    """InstallLocation recorded by the NeDotify installer, or None (BUG-001).

    Reads the Inno Setup uninstall key (HKCU for the per-user install —
    PrivilegesRequired=lowest, which is where this installer.iss writes;
    HKLM as the future elevated-install layout). Each hive is opened in the
    native 64-bit registry view first and then in the 32-bit view: which view
    holds the entry depends on Inno's install mode, and a wrong-view miss must
    not silently disable the elevation root. REG_EXPAND_SZ values are
    environment-expanded before use. Returns None when the key or value is
    missing/unreadable: fail closed.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    view_64 = getattr(winreg, "KEY_WOW64_64KEY", 0)
    view_32 = getattr(winreg, "KEY_WOW64_32KEY", 0)
    expand_sz = getattr(winreg, "REG_EXPAND_SZ", -1)
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (view_64, view_32):
            try:
                with winreg.OpenKey(hive, _INNO_UNINSTALL_SUBKEY, 0,
                                    winreg.KEY_READ | view) as key:
                    value, value_type = winreg.QueryValueEx(key, "InstallLocation")
            except OSError:
                continue
            if isinstance(value, str) and value.strip():
                if value_type == expand_sz:
                    value = os.path.expandvars(value)
                return value.strip().strip('"').strip()
    return None


def _path_inside_root(path_norm: str, root_norm: str) -> bool:
    """True when the normcased *path_norm* lives inside *root_norm*.

    commonpath-based (not startswith), so ``C:\\NeDotifyEvil`` never passes a
    ``C:\\NeDotify`` check; different drives return False instead of raising.
    """
    if not path_norm or not root_norm:
        return False
    try:
        return os.path.commonpath([root_norm, path_norm]) == root_norm
    except ValueError:
        return False


def _app_runs_from_install_location(root_norm: str) -> bool:
    """True when THIS process runs from EXACTLY the verified install directory.

    Ties the registry-verified root to the actually running application: a
    forged HKCU InstallLocation then cannot vouch for binaries outside the
    real installation (BUG-001 hardening). The root must equal the directory
    of the running executable — a WIDER ancestor (e.g. ``C:\\Users\\<user>``,
    a strict superset of the real install dir) would let a rogue HKCU entry
    bless a winws.exe planted in any sibling of the real install, because the
    running app would legitimately live "inside" such a root. In a frozen
    build sys.executable is {app}\\NeDotify.exe and Inno writes
    InstallLocation={app}, so the exact match holds for every install this
    installer produces; a dev run (python.exe in a venv) fails this check and
    keeps the strict Program Files rule.
    """
    exe = getattr(sys, "executable", "") or ""
    if not exe:
        return False
    try:
        exe_norm = os.path.normcase(os.path.realpath(os.path.abspath(exe)))
    except OSError:
        return False
    return os.path.dirname(exe_norm) == root_norm


def _protected_elevation_path(path):
    """Only verified installation roots can supply elevated code (BUG-001).

    Two accepted roots, both resolved by the OS/registry rather than through
    environment variables or the writable application settings:

    1. Program Files / Program Files (x86) — administrator-owned machine roots.
    2. The application's own installation directory, verified through the Inno
       Setup uninstall key (InstallLocation): the exe must live inside it, the
       binary itself must pass validate_zapret_binary (approved name + PE
       image), AND the running NeDotify must itself live inside it.

    The downloaded bundle in ~/.nedotify/zapret stays FORBIDDEN: it sits in
    user-writable storage and is replaced at runtime (TOCTOU window).

    Residual risk, documented (BUG-001 review): TOCTOU between these checks
    and the ShellExecuteW dispatch is narrowed but not eliminated — the file
    is re-resolved by realpath at check time, yet a same-user process can
    swap it between the checks and the launch. This is inherent to a per-user
    install ({localappdata}\\Programs\\NeDotify is itself user-writable): the
    gate's protection is bounded by "approved name + valid PE image + the
    running exe lives in the registry-verified install dir + the user must
    accept the UAC prompt", not by filesystem immutability. A fully hardened
    design would copy the bundle into an administrator-owned root via an
    elevated helper — out of scope here (see installer.iss policy note).
    """
    if sys.platform != 'win32':
        return False
    import ctypes
    resolved = os.path.normcase(os.path.realpath(path))
    for csidl in (0x0026, 0x002A):  # Program Files, Program Files (x86)
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
            root = os.path.normcase(os.path.realpath(buf.value))
            if _path_inside_root(resolved, root):
                logger.debug("Elevation root accepted: Program Files (%s)", root)
                return True
    install_root = _query_registry_install_location()
    if not install_root:
        logger.info(
            "Elevation denied for %s: not in Program Files and no installer "
            "InstallLocation found (key %s)", resolved, _INNO_UNINSTALL_SUBKEY)
        return False
    try:
        root_norm = os.path.normcase(os.path.realpath(install_root))
    except OSError:
        root_norm = os.path.normcase(os.path.abspath(install_root))
    if not _path_inside_root(resolved, root_norm):
        logger.info(
            "Elevation denied for %s: outside the verified install location %s",
            resolved, root_norm)
        return False
    if not _app_runs_from_install_location(root_norm):
        logger.warning(
            "Elevation denied for %s: registry InstallLocation %s does not host "
            "the running application (%s) — possible forged uninstall entry",
            resolved, root_norm, os.path.normcase(os.path.abspath(sys.executable or "")))
        return False
    if not validate_zapret_binary(path, None, extra_roots=[install_root]):
        logger.warning(
            "Elevation denied for %s: binary failed validation inside the "
            "verified install location %s", resolved, root_norm)
        return False
    logger.info("Elevation root accepted: verified install location %s", root_norm)
    return True


# Z-4: internet probe hosts — TCP-connect to port 443, first success = online.
INTERNET_CHECK_HOSTS = ["ya.ru", "gosuslugi.ru", "77.88.8.8", "8.8.8.8"]

# Upper bound of one _read_log_tail diagnosis read (BUG-019 perf guard): the
# log rotates at 1 MiB per launch, but a long-lived elevated cmd.exe can
# append past that; crash analysis only ever needs the tail.
_LOG_READ_WINDOW_BYTES = 256 * 1024


def _decode_console_bytes(raw: bytes) -> str:
    """Decode subprocess/log output across the Windows console-codepage zoo.

    BUG-018: wmic writes UTF-16LE (with a BOM) whenever its stdout is
    redirected, while tasklist and PowerShell emit the OEM/ANSI codepage
    (CP866 on Russian systems). The old fixed utf-8 decode turned every
    ASCII character of wmic output into 'char + NUL', so the 'ProcessId'
    column was never found and the wmic branch of _scan_pids_with always
    came back empty. Detection order: BOM, then the NUL-byte signature of
    UTF-16LE, then strict utf-8, then the OEM (cp866) and ANSI (mbcs)
    codepages, then a lossy utf-8 fallback.
    """
    if not raw:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if b"\x00" in raw[:1024]:
        # UTF-16LE (with or without BOM): ASCII survives as-is.
        try:
            return raw.decode("utf-16-le", errors="replace")
        except Exception:
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for encoding in ("cp866", "mbcs"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _check_output_text(cmd, timeout: float, shell: bool = False) -> str:
    """subprocess.check_output that never dies on console codepages.

    Windows console tools (tasklist / wmic / powershell) emit OEM codepage
    output (CP866 on Russian systems: session name «Консоль», Cyrillic exe
    paths) — or UTF-16LE in wmic's redirected case. With text=True the strict
    UTF-8 reader thread crashes and check_output silently returns nothing,
    disabling every PID scan below. All match targets in this module are ASCII
    (winws.exe, PIDs, validated --args), so a lenient decode is sufficient and
    locale-proof (BUG-018).
    """
    try:
        out = subprocess.check_output(cmd, shell=shell, stderr=subprocess.DEVNULL, timeout=timeout)
        return _decode_console_bytes(out)
    except Exception as e:
        logger.debug("subprocess scan failed (%r): %s", cmd, e)
        return ""


# Crash-analysis keys (BUG-027): anchored patterns, not bare substrings.
# These match the real message shapes: FormatMessage text for WinDivertOpen
# error 5 ("Access is denied." / «Отказано в доступе.»), Python/runtime
# "Permission denied", "WinError 5", UAC "requires elevation", and the
# Russian cmd.exe/console OEM strings. Russian keys work again after the
# BUG-019 decoder fix (CP866 log content is decoded, not mojibake'd).
# Deliberately NOT matched: a bare "access denied" (a path like
# C:\Access Denied Files\... would misdiagnose as UAC — FormatMessage
# always writes "Access is denied") and a bare «администратор» (the built-in
# Russian account IS named «Администратор», so user-profile paths
# C:\Users\Администратор\... would misfire; only "права администратора" /
# "от имени администратора" shapes are matched).
_ELEVATION_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"access\s+is\s+denied",
    r"permission\s+denied",
    r"\bwinerror\s*:?\s*5\b",
    r"\berror\s*:?\s*5\b",
    r"\berr\s*=\s*5\b",
    r"\berr\s+5\b",
    r"\belevat(e|ed|ion|ing)\b",
    r"requires?\s+(elevation|administrator|admin)",
    r"run\s+as\s+administrator",
    r"administrator\s+(privileges|rights|permission)",
    r"\bнедостаточно прав\b",
    r"\bтребуются права\b",
    r"\bотказано в доступе\b",
    r"\bправ\w*\s+администратор",
    r"\bот\s+имени\s+администратор",
))

# "Driver busy" markers for the WinDivert branch of _analyze_crash.
_WINBUSY_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bbusy\b",
    r"\bin\s+use\b",
    r"\bbound\b",
    r"\balready\b",
    r"\bзанят\w*\b",
))


def check_internet(timeout: float = 1.5) -> bool:
    """Fast check for active internet connection without blocking UI."""
    for host in INTERNET_CHECK_HOSTS:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, 443))
            return True
        except Exception:
            continue
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    return False


# BUG-037: the status probe targets a host the bypass actually covers, unlike
# check_internet (whose hosts — ya.ru, gosuslugi.ru, numeric DNS IPs — are
# deliberately OUTSIDE the hostlist and say nothing about desync).
_STATUS_PROBE_HOST = "youtube.com"
_STATUS_PROBE_PORT = 443


def _probe_covered_host(timeout: float = 1.5) -> Optional[bool]:
    """One lightweight TCP connect to a host inside ZAPRET_SCOPED_HOSTS.

    Runs on the background status thread only, single attempt, TCP timeout
    <= 1.5 s (DNS resolution inside connect() is NOT covered by the socket
    timeout, but this is a daemon thread and get_status() always serves the
    previous cache — the UI never blocks on it).

    Result semantics (BUG-037): True/False only refine the status message —
    'домены приложения доступны/недоступны'. A successful TCP handshake does
    NOT prove the DPI desync worked; a failure does not prove it failed (the
    host itself can be down). Returns None when the probe could not even be
    attempted (unexpected error), which the caller reports neutrally.
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((_STATUS_PROBE_HOST, _STATUS_PROBE_PORT))
        return True
    except (OSError, socket.timeout):
        return False
    except Exception:
        logger.debug("covered-host status probe failed unexpectedly", exc_info=True)
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


class ZapretService:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager
        self._selection_cancel = threading.Event()
        self._selection_active = False
        self._selection_owner = None
        self._binary_update_owner = None
        self._start_owner = None
        self.process = None
        self._log_handle = None
        self._lock = threading.RLock()
        self._elevation_hwnd_provider = None
        # Z-8: serializes download/update work (network fetch + binary extraction)
        # so a background auto-update can never race start()'s auto-download or a
        # second concurrent update writing the same winws.exe files.
        self._update_lock = threading.RLock()
        self._last_args = ""

        # ── lifecycle state machine (audit A1) ──
        # `_state` follows STOPPED -> STARTING -> RUNNING -> STOPPING -> STOPPED;
        # `_generation` is bumped by every start()/stop() so a start whose
        # generation has been superseded can never launch (BUG-002/003).
        self._state = _STATE_STOPPED
        self._generation = 0
        # Instance marker written into the pidfile record and required by the
        # restricted ownership fallback (BUG-047).
        self._known_uid = ""
        self._volatile_pid_record = None
        # Handle of the kill-on-close Job Object binding our non-elevated
        # child to this process (BUG-023). Must stay open while the child
        # lives; closing it kills the child.
        self._job_handle = None
        # Set when a state-file write failed (BUG-015): stop() then reports a
        # degraded result instead of a plain "stopped".
        self._state_write_failed = False
        # Set when the data directory could not be created (BUG-017): Zapret
        # degrades instead of crashing the whole application.
        self._storage_unavailable = False
        # Hook for late-crash and still-running reports (BUG-025/009). The
        # service never imports the api layer; AppApi installs itself here.
        self._event_callback = None
        # How long _confirm_launch polls the child before trusting it (BUG-025).
        self._launch_confirm_window = 2.0
        # How long _launch_elevated scans for the elevated child's PID (BUG-040).
        self._elevation_scan_window = 5.0
        # A dispatched UAC launch without an attributable PID is UNKNOWN,
        # never evidence of a running bypass. Retain this guard separately
        # from liveness so a retry cannot launch a second driver.
        self._elevation_pid_unknown = False
        self._elevation_inflight = None
        self._elevation_dispatched = False

        self.app_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "zapret")
        self.logs_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "logs")
        # Second legitimate root for the binary: the application directory
        # (repo checkout under `python main.py`; the installed application
        # directory in a frozen build). find_binary() also looks for
        # bin/winws.exe there, so the elevated-launch check has to accept it.
        # A frozen build must use the directory holding NeDotify.exe, NOT
        # sys._MEIPASS: in the onefile layout _MEIPASS is a throwaway
        # extraction dir the installer can never place files into, so an
        # installer-shipped Zapret bundle ({app}\zapret) would be
        # undiscoverable — which kept the installer half of BUG-001 dead.
        if getattr(sys, "frozen", False):
            self.base_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            self.base_dir = getattr(
                sys, "_MEIPASS",
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._rejected_binary_path: Optional[str] = None
        # BUG-017: a missing/unwritable data directory used to raise out of
        # __init__ and take the whole application down. Degrade instead: the
        # flag gates start() with a clear message; the app itself survives.
        try:
            os.makedirs(self.app_dir, exist_ok=True)
            os.makedirs(self.logs_dir, exist_ok=True)
        except OSError as exc:
            self._storage_unavailable = True
            logger.error(
                "Zapret data directory %s is unavailable (%s); Zapret is disabled for this session",
                self.app_dir, exc)

        # Z-2: pidfile identity + cmdline signature snapshot
        self.pid_file = os.path.join(self.app_dir, "run.pid")
        self.cmd_file = os.path.join(self.app_dir, "run.cmd")
        # Z-3: stderr log of the winws process
        self.log_file = os.path.join(self.logs_dir, "zapret.log")

        # Z-5: status cache (built in background, never blocks get_status)
        self._status_cache: Dict[str, Any] = None
        self._status_cache_time = 0.0
        self._status_epoch = 0
        self._lifecycle_watch_key = None
        self._status_ttl = 2.5
        self._status_thread = None
        # BUG-042: the TTL above compares against time.monotonic(), not
        # time.time(). Rationale, fixed decisions:
        # - A backward wall-clock jump (NTP correction, manual change) used to
        #   pin a stale cache for the length of the jump; a monotonic stamp
        #   cannot go backwards within a boot.
        # - Sleep/hibernation: Windows' QPC (time.monotonic) does not advance
        #   while suspended, so the first build after a resume may serve a
        #   cache up to one extra TTL (2.5 s) old. That self-heals within the
        #   next refresh, so NO POWERBROADCAST suspend/resume handlers are
        #   installed — they would add a WndProc dependency for no correctness
        #   gain. Deliberate decision, do not "fix" without a real scenario.
        # - The 24 h autoupdate gate stays on wall-clock on purpose: its
        #   timestamps are PERSISTED in version.json, and a monotonic clock is
        #   only comparable within one boot. A clock jump backward there at
        #   worst extends the interval to the next update check; forward jumps
        #   merely trigger it earlier. Neither breaks anything.
        # BUG-036: last known running-internet state for the one-shot
        # 'zapret_network_issue' transition event (None = not tracked).
        self._last_network_ok: Optional[bool] = None

    # ─── pidfile & process identity helpers (Z-2) ───
    #
    # pidfile record (audit BUG-046): a JSON object
    #   {"pid": <int>, "uid": <hex>, "pids": [<int>, ...], "created": {"<pid>": <filetime>}}
    # `pids` appears after a partially failed stop so no live PID is lost;
    # `uid` is our instance marker and `created` the process creation time
    # recorded at launch (a reused PID has a different creation time, so the
    # restricted ownership fallback cannot adopt a foreign process).
    # Legacy files holding a single plain integer keep working.

    def _atomic_write_text(self, path: str, text: str) -> bool:
        """Write *text* to *path* atomically (tmp + os.replace, BUG-014).

        A crash mid-write can no longer truncate run.pid/run.cmd/version.json.
        Returns False and logs a WARNING on failure (BUG-015) — silently
        pretending the state was saved used to produce a fake "stopped".
        """
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, path)
            self._state_write_failed = False
            return True
        except OSError as exc:
            self._state_write_failed = True
            logger.warning("Failed to write Zapret state file %s: %s", path, exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                logger.debug("Zapret state tmp cleanup failed: %s", tmp, exc_info=True)
            return False

    @staticmethod
    def _record_pids(record: Optional[Dict[str, Any]]) -> List[int]:
        """All PIDs stored in a pidfile record (primary first, deduplicated)."""
        if not isinstance(record, dict):
            return []
        out: List[int] = []
        values = record.get("pids")
        if not isinstance(values, (list, tuple)):
            values = []
        for value in [record.get('pid'), *values]:
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                continue
            try:
                pid = int(value)
            except (TypeError, ValueError):
                continue
            if 0 < pid <= 0xFFFFFFFF and pid not in out:
                out.append(pid)
        return out

    def _get_process_creation_time(self, pid: int) -> Optional[int]:
        """Creation time of *pid* as a 64-bit FILETIME int (None if unknown).

        Recorded together with the pidfile entry and re-checked by the
        ownership fallback, closing the PID-reuse hole (BUG-047): a recycled
        PID always carries a different creation time.
        """
        if not pid or pid <= 0 or sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return None
            try:
                creation = wintypes.FILETIME()
                exited = wintypes.FILETIME()
                kernel_t = wintypes.FILETIME()
                user_t = wintypes.FILETIME()
                if kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exited),
                                            ctypes.byref(kernel_t), ctypes.byref(user_t)):
                    return (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
                return None
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            logger.debug("_get_process_creation_time failed for PID %s", pid, exc_info=True)
            return None

    def _write_pidfile(self, pid: int, pids: Optional[Sequence[int]] = None, uid: str = ""):
        """Persist the pidfile record atomically (BUG-014/046)."""
        all_pids = self._record_pids({'pid': pid, 'pids': pids})
        if not all_pids:
            return
        record: Dict[str, Any] = {"pid": all_pids[0], "uid": uid or ""}
        if len(all_pids) > 1:
            record["pids"] = all_pids
        created = {}
        for known_pid in all_pids:
            stamp = self._get_process_creation_time(known_pid)
            if stamp:
                created[str(known_pid)] = stamp
        if created:
            record["created"] = created
        persisted = self._atomic_write_text(self.pid_file, json.dumps(record))
        with self._lock:
            # Retain identity while this instance is alive even when disk/AV
            # prevents persistence. Otherwise an elevated child vanishes from
            # is_running()/stop() immediately after successful discovery.
            self._volatile_pid_record = None if persisted else record

    def _read_pidfile_record(self) -> Optional[Dict[str, Any]]:
        """Read the pidfile as a record dict; legacy single-int files get
        {"pid": <int>, "uid": ""} so old layouts keep working (BUG-046)."""
        with self._lock:
            volatile = self._volatile_pid_record
            if volatile:
                return dict(volatile)
        try:
            if not os.path.exists(self.pid_file):
                return None
            with open(self.pid_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return None
            try:
                data = json.loads(content)
            except ValueError:
                data = None
            if isinstance(data, dict):
                return data
            if isinstance(data, int) and data > 0:
                return {"pid": data, "uid": ""}
            try:
                return {"pid": int(content), "uid": ""}
            except (TypeError, ValueError):
                return None
        except Exception:
            return None

    def _read_pidfile_pids(self) -> List[int]:
        """Every PID tracked by the pidfile (primary first)."""
        return self._record_pids(self._read_pidfile_record())

    def _read_pidfile(self) -> int | None:
        pids = self._read_pidfile_pids()
        return pids[0] if pids else None

    def _clear_pidfile(self):
        with self._lock:
            self._volatile_pid_record = None
        try:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
        except Exception:
            logger.debug("_clear_pidfile: suppressed exception", exc_info=True)

    def _write_cmd_file(self, raw_args: str) -> bool:
        return self._atomic_write_text(self.cmd_file, raw_args or "")

    def _read_cmd_file(self) -> str:
        try:
            if not os.path.exists(self.cmd_file):
                return ""
            with open(self.cmd_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _clear_cmd_file(self):
        try:
            if os.path.exists(self.cmd_file):
                os.remove(self.cmd_file)
        except Exception:
            logger.debug("_clear_cmd_file: suppressed exception", exc_info=True)

    def _pid_alive(self, pid: int | None) -> bool:
        """Liveness check of a PID without spawning subprocesses (Z-5).

        BUG-044 hygiene: kernel32 is loaded with use_last_error=True, every
        call carries explicit argtypes/restype (the default c_int return
        truncates HANDLE on 64-bit — sign-extension could classify a live
        process as dead) and the error code is read through
        ctypes.get_last_error(), which is reliable under use_last_error.
        """
        if not pid or pid <= 0:
            return False
        if sys.platform != "win32":
            # POSIX only. NEVER use os.kill as a liveness probe on Windows:
            # on Python < 3.14 os.kill(pid, 0) on Windows calls
            # TerminateProcess(pid, 0) — it KILLS the target instead of
            # probing it. This branch is unreachable on win32 by the guard
            # above; keep it that way if the Python version requirement is
            # ever relaxed (requirements.txt currently demands 3.14+).
            try:
                os.kill(pid, 0)
                return True
            except PermissionError:
                return True
            except (OSError, ProcessLookupError):
                return False
            except Exception:
                return False
        try:
            import ctypes
            from ctypes import wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            ERROR_ACCESS_DENIED = 5
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                # A protected process (e.g. elevated winws of another session)
                # answers OpenProcess with ERROR_ACCESS_DENIED — it exists.
                if ctypes.get_last_error() == ERROR_ACCESS_DENIED:
                    return True
                return False
            try:
                code = wintypes.DWORD()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return False
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            logger.debug("_pid_alive: suppressed exception", exc_info=True)
            return False

    def _is_winws_process(self, pid: int | None) -> bool:
        """Verify that the process with the given PID is winws.exe, zapret.exe, or winws.
        Prevents operating on reused or foreign PIDs.
        """
        if not pid or pid <= 0:
            return False
        if sys.platform == "win32":
            # Primary check: QueryFullProcessImageNameW via kernel32.
            # BUG-044 hygiene: explicit prototypes + use_last_error — the
            # default c_int restype sign-extends HANDLEs on 64-bit Windows.
            try:
                import ctypes
                from ctypes import wintypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel32.OpenProcess.restype = wintypes.HANDLE
                kernel32.QueryFullProcessImageNameW.argtypes = [
                    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                    ctypes.POINTER(wintypes.DWORD)]
                kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                            exe_name = os.path.basename(buf.value).lower()
                            return exe_name in _ALLOWED_BINARY_NAMES
                    finally:
                        kernel32.CloseHandle(handle)
            except Exception:
                logger.debug("_is_winws_process ctypes check failed for PID %s", pid, exc_info=True)

            # Fallback check: tasklist CSV query parsed with csv.reader
            out = _check_output_text(
                f'tasklist /FI "PID eq {pid}" /FO CSV /NH',
                timeout=2.5, shell=True
            )
            if out:
                for line in out.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    reader = csv.reader([line])
                    for row in reader:
                        if row and len(row) >= 1:
                            img_name = row[0].strip().lower()
                            return img_name in _ALLOWED_BINARY_NAMES
            return False
        else:
            # POSIX check
            try:
                comm_path = f"/proc/{pid}/comm"
                if os.path.exists(comm_path):
                    with open(comm_path, "r", encoding="utf-8", errors="ignore") as f:
                        return f.read().strip().lower() in _ALLOWED_BINARY_NAMES
                cmd_path = f"/proc/{pid}/cmdline"
                if os.path.exists(cmd_path):
                    with open(cmd_path, "rb") as f:
                        tok = f.read().decode("utf-8", errors="ignore").split("\x00")[0]
                        return os.path.basename(tok).lower() in _ALLOWED_BINARY_NAMES
            except Exception:
                pass
            return self._pid_alive(pid)

    def _get_process_exe_path(self, pid: int | None) -> Optional[str]:
        """Get the full filesystem path of the executable for a PID."""
        if not pid or pid <= 0:
            return None
        if sys.platform == "win32":
            # BUG-044 hygiene: explicit prototypes + use_last_error=True.
            try:
                import ctypes
                from ctypes import wintypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel32.OpenProcess.restype = wintypes.HANDLE
                kernel32.QueryFullProcessImageNameW.argtypes = [
                    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                    ctypes.POINTER(wintypes.DWORD)]
                kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                            return buf.value
                    finally:
                        kernel32.CloseHandle(handle)
            except Exception:
                logger.debug("_get_process_exe_path failed for PID %s", pid, exc_info=True)
        else:
            try:
                exe_link = f"/proc/{pid}/exe"
                if os.path.exists(exe_link):
                    return os.path.realpath(exe_link)
            except Exception:
                pass
        return None

    @staticmethod
    def _path_under_root(exe_norm: str, root: str) -> bool:
        """True when *exe_norm* (normcased absolute path) lives inside *root*.

        The comparison is prefix + os.sep (BUG-005): a bare startswith()
        accepted sibling directories — ``C:\\NeDotifyEvil\\winws.exe`` passed
        the ``C:\\NeDotify`` check.
        """
        if not root or not exe_norm:
            return False
        root_norm = os.path.normcase(os.path.abspath(root))
        prefix = root_norm if root_norm.endswith(os.sep) else root_norm + os.sep
        return exe_norm.startswith(prefix)

    def _is_our_winws_process(self, pid: int | None, signature: str = "",
                              signature_verified: bool = False) -> bool:
        """Verify that the process with the given PID is winws.exe AND belongs to this application.
        Prevents adopting or terminating foreign winws.exe processes (AUDIT #04).

        Command-line matches only discover candidates. The legacy signature
        parameters are retained for callers, but never authorize ownership.
        """
        if not pid or pid <= 0 or not self._pid_alive(pid):
            return False
        if not self._is_winws_process(pid):
            return False

        # 1. Verify executable path matches our app directory or binary path.
        #    Every root comparison requires the os.sep terminator (BUG-005).
        exe_path = self._get_process_exe_path(pid)
        if exe_path:
            norm_exe = os.path.normcase(os.path.abspath(exe_path))
            our_bin = self.find_binary()
            if our_bin and norm_exe == os.path.normcase(os.path.abspath(our_bin)):
                return True
            if self._path_under_root(norm_exe, self.app_dir):
                return True
            # The bundle root covers the frozen build (sys._MEIPASS/bin) and
            # the repo checkout; cwd is kept for the historical dev layout.
            if self._path_under_root(norm_exe, self.base_dir):
                return True
            # Executable path is known and does NOT belong to our app
            return False

        # A common argument string discovers candidates, but cannot prove
        # ownership of an elevated process whose path Windows hides.
        # 2. Restricted last resort (BUG-047): the exe path is unreadable
        #    (typically an elevated process). A bare `saved_pid == pid` could
        #    adopt a foreign elevated winws on PID reuse, so the pidfile must
        #    record THIS pid with OUR instance uid AND the creation time
        #    stored at launch must still match the live process.
        record = self._read_pidfile_record()
        if not record:
            return False
        if pid not in self._record_pids(record):
            return False
        if not self._known_uid or (record.get("uid") or "") != self._known_uid:
            return False
        created = record.get("created")
        if not isinstance(created, dict):
            return False
        expected_created = created.get(str(pid))
        if not expected_created:
            return False
        return self._get_process_creation_time(pid) == expected_created

    def _scan_all_winws_pids(self) -> List[int]:
        """Return PIDs of running winws processes verified to belong to this application."""
        if sys.platform != "win32":
            return []
        pids: List[int] = []
        out = _check_output_text('tasklist /FO CSV /NH', timeout=3.0, shell=True)
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            reader = csv.reader([line])
            for row in reader:
                if row and len(row) >= 2:
                    img_name = row[0].strip().lower()
                    if img_name in _ALLOWED_BINARY_NAMES:
                        try:
                            pid = int(row[1].strip())
                            if pid > 0 and self._pid_alive(pid) and self._is_our_winws_process(pid):
                                if pid not in pids:
                                    pids.append(pid)
                        except ValueError:
                            continue

        if not pids:
            ps_cmd = 'Get-Process -Name winws,zapret -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'
            out = _check_output_text(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                timeout=4.0
            )
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if self._pid_alive(pid) and self._is_our_winws_process(pid):
                        if pid not in pids:
                            pids.append(pid)

        return pids

    def _scan_pids_with(self, args_signature: str) -> List[int]:
        """Return PIDs of winws.exe processes whose cmdline contains the signature.
        Uses csv.DictReader to safely parse WMIC CSV output without breaking on commas inside arguments.
        Verifies process image name for every returned PID.
        """
        if not args_signature:
            return []
        pids: List[int] = []
        if sys.platform != "win32":
            return pids

        # Attempt 1: WMIC with CSV format parsed via csv.DictReader
        out = _check_output_text(
            'wmic process where "name=\'winws.exe\'" get ProcessId,CommandLine /FORMAT:CSV',
            timeout=4.0, shell=True
        )
        clean_lines = [line.strip() for line in out.splitlines() if line.strip()]
        if clean_lines:
            reader = csv.DictReader(clean_lines)
            if reader.fieldnames:
                pid_field = None
                cmd_field = None
                for f in reader.fieldnames:
                    if not f:
                        continue
                    norm = f.strip().lower()
                    if norm == "processid":
                        pid_field = f
                    elif norm == "commandline":
                        cmd_field = f

                if pid_field:
                    for row in reader:
                        pid_val = row.get(pid_field)
                        if not pid_val:
                            continue
                        try:
                            p = int(str(pid_val).strip())
                        except (ValueError, TypeError):
                            continue

                        cmdline = str(row.get(cmd_field, "") or "").strip()
                        if cmdline and args_signature in cmdline:
                            if self._pid_alive(p) and self._is_winws_process(p):
                                if p not in pids:
                                    pids.append(p)

        # Attempt 2: PowerShell CIM query fallback
        if not pids:
            ps_cmd = 'Get-CimInstance Win32_Process -Filter "Name=\'winws.exe\'" | ForEach-Object { "$($_.ProcessId)|$($_.CommandLine)" }'
            out = _check_output_text(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                timeout=6.0
            )
            for line in out.splitlines():
                if "|" in line:
                    pid_str, cmdline = line.split("|", 1)
                    try:
                        p = int(pid_str.strip())
                        cmdline = cmdline.strip()
                        if cmdline and args_signature in cmdline:
                            if self._pid_alive(p) and self._is_winws_process(p):
                                if p not in pids:
                                    pids.append(p)
                    except (ValueError, TypeError):
                        continue

        return pids

    def _classify_running_winws(self) -> Tuple[Optional[int], Optional[int]]:
        """Pre-launch scan (BUG-013): every running winws-image process.

        Returns ``(ours, foreign)``. ``ours`` is an adoptable orphan that
        belongs to this application (strict exe-path prefixes or our pidfile
        record); ``foreign`` is any other winws-image process — another
        account's bypass or a manually started instance. Launching a second
        WinDivert driver over a foreign one fails with "driver busy" or stacks
        two filter engines, so start() refuses in that case.

        Both scan backends may be unavailable: an empty result degrades to the
        historical behavior (launch anyway). Runs WITHOUT the state lock — the
        machine-global guard serializes it against other NeDotify instances.
        """
        if sys.platform != "win32":
            return None, None
        candidates: List[int] = []
        out = _check_output_text('tasklist /FO CSV /NH', timeout=3.0, shell=True)
        if out:
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                reader = csv.reader([line])
                for row in reader:
                    if row and len(row) >= 2 and row[0].strip().lower() in _ALLOWED_BINARY_NAMES:
                        try:
                            pid = int(row[1].strip())
                        except ValueError:
                            continue
                        if pid > 0 and pid not in candidates:
                            candidates.append(pid)
        if not candidates and not out:
            # tasklist itself failed (not "no winws") — try PowerShell once.
            ps_cmd = ('Get-Process -Name winws,zapret -ErrorAction SilentlyContinue '
                      '| Select-Object -ExpandProperty Id')
            out = _check_output_text(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                timeout=4.0
            )
            for line in out.splitlines():
                if line.strip().isdigit():
                    pid = int(line.strip())
                    if pid > 0:
                        candidates.append(pid)

        ours: Optional[int] = None
        foreign: Optional[int] = None
        for pid in candidates:
            if not self._pid_alive(pid):
                continue
            if self._is_our_winws_process(pid):
                if ours is None:
                    ours = pid
            else:
                foreign = pid
                break
        return ours, foreign

    def _tasklist_image_name(self, pid: int) -> Optional[str]:
        """Image name of *pid* via tasklist, or None (BUG-039 helper).

        Used when ctypes cannot read the exe path (typically an elevated
        process): tasklist still reports the image name, so the taskkill
        /FI filter can be qualified instead of dropped. Only approved names
        are returned — the value is interpolated into a shell command line.
        """
        if sys.platform != "win32":
            return None
        out = _check_output_text(
            f'tasklist /FI "PID eq {int(pid)}" /FO CSV /NH', timeout=2.5, shell=True)
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            for row in csv.reader([line]):
                if row and row[0].strip().lower() in _ALLOWED_BINARY_NAMES:
                    return row[0].strip()
        return None

    def _kill_pid(self, pid: int, *, allow_elevation: bool = False) -> bool:
        """Kill exactly one verified PID via taskkill (graceful first, /F fallback).

        BUG-039: the image-name filter uses the ACTUAL executable name of the
        verified process. The old hardcoded `winws*` filter never matched a
        running zapret.exe, so an orphaned one stayed alive forever. When the
        exe path is unreadable (typically an elevated process) the name is
        recovered through tasklist; only when BOTH lookups fail is the filter
        dropped — the PID has already been verified as an approved winws-image
        process by _is_winws_process, so taskkill /PID cannot touch a foreign
        process (AUDIT #03). MUST NOT be called without that verification.
        Residual TOCTOU (documented): between the verification and taskkill the
        PID can die and be reused; with the /FI filter a reused PID is only
        killed if it also carries the same image name, and without a filter a
        reused PID of any name could be hit. The window is milliseconds and the
        stronger alternative (TerminateProcess on a handle captured during
        verification) needs PROCESS_TERMINATE rights a non-admin does not have
        against an elevated process — exactly the case with no filter.
        """
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return False
        if pid <= 0:
            return False
        if not self._pid_alive(pid):
            return True
        if not self._is_winws_process(pid):
            logger.warning(
                "Refusing to kill PID %s: process image is not winws.exe (prevented foreign PID termination)",
                pid
            )
            return False

        # The name is restricted to _ALLOWED_BINARY_NAMES, so it is safe to
        # interpolate into the taskkill command line.
        image_name = None
        exe_path = self._get_process_exe_path(pid)
        if exe_path:
            candidate = os.path.basename(exe_path)
            if candidate.lower() in _ALLOWED_BINARY_NAMES:
                image_name = candidate
        if image_name is None:
            image_name = self._tasklist_image_name(pid)
        filter_part = f'/FI "IMAGENAME eq {image_name}" ' if image_name else ''

        try:
            if sys.platform == "win32":
                subprocess.run(
                    f'taskkill {filter_part}/PID {pid}',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0
                )
                deadline = time.time() + 1.5
                while time.time() < deadline:
                    if not self._pid_alive(pid):
                        return True
                    time.sleep(0.15)

                subprocess.run(
                    f'taskkill /F {filter_part}/PID {pid}',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0
                )
                time.sleep(0.2)
                if not self._pid_alive(pid):
                    return True

                if allow_elevation and self._is_our_winws_process(pid):
                    # Explicit toggle-off only; cleanup never prompts for UAC.
                    import ctypes
                    system_dir = ctypes.create_unicode_buffer(32768)
                    if ctypes.windll.kernel32.GetSystemDirectoryW(system_dir, len(system_dir)):
                        taskkill = os.path.join(system_dir.value, "taskkill.exe")
                        result = self._shell_execute_elevated(
                            taskkill, f'/F {filter_part}/PID {pid}', system_dir.value)
                        if result > 32:
                            deadline = time.time() + 3.0
                            while time.time() < deadline:
                                if not self._pid_alive(pid):
                                    return True
                                time.sleep(0.15)
                # Shutdown must never surprise the user with another UAC dialog.
                logger.warning('Cannot stop elevated Zapret PID %s with current rights', pid)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
                deadline = time.time() + 1.5
                while time.time() < deadline:
                    if not self._pid_alive(pid):
                        return True
                    time.sleep(0.15)
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.2)

            return not self._pid_alive(pid)
        except Exception as e:
            logger.debug("taskkill error for PID %s: %s", pid, e)
            return not self._pid_alive(pid)

    # ─── binary discovery ───

    def _binary_directory(self) -> str:
        """Keep downloaded code in the existing installer-verified UAC root.

        State and version files remain in the user's profile. Source runs and
        portable executables never gain an elevation root through this method.
        """
        if getattr(sys, "frozen", False):
            install_root = _query_registry_install_location()
            if install_root:
                root = os.path.normcase(os.path.realpath(install_root))
                base = os.path.normcase(os.path.realpath(self.base_dir))
                if root == base and _app_runs_from_install_location(root):
                    return os.path.join(self.base_dir, "zapret")
        return self.app_dir

    def find_binary(self, custom_path=None) -> str | None:
        """Find path to winws.exe, zapret.exe or winws binary."""
        self._rejected_binary_path = None
        if custom_path:
            if validate_zapret_binary(custom_path, self.app_dir, extra_roots=[self.base_dir]):
                return custom_path
            logger.warning("Rejected binary_path %r: not an approved winws executable", custom_path)
            self._rejected_binary_path = custom_path
            return None

        candidates = [
            os.path.join(self.app_dir, "winws.exe"),
            os.path.join(self.app_dir, "zapret.exe"),
            os.path.join(self.app_dir, "bin", "winws.exe"),
            os.path.join(self.base_dir, "bin", "winws.exe"),
            os.path.join(self.base_dir, "zapret", "winws.exe")
        ]
        bundle_dir = self._binary_directory()
        if bundle_dir != self.app_dir:
            candidates = [os.path.join(bundle_dir, "winws.exe"),
                          os.path.join(bundle_dir, "zapret.exe")] + candidates

        for c in candidates:
            if validate_zapret_binary(c, self.app_dir, extra_roots=[self.base_dir]):
                return c

        return None

    # ─── liveness (Z-5) ───

    def is_running(self) -> bool:
        """Return only process evidence, never a successful UAC dispatch."""
        with self._lock:
            if self.process and self.process.poll() is None:
                return True
        return any(self._pid_alive(pid) and self._is_our_winws_process(pid)
                   for pid in self._read_pidfile_pids())

    # ─── stderr log & crash analysis (Z-3) ───

    def _rotate_log_if_needed(self):
        """Z-3 rotation: keep zapret.log bounded, previous chunk as *.old.

        Shared by the direct-launch handle and the elevated cmd.exe redirect
        (BUG-028): the elevated path writes the log itself via `>>`, so the
        rotation must happen BEFORE the elevated launch, not only when a
        Popen handle is opened.
        """
        try:
            if os.path.exists(self.log_file) and os.path.getsize(self.log_file) > 1024 * 1024:
                os.replace(self.log_file, self.log_file + ".old")
        except OSError:
            logger.debug("zapret.log rotation failed", exc_info=True)

    def _open_log_handle(self):
        self._close_log_handle()
        try:
            # Repeated launches append forever; rotate once past 1 MiB so the
            # log stays bounded while keeping the previous chunk as *.old.
            self._rotate_log_if_needed()
            self._log_handle = open(self.log_file, "ab")
        except Exception:
            self._log_handle = None

    def _close_log_handle(self):
        try:
            if self._log_handle:
                self._log_handle.close()
        except Exception:
            logger.debug("_close_log_handle: suppressed exception", exc_info=True)
        self._log_handle = None

    def _read_log_tail(self, max_lines: int = 12, offset: int = 0) -> List[str]:
        """Last *max_lines* meaningful log lines, decoded by trial (BUG-019).

        cmd.exe writes its own messages in the OEM codepage (CP866 on Russian
        systems: «Отказано в доступе»), winws stderr is usually ASCII/UTF-8.
        The old fixed utf-8-with-replace read turned CP866 Cyrillic into
        mojibake, which made the Russian crash-analysis keys unreachable.
        *offset* (bytes): read only what was appended after this position —
        the elevated launcher records the file size before dispatching cmd.exe
        so a healthy run is not judged by a PREVIOUS session's log content.

        The read is bounded by _LOG_READ_WINDOW_BYTES: the log rotates at
        1 MiB per launch, but an elevated cmd.exe appends through its own
        handle and can outgrow that inside one long session, and crash
        analysis only needs the tail. With an *offset*, the window never
        reaches below the offset — previous-session content cannot leak into
        this run's diagnosis.
        """
        try:
            if not os.path.exists(self.log_file):
                return []
            window = max(1024, int(_LOG_READ_WINDOW_BYTES))
            with open(self.log_file, "rb") as f:
                size = f.seek(0, os.SEEK_END)
                line_aligned = True
                if offset and offset > 0:
                    pos = min(max(0, offset), size)
                    start = max(pos, size - window)
                else:
                    start = max(0, size - window)
                # Is *start* at a line boundary? Peek one byte back: a
                # trailing newline means the next append starts a fresh
                # line and nothing may be dropped; otherwise the first
                # split line is a fragment of an earlier line and is
                # discarded below.
                if start > 0:
                    f.seek(start - 1)
                    line_aligned = f.read(1) == b"\n"
                f.seek(start)
                raw = f.read()
            text = _decode_console_bytes(raw)
            lines = text.splitlines()
            if not line_aligned and lines:
                lines = lines[1:]
            return [l.rstrip() for l in lines[-max_lines:] if l.strip()]
        except Exception:
            return []

    def _looks_like_elevation_needed(self, tail: List[str]) -> bool:
        """BUG-027: anchored patterns, not bare substrings.

        A bare 'admin' matched file paths like C:\\Users\\Admin\\... and a bare
        'error 5' matched 'error 50' — an ordinary crash was then misdiagnosed
        as a rejected UAC prompt. Patterns are case-insensitive regexes;
        Latin keys are listed first, Russian keys cover the OEM-decoded
        (CP866) cmd.exe messages.
        """
        text = " ".join(tail).lower()
        return any(p.search(text) for p in _ELEVATION_PATTERNS)

    def _analyze_crash(self, tail: List[str]) -> str:
        text = " ".join(tail).lower()
        if self._looks_like_elevation_needed(tail):
            return "Нет прав администратора (UAC отклонён). См. лог zapret.log."
        if re.search(r"windivert|wfp", text):
            if any(p.search(text) for p in _WINBUSY_PATTERNS):
                return "Драйвер WinDivert занят другим процессом. См. лог zapret.log."
            return "Не удалось загрузить драйвер WinDivert. См. лог zapret.log."
        return "winws.exe завершился с ошибкой (краш). См. лог zapret.log."

    # ─── download / update (Z-7/8: outside the state lock) ───

    def _download_zip(self, url: str, timeout: float = 40.0) -> bytes:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            limit = 64 * 1024 * 1024
            body = bytearray()
            while chunk := resp.read(min(256 * 1024, limit + 1 - len(body))):
                body.extend(chunk)
                if len(body) > limit:
                    raise ValueError('Архив Zapret превышает допустимый размер')
            return bytes(body)

    def _extract_zip(self, zip_bytes: bytes):
        """Transactionally replace the bundle binaries (BUG-032).

        The old implementation replaced file-by-file straight inside app_dir:
        a failure on the N-th entry (locked exe, AV grab, disk full) left a
        mixture of old and new binaries that no later run could sort out. Now
        every candidate entry is first unpacked into a temporary directory
        NEXT TO app_dir and validated there; only when ALL of them are good
        are the originals swapped in. A failure before the swap leaves
        app_dir untouched; a failure during the swap is rolled back from
        backups, so the previous bundle survives as a whole.

        Preserved guarantees: zip-slip is closed via os.path.basename,
        0-byte entries are skipped, every file must pass
        is_valid_windows_binary, and the unpacked total is size-capped.
        """
        import zipfile, io, shutil
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            if sum(i.file_size for i in z.infolist()) > 256 * 1024 * 1024:
                raise ValueError('Распакованный архив Zapret слишком большой')
            entries = []
            for name in z.namelist():
                if "x86_64" in name and any(name.endswith(ext) for ext in [".exe", ".dll", ".sys"]):
                    filename = os.path.basename(name)
                    if not filename:
                        continue
                    try:
                        size = z.getinfo(name).file_size
                    except KeyError:
                        continue
                    # A 0-byte .exe is worse than no .exe: Windows answers it
                    # with "Невозможно запустить это приложение на вашем ПК",
                    # which read like a missing install on the user's side.
                    if size <= 0:
                        logger.warning("Skipping empty entry in Zapret archive: %s", name)
                        continue
                    entries.append((name, filename))

            if not entries:
                # Nothing usable inside; callers detect this via find_binary()
                # and keep version.json honest (no phantom install).
                raise ValueError('Архив Zapret не содержит исполняемых файлов')

            destination = self._binary_directory()
            os.makedirs(destination, exist_ok=True)
            parent = os.path.dirname(destination) or "."
            tmp_dir = os.path.join(
                parent, f".zapret_extract_{os.getpid()}_{uuid.uuid4().hex[:8]}")
            os.makedirs(tmp_dir)
            staged: List[Tuple[str, str]] = []  # (staged_path, target_path)
            preserve_recovery = False
            try:
                # Phase 1: unpack and validate EVERYTHING away from app_dir.
                for name, filename in entries:
                    staged_path = os.path.join(tmp_dir, filename)
                    with open(staged_path, "wb") as f:
                        f.write(z.read(name))
                    if not is_valid_windows_binary(staged_path):
                        raise ValueError('В архиве найден повреждённый исполняемый файл')
                    staged.append((staged_path, os.path.join(destination, filename)))

                required = {name.lower() for name in _REQUIRED_BUNDLE_FILES}
                missing = required - {os.path.basename(p).lower() for p, _ in staged}
                if missing:
                    raise ValueError("Неполный пакет Zapret: отсутствуют " + ", ".join(sorted(missing)))

                # Phase 2: swap in. Existing originals are copied into the
                # temp dir first so a mid-swap failure (a running exe locks
                # os.replace) can be undone instead of leaving half of the
                # old bundle behind. The backups live in a ".bak" subfolder —
                # a zapret archive can never contain that name after the
                # basename filter, so no staged file can collide with one.
                backups: Dict[str, str] = {}
                moved: List[str] = []
                try:
                    for staged_path, target_path in staged:
                        if os.path.exists(target_path):
                            bak_dir = os.path.join(tmp_dir, ".bak")
                            os.makedirs(bak_dir, exist_ok=True)
                            backup_path = os.path.join(bak_dir, os.path.basename(target_path))
                            shutil.copy2(target_path, backup_path)
                            backups[target_path] = backup_path
                        os.replace(staged_path, target_path)
                        moved.append(target_path)
                except Exception:
                    # Restore the exact previous set, including removal of
                    # files introduced by the failed transaction.
                    for target_path in reversed(moved):
                        backup_path = backups.get(target_path)
                        try:
                            if backup_path:
                                os.replace(backup_path, target_path)
                            else:
                                os.remove(target_path)
                        except OSError:
                            preserve_recovery = True
                            logger.error("Zapret update rollback failed for %s",
                                         target_path, exc_info=True)
                    raise
            finally:
                if not preserve_recovery:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                else:
                    logger.error('Zapret recovery files retained at %s', tmp_dir)

    def _bundle_complete(self):
        directory = self._binary_directory()
        return all(is_valid_windows_binary(os.path.join(directory, name))
                   for name in _REQUIRED_BUNDLE_FILES)

    @contextmanager
    def _bundle_install_guard(self):
        owner = threading.get_ident()
        with self._lock:
            previous = self._binary_update_owner
            if previous is not None and previous != owner:
                raise RuntimeError('Файлы Zapret уже обновляются')
            if (self._elevation_inflight is not None or self._elevation_pid_unknown
                    or self._state == _STATE_STOPPING
                    or (self._state == _STATE_STARTING and self._start_owner != owner)):
                raise RuntimeError('Дождитесь завершения запуска или остановки Zapret')
            self._binary_update_owner = owner
        try:
            yield
        finally:
            with self._lock:
                self._binary_update_owner = previous

    def _write_version_info(self, version: str, **extra):
        version_file = os.path.join(self.app_dir, "version.json")
        data = {"version": version, "last_updated": time.time()}
        data.update(extra)
        # Atomic write (BUG-014): a truncated version.json used to read as
        # version '' and announce phantom updates (BUG-016's trigger).
        if not self._atomic_write_text(version_file, json.dumps(data, indent=2)):
            raise OSError('Не удалось сохранить версию установленного Zapret')

    # ─── version.json metadata (audit C1: BUG-004/016) ───
    #
    # version.json carries both the installed version and update-channel
    # metadata. Rules:
    # - The "version" field is FABRICATED ONLY by a successful install
    #   (_write_version_info from download_binaries/update_zapret). Metadata
    #   updates (last_check, pending markers) never invent one (BUG-016: the
    #   auto-updater used to write version:'' when the file was broken).
    # - pending_update is written only for releases this build can actually
    #   install; a refused or repeatedly failing pending is cleared or
    #   rate-limited instead of sticking forever (BUG-004).

    def _read_version_meta(self) -> Dict[str, Any]:
        """Read version.json as a dict; an unreadable/absent file reads as {}.

        A broken file is MISSING metadata, never a fabricated version —
        callers decide what an empty record means (BUG-016)."""
        version_file = os.path.join(self.app_dir, "version.json")
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _update_version_meta(self, **extra) -> None:
        """Merge metadata keys (last_check, pending_update, ...) into
        version.json, preserving the recorded version. A missing file is not
        created: recovery of a broken file happens only when a real install
        writes fresh metadata (BUG-016)."""
        version_file = os.path.join(self.app_dir, "version.json")
        data = self._read_version_meta()
        if not data and not os.path.exists(version_file):
            return
        data.update(extra)
        self._atomic_write_text(version_file, json.dumps(data, indent=2))

    def _get_pending_update(self) -> str:
        import json
        version_file = os.path.join(self.app_dir, "version.json")
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                return json.load(f).get("pending_update") or ""
        except Exception:
            return ""

    def _clear_pending_update(self) -> None:
        """Drop the pending_update marker and its failure timestamp (BUG-004).

        A pending that can never be applied must not live forever: the old
        code left it set on every refusal, so the status promised an update
        the update button always refused and every start() paid a GitHub
        round-trip trying to apply it."""
        version_file = os.path.join(self.app_dir, "version.json")
        if not os.path.exists(version_file):
            return
        data = self._read_version_meta()
        if "pending_update" in data or "pending_failed_at" in data:
            data.pop("pending_update", None)
            data.pop("pending_failed_at", None)
            self._atomic_write_text(version_file, json.dumps(data, indent=2))

    def _mark_pending_failure(self) -> None:
        """Record that applying the pending update just failed (BUG-004):
        start() then defers the next attempt instead of retrying on every
        launch. The pending marker itself is kept — the failure may be a
        transient network outage."""
        self._update_version_meta(pending_failed_at=time.time())

    def _pending_retry_allowed(self) -> bool:
        """True when a previously failed pending-apply may be retried: at most
        once per 24 h (BUG-004), so toggle-on never blocks on a doomed GitHub
        call every time."""
        failed_at = self._read_version_meta().get("pending_failed_at")
        try:
            failed_at = float(failed_at)
        except (TypeError, ValueError):
            return True
        return (time.time() - failed_at) > 86400.0

    def download_binaries(self) -> Tuple[bool, str]:
        """Download and extract winws/zapret binary bundle from official bol-van/zapret release.

        BUG-038: this runs synchronously inside start() when the binary is
        missing or broken — up to ~30 s with no feedback, which read as a
        hanging toggle. The phases are reported through the event hook
        ('zapret_download_started' / 'zapret_download_finished' /
        'zapret_download_failed'). Cancellation needs none: the generation
        counter already guarantees a superseded start never launches."""
        if self._storage_unavailable:
            # BUG-017 gate (defense in depth): start() checks this already,
            # but extraction into a missing data directory would only fail
            # after a full download.
            return False, ("Каталог данных Zapret недоступен — установка файлов Zapret "
                           "невозможна. Проверьте права доступа и свободное место для ~/.nedotify.")
        with self._update_lock:
            self._emit_event("zapret_download_started", {
                "message": "Загрузка файлов Zapret…", "url": ZAPRET_ZIP_URL})
            try:
                logger.info("Downloading Zapret bundle from GitHub...")
                zip_bytes = self._download_zip(ZAPRET_ZIP_URL, timeout=30.0)

                if not _verify_zip_sha256(zip_bytes):
                    msg = f"Проверка SHA-256 не пройдена: архив {ZAPRET_VERSION} повреждён или подменён. Установка отменена."
                    logger.error(msg)
                    self._emit_event("zapret_download_failed", {"message": msg})
                    return False, msg

                with self._bundle_install_guard():
                    if self.is_running():
                        raise RuntimeError("Остановите Zapret перед заменой его файлов")
                    self._extract_zip(zip_bytes)
                    if not self._bundle_complete():
                        # Archive layout changed or nothing usable inside: never bump
                        # version.json in this case, otherwise the app would believe
                        # it is "installed" with no winws.exe on disk.
                        msg = f"Архив {ZAPRET_VERSION} не содержит winws.exe — установка отменена."
                        logger.error(msg)
                        self._emit_event("zapret_download_failed", {"message": msg})
                        return False, msg
                    self._write_version_info(ZAPRET_VERSION)
                logger.info("Zapret binaries successfully extracted to %s", self._binary_directory())
                msg = "Файлы Zapret успешно загружены!"
                self._emit_event("zapret_download_finished", {
                    "message": msg, "version": ZAPRET_VERSION})
                return True, msg
            except Exception as e:
                logger.error("Failed to download Zapret: %s", e)
                msg = f"Ошибка загрузки Zapret: {e}"
                self._emit_event("zapret_download_failed", {"message": msg})
                return False, msg

    def get_local_version(self) -> str:
        """Get local installed Zapret version tag ('' when nothing is installed
        or the metadata is unreadable — callers must not treat '' as an update
        trigger while a working binary exists, BUG-016)."""
        return str(self._read_version_meta().get("version") or "")

    def get_latest_release_info(self) -> Tuple[str | None, str | None, str]:
        """Fetch latest release tag and zip download URL from GitHub.

        Returns ``(tag, url, error)``. BUG-010: a network failure used to
        collapse into ``(None, None)``, which check_for_updates() then
        reported as "у вас последняя версия" — indistinguishable from a
        successful check. ``error`` is '' on success and carries a
        user-facing reason otherwise."""
        import urllib.request, json
        api_url = "https://api.github.com/repos/bol-van/zapret/releases/latest"
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tag = data.get("tag_name")
                if not tag:
                    return None, None, "GitHub ответил без тега последней версии"
                for a in data.get("assets", []):
                    if a.get("name", "").endswith(".zip"):
                        return tag, a.get("browser_download_url"), ""
                return tag, f"https://github.com/bol-van/zapret/releases/download/{tag}/zapret-{tag}.zip", ""
        except Exception as e:
            logger.warning("Failed to fetch latest Zapret release: %s", e)
            return None, None, f"Не удалось связаться с GitHub: {e}"

    def check_for_updates(self) -> Dict[str, Any]:
        """Check whether a newer Zapret release exists.

        Contract (audit C1):
        - ``error``: non-empty when the check itself failed (no network,
          GitHub unreachable). The UI must show a "check failed" state —
          never "у вас последняя версия" (BUG-010).
        - ``update_available``: a NEWER release exists (numeric comparison,
          BUG-029). False on error, and when the local version metadata is
          unreadable while a working binary is installed (BUG-016: a
          truncated version.json must not announce phantom updates).
        - ``auto_installable``: the found release is exactly the pinned one
          this build carries a trusted SHA-256 for — the "Обновить" button
          can install it without touching the application.
        - ``manual_update_required``: a newer release exists but cannot be
          auto-installed (no trusted hash); the application itself must be
          updated. Together with ``auto_installable`` this lets the UI
          distinguish "нажмите Обновить" from "обновите приложение"
          (BUG-004: no promises the updater cannot keep).
        - ``unknown_format``: a release tag did not parse as a version; the
          announcement is conservative.
        """
        current_ver = self.get_local_version()
        binary_found = bool(self.find_binary())
        latest_tag, zip_url, fetch_error = self.get_latest_release_info()
        result: Dict[str, Any] = {
            "current_version": current_ver,
            "latest_version": latest_tag or current_ver or "",
            "update_available": False,
            "download_url": zip_url or "",
            "error": "",
            "auto_installable": False,
            "manual_update_required": False,
            "unknown_format": False,
            "version_unknown": False,
        }
        if fetch_error or not latest_tag:
            result["error"] = fetch_error or (
                "Не удалось получить информацию о последней версии Zapret с GitHub")
            # BUG-010 hardening: a failed check learned nothing about what the
            # latest release is — it must not publish the CURRENT version as
            # ``latest_version`` (a consumer could read that as "the latest
            # release is v<current>, nothing to do").
            result["latest_version"] = ""
            result["download_url"] = ""
            return result

        result["auto_installable"] = bool(
            zip_url == ZAPRET_ZIP_URL and latest_tag == ZAPRET_VERSION)

        # BUG-016: a broken version.json reads as version '' while a working
        # binary is on disk. That is missing metadata, not a missing install —
        # announcing an update would send the user to re-download over a
        # phantom difference. The "Обновить" button stays available and
        # repairs the metadata by actually installing the pinned release.
        if not current_ver and binary_found:
            result["version_unknown"] = True
            return result

        is_newer, unknown_format = _version_is_newer(latest_tag, current_ver)
        result["update_available"] = bool(is_newer)
        result["unknown_format"] = unknown_format
        result["manual_update_required"] = bool(is_newer and not result["auto_installable"])
        return result

    def update_zapret(self, force: bool = False) -> Tuple[bool, str]:
        """Update Zapret to the latest GitHub release. Serialized by _update_lock
        (Z-7/8): downloads and extraction happen outside the state lock, but never
        concurrently with another update or auto-download.

        BUG-008: a failed stop() aborts the update BEFORE extraction —
        os.replace against a running winws.exe fails halfway and used to
        leave a mixture of old and new binaries on disk. A restart that fails
        AFTER the binaries were swapped is reported honestly instead of as a
        plain success.
        BUG-004: refusing a release without a trusted SHA-256 also clears any
        pending marker — that release can never be installed by this build,
        so keeping the pending "применится при следующем запуске" promise was
        a permanent deadlock."""
        if self._storage_unavailable:
            # BUG-017 gate: update_zapret is reachable without start()'s gate
            # (background auto-update), and extraction into a missing data
            # directory would fail with an opaque FileNotFoundError.
            return False, ("Каталог данных Zapret недоступен — обновление невозможно. "
                           "Проверьте права доступа и свободное место для ~/.nedotify.")
        with self._update_lock:
            latest_tag, zip_url, fetch_error = self.get_latest_release_info()
            if fetch_error or not latest_tag or not zip_url:
                return False, (fetch_error or
                               "Не удалось получить информацию о последней версии Zapret с GitHub")

            current_ver = self.get_local_version()
            # Same tag already on disk with a usable binary — nothing to fetch,
            # even with force=True (a forced re-download of the identical zip
            # only wastes bandwidth and can race a concurrent start()). A
            # pending marker for it is stale — drop it, otherwise every
            # start() would keep paying a GitHub call for a no-op (BUG-004).
            if latest_tag == current_ver and self._bundle_complete():
                self._clear_pending_update()
                return True, f"У вас уже установлена последняя версия Zapret ({current_ver})"

            try:
                if zip_url != ZAPRET_ZIP_URL or latest_tag != ZAPRET_VERSION:
                    # No pinned hash for this release → this build can never
                    # install it. Clear the pending marker (retrying cannot
                    # succeed until the application itself is updated).
                    self._clear_pending_update()
                    msg = (f"Для версии {latest_tag} нет доверенной SHA-256: автоматическая "
                           "установка недоступна. Обновите приложение NeDotify — новая версия "
                           "приложения поддерживает свежие релизы Zapret.")
                    logger.warning(msg)
                    return False, msg
                logger.info("Downloading Zapret %s from %s...", latest_tag, zip_url)
                zip_bytes = self._download_zip(zip_url, timeout=40.0)

                # Verify integrity: pinned hash exists only for the bundled release.
                expected_hash = ZAPRET_ZIP_SHA256 if zip_url == ZAPRET_ZIP_URL else ""
                if not _verify_zip_sha256(zip_bytes, expected_hash):
                    msg = f"Проверка SHA-256 не пройдена: архив {latest_tag} повреждён или подменён. Обновление отменено."
                    logger.error(msg)
                    return False, msg

                with self._bundle_install_guard():
                    was_running = self.is_running()
                    restart_generation = None
                    if was_running:
                        stopped, stop_msg = self.stop()
                        with self._lock:
                            restart_generation = self._generation
                        time.sleep(1.0)
                        if not stopped:
                            # BUG-008: never unpack over a live winws.exe — the
                            # swap would fail midway and leave a mixture of old
                            # and new binaries with the process still running.
                            msg = (f"Обновление отменено: не удалось остановить Zapret ({stop_msg}) — "
                                   "нельзя заменять файлы работающего процесса. Остановите Zapret "
                                   "и повторите обновление.")
                            logger.warning(msg)
                            return False, msg

                    try:
                        self._extract_zip(zip_bytes)
                    except Exception as exc:
                        note = self._restore_after_failed_update(restart_generation) if was_running else ""
                        raise RuntimeError(f"{exc}.{note}") from None
                    if not self._bundle_complete():
                        # Extraction produced no usable binary (e.g. release layout
                        # changed): keep the old version.json so the next attempt
                        # still reports an update instead of a phantom install.
                        note = self._restore_after_failed_update(restart_generation) if was_running else ""
                        msg = (f"Архив {latest_tag} не содержит winws.exe — обновление отменено, "
                               f"предыдущая версия сохранена.{note}")
                        logger.error(msg)
                        return False, msg
                    # Rewriting version.json drops any pending_update flag and any
                    # failure timestamp (BUG-004): success is the only moment a
                    # version value is fabricated.
                    self._write_version_info(latest_tag)
                    logger.info("Zapret successfully updated to %s", latest_tag)

                    message = f"Zapret успешно обновлен до версии {latest_tag}!"
                    if was_running:
                        with self._lock:
                            if restart_generation != self._generation:
                                return True, message + ' Автоперезапуск отменён новой командой остановки.'
                        mode = "youtube_discord"
                        custom_args = ""
                        bin_path = None
                        if self.settings:
                            mode = self.settings.get("zapret", "mode", "youtube_discord")
                            custom_args = self.settings.get("zapret", "custom_args", "")
                            bin_path = self.settings.get("zapret", "binary_path", "")
                        # BUG-008 honesty: the binaries ARE updated at this point,
                        # but the user asked for an update of a RUNNING bypass. A
                        # failed restart used to be swallowed — the UI showed a
                        # success while the bypass was left off with enabled=true.
                        try:
                            restarted, start_msg = self.start(
                                mode=mode, custom_args=custom_args, binary_path=bin_path,
                                expected_generation=restart_generation)
                        except Exception as start_exc:
                            logger.warning("Zapret restart after update raised",
                                           exc_info=True)
                            restarted, start_msg = False, str(start_exc)
                        if not restarted:
                            message += (f" Но запустить обновлённый Zapret не удалось: "
                                        f"{start_msg} — включите его повторно.")
                            logger.warning("Zapret update succeeded but the restart "
                                           "failed: %s", start_msg)

                    return True, message
            except Exception as e:
                logger.error("Failed to update Zapret: %s", e)
                return False, f"Ошибка при обновлении Zapret: {e}"

    def _restore_after_failed_update(self, expected_generation=None) -> str:
        """Best-effort restart of the bypass after a failed update that had to
        stop it (BUG-008): the previous bundle is intact thanks to the
        transactional extraction, so a failed update must not silently turn
        into a disabled Zapret. Returns a user-facing note about the outcome."""
        try:
            with self._lock:
                if expected_generation is not None and expected_generation != self._generation:
                    return ' Перезапуск отменён новой командой остановки.'
            mode = "youtube_discord"
            custom_args = ""
            bin_path = None
            if self.settings:
                mode = self.settings.get("zapret", "mode", "youtube_discord")
                custom_args = self.settings.get("zapret", "custom_args", "")
                bin_path = self.settings.get("zapret", "binary_path", "")
            ok, msg = self.start(mode=mode, custom_args=custom_args, binary_path=bin_path,
                                 expected_generation=expected_generation)
            if ok:
                logger.info("Zapret restarted on the previous binaries after a failed update")
                return " Zapret перезапущен на предыдущей версии."
            logger.warning("Zapret could not be restarted after a failed update: %s", msg)
            return f" Внимание: Zapret остаётся остановлен ({msg})."
        except Exception:
            logger.warning("Zapret restart after a failed update raised", exc_info=True)
            return " Внимание: Zapret остаётся остановлен — включите его повторно."

    def auto_update_in_background(self):
        """Z-8: background update check — only when autoupdate is enabled (default OFF).
        A running winws is never restarted: the update is marked pending and
        applied on the next launch.

        BUG-004: a pending marker is written ONLY for releases this build can
        install (pinned URL + pinned tag). Anything newer without a trusted
        hash is logged and left alone — pending for an uninstallable release
        deadlocked the channel and slowed every start().
        BUG-010: a failed GitHub fetch is not "no updates" — nothing that
        looks like a completed check is recorded, so tomorrow's check retries.
        BUG-016: broken version.json is never "repaired" with version:''."""
        def _bg():
            try:
                time.sleep(5.0)  # Wait for main app startup to settle
                self._auto_update_once()
            except Exception as e:
                logger.debug("Background Zapret auto-update error: %s", e)

        threading.Thread(target=_bg, daemon=True).start()

    def _auto_update_once(self):
        """One gated auto-update cycle. Separated from the thread wrapper so
        it can run synchronously in tests.

        BUG-004: the whole cycle runs under _update_lock. The pending and
        last_check writes are read-modify-write transactions on version.json;
        without the lock they could interleave with update_zapret's full
        version rewrite and resurrect a stale version/pending right after a
        successful install. _update_lock is an RLock, so the nested
        update_zapret() call re-enters it on the same thread."""
        if not self.settings or not self.settings.get("zapret", "autoupdate", False):
            return
        with self._update_lock:
            self._auto_update_locked()

    def _auto_update_locked(self):
        last_check = self._read_version_meta().get("last_check", 0)
        try:
            last_check = float(last_check)
        except (TypeError, ValueError):
            last_check = 0.0

        # Check at most once every 24 hours. Deliberately on wall-clock
        # (BUG-042): the timestamp is PERSISTED in version.json and a
        # monotonic clock is only comparable within one boot. A clock jump
        # backward at worst EXTENDS the interval (one skipped check —
        # harmless); a jump forward triggers the check earlier (also
        # harmless). Sleep/hibernation needs no handler: a suspend makes
        # wall-clock jump forward, i.e. at most an earlier check.
        if time.time() - last_check <= 86400:
            return

        latest_tag, zip_url, fetch_error = self.get_latest_release_info()
        if fetch_error or not latest_tag:
            # BUG-010: no network ≠ no updates: record nothing, retry tomorrow.
            logger.info("Zapret update check skipped: %s",
                        fetch_error or "GitHub недоступен")
            return

        cur_ver = self.get_local_version()
        if not cur_ver and self.find_binary():
            # BUG-016: working binaries with unreadable version metadata.
            # Auto-updating over an unknown state — and the old code then
            # wrote version:'' — would fabricate a fresh install record.
            # Skip until a real install (the manual update button) restores
            # the metadata.
            logger.info("Zapret version metadata unreadable; skipping auto-update")
            self._update_version_meta(last_check=time.time())
            return

        is_newer, unknown_format = _version_is_newer(latest_tag, cur_ver)
        if not is_newer:
            self._update_version_meta(last_check=time.time())
            return

        logger.info("New Zapret update found: %s (current: %s)", latest_tag, cur_ver)
        if unknown_format:
            logger.warning("Zapret release tag %r does not parse as a version; "
                           "treating it as newer", latest_tag)
        self._update_version_meta(last_check=time.time())
        if zip_url == ZAPRET_ZIP_URL and latest_tag == ZAPRET_VERSION:
            if self.is_running():
                # Never interrupt a running bypass — offer the update for next launch.
                self._update_version_meta(pending_update=latest_tag)
                logger.info("Zapret update %s marked pending (applies on next launch)", latest_tag)
            else:
                self.update_zapret(force=True)
        else:
            # BUG-004: this build has no trusted hash for the new release.
            # Writing pending would promise an installation the update button
            # always refuses; the application itself needs updating first.
            logger.info("Zapret %s cannot be auto-installed by this build "
                        "(no trusted SHA-256); a manual application update is required",
                        latest_tag)

    # ─── start / stop (Z-2, Z-3; state machine, lock only around transitions) ───

    def select_strategy(self, preferred="youtube_discord", binary_path=None):
        """First-use strategy selection, verified by a real audio download."""
        with self._lock:
            if self._binary_update_owner not in (None, threading.get_ident()):
                return False, 'Дождитесь завершения обновления файлов Zapret', preferred
            if self._selection_active:
                return False, "Подбор уже выполняется", preferred
            if preferred not in PRESET_STRATEGIES:
                return False, "Неизвестная стратегия Zapret", preferred
            self._selection_active = True
            self._selection_owner = threading.get_ident()
            self._selection_cancel.clear()
        modes = list(dict.fromkeys([preferred] + list(PRESET_STRATEGIES)))
        result = (False, "Подбор отменён", preferred)
        started = False
        generation = None
        try:
            for attempt, mode in enumerate(modes, 1):
                if self._selection_cancel.is_set():
                    break
                self._emit_event('zapret_selection_progress', {
                    'attempt': attempt, 'total': len(modes), 'mode': mode,
                    'message': f'Подбор стратегий: попытка {attempt} из {len(modes)} ({mode}). Проверяем YouTube…'})
                ok, message = self.start(mode=mode, binary_path=binary_path, interactive=True)
                if not ok:
                    result = (False, message, mode)
                    break
                started = True
                with self._lock:
                    generation = self._generation
                result = (False, "Подбор отменён", mode)
                if self._selection_cancel.is_set():
                    break
                reachable = self._probe_selection_youtube()
                with self._lock:
                    if self._selection_cancel.is_set() or generation != self._generation:
                        break
                    if reachable and self.is_running():
                        result = (True, "Стратегия подобрана: тестовый аудиофайл YouTube успешно скачан. Другие треки могут иметь ограничения доступа.", mode)
                        break
                started = False  # this stop owns the cleanup, even if UAC is refused
                ok, message = self._stop_impl(bump_generation=True, allow_elevation=True)
                if not ok:
                    result = (False, message, mode)
                    break
            else:
                result = (False, "Ни одна стратегия не прошла проверку YouTube. Проверьте сеть и отключите VPN перед повторным подбором.", preferred)
        except Exception:
            logger.exception("Zapret strategy selection failed")
            # start() may raise after creating its process (for example while
            # recording state). The selection still owns that process.
            with self._lock:
                if not self._selection_cancel.is_set() and self.is_running():
                    started = True
                    generation = self._generation
            result = (False, "Ошибка проверки стратегии Zapret. Повторите подбор.", result[2])
        finally:
            try:
                with self._lock:
                    owns_process = generation == self._generation
                if started and not result[0] and owns_process:
                    ok, message = self._stop_impl(bump_generation=True, allow_elevation=True)
                    if not ok:
                        result = (False, message, result[2])
            finally:
                with self._lock:
                    self._selection_active = False
                    self._selection_owner = None
                    self._status_cache = None
                    self._status_epoch += 1
        return result

    def cancel_selection(self):
        """Signal the selecting worker; it alone stops its current attempt."""
        with self._lock:
            if not self._selection_active:
                return False
            self._selection_cancel.set()
            return True

    def _probe_selection_youtube(self):
        import requests
        with requests.Session() as session:
            session.trust_env = False
            for url in ('https://www.youtube.com/generate_204', 'https://music.youtube.com/'):
                if self._selection_cancel.is_set():
                    return False
                try:
                    with session.get(url, timeout=(4, 4), stream=True, allow_redirects=False) as response:
                        if response.status_code not in (200, 204):
                            return False
                except requests.RequestException:
                    return False
        from services.zapret_probe import probe_youtube_audio
        return probe_youtube_audio(self._selection_cancel.is_set)

    def start(self, mode="youtube_discord", custom_args="", binary_path=None, expected_generation=None, interactive=False) -> Tuple[bool, str]:
        """Start Zapret process with specified strategy. Returns (success, status_message).
        If winws is already running with DIFFERENT arguments (mode switched while
        active), it is restarted with the new strategy instead of a silent no-op.

        Lifecycle (audit A1): the call opens a STARTING epoch identified by a
        generation counter. Any stop()/start() that arrives while this epoch is
        in flight (slow download, UAC, PID discovery) bumps the generation and
        cancels the stale epoch before it can launch — the autostart worker can
        no longer resurrect winws after a toggle-off or during shutdown
        (BUG-002/003)."""
        with self._lock:
            if expected_generation is not None and expected_generation != self._generation:
                return False, _START_CANCELLED_MSG
            if self._binary_update_owner not in (None, threading.get_ident()):
                return False, 'Дождитесь завершения обновления файлов Zapret'
            if self._selection_active:
                if self._selection_owner != threading.get_ident():
                    return False, "Дождитесь завершения подбора стратегий или отмените его"
                if self._selection_cancel.is_set():
                    return False, "Подбор отменён"
            if self._elevation_inflight is not None or self._elevation_pid_unknown:
                return False, ("Не удалось подтвердить PID после запроса UAC. "
                               "Проверьте winws.exe в диспетчере задач и перезапустите "
                               "NeDotify перед повторным включением, чтобы не запустить второй экземпляр.")
            if self._storage_unavailable:
                # BUG-017: the data directory could not be created; launching
                # would produce untracked processes with no pidfile at all.
                return False, ("Каталог данных Zapret недоступен — запуск невозможен. "
                               "Проверьте права доступа и свободное место для ~/.nedotify.")
            if self._state == _STATE_STOPPING:
                return False, "Zapret сейчас останавливается — повторите попытку через мгновение"
            self._generation += 1
            gen = self._generation
            self._start_owner = threading.get_ident()
            self._state = _STATE_STARTING
        try:
            if interactive:
                return self._start_with_generation(gen, mode, custom_args, binary_path, allow_elevation_stop=True)
            return self._start_with_generation(gen, mode, custom_args, binary_path)
        finally:
            # Safety net for exception paths: never leave a stale STARTING
            # behind. A newer command owning the generation is left alone.
            with self._lock:
                if gen == self._generation and self._state == _STATE_STARTING:
                    self._state = _STATE_RUNNING if self.is_running() else _STATE_STOPPED
                if gen == self._generation:
                    self._start_owner = None
                self._status_cache = None
                self._status_cache_time = 0.0
                self._status_epoch += 1
            self._ensure_lifecycle_watcher()

    def _start_with_generation(self, gen: int, mode, custom_args, binary_path, allow_elevation_stop=False) -> Tuple[bool, str]:
        # BUG-031 (D2 ordering fix): the mode/args validation below used to sit
        # AFTER find_binary() and the auto-download — an unknown mode saved in
        # the settings DB (the exact stale-value scenario) made autostart pay
        # the full bundle download before refusing, and a "custom" mode with
        # empty args could overwrite nothing but still touched the disk.
        # Refuse FIRST: the strategy is validated before any binary I/O.
        if mode == "custom":
            if not (custom_args or "").strip():
                return False, ("Для режима custom укажите аргументы winws "
                               "в поле «Свои аргументы» — запускать Zapret "
                               "без стратегии нельзя.")
            raw_args = custom_args.strip()
            try:
                sanitize_zapret_args(raw_args)
            except ValueError as exc:
                logger.warning("Rejected custom Zapret args: %s", exc)
                return False, str(exc)
        elif mode in PRESET_STRATEGIES:
            template = PRESET_STRATEGIES[mode]
            try:
                raw_args = template.format(hosts=",".join(ZAPRET_SCOPED_HOSTS))
            except (KeyError, IndexError):
                # A hand-edited preset without the placeholder: run it as-is
                # rather than failing the launch over a formatting detail.
                logger.warning("Preset %r has no {hosts} placeholder", mode)
                raw_args = template
            try:
                sanitize_zapret_args(raw_args)
            except ValueError as exc:
                logger.warning("Rejected preset Zapret args for %r: %s", mode, exc)
                return False, str(exc)
        else:
            available = ", ".join(list(PRESET_STRATEGIES) + ["custom"])
            return False, (f"Неизвестный режим Zapret: {mode!r}. "
                           f"Доступные режимы: {available}.")

        exe = self.find_binary(binary_path)
        bundle_dir = self._binary_directory()
        if exe and not binary_path and bundle_dir != self.app_dir and not self.is_running():
            # Recover a previous first-run download in the profile, or a
            # partial installed bundle. Never copy unverified cached files
            # into an elevation root: re-fetch the SHA-256-pinned archive.
            if (os.path.normcase(os.path.dirname(exe)) != os.path.normcase(bundle_dir)
                    or any(not is_valid_windows_binary(os.path.join(bundle_dir, name))
                           for name in _REQUIRED_BUNDLE_FILES)):
                exe = None
        if not exe:
            # A user-configured path that failed validation used to be dropped
            # silently, so the user saw only "winws.exe not found" and had no
            # idea their setting was the problem.
            rejected = getattr(self, "_rejected_binary_path", None)
            if rejected:
                return False, (
                    f"Путь к winws.exe отклонён: {rejected}. Ожидается winws.exe, "
                    "zapret.exe или winws в папке zapret или рядом с программой."
                )
            # Try auto-downloading if missing (network I/O — outside the lock)
            logger.info("Zapret binary not found. Attempting automatic download...")
            ok, dl_msg = self.download_binaries()
            exe = self.find_binary(binary_path)
            if not ok or not exe:
                msg = f"Файл winws.exe не найден. {dl_msg}"
                logger.warning(msg)
                return False, msg

        # Validate the image BEFORE any launch attempt. A 0-byte or truncated
        # winws.exe makes subprocess.Popen raise OSError, which drops straight
        # into _launch_elevated, and ShellExecuteW on such a file shows the
        # Windows dialog "Невозможно запустить это приложение на вашем ПК" with
        # no way for the app to explain what happened. Checking here converts
        # that dialog into a message the UI can actually show.
        broken = binary_integrity_error(exe)
        if broken:
            # A corrupt binary is recoverable: the bundle is a known URL with a
            # pinned hash, so one re-download usually fixes it and the user is
            # not left deleting folders by hand.
            logger.warning("Zapret binary is unusable (%s); re-downloading", broken)
            ok, dl_msg = self.download_binaries()
            exe = self.find_binary(binary_path)
            broken = binary_integrity_error(exe) if exe else "Файл winws.exe не найден."
            if not broken:
                logger.info("Zapret binary re-downloaded and verified")
            else:
                logger.error("Refusing to launch Zapret after re-download: %s", broken)
                if not ok:
                    broken = f"{broken} Попытка переустановить не удалась: {dl_msg}"
                return False, broken

        # BUG-031: both non-preset paths used to fall through to the
        # youtube_discord preset silently — a custom start with EMPTY args and
        # any unknown mode (e.g. a stale value saved by an older build or a
        # hand-edited settings row) launched a strategy the user never asked
        # for. Both are explicit refusals now: fail-closed is the only safe
        # default for arguments that reach an elevated process. The validation
        # itself runs at the very top of this method — before find_binary()
        # and the auto-download — so an invalid saved mode never pays for a
        # bundle download it can never use.

        # A newer stop/start command that arrived while we were locating and
        # validating the binary cancels this epoch (audit A1). Check BEFORE
        # the pending-apply below: without this gate a cancelled start still
        # paid a GitHub round-trip, and update_zapret's internal stop()/start()
        # could bounce a process a newer command had just started (BUG-004).
        with self._lock:
            if gen != self._generation:
                return False, _START_CANCELLED_MSG

        # Apply a pending update if one was deferred while the bypass was running (Z-8)
        pending = self._get_pending_update()
        if pending and not self.is_running():
            if not self._pending_retry_allowed():
                # BUG-004: the last apply attempt failed; retrying on every
                # start would pay a GitHub round-trip each toggle-on. The
                # next attempt is deferred by a day (a permanent refusal —
                # an uninstallable release — clears the pending outright).
                logger.info("Pending Zapret update %s skipped: the previous "
                            "attempt failed less than 24h ago", pending)
            else:
                logger.info("Applying pending Zapret update %s before launch...", pending)
                ok, upd_msg = self.update_zapret(force=True)
                if ok:
                    exe = self.find_binary(binary_path)
                    if not exe:
                        return False, 'Обновление не установило исполняемый файл Zapret'
                if not ok:
                    # Transient failure (network, extraction): keep the
                    # pending marker but rate-limit the next attempt.
                    self._mark_pending_failure()
                    logger.warning("Pending Zapret update %s failed: %s", pending, upd_msg)

        with self._lock:
            if gen != self._generation:
                return False, _START_CANCELLED_MSG

        # Serialize the launch decision machine-wide (BUG-043: fast user
        # switching gives every account its own service object and state
        # files, but the WinDivert driver is global). The guard is held only
        # around the scan/launch decision — never across downloads or UAC.
        guard = _global_zapret_guard_acquire()
        try:
            with self._lock:
                if gen != self._generation:
                    return False, _START_CANCELLED_MSG
                if self._state == _STATE_STOPPING:
                    return False, "Zapret сейчас останавливается — повторите попытку через мгновение"
                already = self.is_running()
                if already:
                    # BUG-014: a lost run.cmd must not look like a "mode
                    # change": with a live process and no recorded signature
                    # there is nothing to restart — report the active process.
                    current_cmd = (self._last_args or self._read_cmd_file()).strip()
                    if current_cmd == raw_args.strip() or (not current_cmd and not self._selection_active and not allow_elevation_stop):
                        self._state = _STATE_RUNNING
                        return True, "Zapret активен"
                    restart_needed = True
                else:
                    restart_needed = False

            foreign_pid: Optional[int] = None
            orphan_pid: Optional[int] = None
            restart_orphan_pid: Optional[int] = None
            if not restart_needed:
                if not already:
                    # BUG-013: scan for running winws images BEFORE spawning a
                    # second driver. Slow (tasklist) — outside the state lock,
                    # under the machine guard.
                    ours_pid, foreign_pid = self._classify_running_winws()
                    orphan_pid = ours_pid
                with self._lock:
                    if gen != self._generation:
                        return False, _START_CANCELLED_MSG
                    if foreign_pid is not None:
                        self._state = _STATE_STOPPED
                        msg = ("Уже запущен другой экземпляр Zapret (winws.exe, PID "
                               f"{foreign_pid}). Остановите его — два экземпляра драйвера "
                               "WinDivert конфликтуют.")
                        logger.warning(msg)
                        return False, msg
                    if orphan_pid is not None and self._pid_alive(orphan_pid):
                        # Adopt the orphaned process instead of spawning a
                        # second winws over it (BUG-013). run.cmd is the only
                        # record of the orphan's strategy: when it survives and
                        # names a DIFFERENT one, recording the requested args
                        # over it would desync state from reality — a later
                        # start() could silently no-op on a process still
                        # running the old strategy. Restart precisely instead:
                        # the kill runs outside the state lock, right below.
                        recorded = self._read_cmd_file().strip()
                        if recorded != raw_args.strip() and (recorded or self._selection_active or allow_elevation_stop):
                            restart_orphan_pid = orphan_pid
                        else:
                            self._known_uid = uuid.uuid4().hex[:16]
                            self._write_pidfile(orphan_pid, uid=self._known_uid)
                            self._write_cmd_file(raw_args)
                            self._last_args = raw_args
                            self._state = _STATE_RUNNING
                            logger.info("Adopted orphaned Zapret process (PID %s)", orphan_pid)
                            return True, "Zapret активен (подключён к уже запущенному процессу Zapret)"

            if restart_orphan_pid is not None:
                # The orphan was already verified as ours by the ownership
                # scan, so kill exactly that PID — no extra WMI scan, and the
                # taskkill batch stays outside the state lock (BUG-007).
                logger.info("Orphaned Zapret (PID %s) runs a different strategy than "
                            "requested; restarting it with the new one", restart_orphan_pid)
                killed = (self._kill_pid(restart_orphan_pid, allow_elevation=True) if allow_elevation_stop
                          else self._kill_pid(restart_orphan_pid))
                if not killed or self._pid_alive(restart_orphan_pid):
                    with self._lock:
                        if gen == self._generation:
                            self._state = _STATE_STOPPED
                    msg = (f"Найден запущенный процесс Zapret (PID {restart_orphan_pid}) "
                           "с другой стратегией, но остановить его не удалось — "
                           "новая стратегия не применена.")
                    logger.warning(msg)
                    return False, msg
                with self._lock:
                    if gen != self._generation:
                        return False, _START_CANCELLED_MSG
                    self._clear_pidfile()
                    self._clear_cmd_file()
                    self._last_args = ""

            if restart_needed:
                # Already running with a DIFFERENT strategy (mode switched in the
                # UI while active) — silently returning "active" would leave the
                # old winws arguments in place. Restart with the new ones.
                # BUG-013 still applies: a foreign winws means the restart would
                # stack a second driver, so refuse instead of restarting.
                _, restart_foreign_pid = self._classify_running_winws()
                with self._lock:
                    if gen != self._generation:
                        return False, _START_CANCELLED_MSG
                    if restart_foreign_pid is not None:
                        self._state = _STATE_RUNNING
                        msg = ("Уже запущен другой экземпляр Zapret (winws.exe, PID "
                               f"{restart_foreign_pid}) — новая стратегия не применена.")
                        logger.warning(msg)
                        return False, msg
                # The internal stop does not bump the generation: this start is
                # the newest command and must not cancel itself.
                logger.info("Zapret strategy changed — restarting with new arguments")
                stopped, stop_msg = self._stop_impl(bump_generation=False, allow_elevation=allow_elevation_stop)
                if not stopped:
                    return False, f"Не удалось применить новую стратегию: {stop_msg}"

            with self._lock:
                if gen != self._generation:
                    return False, _START_CANCELLED_MSG
                kind, proc, launch_msg = self._launch(exe, raw_args)
                if kind == 'elevate':
                    # Reserve the launch before releasing the machine guard:
                    # stop can cancel it, but no second start may bypass UAC.
                    self._elevation_inflight = gen
                    self._elevation_dispatched = False
        finally:
            _global_zapret_guard_release(guard)

        if kind == "failed":
            with self._lock:
                if gen == self._generation and self._state != _STATE_STOPPING:
                    self._state = _STATE_STOPPED
            return False, launch_msg
        if kind == "elevate":
            # Elevation blocks on the UAC secure desktop and on multi-second
            # PID scans — strictly outside the state lock (BUG-007).
            ok, msg = self._launch_elevated(exe, raw_args)
            with self._lock:
                if gen == self._generation:
                    self._state = _STATE_RUNNING if ok else _STATE_STOPPED
            return ok, msg
        return self._confirm_launch(proc, gen)

    def _launch(self, exe: str, raw_args: str) -> Tuple[str, Any, str]:
        """Launch the validated binary. Called with self._lock held and must
        stay fast — no UAC, no PID scans (BUG-007). The elevated fallback and
        the survival confirmation run outside the lock.

        Returns ``(kind, process, message)`` with kind in
        {"started", "elevate", "failed"}:
        - "started": child is alive after the quick in-lock poll; the caller
          runs _confirm_launch outside the lock.
        - "elevate": the child needs elevation; the caller runs
          _launch_elevated outside the lock.
        - "failed": launch is over, message is user-facing.
        """
        if not validate_zapret_binary(exe, self.app_dir, extra_roots=[self.base_dir]):
            return ("failed", None, 'Отказано в запуске непроверенного исполняемого файла Zapret')
        # Instance marker for the pidfile record (BUG-047). Generated even on
        # the elevation path so the discovered elevated PID is recorded with it.
        uid = uuid.uuid4().hex[:16]
        self._known_uid = uid
        logger.info("Starting Zapret: %s %s", exe, raw_args)

        # Validate once, before anything is recorded: run.cmd must never
        # describe a launch that never happened (a stale signature makes the
        # next stop() pay for a multi-second scan for nothing).
        try:
            args_list = [exe] + sanitize_zapret_args(raw_args)
        except ValueError as exc:
            logger.error("Refusing to launch Zapret with unsafe arguments: %s", exc)
            return ("failed", None, str(exc))

        # The signature file is what makes a later stop() find an orphaned
        # elevated process; a failed write is degraded-and-warned (BUG-015),
        # not a reason to skip the launch itself.
        self._last_args = raw_args
        self._write_cmd_file(raw_args)

        if sys.platform == "win32":
            import ctypes
            self._open_log_handle()
            try:
                self.process = subprocess.Popen(
                    args_list,
                    cwd=os.path.dirname(exe),
                    stdout=subprocess.DEVNULL,
                    stderr=self._log_handle or subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except OSError as exc:
                self._close_log_handle()
                self.process = None
                # BUG-045: an AV that quarantines/locks winws between the
                # validation above and Popen used to fall into the elevation
                # branch and surfaced as the misleading «не является
                # разрешённым исполняемым файлом». UAC is requested ONLY for
                # ERROR_ELEVATION_REQUIRED (winerror 740) — the one failure a
                # UAC launch can actually fix (an exe with a
                # requireAdministrator manifest). Empirically (Python 3.14.7)
                # that error arrives as a PLAIN OSError with winerror=740 and
                # errno=22, NOT as PermissionError — so the check reads the
                # winerror attribute (with the errno==740 belt for manually
                # raised look-alikes). A missing file (FileNotFoundError,
                # winerror 2) means an AV quarantine; ACCESS_DENIED (5) or a
                # bad image (193) with the file still present means an AV /
                # file-ACL lock — elevating any of those would only produce a
                # pointless UAC dialog that fails again inside the elevated
                # cmd.exe, so they are reported honestly instead.
                winerror = getattr(exc, "winerror", None)
                errno = getattr(exc, "errno", None)
                if winerror == 740 or errno == 740:
                    return ("elevate", None, "")
                if isinstance(exc, FileNotFoundError) or not os.path.isfile(exe):
                    msg = ("Файл winws.exe отсутствует или заблокирован антивирусом. "
                           "Проверьте карантин антивируса и повторно включите Zapret, "
                           "чтобы файлы были скачаны заново.")
                    logger.warning("winws launch failed and %s is missing (AV quarantine?): %s", exe, exc)
                    return ("failed", None, msg)
                msg = (f"Не удалось запустить winws.exe: {exc}. Файл на месте, но "
                       "Windows отказала в запуске — проверьте антивирус и права "
                       "доступа к файлу. См. лог zapret.log.")
                logger.warning("winws launch failed for %s (winerror=%s): %s",
                               exe, winerror, exc)
                return ("failed", None, msg)

            # BUG-023: bind the non-elevated child to a kill-on-close Job
            # Object so winws can never outlive this process (crash, kill,
            # missed cleanup). ShellExecuteW children cannot be assigned —
            # documented limitation for the elevated path.
            self._close_job_handle()
            job = _win32_create_kill_on_close_job()
            if job is not None:
                if _win32_assign_process_to_job(job, int(self.process._handle)):
                    self._job_handle = job
                else:
                    _win32_close_handle(job)
                    logger.warning("Could not assign winws.exe to the lifecycle Job Object; "
                                   "it may survive a NeDotify crash")

            self._write_pidfile(self.process.pid, uid=uid)
            # A real child now exists: any earlier "launched but PID unknown"
            # presumption is superseded by hard evidence (BUG-040).
            self._elevation_pid_unknown = False
            # Fast path (BUG-025): catch an instant exit under the lock so the
            # elevation branch can trigger immediately. The extended survival
            # window runs outside the lock in _confirm_launch.
            for _ in range(2):
                time.sleep(0.3)
                if self.process.poll() is not None:
                    rc = self.process.poll()
                    self.process = None
                    self._close_log_handle()
                    self._close_job_handle()
                    self._clear_pidfile()
                    tail = self._read_log_tail()
                    if self._looks_like_elevation_needed(tail):
                        return ("elevate", None, "")
                    self._clear_cmd_file()
                    msg = self._analyze_crash(tail)
                    if rc is not None:
                        msg = f"{msg} Код завершения: {rc}"
                    return ("failed", None, msg)
            return ("started", self.process, "")

        # Non-Windows
        try:
            self._open_log_handle()
            args_list = [exe] + sanitize_zapret_args(raw_args)
            self.process = subprocess.Popen(
                args_list,
                stdout=subprocess.DEVNULL,
                stderr=self._log_handle or subprocess.DEVNULL
            )
            self._write_pidfile(self.process.pid, uid=uid)
            self._elevation_pid_unknown = False
            return ("started", self.process, "")
        except Exception as e:
            self._close_log_handle()
            self._clear_pidfile()
            self._clear_cmd_file()
            return ("failed", None, str(e))

    def _confirm_launch(self, proc, gen: int) -> Tuple[bool, str]:
        """Confirm the child survived its first seconds (BUG-025).

        The in-lock fast path already caught an instant exit; this window
        polls a few more times over ~2s WITHOUT holding the state lock. A
        crash inside the window fails the start synchronously and emits
        'zapret_crashed'; a later crash is reported by _watch_child_lifecycle.
        A stop/start arriving mid-window cancels this epoch silently — the
        newer command owns the outcome.
        """
        deadline = time.monotonic() + max(0.0, float(self._launch_confirm_window))
        rc = None
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            if time.monotonic() >= deadline:
                with self._lock:
                    if gen != self._generation:
                        return False, _START_CANCELLED_MSG
                    self._state = _STATE_RUNNING
                return True, "Zapret активен"
            time.sleep(0.25)

        # The child died inside the confirmation window.
        with self._lock:
            if gen != self._generation:
                return False, _START_CANCELLED_MSG
            if self.process is proc:
                # Only tear down handles we still own: a newer epoch may have
                # already launched its own child with its own log/job handles.
                self.process = None
                self._close_log_handle()
                self._close_job_handle()
            self._clear_pidfile()
            self._clear_cmd_file()
            self._last_args = ""
            self._state = _STATE_STOPPED
        tail = self._read_log_tail()
        msg = self._analyze_crash(tail)
        if rc is not None:
            msg = f"{msg} Код завершения: {rc}"
        logger.warning("Zapret exited during the launch confirmation window: %s", msg)
        with self._lock:
            if gen != self._generation:
                return False, _START_CANCELLED_MSG
        self._emit_event("zapret_crashed", {"message": msg, "returncode": rc, "late": False})
        return False, msg

    def _watch_child_lifecycle(self, proc, gen: int) -> None:
        """Report a LATE crash — an exit after start() already returned success.

        Runs on a daemon thread parked in proc.wait(); intentional stops (a
        newer generation) stay silent. An unexpected exit re-syncs the state
        machine and raises 'zapret_crashed' through the event hook so the UI
        can react long after the toggle returned (BUG-025)."""
        try:
            proc.wait()
        except Exception:
            return
        with self._lock:
            cancelled = gen != self._generation or self._state in (_STATE_STOPPING, _STATE_STOPPED)
            if cancelled:
                return  # A newer command owns this process and its state files.
            if self.process is proc:
                self.process = None
                self._close_log_handle()
                self._close_job_handle()
                self._clear_pidfile()
                self._clear_cmd_file()
                self._last_args = ""
            if not cancelled:
                self._state = _STATE_STOPPED
                self._status_cache = None
                self._status_cache_time = 0.0
                self._status_epoch += 1
        if cancelled:
            return
        tail = self._read_log_tail()
        msg = self._analyze_crash(tail)
        logger.warning("Zapret process exited unexpectedly: %s", msg)
        self._emit_event("zapret_crashed", {
            "message": msg, "returncode": getattr(proc, "returncode", None), "late": True})

    def _ensure_lifecycle_watcher(self) -> None:
        """Rearm the lifecycle watcher for either a child or detached PID."""
        with self._lock:
            if self._state != _STATE_RUNNING:
                return
            proc = self.process
            identity = proc if proc is not None else self._read_pidfile()
            key = (identity, self._generation)
            if identity is None or self._lifecycle_watch_key == key:
                return
            self._lifecycle_watch_key = key
            threading.Thread(
                target=self._watch_child_lifecycle if proc is not None else self._watch_elevated_lifecycle,
                args=key, name="ZapretLifecycleWatch", daemon=True).start()

    def _watch_elevated_lifecycle(self, pid: int, gen: int) -> None:
        """Resync the UI when the elevated process exits after PID discovery."""
        record = self._read_pidfile_record() or {}
        timestamps = record.get('created')
        created = timestamps.get(str(pid)) if isinstance(timestamps, dict) else None
        while True:
            with self._lock:
                if gen != self._generation or self._state != _STATE_RUNNING:
                    return
            alive = self._pid_alive(pid)
            if alive and created:
                current = self._get_process_creation_time(pid)
                alive = current is None or current == created
            if not alive:
                break
            time.sleep(0.5)
        with self._lock:
            if gen != self._generation or self._state != _STATE_RUNNING:
                return
            survivors = [other for other in self._record_pids(record)
                         if other != pid and self._pid_alive(other) and self._is_our_winws_process(other)]
            if survivors:
                self._write_pidfile(survivors[0], pids=survivors, uid=record.get('uid', ''))
                self._status_cache = None
                self._status_epoch += 1
                self._ensure_lifecycle_watcher()
                return
            self._state = _STATE_STOPPED
            self._clear_pidfile()
            self._clear_cmd_file()
            self._last_args = ""
            self._status_cache = None
            self._status_cache_time = 0.0
            self._status_epoch += 1
        self._emit_event("zapret_crashed", {
            "message": self._analyze_crash(self._read_log_tail()),
            "returncode": None, "late": True})

    def set_event_callback(self, callback) -> None:
        """Register the UI event hook, e.g. for late-crash reports (BUG-025).

        The service never imports the api layer: AppApi installs a callable
        receiving ``(event_name, payload)`` and translates it into a bridge
        event (currently 'zapret_crashed')."""
        self._event_callback = callback

    def _emit_event(self, event_name: str, payload: Dict[str, Any]) -> None:
        callback = self._event_callback
        if not callback:
            return
        try:
            callback(event_name, payload)
        except Exception:
            logger.debug("Zapret event callback failed for %s", event_name, exc_info=True)

    def _close_job_handle(self) -> None:
        """Close the kill-on-close Job Object handle.

        While the child lives the handle must stay open (closing is what
        triggers the kill); on stop/crash paths closing it also kills any
        child that survived terminate() — exactly the wanted fallback."""
        job, self._job_handle = self._job_handle, None
        if job:
            _win32_close_handle(job)

    def _set_elevation_window(self, hwnd_provider):
        """Resolve the current UI owner only when an elevation is requested."""
        with self._lock:
            self._elevation_hwnd_provider = hwnd_provider

    def _shell_execute_elevated(self, exe: str, params: str, cwd: str) -> int:
        """Keep an initially visible player visible when returning from UAC.

        SW_HIDE belongs to the elevated console, not to the player. Supply an
        explicit owner and recover a hidden player after the secure desktop
        returns. A player already hidden in the tray or minimized stays so.
        """
        import ctypes
        from ctypes import wintypes

        with self._lock:
            provider = self._elevation_hwnd_provider
        user32 = ctypes.windll.user32
        owner = None
        was_visible = False
        try:
            owner = provider() if provider else None
            if owner:
                owner = wintypes.HWND(int(owner))
                # BUG-048: the window can be destroyed between the provider
                # call and ShellExecuteW; a dead HWND must not reach the call
                # as the UAC owner. Re-validate right before invoking.
                if not user32.IsWindow(owner):
                    logger.debug(
                        "UAC owner HWND %s is no longer valid; continuing without owner",
                        owner.value)
                    owner = None
                else:
                    was_visible = bool(user32.IsWindowVisible(owner)) and not user32.IsIconic(owner)
        except Exception:
            logger.debug("Cannot resolve UAC window owner", exc_info=True)
            owner = None

        shell_execute = ctypes.windll.shell32.ShellExecuteW
        shell_execute.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
        shell_execute.restype = ctypes.c_ssize_t
        try:
            return shell_execute(owner, "runas", exe, params, cwd, 0)
        finally:
            if was_visible and owner:
                try:
                    # Do not revive a destroyed/replaced window, or undo a
                    # minimize performed while elevation was in progress.
                    if (provider() == owner.value and user32.IsWindow(owner)
                            and not user32.IsWindowVisible(owner)
                            and not user32.IsIconic(owner)):
                        user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
                        user32.ShowWindowAsync.restype = wintypes.BOOL
                        user32.ShowWindowAsync(owner, 8)  # SW_SHOWNA: retain size/state
                        logger.warning("Restored player window hidden during Zapret UAC")
                except Exception:
                    logger.warning("Could not restore player window after UAC", exc_info=True)

    def _launch_elevated(self, exe: str, raw_args: str) -> Tuple[bool, str]:
        """Coordinate UAC, PID discovery by scanning, and stale-launch cleanup."""
        with self._lock:
            launch_gen = self._elevation_inflight
            if launch_gen is None:
                launch_gen = self._generation
                self._elevation_inflight = launch_gen
                self._elevation_dispatched = False
        try:
            with self._lock:
                if launch_gen != self._generation:
                    return False, _START_CANCELLED_MSG
            ok, message = self._launch_elevated_attempt(exe, raw_args)
            with self._lock:
                stale = launch_gen != self._generation
            if stale:
                if ok:
                    stopped, stop_message = self._stop_impl(bump_generation=True, allow_elevation=True)
                    if not stopped:
                        return False, stop_message
                return False, _START_CANCELLED_MSG
            return ok, message
        except Exception:
            logger.exception('Elevated Zapret launch or PID discovery failed')
            return False, 'Не удалось подтвердить запуск Zapret. Проверьте PID winws.exe перед повторным включением.'
        finally:
            with self._lock:
                if not self._elevation_dispatched:
                    self._elevation_pid_unknown = False
                self._elevation_inflight = None

    def _launch_elevated_attempt(self, exe: str, raw_args: str) -> Tuple[bool, str]:
        """Elevation required (WinError 740 / missing rights) — use ShellExecuteW 'runas'.
        Launches an elevated cmd.exe that redirects winws stdout/stderr to zapret.log (AUDIT #05),
        in APPEND mode (BUG-028) so a launch never truncates the previous session's log.
        The elevated child cannot be assigned to the kill-on-close Job Object and
        cannot be adopted through a Popen handle, so its PID is discovered by
        scanning (cmdline signature first, then exe-path ownership) and recorded
        in run.pid together with this instance's uid (BUG-047 fallback)."""
        logger.info("Elevating Zapret via ShellExecuteW 'runas'...")
        # Each elevation attempt starts with no presumption: the flag is only
        # raised when THIS attempt dispatches and then fails to attribute a PID.
        with self._lock:
            self._elevation_pid_unknown = False

        if not validate_zapret_binary(exe, self.app_dir, extra_roots=[self.base_dir]):
            msg = f"Отказано в запуске: {os.path.basename(exe)} не является разрешённым исполняемым файлом Zapret."
            logger.error(msg)
            return False, msg
        if not _protected_elevation_path(exe):
            # BUG-001: a downloaded bundle in ~/.nedotify/zapret (user-writable
            # storage, TOCTOU) stays forbidden. The old message told the user
            # to install into Program Files — nothing in the app can do that.
            msg = ("Запуск Zapret с правами администратора разрешён только из "
                   "защищённого каталога установки (Program Files или каталог "
                   "установки NeDotify, подтверждённый установщиком). Сейчас файл "
                   f"находится в пользовательской папке: {os.path.dirname(exe)}. "
                   "Переустановите или обновите приложение NeDotify и повторите попытку.")
            logger.warning("Elevation denied for %s: not a verified installation root "
                           "(Program Files or installer-verified InstallLocation)", exe)
            return False, msg
        if any(character in str(path) for path in (exe, self.log_file)
               for character in ('%', '"', '\r', '\n')):
            return False, 'Путь Zapret или его журнала содержит символы, небезопасные для запуска через cmd.exe.'
        try:
            tokens = sanitize_zapret_args(raw_args)
        except ValueError as exc:
            logger.error("Refusing elevated launch with unsafe arguments: %s", exc)
            return False, str(exc)

        self._close_log_handle()
        # BUG-028: the elevated cmd.exe APPENDS to zapret.log; rotate here so
        # the Z-3 bound holds on the elevated path too. The log size is
        # remembered so the post-launch analysis below judges only what THIS
        # run wrote — a healthy winws is silent, and the tail of a previous
        # session would otherwise be misread as its crash.
        self._rotate_log_if_needed()
        try:
            log_offset = os.path.getsize(self.log_file) if os.path.exists(self.log_file) else 0
        except OSError:
            log_offset = 0
        params = subprocess.list2cmdline(tokens)
        import ctypes
        system_dir = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetSystemDirectoryW(system_dir, len(system_dir)):
            return False, 'Не удалось определить системный каталог Windows'
        comspec = os.path.join(system_dir.value, 'cmd.exe')
        cmd_params = f'/d /v:off /c ""{exe}" {params} >> "{self.log_file}" 2>&1"'

        with self._lock:
            self._elevation_dispatched = True
            self._elevation_pid_unknown = True
        ret = self._shell_execute_elevated(comspec, cmd_params, os.path.dirname(exe))
        if ret <= 32:
            with self._lock:
                self._elevation_dispatched = False
        if ret == 5:
            msg = "Запуск отменён: требуются права Администратора для драйвера WinDivert (UAC отклонён)."
            logger.warning(msg)
            return False, msg
        if ret <= 32:
            msg = f"Ошибка запуска с правами Администратора (код {ret}). См. лог zapret.log."
            logger.error(msg)
            return False, msg

        # Wait up to 5s for PID to appear in pidfile or via signature scan.
        # BUG-007: the deadline is re-checked BEFORE every sub-scan, not only
        # between loop iterations — one wmic/CIM/tasklist/PowerShell iteration
        # used to run up to ~17s past the deadline while the state lock was
        # held. (The scans themselves now also run outside the state lock.)
        pid = None
        deadline = time.time() + max(0.0, float(getattr(self, "_elevation_scan_window", 5.0)))
        while time.time() < deadline:
            file_pid = self._read_pidfile()
            if file_pid and self._pid_alive(file_pid) and self._is_our_winws_process(file_pid):
                pid = file_pid
                break
            if time.time() >= deadline:
                break
            pids = self._scan_pids_with(raw_args)
            for p in pids:
                if self._is_our_winws_process(p, raw_args, signature_verified=True):
                    pid = p
                    self._write_pidfile(pid, uid=getattr(self, "_known_uid", ""))
                    break
            if pid:
                break
            if time.time() >= deadline:
                break
            # Fallback across integrity boundary: if CommandLine is empty in WMI/CIM,
            # discover running winws.exe belonging to our app (AUDIT #04)
            all_winws = self._scan_all_winws_pids()
            for p in all_winws:
                if self._is_our_winws_process(p, raw_args):
                    pid = p
                    self._write_pidfile(pid, uid=getattr(self, "_known_uid", ""))
                    break
            if pid:
                break
            time.sleep(0.3)

        if pid:
            logger.info("Elevated winws.exe detected (PID %s)", pid)
            with self._lock:
                self._elevation_pid_unknown = False
            return True, "Zapret активен"

        # Check if an existing valid PID is still running — NEVER clear if alive
        existing_pid = self._read_pidfile()
        if existing_pid and self._pid_alive(existing_pid) and self._is_our_winws_process(existing_pid):
            with self._lock:
                self._elevation_pid_unknown = False
            return True, "Zapret активен (ранее запущен)"

        tail = self._read_log_tail(offset=log_offset)
        if not tail:
            # Dispatch is not proof of process liveness. Keep the duplicate
            # launch guard, but do not report success or turn the switch on.
            with self._lock:
                self._elevation_pid_unknown = True
            msg = ("Не удалось подтвердить запуск Zapret: PID не определён. "
                   "Проверьте winws.exe в диспетчере задач и перезапустите NeDotify "
                   "перед повторным включением, чтобы не запустить второй экземпляр.")
            logger.warning("Elevated launch dispatched (ret=%s) but PID discovery "
                           "failed; launch state is unknown", ret)
            return False, msg
        msg = self._analyze_crash(tail)
        logger.warning("Elevated launch failed; log analysis: %s", msg)
        return False, 'PID Zapret не подтверждён. ' + msg

    def stop(self) -> Tuple[bool, str]:
        """Stop only the Zapret process started by this app (Z-2).
        Never uses taskkill /IM — external winws processes are left untouched (AUDIT #03, #04).
        If termination fails, pidfile is preserved to prevent orphaned WinDivert driver lock.
        Every call opens a new STOPPING epoch (the generation counter arbitrates
        against in-flight starts, BUG-002/003)."""
        self._selection_cancel.set()
        try:
            return self._stop_impl(bump_generation=True)
        finally:
            with self._lock:
                self._status_cache = None
                self._status_cache_time = 0.0
                self._status_epoch += 1
            self._ensure_lifecycle_watcher()

    def stop_interactive(self) -> Tuple[bool, str]:
        """User-requested stop; may elevate termination of our verified PID."""
        self._selection_cancel.set()
        try:
            return self._stop_impl(bump_generation=True, allow_elevation=True)
        finally:
            with self._lock:
                self._status_cache = None
                self._status_cache_time = 0.0
                self._status_epoch += 1
            self._ensure_lifecycle_watcher()

    def _stop_impl(self, bump_generation: bool = True, *, allow_elevation: bool = False) -> Tuple[bool, str]:
        """Shared stop logic. ``bump_generation=False`` is for the internal
        restart path in start(): the running start IS the newest command and
        must not cancel itself."""
        if self._storage_unavailable:
            # Killing still works through the live Popen handle; the state
            # files cannot be maintained, so reporting stays degraded.
            logger.warning("Zapret stop with unavailable data directory: "
                           "pidfile/cmd tracking is degraded")
        with self._lock:
            if bump_generation:
                self._generation += 1
            stop_gen = self._generation
            self._state = _STATE_STOPPING
            # An in-flight wrapper may already have discovered and then
            # stopped its child. Only pre-dispatch or truly unresolved UAC
            # must retain the unknown guard; never resurrect it after stop.
            was_unknown = self._elevation_pid_unknown or (
                self._elevation_inflight is not None and not self._elevation_dispatched)
            self._elevation_pid_unknown = False
            if self.process:
                try:
                    self.process.terminate()
                except Exception:
                    logger.debug("stop: suppressed exception on process.terminate", exc_info=True)
                # terminate() is asynchronous: reap the child so the pidfile /
                # taskkill path below does not race a dying process.
                try:
                    self.process.wait(timeout=2.0)
                except Exception:
                    logger.debug("stop: child did not exit within 2s after terminate", exc_info=True)
                if self.process.poll() is not None:
                    self.process = None
            self._close_log_handle()

        guard = _global_zapret_guard_acquire()
        try:
            try:
                # A Popen handle is authoritative even if pidfile creation or
                # command-line discovery failed. Never discard a live child.
                with self._lock:
                    if stop_gen != self._generation:
                        return False, 'Остановка отменена новой командой Zapret'
                    child = self.process
                    self._close_job_handle()
                if child and child.poll() is None:
                    try:
                        child.kill()
                        child.wait(timeout=1.0)
                    except Exception:
                        logger.debug('Child survived the stop fallback', exc_info=True)
                    if child.poll() is None:
                        with self._lock:
                            self._state = _STATE_RUNNING
                        return False, f'Не удалось остановить дочерний процесс Zapret (PID {child.pid}). Повторите остановку.'
                    with self._lock:
                        if self.process is child:
                            self.process = None
                record = self._read_pidfile_record()
                pid = self._read_pidfile()
                target_pids = set()
                # BUG-046: the pidfile may carry several live PIDs after a
                # previously partial stop — every one of them is a target.
                for known in self._record_pids(record):
                    if known and self._pid_alive(known) and self._is_our_winws_process(known):
                        target_pids.add(known)

                # Fallback: kill only processes matching our cmdline signature (elevated case).
                # Skipped when the pidfile already yielded live targets: every
                # launched PID is recorded there (BUG-046 keeps survivors, the
                # elevated discovery writes its PID), the kill-on-close Job
                # Object covers untracked Popen children, and the WMI scan
                # costs ~10s — enough to blow the shutdown's bounded-stop
                # budget on every single exit. When the pidfile yields nothing
                # (elevated discovery failed, BUG-040), the scan still runs.
                signature = self._last_args or self._read_cmd_file()
                if signature and not target_pids:
                    for p in self._scan_pids_with(signature):
                        # p matched the signature in this very scan: skip the
                        # redundant second WMI pass inside the ownership check.
                        if self._pid_alive(p) and self._is_our_winws_process(
                                p, signature, signature_verified=True):
                            target_pids.add(p)

                # If no active target PIDs found:
                if was_unknown and not target_pids:
                    with self._lock:
                        self._elevation_pid_unknown = True
                        self._state = _STATE_STOPPED
                    return False, ("PID Zapret не определён — остановка не подтверждена. "
                                   "Проверьте winws.exe в диспетчере задач перед перезапуском NeDotify.")

                if not target_pids:
                    if pid and not self._pid_alive(pid):
                        self._clear_pidfile()
                    self._clear_cmd_file()
                    self._last_args = ""
                    with self._lock:
                        self._state = _STATE_STOPPED
                    if self._state_write_failed:
                        # BUG-015: a failed state write may have left a process
                        # invisible to the pidfile/signature tracking; a plain
                        # "stopped" would be a guess, not a fact.
                        msg = ("Zapret остановлен, но запись состояния процесса не удалась — "
                               "проверьте диспетчер задач: если winws.exe продолжает работать, "
                               "остановите его вручную.")
                        logger.warning(msg)
                        return True, msg
                    return True, "Zapret остановлен"

                failed_pids = []
                for p in sorted(target_pids):
                    if self._pid_alive(p):
                        killed = (self._kill_pid(p, allow_elevation=True) if allow_elevation
                                  else self._kill_pid(p))
                        if not killed or self._pid_alive(p):
                            failed_pids.append(p)

                if failed_pids:
                    # DO NOT clear pidfile if any process is still alive!
                    # BUG-046: store EVERY surviving PID (the old code kept
                    # only failed_pids[0], losing the rest), keeping the
                    # previous primary when it is among the survivors.
                    previous_primary = record.get("pid") if record else None
                    primary = previous_primary if previous_primary in failed_pids else failed_pids[0]
                    self._write_pidfile(primary, pids=failed_pids,
                                        uid=(record or {}).get("uid", ""))
                    msg = (
                        f"Не удалось остановить процесс Zapret (PID {', '.join(str(x) for x in failed_pids)}). "
                        f"Возможно, требуются права Администратора для остановки elevated winws.exe. "
                        f"Pidfile сохранён для предотвращения утечки драйвера WinDivert."
                    )
                    logger.warning(msg)
                    with self._lock:
                        # BUG-009: the process is factually still running — the
                        # state machine must say so instead of pretending.
                        self._state = _STATE_RUNNING
                    return False, msg

                # All target processes successfully terminated
                self._clear_pidfile()
                self._clear_cmd_file()
                self._last_args = ""
                logger.info("Zapret process stopped successfully (own PID only)")
                with self._lock:
                    self._state = _STATE_STOPPED
                return True, "Zapret остановлен"
            except Exception as e:
                logger.error("Zapret stop error: %s", e, exc_info=True)
                pid = self._read_pidfile()
                if pid and self._pid_alive(pid) and self._is_our_winws_process(pid):
                    with self._lock:
                        self._state = _STATE_RUNNING
                    return False, f"Ошибка при остановке Zapret: {e}"
                self._clear_pidfile()
                self._clear_cmd_file()
                self._last_args = ""
                with self._lock:
                    self._state = _STATE_STOPPED
                return False, f"Ошибка при остановке Zapret: {e}"
        finally:
            # The kill-on-close job outlives the child but never the stop
            # request: closing it also kills a child that survived terminate()
            # — the last-resort fallback (BUG-023).
            with self._lock:
                if stop_gen == self._generation:
                    self._close_job_handle()
            _global_zapret_guard_release(guard)

    # ─── status (Z-5: instant via cache, refreshed in background) ───

    def get_status(self) -> Dict[str, Any]:
        """Return cached status instantly; refresh happens in background."""
        # BUG-042: monotonic stamp — immune to backward wall-clock jumps that
        # used to pin a stale cache (see the __init__ comment for the full
        # sleep/hibernation decision).
        now = time.monotonic()
        with self._lock:
            if self._status_cache and (now - self._status_cache_time) < self._status_ttl:
                return dict(self._status_cache)
            if self._status_cache is None:
                self._status_cache = {
                    "binary_found": False,
                    "binary_path": "",
                    "running": False,
                    "has_internet": True,
                    "version": "",
                    "message": "Определение статуса...",
                    "pending_update": ""
                }
            result = dict(self._status_cache)
        self._refresh_status_async()
        return result

    def _refresh_status_async(self):
        with self._lock:
            if self._status_thread and self._status_thread.is_alive():
                return
            self._status_thread = threading.Thread(target=self._build_status, daemon=True)
            self._status_thread.start()

    def _track_network_state(self, running: bool, has_net: bool, snapshot=None) -> None:
        """BUG-036: emit 'zapret_network_issue' ONCE per True->False transition.

        Fires only while the bypass is running and only on the transition
        working -> broken, so a long outage does not spam the UI. The UI can
        use it to offer a strategy restart.

        Deliberately NOT done here (documented decision): no automatic winws
        restart and no adapter-change listener (NetworkAddressChanged). A
        network flap would then bounce a machine-wide WinDivert driver and
        kill a session the user is actively using; the status message plus
        this one-shot event leave the decision to the user. A restarted
        strategy re-resolves the current adapter anyway on the next launch.
        """
        with self._lock:
            if snapshot is not None and snapshot != (self._generation, self._status_epoch):
                return
            previous = self._last_network_ok
            if not running:
                # Nothing to watch while stopped; the next start re-arms the
                # tracker from a clean slate.
                self._last_network_ok = None
                return
            self._last_network_ok = bool(has_net)
        if previous is True and not has_net:
            msg = ("Zapret запущен, но подключение к интернету потеряно. "
                   "Если сменилась сеть или адаптер — выключите и включите "
                   "Zapret, чтобы применить стратегию к новому интерфейсу.")
            logger.warning("Running Zapret lost connectivity; emitting zapret_network_issue")
            self._emit_event("zapret_network_issue", {"message": msg, "running": running})

    def _build_status(self):
        with self._lock:
            snapshot = (self._generation, self._status_epoch)
        try:
            exe = self.find_binary()
            running = self.is_running()
            has_net = check_internet() if running else True
            # BUG-036: one-shot transition event; must run before anything can
            # fail below so a lost network is reported even if the rest of the
            # build throws.
            cur_version = self.get_local_version()
            pending = self._get_pending_update()

            if self._elevation_pid_unknown:
                message = ("Состояние Zapret неизвестно: PID не определён. "
                           "Проверьте winws.exe в диспетчере задач перед перезапуском NeDotify.")
            elif not exe:
                message = "Файл winws.exe не найден. Нажмите 'Обновить Zapret'."
            elif not running:
                message = "Zapret отключен"
            elif pending:
                if pending == ZAPRET_VERSION:
                    message = f"Доступно обновление {pending} (применится при следующем запуске)"
                else:
                    # BUG-004: a pending tag this build cannot install (no
                    # trusted SHA-256) must not promise an automatic apply —
                    # the application itself has to be updated first.
                    message = f"Доступна версия Zapret {pending} — для установки обновите приложение NeDotify"
            elif not has_net:
                message = "Zapret запущен, но нет подключения к интернету"
            else:
                # BUG-037: the process being up does not prove the bypass
                # works, so the message no longer claims «Zapret активен».
                # A single covered-host probe refines it: reachability of an
                # in-hostlist host is the closest cheap signal available
                # without asserting desync success (which is unprovable
                # statically and here). None (probe could not run) stays
                # neutral — neither reachable nor broken is claimed.
                covered_ok = _probe_covered_host()
                if covered_ok is True:
                    message = (f"Zapret запущен ({cur_version}); домены приложения "
                               "отвечают. Реальный обход DPI видно только вживую")
                elif covered_ok is False:
                    message = (f"Zapret запущен ({cur_version}), но домены "
                               "приложения не отвечают — возможно, обход "
                               "не работает или сайт недоступен")
                else:
                    message = (f"Zapret запущен ({cur_version}). "
                               "Реальный обход DPI видно только вживую")

            status = {
                "binary_found": bool(exe),
                "binary_path": exe or "",
                "running": running,
                "state_unknown": self._elevation_pid_unknown,
                "has_internet": has_net,
                "version": cur_version,
                "message": message,
                "pending_update": pending
            }
            with self._lock:
                if snapshot != (self._generation, self._status_epoch):
                    return
                self._status_cache = status
                self._status_cache_time = time.monotonic()
            self._track_network_state(running, has_net, snapshot=snapshot)
        except Exception as e:
            logger.debug("Zapret status refresh error: %s", e)
            # BUG-041: this path used to patch only two keys onto whatever the
            # cache held (possibly the empty dict), yielding a status without
            # binary_found/version/pending_update. Consumers key off those
            # fields, so rebuild from the full template and only carry over
            # what a previous build actually knew.
            with self._lock:
                if snapshot != (self._generation, self._status_epoch):
                    return
                previous = self._status_cache if isinstance(self._status_cache, dict) else {}
                try:
                    running = self.is_running()
                except Exception:
                    running = False
                self._status_cache = {
                    "binary_found": bool(previous.get("binary_found", False)),
                    "binary_path": str(previous.get("binary_path") or ""),
                    "running": running,
                    "has_internet": bool(previous.get("has_internet", True)),
                    "version": str(previous.get("version") or ""),
                    "message": "Ошибка определения статуса",
                    "pending_update": str(previous.get("pending_update") or ""),
                }
                self._status_cache_time = time.monotonic()
