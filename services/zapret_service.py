"""
NeDotify - Zapret (DPI Bypass) Service
Launches and manages winws / zapret background process for Windows to bypass DPI blocks (YouTube, Discord, Spotify, etc.)
"""

import logging
import os
import shlex
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

PRESET_STRATEGIES = {
    "youtube_discord": "--wf-l3=ipv4,ipv6 --wf-tcp=80,443 --dpi-desync=fake,split2 --dpi-desync-repeats=6 --dpi-desync-fooling=md5sig",
    "standard": "--wf-l3=ipv4,ipv6 --wf-tcp=80,443 --dpi-desync=fake,split2 --dpi-desync-repeats=6",
    "aggressive": "--wf-l3=ipv4,ipv6 --wf-tcp=80,443,4433 --wf-udp=443,50000-65535 --dpi-desync=fake,disorder2 --dpi-desync-repeats=11 --dpi-desync-fooling=md5sig,badsum"
}


class ZapretService:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager
        self.process = None
        self._lock = threading.Lock()
        self.app_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "zapret")
        os.makedirs(self.app_dir, exist_ok=True)
    def find_binary(self, custom_path=None):
        """Find path to winws.exe or zapret binary."""
        if custom_path and os.path.exists(custom_path):
            return custom_path

        candidates = [
            os.path.join(self.app_dir, "winws.exe"),
            os.path.join(self.app_dir, "bin", "winws.exe"),
            os.path.join(os.getcwd(), "bin", "winws.exe"),
            os.path.join(os.getcwd(), "zapret", "winws.exe")
        ]

        for c in candidates:
            if os.path.exists(c):
                return c

        return None

    def is_running(self):
        """Check if Zapret process is currently running."""
        with self._lock:
            if self.process and self.process.poll() is None:
                return True
        try:
            cmd = 'tasklist /FI "IMAGENAME eq winws.exe" /NH'
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            return "winws.exe" in out.lower()
        except Exception:
            return False

    def start(self, mode="youtube_discord", custom_args="", binary_path=None):
        """Start Zapret process with specified strategy."""
        with self._lock:
            if self.is_running():
                logger.info("Zapret process already running")
                return True
            exe = self.find_binary(binary_path)
            if not exe:
                logger.warning(f"Zapret binary winws.exe not found in {self.app_dir}")
                return False

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
                return True
            except Exception as e:
                logger.error(f"Failed to start Zapret: {e}")
                return False

    def stop(self):
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
                        "taskkill /F /IM winws.exe",
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
            except Exception as e:
                logger.debug(f"Taskkill error: {e}")

            return True

    def get_status(self):
        """Return status dictionary for UI."""
        exe = self.find_binary()
        running = self.is_running()
        return {
            "binary_found": bool(exe),
            "binary_path": exe or "",
            "running": running
        }
