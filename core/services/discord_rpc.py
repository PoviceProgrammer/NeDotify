"""
AURA Music - Discord Rich Presence Service
Integrates local playback metadata (track title, artist, progress, playing state) with Discord RPC.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

try:
    from pypresence import Presence
    HAS_PYPRESENCE = True
except ImportError:
    Presence = None
    HAS_PYPRESENCE = False


class DiscordRPCService:
    """Manages Discord Rich Presence connection and status updates."""

    def __init__(self, settings=None, client_id="1329524021200158781"):
        self.client_id = client_id
        self.settings = settings
        self.rpc = None
        self.connected = False
        self.current_track = None
        self.current_artist = None
        self.start_time = None
        self.duration_sec = 0
        self._lock = threading.Lock()
        self._connecting = False

    def is_enabled(self) -> bool:
        if self.settings:
            return bool(self.settings.get("app", "discord_rpc_enabled", True))
        return True

    def start(self):
        """Asynchronously connect to local Discord IPC socket."""
        if not HAS_PYPRESENCE:
            logger.info("pypresence module not installed, Discord RPC disabled.")
            return

        if not self.is_enabled():
            logger.info("Discord RPC is disabled in application settings.")
            return

        with self._lock:
            if self.connected or self._connecting:
                return
            self._connecting = True

        def _connect():
            try:
                self.rpc = Presence(self.client_id)
                self.rpc.connect()
                self.connected = True
                logger.info("Discord RPC connected successfully.")
            except Exception as e:
                self.connected = False
                logger.debug(f"Discord RPC connection attempt failed (Discord client not running): {e}")
            finally:
                self._connecting = False

        threading.Thread(target=_connect, daemon=True).start()

    def update_presence(
        self,
        track_title: str,
        track_artist: str = "",
        is_playing: bool = True,
        duration_sec: float = 0,
        current_pos_sec: float = 0
    ):
        """Update Discord user presence status with current track details."""
        if not self.is_enabled():
            if self.connected:
                self.clear_presence()
            return

        if not self.connected:
            self.start()
            if not self.connected or not self.rpc:
                return

        try:
            title = (track_title or "Неизвестный трек").strip()
            artist = (track_artist or "AURA Music").strip()
            now = int(time.time())

            # Track change reset
            if self.current_track != title or self.current_artist != artist:
                self.current_track = title
                self.current_artist = artist
                self.start_time = now - int(current_pos_sec if current_pos_sec > 0 else 0)

            if is_playing:
                # Construct Rich Presence payload
                payload = {
                    "details": title[:128],
                    "state": f"от {artist}"[:128] if artist else "AURA Music Player",
                    "large_image": "aura_logo",
                    "large_text": "AURA Music Player",
                    "small_image": "play",
                    "small_text": "Воспроизводится",
                    "buttons": [
                        {"label": "AURA Music", "url": "https://github.com/PoviceProgrammer/NeDotify"}
                    ]
                }

                # Add progress timestamps if duration is known
                if duration_sec and duration_sec > 0:
                    start_ts = now - int(current_pos_sec if current_pos_sec > 0 else 0)
                    end_ts = start_ts + int(duration_sec)
                    payload["start"] = start_ts
                    payload["end"] = end_ts
                elif self.start_time:
                    payload["start"] = self.start_time

                self.rpc.update(**payload)
            else:
                self.rpc.update(
                    details=title[:128],
                    state=f"от {artist} (На паузе)"[:128],
                    large_image="aura_logo",
                    large_text="AURA Music Player",
                    small_image="pause",
                    small_text="На паузе",
                    buttons=[
                        {"label": "AURA Music", "url": "https://github.com/PoviceProgrammer/NeDotify"}
                    ]
                )
        except Exception as e:
            logger.debug(f"Failed to update Discord RPC: {e}")
            self.connected = False

    def clear_presence(self):
        """Clear presence status from Discord profile."""
        if not self.connected or not self.rpc:
            return
        try:
            self.rpc.clear()
        except Exception:
            pass

    def stop(self):
        """Disconnect Discord RPC."""
        self.clear_presence()
        if self.rpc:
            try:
                self.rpc.close()
            except Exception:
                pass
            self.rpc = None
            self.connected = False
