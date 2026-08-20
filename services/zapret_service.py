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
        download/update work outside the lock; autoupdate defaults to OFF and,
        when enabled, a running winws is never restarted (update applies on next launch).
"""

import logging
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from typing import Dict, Any, Tuple, List

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
_ALLOWED_ARG_RE = re.compile(r'^--[A-Za-z0-9][A-Za-z0-9\-]*(=[A-Za-z0-9,.:_/\-]*)?$')

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
        tokens = shlex.split(raw_args)
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


def check_internet(timeout: float = 1.5) -> bool:
    """Fast check for active internet connection without blocking UI."""
    for host in INTERNET_CHECK_HOSTS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, 443))
            sock.close()
            return True
        except Exception:
            continue
    return False


class ZapretService:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager
        self.process = None
        self._log_handle = None
        self._lock = threading.RLock()
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

    def _write_pidfile(self, pid):
        try:
            with open(self.pid_file, "w", encoding="utf-8") as f:
                f.write(str(pid))
        except Exception as e:
            logger.debug("Failed to write pidfile: %s", e)

    def _read_pidfile(self) -> int | None:
        try:
            with open(self.pid_file, "r", encoding="utf-8") as f:
                return int(f.read().strip() or "0")
        except Exception:
            return None

    def _clear_pidfile(self):
        try:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
        except Exception:
            pass

    def _write_cmd_file(self, raw_args):
        try:
            with open(self.cmd_file, "w", encoding="utf-8") as f:
                f.write(raw_args or "")
        except Exception:
            pass

    def _read_cmd_file(self) -> str:
        try:
            with open(self.cmd_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _pid_alive(self, pid) -> bool:
        """Liveness check of a PID without spawning subprocesses (Z-5)."""
        if not pid or pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not handle:
                    return False
                try:
                    code = ctypes.c_ulong()
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                        return code.value == STILL_ACTIVE
                    return False
                finally:
                    kernel32.CloseHandle(handle)
            except Exception:
                pass
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _scan_pids_with(self, args_signature: str) -> List[int]:
        """Return PIDs of winws.exe processes whose cmdline contains the signature."""
        if not args_signature:
            return []
        pids: List[int] = []
        if sys.platform != "win32":
            return pids
        try:
            cmd = 'wmic process where "name=\'winws.exe\'" get ProcessId,CommandLine /FORMAT:CSV'
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=4.0)
            for line in out.splitlines():
                parts = line.split(",", 2)
                if len(parts) == 3 and args_signature in parts[2]:
                    try:
                        pids.append(int(parts[1]))
                    except ValueError:
                        continue
        except Exception as e:
            logger.debug("wmic scan failed: %s", e)
            try:
                ps_cmd = 'Get-CimInstance Win32_Process -Filter "Name=\'winws.exe\'" | ForEach-Object { "$($_.ProcessId)|$($_.CommandLine)" }'
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    text=True, stderr=subprocess.DEVNULL, timeout=6.0
                )
                for line in out.splitlines():
                    if "|" in line:
                        pid_str, cmdline = line.split("|", 1)
                        if args_signature in (cmdline or ""):
                            try:
                                pids.append(int(pid_str.strip()))
                            except ValueError:
                                continue
            except Exception as e2:
                logger.debug("PowerShell CIM scan failed: %s", e2)
        return pids

    def _kill_pid(self, pid) -> bool:
        """Kill exactly one PID via taskkill /PID (graceful first, /F fallback)."""
        if not pid or pid <= 0:
            return False
        try:
            subprocess.run(
                f"taskkill /PID {pid}",
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0
            )
            deadline = time.time() + 1.5
            while time.time() < deadline:
                if not self._pid_alive(pid):
                    return True
                time.sleep(0.15)
            subprocess.run(
                f"taskkill /PID {pid} /F",
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0
            )
            time.sleep(0.2)
            return not self._pid_alive(pid)
        except Exception as e:
            logger.debug("taskkill error for PID %s: %s", pid, e)
            return False

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
        if pid and self._pid_alive(pid):
            return True
        signature = self._last_args or self._read_cmd_file()
        if signature:
            pids = self._scan_pids_with(signature)
            if pids:
                self._write_pidfile(pids[0])
                return True
        return False

    # ─── stderr log & crash analysis (Z-3) ───

    def _open_log_handle(self):
        self._close_log_handle()
        try:
            self._log_handle = open(self.log_file, "ab")
        except Exception:
            self._log_handle = None

    def _close_log_handle(self):
        try:
            if self._log_handle:
                self._log_handle.close()
        except Exception:
            pass
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
        try:
            logger.info("Downloading Zapret bundle from GitHub...")
            zip_bytes = self._download_zip(ZAPRET_ZIP_URL, timeout=30.0)

            if not _verify_zip_sha256(zip_bytes):
                msg = f"Проверка SHA-256 не пройдена: архив {ZAPRET_VERSION} повреждён или подменён. Установка отменена."
                logger.error(msg)
                return False, msg

            self._extract_zip(zip_bytes)
            self._write_version_info(ZAPRET_VERSION)
            logger.info("Zapret binaries successfully extracted to %s", self.app_dir)
            return True, "Файлы Zapret успешно загружены!"
        except Exception as e:
            logger.error("Failed to download Zapret: %s", e)
            return False, f"Ошибка загрузки Zapret: {e}"

    def get_local_version(self) -> str:
        """Get local installed Zapret version tag."""
        import json
        version_file = os.path.join(self.app_dir, "version.json")
        try:
            if os.path.exists(version_file):
                with open(version_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("version", ZAPRET_VERSION)
        except Exception:
            pass
        return ZAPRET_VERSION

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
        """Update Zapret to the latest GitHub release. Runs outside the state lock (Z-7)."""
        latest_tag, zip_url = self.get_latest_release_info()
        if not latest_tag or not zip_url:
            return False, "Не удалось получить информацию о последней версии Zapret с GitHub"

        current_ver = self.get_local_version()
        if not force and latest_tag == current_ver:
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
                        pass

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
        """Start Zapret process with specified strategy. Returns (success, status_message)."""
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
                return True, "Zapret активен"
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
            return False, str(e)

    def _launch_elevated(self, exe: str, raw_args: str) -> Tuple[bool, str]:
        """Elevation required (WinError 740 / missing rights) — use ShellExecuteW 'runas'.
        Launches winws.exe with elevation and writes its PID directly to run.pid."""
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

        # The executable is elevated DIRECTLY. An intermediate PowerShell -Command
        # string was previously used to capture the PID, but interpolating arguments
        # into it allowed arbitrary code execution as Administrator. The PID is now
        # recovered from the pidfile or the cmdline signature scan below instead.
        params = subprocess.list2cmdline(tokens)
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, params, os.path.dirname(exe), 0  # SW_HIDE
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
            if file_pid and self._pid_alive(file_pid):
                pid = file_pid
                break
            pids = self._scan_pids_with(raw_args)
            if pids:
                pid = pids[0]
                self._write_pidfile(pid)
                break
            time.sleep(0.3)

        if pid:
            logger.info("Elevated winws.exe detected (PID %s)", pid)
            return True, "Zapret активен"

        # Check if an existing valid PID is still running — NEVER clear if alive
        existing_pid = self._read_pidfile()
        if existing_pid and self._pid_alive(existing_pid):
            return True, "Zapret активен (ранее запущен)"

        tail = self._read_log_tail()
        msg = self._analyze_crash(tail) if tail else "winws.exe не запустился с правами Администратора. См. лог zapret.log."
        return False, msg

    def stop(self) -> Tuple[bool, str]:
        """Stop only the Zapret process started by this app (Z-2).
        Never uses taskkill /IM — external winws processes are left untouched."""
        with self._lock:
            if self.process:
                try:
                    self.process.terminate()
                except Exception:
                    pass
                self.process = None
            self._close_log_handle()

        try:
            pid = self._read_pidfile()
            killed = False
            if pid and self._pid_alive(pid):
                killed = self._kill_pid(pid)

            # Fallback: kill only processes matching our cmdline signature (elevated case)
            signature = self._last_args or self._read_cmd_file()
            if signature:
                for p in self._scan_pids_with(signature):
                    if p != pid and self._pid_alive(p):
                        killed = self._kill_pid(p) or killed

            self._clear_pidfile()
            if killed:
                logger.info("Zapret process stopped (own PID only)")
        except Exception as e:
            logger.debug(f"Zapret stop error: {e}")

        return True, "Zapret остановлен"

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