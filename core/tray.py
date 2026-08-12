import threading
import logging
from typing import Optional, Any

try:
    from PIL import Image
    import pystray
    from pystray import MenuItem as item
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

logger = logging.getLogger(__name__)












class TrayIcon:
    def __init__(self, api, icon_path):
        self.api = api
        self.icon_path = icon_path




        self.icon: Optional[Any] = None

    def create_image(self):
        try:
            return Image.open(self.icon_path)
        except Exception:
            image = Image.new("RGB", (64, 64), color=(30, 215, 96))
            return image


    def on_show(self, icon, item):
        if self.api and self.api._window:

            self.api._window.restore()


    def on_play_pause(self, icon, item):

        if self.api and hasattr(self.api, "_core") and self.api._core.engine:
            self.api.play_pause()



    def on_next(self, icon, item):
        if self.api and hasattr(self.api, "_core") and self.api._core.engine:
            self.api.next_track()



    def on_prev(self, icon, item):
        if self.api and hasattr(self.api, "_core") and self.api._core.engine:
            self.api.prev_track()



    def on_exit(self, icon, item):
        icon.stop()
        if self.api and self.api._window:

            self.api._window.destroy()


    def start(self):
        if not HAS_PYSTRAY:
            return


        def _run_tray():
            try:
                image = self.create_image()
                menu = (
                    item("Show AURA Music", self.on_show, default=True),
                    item("Play / Pause", self.on_play_pause),
                    item("Next Track", self.on_next),
                    item("Exit", self.on_exit),
                )
                self.icon = pystray.Icon("AURA Music", image, "AURA Music", menu)
                self.icon.run()
            except Exception as e:
                logger.warning(f"Failed to start system tray: {e}")

        threading.Thread(target=_run_tray, daemon=True).start()
