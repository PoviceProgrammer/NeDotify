import logging
import threading
import time

logger = logging.getLogger(__name__)

try:
    from pypresence import Presence
    HAS_PYPRESENCE = True
except ImportError:
    HAS_PYPRESENCE = False







class DiscordRPCService:
    def __init__(self, client_id="1329524021200158781"):
        self.client_id = client_id
        self.rpc = None
        self.connected = False
        self.current_track = None
        self.start_time = None



    def start(self):



        if not HAS_PYPRESENCE:


            return

        def _connect():
            try:
                self.rpc = Presence(self.client_id)
                self.rpc.connect()
                self.connected = True
                logger.info("Discord RPC connected.")
            except Exception as e:




                logger.debug(f"Discord RPC connection failed (Discord not running or invalid Client ID): {e}")




        threading.Thread(target=_connect, daemon=True).start()

    def update_presence(self, track_title, track_artist, is_playing):
        if not self.connected or not self.rpc:
            return

        try:
            if is_playing:
                if self.current_track != track_title:
                    self.start_time = int(time.time())
                    self.current_track = track_title
                self.rpc.update(
                    state=track_artist if track_artist else "Unknown Artist",
                    details=track_title,
                    start=self.start_time,
                    large_text="AURA Music",
                )
            else:
                self.rpc.update(
                    state=track_artist if track_artist else "Unknown Artist",
                    details=track_title,
                    large_text="AURA Music",





                )




        except Exception as e:
            logger.debug(f"Failed to update Discord RPC: {e}")
            self.connected = False

    def clear_presence(self):
        if not self.connected or not self.rpc:
            return

        try:
            self.rpc.clear()
        except Exception:
            pass
