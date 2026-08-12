"""
NeDotify - Zapret (DPI Bypass) Service
Launches and manages winws / zapret background process for Windows to bypass DPI blocks.
"""

import logging
import os
import socket
import subprocess
import sys
import threading
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

PRESET_STRATEGIES = {
    "youtube_discord": "--wf-l3=ipv4,ipv6 --wf-tcp=80,443 --dpi-desync=fake,split2 --dpi-desync-repeats=6 --dpi-desync-fooling=md5sig",
    "standard": "--wf-l3=ipv4,ipv6 --wf-tcp=80,443 --dpi-desync=fake,split2 --dpi-desync-repeats=6",
    "aggressive": "--wf-l3=ipv4,ipv6 --wf-tcp=80,443,4433 --wf-udp=443,50000-65535 --dpi-desync=fake,disorder2 --dpi-desync-repeats=11 --dpi-desync-fooling=md5sig,badsum"
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
        self._lock = threading.Lock()
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
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            if "winws.exe" in out.lower():
                return True

            cmd_zap = 'tasklist /FI "IMAGENAME eq zapret.exe" /NH'
            out_zap = subprocess.check_output(cmd_zap, shell=True, text=True, stderr=subprocess.DEVNULL)
            return "zapret.exe" in out_zap.lower()
        except Exception:
            return False

    def start(self, mode="youtube_discord", custom_args="", binary_path=None) -> Tuple[bool, str]:
        """Start Zapret process with specified strategy. Returns (success, status_message)."""
        with self._lock:
            exe = self.find_binary(binary_path)
            if not exe:
                msg = "Файл winws.exe не найден. Переустановите Zapret."
                logger.warning(msg)
                return False, msg

            has_net = check_internet(timeout=2.5)

            if self.is_running():
                msg = "Zapret активен" if has_net else "Zapret запущен, но нет подключения к интернету"
                return True, msg

            if mode == "custom" and custom_args.strip():
                args = custom_args.strip()
            else:
                args = PRESET_STRATEGIES.get(mode, PRESET_STRATEGIES["youtube_discord"])

            cmd = f'"{exe}" {args}'
            logger.info(f"Starting Zapret: {cmd}")

            try:
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NO_WINDOW

                self.process = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=os.path.dirname(exe),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags
                )

                if not has_net:
                    return True, "Zapret запущен, но нет подключения к интернету"
                return True, "Zapret активен"
            except Exception as e:
                msg = f"Не удалось запустить Zapret. Проверьте права администратора: {e}"
                logger.error(msg)
                return False, msg

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
                        stderr=subprocess.DEVNULL
                    )
            except Exception as e:
                logger.debug(f"Taskkill error: {e}")

            return True, "Zapret остановлен"

    def get_status(self) -> Dict[str, Any]:
        """Return status dictionary for UI."""
        exe = self.find_binary()
        running = self.is_running()
        has_net = check_internet(timeout=2.0) if running else True

        if not exe:
            message = "Файл winws.exe не найден. Переустановите Zapret."
        elif not running:
            message = "Zapret отключен"
        elif not has_net:
            message = "Zapret запущен, но нет подключения к интернету"
        else:
            message = "Zapret активен"

        return {
            "binary_found": bool(exe),
            "binary_path": exe or "",
            "running": running,
            "has_internet": has_net,
            "message": message
        }
