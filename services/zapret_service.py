"""
NeDotify - Zapret (DPI Bypass) Service
Launches and manages winws / zapret background process for Windows to bypass DPI blocks.
"""

import logging
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
from typing import Dict, Any, Tuple

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


def check_internet(timeout: float = 3.0) -> bool:
    """Fast check for active internet connection without blocking UI."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("1.1.1.1", 53))
        sock.close()
        return True
    except Exception:
        return False


class ZapretService:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager
        self.process = None
        self._lock = threading.RLock()
        self.app_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "zapret")
        os.makedirs(self.app_dir, exist_ok=True)

    def find_binary(self, custom_path=None) -> str | None:
        """Find path to winws.exe, zapret.exe or winws binary."""
        if custom_path and os.path.exists(custom_path):
            return custom_path

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

    def is_running(self) -> bool:
        """Check if Zapret process is currently running."""
        with self._lock:
            if self.process and self.process.poll() is None:
                return True
        try:
            cmd = 'tasklist /FI "IMAGENAME eq winws.exe" /NH'
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=2.0)
            if "winws.exe" in out.lower():
                return True

            cmd_zap = 'tasklist /FI "IMAGENAME eq zapret.exe" /NH'
            out_zap = subprocess.check_output(cmd_zap, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=2.0)
            return "zapret.exe" in out_zap.lower()
        except Exception:
            return False

    def download_binaries(self) -> Tuple[bool, str]:
        """Download and extract winws/zapret binary bundle from official bol-van/zapret release."""
        import urllib.request, zipfile, io
        url = ZAPRET_ZIP_URL
        try:
            logger.info("Downloading Zapret bundle from GitHub...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                zip_bytes = resp.read()

            if not _verify_zip_sha256(zip_bytes):
                msg = f"Проверка SHA-256 не пройдена: архив {ZAPRET_VERSION} повреждён или подменён. Установка отменена."
                logger.error(msg)
                return False, msg

            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                for name in z.namelist():
                    if "x86_64" in name and any(name.endswith(ext) for ext in [".exe", ".dll", ".sys"]):
                        filename = os.path.basename(name)
                        if filename:
                            target_path = os.path.join(self.app_dir, filename)
                            with open(target_path, "wb") as f:
                                f.write(z.read(name))
            logger.info("Zapret binaries successfully extracted to %s", self.app_dir)
            return True, "Файлы Zapret успешно загружены!"
        except Exception as e:
            logger.error("Failed to download Zapret: %s", e)
            return False, f"Ошибка загрузки Zapret: {e}"

    def start(self, mode="youtube_discord", custom_args="", binary_path=None) -> Tuple[bool, str]:
        """Start Zapret process with specified strategy. Returns (success, status_message)."""
        with self._lock:
            exe = self.find_binary(binary_path)
            if not exe:
                # Try auto-downloading if missing
                logger.info("Zapret binary not found. Attempting automatic download...")
                ok, dl_msg = self.download_binaries()
                exe = self.find_binary(binary_path)
                if not exe:
                    msg = f"Файл winws.exe не найден. {dl_msg}"
                    logger.warning(msg)
                    return False, msg

            if self.is_running():
                return True, "Zapret активен"

            if mode == "custom" and custom_args.strip():
                raw_args = custom_args.strip()
            else:
                raw_args = PRESET_STRATEGIES.get(mode, PRESET_STRATEGIES["youtube_discord"])

            logger.info(f"Starting Zapret: {exe} {raw_args}")

            if sys.platform == "win32":
                import ctypes
                try:
                    # First try standard Popen (if NeDotify already runs elevated)
                    try:
                        args_list = [exe] + shlex.split(raw_args)
                    except Exception:
                        args_list = [exe] + raw_args.split()

                    self.process = subprocess.Popen(
                        args_list,
                        cwd=os.path.dirname(exe),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    time.sleep(0.35)
                    if self.process.poll() is not None:
                        raise OSError(740, "Elevation required")
                    return True, "Zapret активен"
                except OSError:
                    # Elevation required (WinError 740) -> Use Windows ShellExecuteW 'runas'
                    logger.info("Elevating Zapret via ShellExecuteW 'runas'...")
                    ret = ctypes.windll.shell32.ShellExecuteW(
                        None,
                        "runas",
                        exe,
                        raw_args,
                        os.path.dirname(exe),
                        0  # SW_HIDE = 0
                    )
                    # ret > 32 indicates success in ShellExecute
                    if ret == 5:
                        msg = "Запуск отменён: требуются права Администратора для драйвера WinDivert."
                        logger.warning(msg)
                        return False, msg
                    elif ret <= 32:
                        msg = f"Ошибка запуска с правами Администратора (код {ret})"
                        logger.error(msg)
                        return False, msg

                    time.sleep(0.8)
                    if not self.is_running():
                        msg = "winws.exe запустился, но завершил работу. Проверьте права Администратора."
                        return False, msg

                    return True, "Zapret активен"
            else:
                # Non-Windows
                try:
                    args_list = [exe] + shlex.split(raw_args)
                    self.process = subprocess.Popen(args_list, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True, "Zapret активен"
                except Exception as e:
                    return False, str(e)

    def stop(self) -> Tuple[bool, str]:
        """Stop Zapret process."""
        with self._lock:
            if self.process:
                try:
                    self.process.terminate()
                except Exception:
                    pass
                self.process = None

            try:
                if sys.platform == "win32":
                    subprocess.run(
                        "taskkill /F /IM winws.exe /IM zapret.exe",
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3.0
                    )
            except Exception as e:
                logger.debug(f"Taskkill error: {e}")

            return True, "Zapret остановлен"

    def get_local_version(self) -> str:
        """Get local installed Zapret version tag."""
        import json
        version_file = os.path.join(self.app_dir, "version.json")
        try:
            if os.path.exists(version_file):
                with open(version_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("version", "v72.13")
        except Exception:
            pass
        return "v72.13"

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
        """Update Zapret to the latest GitHub release."""
        with self._lock:
            latest_tag, zip_url = self.get_latest_release_info()
            if not latest_tag or not zip_url:
                return False, "Не удалось получить информацию о последней версии Zapret с GitHub"

            current_ver = self.get_local_version()
            if not force and latest_tag == current_ver:
                return True, f"У вас уже установлена последняя версия Zapret ({current_ver})"

            was_running = self.is_running()
            if was_running:
                self.stop()
                time.sleep(1.0)

            # Download and extract the latest zip
            import urllib.request, zipfile, io, json
            try:
                logger.info("Downloading Zapret %s from %s...", latest_tag, zip_url)
                req = urllib.request.Request(zip_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=40) as resp:
                    zip_bytes = resp.read()

                # Verify integrity: pinned hash exists only for the bundled release.
                expected_hash = ZAPRET_ZIP_SHA256 if zip_url == ZAPRET_ZIP_URL else ""
                if not _verify_zip_sha256(zip_bytes, expected_hash):
                    msg = f"Проверка SHA-256 не пройдена: архив {latest_tag} повреждён или подменён. Обновление отменено."
                    logger.error(msg)
                    return False, msg

                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                    for name in z.namelist():
                        if "x86_64" in name and any(name.endswith(ext) for ext in [".exe", ".dll", ".sys"]):
                            filename = os.path.basename(name)
                            if filename:
                                target_path = os.path.join(self.app_dir, filename)
                                with open(target_path, "wb") as f:
                                    f.write(z.read(name))

                # Save new version info
                version_file = os.path.join(self.app_dir, "version.json")
                with open(version_file, "w", encoding="utf-8") as f:
                    json.dump({"version": latest_tag, "last_updated": time.time()}, f, indent=2)

                logger.info("Zapret successfully updated to %s", latest_tag)

                # Restart if it was running
                if was_running:
                    mode = "youtube_discord"
                    if self.settings:
                        mode = self.settings.get("zapret", "mode", "youtube_discord")
                    self.start(mode=mode)

                return True, f"Zapret успешно обновлен до версии {latest_tag}!"
            except Exception as e:
                logger.error("Failed to update Zapret: %s", e)
                return False, f"Ошибка при обновлении Zapret: {e}"

    def auto_update_in_background(self):
        """Run periodic background update check."""
        def _bg():
            try:
                time.sleep(5.0)  # Wait for main app startup to settle
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
                if time.time() - last_check > 86400:
                    latest_tag, _ = self.get_latest_release_info()
                    if latest_tag:
                        cur_ver = self.get_local_version()
                        if cur_ver != latest_tag:
                            logger.info("New Zapret update found: %s (current: %s). Auto-updating...", latest_tag, cur_ver)
                            self.update_zapret(force=True)
                        else:
                            # Update last_check timestamp
                            try:
                                with open(version_file, "w", encoding="utf-8") as f:
                                    json.dump({"version": cur_ver, "last_check": time.time()}, f, indent=2)
                            except Exception:
                                pass
            except Exception as e:
                logger.debug("Background Zapret auto-update error: %s", e)

        threading.Thread(target=_bg, daemon=True).start()

    def get_status(self) -> Dict[str, Any]:
        """Return status dictionary for UI."""
        exe = self.find_binary()
        running = self.is_running()
        has_net = check_internet(timeout=2.0) if running else True
        cur_version = self.get_local_version()

        if not exe:
            message = "Файл winws.exe не найден. Нажмите 'Обновить Zapret'."
        elif not running:
            message = "Zapret отключен"
        elif not has_net:
            message = "Zapret запущен, но нет подключения к интернету"
        else:
            message = f"Zapret активен ({cur_version})"

        return {
            "binary_found": bool(exe),
            "binary_path": exe or "",
            "running": running,
            "has_internet": has_net,
            "version": cur_version,
            "message": message
        }
