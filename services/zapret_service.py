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
"""

import csv
import io
import logging
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from typing import Dict, Any, Tuple, List, Optional, Set

logger = logging.getLogger(__name__)

ZAPRET_VERSION = "v72.13"
ZAPRET_ZIP_URL = f"https://github.com/bol-van/zapret/releases/download/{ZAPRET_VERSION}/zapret-{ZAPRET_VERSION}.zip"
# SHA-256 of the pinned release archive, verified before extraction.
# If it ever mismatches, the bundle is refused (no extraction, no launch).
ZAPRET_ZIP_SHA256 = "c493e33a0dc4eba23a8686efdaba55f59755ad6ade3564aebd9d13f4c65e2e0c"


def _verify_zip_sha256(zip_bytes: bytes, expected_sha256: str = ZAPRET_ZIP_SHA256) -> bool:
    """Constant-time SHA-256 check of a downloaded zip archive."""
    import hashlib
    import hmac
    if not expected_sha256:
        return True  # No pinned hash — verification not possible
    digest = hashlib.sha256(zip_bytes).hexdigest()
    return hmac.compare_digest(digest, expected_sha256)

PRESET_STRATEGIES = {
    "youtube_discord": "--wf-tcp=80,443 --filter-tcp=80,443 --dpi-desync=fake,split2 --dpi-desync-split-pos=1 --dpi-desync-repeats=6 --dpi-desync-fooling=badseq",
    "standard": "--wf-tcp=80,443 --filter-tcp=80,443 --dpi-desync=fake,split2 --dpi-desync-split-pos=1 --dpi-desync-repeats=4 --dpi-desync-fooling=badseq",
    "aggressive": "--wf-tcp=80,443 --filter-tcp=80,443 --dpi-desync=disorder2 --dpi-desync-split-pos=1 --dpi-desync-fooling=badseq",
    "multisplit": "--wf-tcp=80,443 --filter-tcp=80,443 --dpi-desync=fake,multisplit --dpi-desync-split-pos=1,5 --dpi-desync-repeats=6 --dpi-desync-fooling=badseq"
}

# Security: winws arguments reach an ELEVATED process, so every token is validated
# against this grammar before it is ever passed to ShellExecuteW. Anything outside
# it (quotes, semicolons, ampersands, backticks, pipes, redirects) is rejected.
_ALLOWED_ARG_RE = re.compile(r'^--[A-Za-z0-9][A-Za-z0-9\-]*(=[A-Za-z0-9,.:_/\-\\ ]*)?$')

# Only these executable names may ever be launched, elevated or not.
_ALLOWED_BINARY_NAMES = frozenset({"winws.exe", "zapret.exe", "winws"})


def sanitize_zapret_args(raw_args: str) -> List[str]:
    """Split and validate winws arguments. Raises ValueError on anything unsafe.

    Returns the validated token list. Callers must pass this list to Popen or
    join it with subprocess.list2cmdline — never interpolate raw_args into a shell
    or PowerShell command string.
    """
    if not raw_args:
        return []
    try:
        tokens = shlex.split(raw_args, posix=(sys.platform != "win32"))
    except ValueError as exc:
        raise ValueError(f"Не удалось разобрать аргументы: {exc}") from exc
    for tok in tokens:
        if not _ALLOWED_ARG_RE.match(tok):
            raise ValueError(f"Недопустимый аргумент Zapret: {tok!r}")
    return tokens


def validate_zapret_binary(path: str) -> bool:
    """True only for an existing file whose name is an approved winws binary."""
    if not path:
        return False
    try:
        if not os.path.isfile(path):
            return False
    except OSError:
        return False
    return os.path.basename(path).lower() in _ALLOWED_BINARY_NAMES


# Z-4: internet probe hosts — TCP-connect to port 443, first success = online.
INTERNET_CHECK_HOSTS = ["ya.ru", "gosuslugi.ru", "77.88.8.8", "8.8.8.8"]


def _check_output_text(cmd, timeout: float, shell: bool = False) -> str:
    """subprocess.check_output that never dies on console codepages.

    Windows console tools (tasklist / wmic / powershell) emit OEM codepage
    output (CP866 on Russian systems: session name «Консоль», Cyrillic exe
    paths). With text=True the strict UTF-8 reader thread crashes and
    check_output silently returns nothing, disabling every PID scan below.
    All match targets in this module are ASCII (winws.exe, PIDs, validated
    --args), so a lenient replace-decode is sufficient and locale-proof.
    """
    try:
        out = subprocess.check_output(cmd, shell=shell, stderr=subprocess.DEVNULL, timeout=timeout)
        return out.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("subprocess scan failed (%r): %s", cmd, e)
        return ""


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


class ZapretService:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager
        self.process = None
        self._log_handle = None
        self._lock = threading.RLock()
        # Z-8: serializes download/update work (network fetch + binary extraction)
        # so a background auto-update can never race start()'s auto-download or a
        # second concurrent update writing the same winws.exe files.
        self._update_lock = threading.Lock()
        self._last_args = ""

        self.app_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "zapret")
        self.logs_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "logs")
        os.makedirs(self.app_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

        # Z-2: pidfile identity + cmdline signature snapshot
        self.pid_file = os.path.join(self.app_dir, "run.pid")
        self.cmd_file = os.path.join(self.app_dir, "run.cmd")
        # Z-3: stderr log of the winws process
        self.log_file = os.path.join(self.logs_dir, "zapret.log")

        # Z-5: status cache (built in background, never blocks get_status)
        self._status_cache: Dict[str, Any] = None
        self._status_cache_time = 0.0
        self._status_ttl = 2.5
        self._status_thread = None

    # ─── pidfile & process identity helpers (Z-2) ───

    def _write_pidfile(self, pid: int):
        try:
            with open(self.pid_file, "w", encoding="utf-8") as f:
                f.write(str(pid))
        except Exception as e:
            logger.debug("Failed to write pidfile: %s", e)

    def _read_pidfile(self) -> int | None:
        try:
            if not os.path.exists(self.pid_file):
                return None
            with open(self.pid_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    val = int(content)
                    return val if val > 0 else None
                return None
        except Exception:
            return None

    def _clear_pidfile(self):
        try:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
        except Exception:
            logger.debug("_clear_pidfile: suppressed exception", exc_info=True)

    def _write_cmd_file(self, raw_args: str):
        try:
            with open(self.cmd_file, "w", encoding="utf-8") as f:
                f.write(raw_args or "")
        except Exception:
            logger.debug("_write_cmd_file: suppressed exception", exc_info=True)

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
        """Liveness check of a PID without spawning subprocesses (Z-5)."""
        if not pid or pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259
                ERROR_ACCESS_DENIED = 5
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not handle:
                    err = kernel32.GetLastError()
                    if err == ERROR_ACCESS_DENIED:
                        return True
                    return False
                try:
                    code = ctypes.c_ulong()
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                        return code.value == STILL_ACTIVE
                    return False
                finally:
                    kernel32.CloseHandle(handle)
            except Exception:
                logger.debug("_pid_alive: suppressed exception", exc_info=True)
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except (OSError, ProcessLookupError):
            return False
        except Exception:
            return False

    def _is_winws_process(self, pid: int | None) -> bool:
        """Verify that the process with the given PID is winws.exe, zapret.exe, or winws.
        Prevents operating on reused or foreign PIDs.
        """
        if not pid or pid <= 0:
            return False
        if sys.platform == "win32":
            # Primary check: QueryFullProcessImageNameW via kernel32
            try:
                import ctypes
                from ctypes import wintypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if hasattr(kernel32, "QueryFullProcessImageNameW") and kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
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
            try:
                import ctypes
                from ctypes import wintypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if hasattr(kernel32, "QueryFullProcessImageNameW") and kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
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

    def _is_our_winws_process(self, pid: int | None, signature: str = "") -> bool:
        """Verify that the process with the given PID is winws.exe AND belongs to this application.
        Prevents adopting or terminating foreign winws.exe processes (AUDIT #04).
        """
        if not pid or pid <= 0 or not self._pid_alive(pid):
            return False
        if not self._is_winws_process(pid):
            return False

        # 1. Verify executable path matches our app directory or binary path
        exe_path = self._get_process_exe_path(pid)
        if exe_path:
            norm_exe = os.path.normcase(os.path.abspath(exe_path))
            our_bin = self.find_binary()
            if our_bin and norm_exe == os.path.normcase(os.path.abspath(our_bin)):
                return True
            app_dir_norm = os.path.normcase(os.path.abspath(self.app_dir))
            if norm_exe.startswith(app_dir_norm):
                return True
            cwd_norm = os.path.normcase(os.path.abspath(os.getcwd()))
            if norm_exe.startswith(cwd_norm):
                return True
            # Executable path is known and does NOT belong to our app
            return False

        # 2. Check launch command line signature if available
        if signature:
            matching = self._scan_pids_with(signature)
            if pid in matching:
                return True

        # 3. Fallback: check if it matches our own saved PID from pidfile
        saved_pid = self._read_pidfile()
        if saved_pid and saved_pid == pid:
            return True

        return False

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

    def _kill_pid(self, pid: int) -> bool:
        """Kill exactly one PID via taskkill with IMAGENAME filter (graceful first, /F fallback).
        MUST verify process image name is an approved winws executable before terminating (AUDIT #03).
        """
        if not pid or pid <= 0:
            return False
        if not self._pid_alive(pid):
            return True
        if not self._is_winws_process(pid):
            logger.warning(
                "Refusing to kill PID %s: process image is not winws.exe (prevented foreign PID termination)",
                pid
            )
            return False

        try:
            if sys.platform == "win32":
                subprocess.run(
                    f'taskkill /FI "IMAGENAME eq winws*" /PID {pid}',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0
                )
                deadline = time.time() + 1.5
                while time.time() < deadline:
                    if not self._pid_alive(pid):
                        return True
                    time.sleep(0.15)

                subprocess.run(
                    f'taskkill /F /FI "IMAGENAME eq winws*" /PID {pid}',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0
                )
                time.sleep(0.2)
                if not self._pid_alive(pid):
                    return True

                # If still alive (e.g. elevated winws started under admin rights), try elevated taskkill
                try:
                    import ctypes
                    ret = ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", "taskkill.exe", f'/F /FI "IMAGENAME eq winws*" /PID {pid}', None, 0
                    )
                    if ret > 32:
                        elev_deadline = time.time() + 2.0
                        while time.time() < elev_deadline:
                            if not self._pid_alive(pid):
                                return True
                            time.sleep(0.2)
                except Exception as e_elev:
                    logger.debug("Elevated taskkill attempt failed for PID %s: %s", pid, e_elev)
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

    def find_binary(self, custom_path=None) -> str | None:
        """Find path to winws.exe, zapret.exe or winws binary."""
        if custom_path:
            if validate_zapret_binary(custom_path):
                return custom_path
            logger.warning("Rejected binary_path %r: not an approved winws executable", custom_path)

        candidates = [
            os.path.join(self.app_dir, "winws.exe"),
            os.path.join(self.app_dir, "zapret.exe"),
            os.path.join(self.app_dir, "bin", "winws.exe"),
            os.path.join(os.getcwd(), "bin", "winws.exe"),
            os.path.join(os.getcwd(), "zapret", "winws.exe")
        ]

        for c in candidates:
            if os.path.exists(c):
                return c

        return None

    # ─── liveness (Z-5) ───

    def is_running(self) -> bool:
        """Fast check: own Popen handle, saved pidfile PID, or running winws process."""
        with self._lock:
            if self.process and self.process.poll() is None:
                return True
        pid = self._read_pidfile()
        if pid and self._pid_alive(pid) and self._is_our_winws_process(pid):
            return True
        signature = self._last_args or self._read_cmd_file()
        if signature:
            pids = self._scan_pids_with(signature)
            for p in pids:
                if self._is_our_winws_process(p, signature):
                    self._write_pidfile(p)
                    return True
        # Fallback: only check winws processes verified to belong to our application (AUDIT #04)
        all_winws = self._scan_all_winws_pids()
        if all_winws and (self._read_cmd_file() or self._last_args):
            for p in all_winws:
                if self._is_our_winws_process(p, signature):
                    self._write_pidfile(p)
                    return True
        return False

    # ─── stderr log & crash analysis (Z-3) ───

    def _open_log_handle(self):
        self._close_log_handle()
        try:
            # Repeated launches append forever; rotate once past 1 MiB so the
            # log stays bounded while keeping the previous chunk as *.old.
            try:
                if os.path.exists(self.log_file) and os.path.getsize(self.log_file) > 1024 * 1024:
                    os.replace(self.log_file, self.log_file + ".old")
            except OSError:
                logger.debug("zapret.log rotation failed", exc_info=True)
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

    def _read_log_tail(self, max_lines: int = 12) -> List[str]:
        try:
            if not os.path.exists(self.log_file):
                return []
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return [l.rstrip() for l in lines[-max_lines:] if l.strip()]
        except Exception:
            return []

    def _looks_like_elevation_needed(self, tail: List[str]) -> bool:
        text = " ".join(tail).lower()
        return any(k in text for k in (
            "access denied", "elevat", "permission", "error 5", "winerror 5",
            "недостаточно прав", "админ", "admin"
        ))

    def _analyze_crash(self, tail: List[str]) -> str:
        text = " ".join(tail).lower()
        if self._looks_like_elevation_needed(tail):
            return "Нет прав администратора (UAC отклонён). См. лог zapret.log."
        if "windivert" in text or "wfp" in text:
            if any(k in text for k in ("busy", "in use", "bound", "already", "занят")):
                return "Драйвер WinDivert занят другим процессом. См. лог zapret.log."
            return "Не удалось загрузить драйвер WinDivert. См. лог zapret.log."
        return "winws.exe завершился с ошибкой (краш). См. лог zapret.log."

    # ─── download / update (Z-7/8: outside the state lock) ───

    def _download_zip(self, url: str, timeout: float = 40.0) -> bytes:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _extract_zip(self, zip_bytes: bytes):
        import zipfile, io
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for name in z.namelist():
                if "x86_64" in name and any(name.endswith(ext) for ext in [".exe", ".dll", ".sys"]):
                    filename = os.path.basename(name)
                    if filename:
                        target_path = os.path.join(self.app_dir, filename)
                        with open(target_path, "wb") as f:
                            f.write(z.read(name))

    def _write_version_info(self, version: str, **extra):
        import json
        version_file = os.path.join(self.app_dir, "version.json")
        data = {"version": version, "last_updated": time.time()}
        data.update(extra)
        try:
            with open(version_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug("Failed to write version.json: %s", e)

    def _get_pending_update(self) -> str:
        import json
        version_file = os.path.join(self.app_dir, "version.json")
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                return json.load(f).get("pending_update") or ""
        except Exception:
            return ""

    def download_binaries(self) -> Tuple[bool, str]:
        """Download and extract winws/zapret binary bundle from official bol-van/zapret release."""
        with self._update_lock:
            try:
                logger.info("Downloading Zapret bundle from GitHub...")
                zip_bytes = self._download_zip(ZAPRET_ZIP_URL, timeout=30.0)

                if not _verify_zip_sha256(zip_bytes):
                    msg = f"Проверка SHA-256 не пройдена: архив {ZAPRET_VERSION} повреждён или подменён. Установка отменена."
                    logger.error(msg)
                    return False, msg

                self._extract_zip(zip_bytes)
                if not self.find_binary():
                    # Archive layout changed or nothing usable inside: never bump
                    # version.json in this case, otherwise the app would believe
                    # it is "installed" with no winws.exe on disk.
                    msg = f"Архив {ZAPRET_VERSION} не содержит winws.exe — установка отменена."
                    logger.error(msg)
                    return False, msg
                self._write_version_info(ZAPRET_VERSION)
                logger.info("Zapret binaries successfully extracted to %s", self.app_dir)
                return True, "Файлы Zapret успешно загружены!"
            except Exception as e:
                logger.error("Failed to download Zapret: %s", e)
                return False, f"Ошибка загрузки Zapret: {e}"

    def get_local_version(self) -> str:
        """Get local installed Zapret version tag ('' when nothing is installed)."""
        import json
        version_file = os.path.join(self.app_dir, "version.json")
        try:
            if os.path.exists(version_file):
                with open(version_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("version", "")
        except Exception:
            logger.debug("get_local_version: suppressed exception", exc_info=True)
        return ""

    def get_latest_release_info(self) -> Tuple[str | None, str | None]:
        """Fetch latest release tag and zip download URL from GitHub."""
        import urllib.request, json
        api_url = "https://api.github.com/repos/bol-van/zapret/releases/latest"
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tag = data.get("tag_name")
                for a in data.get("assets", []):
                    if a.get("name", "").endswith(".zip"):
                        return tag, a.get("browser_download_url")
                return tag, f"https://github.com/bol-van/zapret/releases/download/{tag}/zapret-{tag}.zip"
        except Exception as e:
            logger.warning("Failed to fetch latest Zapret release: %s", e)
            return None, None

    def check_for_updates(self) -> Dict[str, Any]:
        """Check if an update is available."""
        current_ver = self.get_local_version()
        latest_tag, zip_url = self.get_latest_release_info()
        update_available = bool(latest_tag and latest_tag != current_ver)
        return {
            "current_version": current_ver,
            "latest_version": latest_tag or current_ver,
            "update_available": update_available,
            "download_url": zip_url or ""
        }

    def update_zapret(self, force: bool = False) -> Tuple[bool, str]:
        """Update Zapret to the latest GitHub release. Serialized by _update_lock
        (Z-7/8): downloads and extraction happen outside the state lock, but never
        concurrently with another update or auto-download."""
        with self._update_lock:
            latest_tag, zip_url = self.get_latest_release_info()
            if not latest_tag or not zip_url:
                return False, "Не удалось получить информацию о последней версии Zapret с GitHub"

            current_ver = self.get_local_version()
            # Same tag already on disk with a usable binary — nothing to fetch,
            # even with force=True (a forced re-download of the identical zip
            # only wastes bandwidth and can race a concurrent start()).
            if latest_tag == current_ver and self.find_binary():
                return True, f"У вас уже установлена последняя версия Zapret ({current_ver})"

            try:
                logger.info("Downloading Zapret %s from %s...", latest_tag, zip_url)
                zip_bytes = self._download_zip(zip_url, timeout=40.0)

                # Verify integrity: pinned hash exists only for the bundled release.
                expected_hash = ZAPRET_ZIP_SHA256 if zip_url == ZAPRET_ZIP_URL else ""
                if not _verify_zip_sha256(zip_bytes, expected_hash):
                    msg = f"Проверка SHA-256 не пройдена: архив {latest_tag} повреждён или подменён. Обновление отменено."
                    logger.error(msg)
                    return False, msg

                was_running = self.is_running()
                if was_running:
                    self.stop()
                    time.sleep(1.0)

                self._extract_zip(zip_bytes)
                if not self.find_binary():
                    # Extraction produced no usable binary (e.g. release layout
                    # changed): keep the old version.json so the next attempt
                    # still reports an update instead of a phantom install.
                    msg = f"Архив {latest_tag} не содержит winws.exe — обновление отменено, предыдущая версия сохранена."
                    logger.error(msg)
                    return False, msg
                # Rewriting version.json drops any pending_update flag.
                self._write_version_info(latest_tag)
                logger.info("Zapret successfully updated to %s", latest_tag)

                if was_running:
                    mode = "youtube_discord"
                    custom_args = ""
                    bin_path = None
                    if self.settings:
                        mode = self.settings.get("zapret", "mode", "youtube_discord")
                        custom_args = self.settings.get("zapret", "custom_args", "")
                        bin_path = self.settings.get("zapret", "binary_path", "")
                    self.start(mode=mode, custom_args=custom_args, binary_path=bin_path)

                return True, f"Zapret успешно обновлен до версии {latest_tag}!"
            except Exception as e:
                logger.error("Failed to update Zapret: %s", e)
                return False, f"Ошибка при обновлении Zapret: {e}"

    def auto_update_in_background(self):
        """Z-8: background update check — only when autoupdate is enabled (default OFF).
        A running winws is never restarted: the update is marked pending and
        applied on the next launch."""
        def _bg():
            try:
                time.sleep(5.0)  # Wait for main app startup to settle
                if not self.settings or not self.settings.get("zapret", "autoupdate", False):
                    return

                import json
                version_file = os.path.join(self.app_dir, "version.json")
                last_check = 0
                if os.path.exists(version_file):
                    try:
                        with open(version_file, "r", encoding="utf-8") as f:
                            last_check = json.load(f).get("last_check", 0)
                    except Exception:
                        logger.debug("_bg: suppressed exception", exc_info=True)

                # Check at most once every 24 hours
                if time.time() - last_check <= 86400:
                    return

                latest_tag, _ = self.get_latest_release_info()
                if not latest_tag:
                    return

                cur_ver = self.get_local_version()
                if latest_tag == cur_ver:
                    self._write_version_info(cur_ver, last_check=time.time())
                    return

                logger.info("New Zapret update found: %s (current: %s)", latest_tag, cur_ver)
                if self.is_running():
                    # Never interrupt a running bypass — offer the update for next launch.
                    self._write_version_info(cur_ver, last_check=time.time(), pending_update=latest_tag)
                    logger.info("Zapret update %s marked pending (applies on next launch)", latest_tag)
                else:
                    self.update_zapret(force=True)
                    self._write_version_info(self.get_local_version(), last_check=time.time())
            except Exception as e:
                logger.debug("Background Zapret auto-update error: %s", e)

        threading.Thread(target=_bg, daemon=True).start()

    # ─── start / stop (Z-2, Z-3; lock only around state transitions) ───

    def start(self, mode="youtube_discord", custom_args="", binary_path=None) -> Tuple[bool, str]:
        """Start Zapret process with specified strategy. Returns (success, status_message).
        If winws is already running with DIFFERENT arguments (mode switched while
        active), it is restarted with the new strategy instead of a silent no-op."""
        exe = self.find_binary(binary_path)
        if not exe:
            # Try auto-downloading if missing (network I/O — outside the lock)
            logger.info("Zapret binary not found. Attempting automatic download...")
            ok, dl_msg = self.download_binaries()
            exe = self.find_binary(binary_path)
            if not exe:
                msg = f"Файл winws.exe не найден. {dl_msg}"
                logger.warning(msg)
                return False, msg

        if mode == "custom" and (custom_args or "").strip():
            raw_args = custom_args.strip()
            try:
                sanitize_zapret_args(raw_args)
            except ValueError as exc:
                logger.warning("Rejected custom Zapret args: %s", exc)
                return False, str(exc)
        else:
            raw_args = PRESET_STRATEGIES.get(mode, PRESET_STRATEGIES["youtube_discord"])

        # Apply a pending update if one was deferred while the bypass was running (Z-8)
        pending = self._get_pending_update()
        if pending and not self.is_running():
            logger.info("Applying pending Zapret update %s before launch...", pending)
            self.update_zapret(force=True)

        with self._lock:
            if self.is_running():
                current_cmd = (self._last_args or self._read_cmd_file()).strip()
                if current_cmd == raw_args.strip():
                    return True, "Zapret активен"
                # Already running with a DIFFERENT strategy (mode switched in the
                # UI while active) — silently returning "active" would leave the
                # old winws arguments in place. Restart with the new ones.
                logger.info("Zapret strategy changed — restarting with new arguments")
                stopped, stop_msg = self.stop()
                if not stopped:
                    return False, f"Не удалось применить новую стратегию: {stop_msg}"
            return self._launch(exe, raw_args)

    def _launch(self, exe: str, raw_args: str) -> Tuple[bool, str]:
        self._last_args = raw_args
        self._write_cmd_file(raw_args)
        logger.info("Starting Zapret: %s %s", exe, raw_args)

        if sys.platform == "win32":
            import ctypes
            try:
                args_list = [exe] + sanitize_zapret_args(raw_args)
            except ValueError as exc:
                logger.error("Refusing to launch Zapret with unsafe arguments: %s", exc)
                return False, str(exc)

            self._open_log_handle()
            try:
                self.process = subprocess.Popen(
                    args_list,
                    cwd=os.path.dirname(exe),
                    stdout=subprocess.DEVNULL,
                    stderr=self._log_handle or subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except OSError:
                self._close_log_handle()
                self.process = None
                return self._launch_elevated(exe, raw_args)

            self._write_pidfile(self.process.pid)
            time.sleep(0.6)
            if self.process.poll() is not None:
                # Crashed instantly — analyze the captured stderr log (Z-3)
                rc = self.process.poll()
                self.process = None
                self._close_log_handle()
                self._clear_pidfile()
                tail = self._read_log_tail()
                if self._looks_like_elevation_needed(tail):
                    return self._launch_elevated(exe, raw_args)
                self._clear_cmd_file()
                msg = self._analyze_crash(tail)
                if rc is not None:
                    msg = f"{msg} Код завершения: {rc}"
                return False, msg
            return True, "Zapret активен"

        # Non-Windows
        try:
            self._open_log_handle()
            args_list = [exe] + sanitize_zapret_args(raw_args)
            self.process = subprocess.Popen(
                args_list,
                stdout=subprocess.DEVNULL,
                stderr=self._log_handle or subprocess.DEVNULL
            )
            self._write_pidfile(self.process.pid)
            return True, "Zapret активен"
        except Exception as e:
            self._close_log_handle()
            self._clear_pidfile()
            self._clear_cmd_file()
            return False, str(e)

    def _launch_elevated(self, exe: str, raw_args: str) -> Tuple[bool, str]:
        """Elevation required (WinError 740 / missing rights) — use ShellExecuteW 'runas'.
        Launches winws.exe with elevation, redirecting stdout/stderr to zapret.log (AUDIT #05),
        and writes its PID directly to run.pid."""
        import ctypes
        logger.info("Elevating Zapret via ShellExecuteW 'runas'...")

        if not validate_zapret_binary(exe):
            msg = f"Отказано в запуске: {os.path.basename(exe)} не является разрешённым исполняемым файлом Zapret."
            logger.error(msg)
            return False, msg
        try:
            tokens = sanitize_zapret_args(raw_args)
        except ValueError as exc:
            logger.error("Refusing elevated launch with unsafe arguments: %s", exc)
            return False, str(exc)

        self._close_log_handle()
        params = subprocess.list2cmdline(tokens)
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        cmd_params = f'/c ""{exe}" {params} > "{self.log_file}" 2>&1"'

        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", comspec, cmd_params, os.path.dirname(exe), 0  # SW_HIDE
        )
        if ret == 5:
            msg = "Запуск отменён: требуются права Администратора для драйвера WinDivert (UAC отклонён)."
            logger.warning(msg)
            return False, msg
        if ret <= 32:
            msg = f"Ошибка запуска с правами Администратора (код {ret}). См. лог zapret.log."
            logger.error(msg)
            return False, msg

        # Wait up to 5s for PID to appear in pidfile or via signature scan
        pid = None
        deadline = time.time() + 5.0
        while time.time() < deadline:
            file_pid = self._read_pidfile()
            if file_pid and self._pid_alive(file_pid) and self._is_our_winws_process(file_pid):
                pid = file_pid
                break
            pids = self._scan_pids_with(raw_args)
            for p in pids:
                if self._is_our_winws_process(p, raw_args):
                    pid = p
                    self._write_pidfile(pid)
                    break
            if pid:
                break
            # Fallback across integrity boundary: if CommandLine is empty in WMI/CIM,
            # discover running winws.exe belonging to our app (AUDIT #04)
            all_winws = self._scan_all_winws_pids()
            for p in all_winws:
                if self._is_our_winws_process(p, raw_args):
                    pid = p
                    self._write_pidfile(pid)
                    break
            if pid:
                break
            time.sleep(0.3)

        if pid:
            logger.info("Elevated winws.exe detected (PID %s)", pid)
            return True, "Zapret активен"

        # Check if an existing valid PID is still running — NEVER clear if alive
        existing_pid = self._read_pidfile()
        if existing_pid and self._pid_alive(existing_pid) and self._is_our_winws_process(existing_pid):
            return True, "Zapret активен (ранее запущен)"

        tail = self._read_log_tail()
        msg = self._analyze_crash(tail) if tail else "winws.exe не запустился с правами Администратора. См. лог zapret.log."
        return False, msg

    def stop(self) -> Tuple[bool, str]:
        """Stop only the Zapret process started by this app (Z-2).
        Never uses taskkill /IM — external winws processes are left untouched (AUDIT #03, #04).
        If termination fails, pidfile is preserved to prevent orphaned WinDivert driver lock.
        """
        with self._lock:
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
                self.process = None
            self._close_log_handle()

        try:
            pid = self._read_pidfile()
            target_pids = set()
            if pid and self._pid_alive(pid) and self._is_our_winws_process(pid):
                target_pids.add(pid)

            # Fallback: kill only processes matching our cmdline signature (elevated case)
            signature = self._last_args or self._read_cmd_file()
            if signature:
                for p in self._scan_pids_with(signature):
                    if self._pid_alive(p) and self._is_our_winws_process(p, signature):
                        target_pids.add(p)

            # If no active target PIDs found:
            if not target_pids:
                if pid and not self._pid_alive(pid):
                    self._clear_pidfile()
                self._clear_cmd_file()
                return True, "Zapret остановлен"

            failed_pids = []
            for p in target_pids:
                if self._pid_alive(p):
                    killed = self._kill_pid(p)
                    if not killed or self._pid_alive(p):
                        failed_pids.append(p)

            if failed_pids:
                # DO NOT clear pidfile if any process is still alive!
                # Update pidfile with the living PID so tracking is preserved
                self._write_pidfile(failed_pids[0])
                msg = (
                    f"Не удалось остановить процесс Zapret (PID {', '.join(str(x) for x in failed_pids)}). "
                    f"Возможно, требуются права Администратора для остановки elevated winws.exe. "
                    f"Pidfile сохранён для предотвращения утечки драйвера WinDivert."
                )
                logger.warning(msg)
                return False, msg

            # All target processes successfully terminated
            self._clear_pidfile()
            self._clear_cmd_file()
            logger.info("Zapret process stopped successfully (own PID only)")
            return True, "Zapret остановлен"
        except Exception as e:
            logger.error("Zapret stop error: %s", e, exc_info=True)
            pid = self._read_pidfile()
            if pid and self._pid_alive(pid) and self._is_our_winws_process(pid):
                return False, f"Ошибка при остановке Zapret: {e}"
            self._clear_pidfile()
            self._clear_cmd_file()
            return False, f"Ошибка при остановке Zapret: {e}"

    # ─── status (Z-5: instant via cache, refreshed in background) ───

    def get_status(self) -> Dict[str, Any]:
        """Return cached status instantly; refresh happens in background."""
        now = time.time()
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
        self._refresh_status_async()
        return dict(self._status_cache)

    def _refresh_status_async(self):
        with self._lock:
            if self._status_thread and self._status_thread.is_alive():
                return
            self._status_thread = threading.Thread(target=self._build_status, daemon=True)
            self._status_thread.start()

    def _build_status(self):
        try:
            exe = self.find_binary()
            running = self.is_running()
            has_net = check_internet() if running else True
            cur_version = self.get_local_version()
            pending = self._get_pending_update()

            if not exe:
                message = "Файл winws.exe не найден. Нажмите 'Обновить Zapret'."
            elif not running:
                message = "Zapret отключен"
            elif pending:
                message = f"Доступно обновление {pending} (применится при следующем запуске)"
            elif not has_net:
                message = "Zapret запущен, но нет подключения к интернету"
            else:
                message = f"Zapret активен ({cur_version})"

            status = {
                "binary_found": bool(exe),
                "binary_path": exe or "",
                "running": running,
                "has_internet": has_net,
                "version": cur_version,
                "message": message,
                "pending_update": pending
            }
            with self._lock:
                self._status_cache = status
                self._status_cache_time = time.time()
        except Exception as e:
            logger.debug("Zapret status refresh error: %s", e)
            with self._lock:
                if not self._status_cache:
                    self._status_cache = {}
                self._status_cache["running"] = self.is_running()
                self._status_cache["message"] = "Ошибка определения статуса"
                self._status_cache_time = time.time()