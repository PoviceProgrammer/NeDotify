"""
AURA Music - Audio Engine (Frontend-driven)
Manages the playback queue and track resolution. 
Playback is handled entirely by HTML5 Audio on the frontend.
"""

import os
import logging
from typing import Optional, Callable
from audio.queue import PlaybackQueue

logger = logging.getLogger(__name__)





class AudioEngine:
    """
    Queue manager and state coordinator for the JS-based audio player.
    """



    def __init__(self):
        self.queue = PlaybackQueue()
        self.proxy = None
        self._on_track_changed = None
        self._on_queue_end = None

        self.app_core = None





    def cleanup(self):
        pass




    def play_track(self, track: dict) -> None:
        if not track:
            return None
        self.queue.add_track(track, play_next=True)
        self.queue.next_track()
        self._notify_track_changed()

    def play_queue(self, track_list: Optional[list] = None, index: int = 0) -> None:
        if track_list is not None:
            self.queue.clear()
            for t in track_list:
                self.queue.add_track(t)
        if not self.queue.tracks:
            return None
        self.queue._current_index = index - 1
        self.next_track()

    def add_to_queue(self, track: dict, play_next: bool = False) -> None:
        self.queue.add_track(track, play_next=play_next)

    def next_track(self):
        track = self.queue.next_track()
        if track:
            self._notify_track_changed()
            return None
        if self._on_queue_end:
            self._on_queue_end()
            return None

    def prev_track(self):
        track = self.queue.previous_track()
        if track:
            self._notify_track_changed()
            return None

    def toggle_shuffle(self) -> bool:
        self.queue.shuffle = not self.queue.shuffle
        return self.queue.shuffle

    def toggle_repeat(self) -> str:
        modes = ["off", "all", "one"]
        current_idx = modes.index(self.queue.repeat)
        self.queue.repeat = modes[(current_idx + 1) % len(modes)]
        return self.queue.repeat

    def _notify_track_changed(self):
        if self._on_track_changed and self.queue.current_track:
            track = self.queue.current_track.copy()
            if not track.get("stream_url"):
                if track.get("source") == "local":
                    track["stream_url"] = track.get("url") or track.get("file_path")
                elif track.get("file_path") and os.path.exists(track["file_path"]):
                    track["stream_url"] = track["file_path"]
                elif self.proxy and getattr(self.proxy, "port", None):
                    import urllib.parse as urllib
                    t_id = track.get("id") or 0
                    src = track.get("source") or "youtube"
                    src_id = urllib.parse.quote(str(track.get("source_id") or ""))
                    title = urllib.parse.quote(str(track.get("title") or ""))
                    artist = urllib.parse.quote(str(track.get("artist") or ""))
                    proxy_url = f"http://127.0.0.1:{self.proxy.port}/api/stream?track_id={t_id}&source={src}&source_id={src_id}&title={title}&artist={artist}"
                    track["stream_url"] = proxy_url
            self._on_track_changed(track)

    def resolve_stream_url(self, track: dict) -> Optional[str]:
        if not track:
            return None
        source = track.get("source")
        source_id = track.get("source_id") or track.get("id")
        if not source:
            if track.get("url"):
                source = "local"
            else:
                source = "youtube"
        if not source_id and track.get("title"):
            source_id = f"{track.get('artist', '')} {track.get('title')}".strip()
        if source == "local":
            return track.get("url")
        if source == "youtube":
            import threading
            url = None
            if source_id and len(source_id) > 3 and " " not in source_id:
                event = threading.Event()

                def cb(*args):
                    nonlocal url
                    try:
                        url = args[0] if args else None
                        if len(args) > 1 and args[1] and track.get("id"):
                            info = args[1]
                            dur = info.get("duration", 0)
                            if dur > 0 and track.get("duration", 0) <= 0:
                                try:
                                    self.app_core.db.update_track(track["id"], duration=dur)
                                    track["duration"] = dur
                                except Exception as dbe:
                                    logger.error(f"Failed to update duration in resolve: {dbe}")
                    finally:
                        event.set()

                def err_cb(e):
                    try:
                        logger.error(f"YouTube stream resolution error: {e}")
                    finally:
                        event.set()

                try:
                    self.app_core.youtube.get_stream_url(source_id, cb, err_cb)
                except Exception:
                    event.set()
                event.wait(timeout=15)
            if url or not track.get("title"):
                return url
            search_query = f"{track.get('artist', '')} {track['title']} audio".strip()
            logger.info(f"Fallback search for failed track: {search_query}")
            search_event = threading.Event()
            search_results = []

            def s_cb(res):
                nonlocal search_results
                try:
                    search_results = res
                finally:
                    search_event.set()

            def s_err(e):
                search_event.set()

            try:
                self.app_core.youtube.search(search_query, max_results=1, callback=s_cb, error_callback=s_err)
            except Exception:
                search_event.set()
            search_event.wait(timeout=10)
            if search_results and len(search_results) > 0:
                new_id = search_results[0].get("source_id")
                if new_id:
                    logger.info(f"Fallback found new ID: {new_id}")
                    if track.get("id"):
                        try:
                            self.app_core.db.update_track(track["id"], source_id=new_id)
                        except Exception:
                            pass
                    track["source_id"] = new_id
                    event2 = threading.Event()

                    def cb2(*args):
                        nonlocal url
                        try:
                            url = args[0] if args else None
                        finally:
                            event2.set()

                    def err_cb2(e):
                        event2.set()

                    try:
                        self.app_core.youtube.get_stream_url(new_id, cb2, err_cb2)
                    except Exception:
                        event2.set()
                    event2.wait(timeout=15)
            return url
        if source == "spotify":
            import threading
            url = None
            artist = track.get("artist", "")
            title = track.get("title", "")
            search_query = f"{artist} {title}".strip()
            event = threading.Event()

            def on_searched(results):
                try:
                    if results and len(results) > 0:
                        vid = results[0].get("source_id")
                        if vid:
                            def on_stream(s_url, *args):
                                nonlocal url
                                try:
                                    url = s_url
                                finally:
                                    event.set()

                            def on_err(e):
                                event.set()

                            self.app_core.youtube.get_stream_url(vid, on_stream, on_err)
                            return
                except Exception as e:
                    logger.error(f"Spotify search err: {e}")
                event.set()

            def on_search_err(e):
                event.set()

            try:
                self.app_core.youtube.search(search_query, max_results=1, callback=on_searched, error_callback=on_search_err)
            except Exception:
                event.set()
            event.wait(timeout=10)
            return url
        if source == "soundcloud":
            import threading
            url = None
            event = threading.Event()
            sc_target = str(track.get("source_id") or track.get("source_url") or track.get("url") or f"{track.get('artist', '')} {track.get('title', '')}".strip())

            def cb(*args):
                nonlocal url
                try:
                    url = args[0] if args else None
                    if len(args) > 1 and args[1] and track.get("id"):
                        info = args[1]
                        dur = int(info.get("duration", 0) / 1000) if info.get("duration") else 0
                        if dur > 0 and track.get("duration", 0) <= 0:
                            try:
                                self.app_core.db.update_track(track["id"], duration=dur)
                                track["duration"] = dur
                            except Exception as dbe:
                                logger.error(f"Failed to update duration in resolve: {dbe}")
                finally:
                    event.set()

            def err_cb(e):
                try:
                    logger.error(f"SoundCloud stream resolution error: {e}")
                finally:
                    event.set()

            try:
                self.app_core.soundcloud.get_stream_url(sc_target, cb, err_cb)
            except Exception:
                event.set()
            event.wait(timeout=15)
            if url or not track.get("title"):
                return url
            search_query = f"{track.get('artist', '')} {track.get('title')}".strip()
            logger.info(f"SoundCloud direct stream failed, performing YouTube fallback search for: {search_query}")
            event2 = threading.Event()

            def s_cb(res):
                try:
                    if res and len(res) > 0:
                        vid = res[0].get("source_id")
                        if vid:
                            def cb2(*args):
                                nonlocal url
                                try:
                                    url = args[0] if args else None
                                finally:
                                    event2.set()

                            def err_cb2(e):
                                event2.set()

                            self.app_core.youtube.get_stream_url(vid, cb2, err_cb2)
                            return
                except Exception as e:
                    logger.error(f"SoundCloud fallback err: {e}")
                event2.set()

            def s_err(e):
                event2.set()

            try:
                self.app_core.youtube.search(search_query, max_results=1, callback=s_cb, error_callback=s_err)
            except Exception:
                event2.set()
            event2.wait(timeout=10)
            return url
        if source == "yandex":
            import threading
            url = None
            event = threading.Event()

            def cb(*args):
                nonlocal url
                try:
                    url = args[0] if args else None
                finally:
                    event.set()

            def err_cb(e):
                try:
                    logger.error(f"Yandex stream resolution error: {e}")
                finally:
                    event.set()

            try:
                self.app_core.yandex.get_stream_url(source_id, cb, err_cb)
            except Exception:
                event.set()
            event.wait(timeout=10)
            return url
        return None