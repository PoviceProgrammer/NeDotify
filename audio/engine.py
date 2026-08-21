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
        self.queue.set_tracks([track], start_index=0)
        self._notify_track_changed()

    def play_queue(self, track_list: Optional[list] = None, index: int = 0) -> None:
        if track_list is not None:
            safe_index = max(0, min(index, len(track_list) - 1)) if track_list else 0
            self.queue.set_tracks(track_list, start_index=safe_index)
        if not self.queue.tracks:
            return None
        self._notify_track_changed()

    def add_to_queue(self, track: dict, play_next: bool = False) -> None:
        self.queue.add_track(track, play_next=play_next)

    def next_track(self):
        """Advance the queue and notify the UI. Returns the new track or None at the end."""
        track = self.queue.next_track()
        if track:
            self._notify_track_changed()
            return track
        if self._on_queue_end:
            self._on_queue_end()
        return None

    def prev_track(self):
        """Step back in the queue and notify the UI. Returns the new track or None."""
        track = self.queue.previous_track()
        if track:
            self._notify_track_changed()
        return track

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
                import urllib.parse as urllib_parse
                fp = track.get("file_path")
                if not fp and track.get("source") == "local":
                    fp = track.get("url")
                if fp and (fp.startswith("http://") or fp.startswith("https://")):
                    # Remote stream URL: serve through proxy (SSRF-guarded), never expose raw URL
                    if self.proxy and getattr(self.proxy, "port", None):
                        src = track.get("source") or "youtube"
                        src_id = urllib_parse.quote(str(track.get("source_id") or ""))
                        title = urllib_parse.quote(str(track.get("title") or ""))
                        artist = urllib_parse.quote(str(track.get("artist") or ""))
                        if not any(d in fp for d in ("youtube.com", "youtu.be", "soundcloud.com", "music.yandex.ru")):
                            quoted_url = urllib_parse.quote(fp)
                            proxy_url = (f"http://127.0.0.1:{self.proxy.port}/?url={quoted_url}&source={src}"
                                         f"&source_id={src_id}&title={title}&artist={artist}"
                                         f"{self.proxy.auth_query()}")
                        else:
                            t_id = track.get("id") or 0
                            proxy_url = (f"http://127.0.0.1:{self.proxy.port}/api/stream?track_id={t_id}&source={src}"
                                         f"&source_id={src_id}&title={title}&artist={artist}"
                                         f"{self.proxy.auth_query()}")
                        track["stream_url"] = proxy_url
                elif fp and os.path.exists(fp):
                    # Local cached file: always serve through proxy - browsers cannot play raw fs paths
                    if self.proxy and getattr(self.proxy, "port", None):
                        t_id = track.get("id") or 0
                        src = track.get("source") or "youtube"
                        src_id = urllib_parse.quote(str(track.get("source_id") or ""))
                        title = urllib_parse.quote(str(track.get("title") or ""))
                        artist = urllib_parse.quote(str(track.get("artist") or ""))
                        track["stream_url"] = (f"http://127.0.0.1:{self.proxy.port}/api/stream?track_id={t_id}&source={src}"
                                               f"&source_id={src_id}&title={title}&artist={artist}"
                                               f"{self.proxy.auth_query()}")
                # else: stream not resolved yet - leave stream_url empty; frontend shows loading state
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

        # C-3: cache layer + single-flight in front of the network cascade
        resolver = getattr(self.app_core, "resolver", None) if self.app_core else None
        if resolver is not None:
            cached = resolver.get_cached_url(source, source_id)
            if cached:
                return cached

            def _network():
                try:
                    return self._resolve_via_network(track), None
                except Exception as e:
                    return None, str(e)

            return resolver.resolve(source, source_id, _network)

        return self._resolve_via_network(track)

    def _resolve_via_network(self, track: dict) -> Optional[str]:
        """Full network resolution cascade: source service -> search fallbacks (C-3)."""
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
                    event.set()

                try:
                    video_url = f"https://www.youtube.com/watch?v={source_id}" if not str(source_id).startswith("http") else str(source_id)
                    self.app_core.youtube.get_stream_url(video_url, cb, err_cb)
                except Exception:
                    event.set()
                event.wait(timeout=10)

            if url:
                return url

            # Tier 1 Fallback: SoundCloud Search (fast, no bot challenges, high reliability)
            track_title = track.get("title", "")
            track_artist = track.get("artist", "")

            # If title is missing, equal to source_id, or looks like a 11-char hash
            if not track_title or track_title == source_id or (len(track_title) == 11 and " " not in track_title):
                try:
                    import urllib.request, json
                    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={source_id}&format=json"
                    req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        o_data = json.loads(resp.read().decode('utf-8'))
                        if o_data.get('title'):
                            track_title = o_data['title']
                            track['title'] = track_title
                        if o_data.get('author_name') and not track_artist:
                            track_artist = o_data['author_name']
                            track['artist'] = track_artist
                except Exception:
                    logger.debug("err_cb: suppressed exception", exc_info=True)
            
            import re
            def _build_queries(artist_str, title_str):
                c_queries = []
                def clean_noise(text):
                    if not text: return ""
                    t = re.sub(r'[\(\[\{][^\)\]\}]*(?:official|video|audio|клип|релиз|remix|edit|lyric|prod|ft\.|feat\.|4k|hd|hq|live|topic)[^\)\]\}]*[\)\]\}]', '', text, flags=re.IGNORECASE)
                    t = re.sub(r'\b(official\s+video|official\s+audio|music\s+video|lyric\s+video|премьера\s+клипа|клип|релиз)\b', '', t, flags=re.IGNORECASE)
                    t = re.sub(r'[\(\[\{]\s*[\)\]\}]', '', t)
                    return ' '.join(t.split()).strip()

                clean_t = clean_noise(title_str)
                clean_a = clean_noise(artist_str)

                if ' - ' in clean_t:
                    parts = clean_t.split(' - ', 1)
                    if len(parts) == 2:
                        c_queries.append(f"{parts[0].strip()} {parts[1].strip()}")
                        c_queries.append(clean_t.replace(' - ', ' '))
                        c_queries.append(parts[1].strip())

                if clean_a and clean_t:
                    clean_a_short = re.sub(r'\s*-\s*Topic\b', '', clean_a, flags=re.IGNORECASE).strip()
                    if clean_a_short.lower() not in clean_t.lower():
                        c_queries.append(f"{clean_a_short} {clean_t}")
                    else:
                        c_queries.append(clean_t)
                        
                if clean_t:
                    c_queries.append(clean_t)

                raw = f"{artist_str} {title_str}".strip()
                if raw:
                    c_queries.append(raw)

                out = []
                for q in c_queries:
                    qn = ' '.join(q.split()).strip()
                    if qn and len(qn) > 1 and qn not in out:
                        out.append(qn)
                return out

            candidates = _build_queries(track_artist, track_title)
            for sc_query in candidates:
                logger.info(f"YouTube resolution failed; trying SoundCloud fallback search for: {sc_query}")
                sc_event = threading.Event()
                sc_results = []

                def sc_cb(res):
                    if res:
                        sc_results.extend(res)
                    sc_event.set()

                try:
                    if hasattr(self.app_core, "soundcloud") and self.app_core.soundcloud:
                        self.app_core.soundcloud.search(sc_query, max_results=3, callback=sc_cb, error_callback=lambda e: sc_event.set())
                except Exception as ex:
                    logger.debug(f"SoundCloud fallback search error: {ex}")
                    sc_event.set()

                sc_event.wait(timeout=3.0)

                if sc_results:
                    target_sc = sc_results[0].get("source_url") or sc_results[0].get("source_id")
                    sc_stream_event = threading.Event()

                    def _sc_done(s_url, s_meta=None):
                        nonlocal url
                        url = s_url
                        sc_stream_event.set()

                    try:
                        self.app_core.soundcloud.get_stream_url(target_sc, _sc_done, lambda e: sc_stream_event.set())
                    except Exception:
                        sc_stream_event.set()

                    sc_stream_event.wait(timeout=3.5)
                    if url:
                        logger.info(f"SoundCloud fallback stream resolved successfully: {url[:50]}...")
                        if track.get("id"):
                            try:
                                self.app_core.db.cache_stream(source, source_id, url)
                            except Exception:
                                logger.debug("_sc_done: suppressed exception", exc_info=True)
                        return url

            # Tier 2 Fallback: YouTube Search Alternative
            search_query = f"{track_artist} {track_title} audio".strip()
            if search_query:
                search_event = threading.Event()
                search_results = []

                def s_cb(res):
                    if res:
                        search_results.extend(res)
                    search_event.set()

                try:
                    self.app_core.youtube.search(search_query, max_results=1, callback=s_cb, error_callback=lambda e: search_event.set())
                except Exception:
                    search_event.set()

                search_event.wait(timeout=6)
                if search_results and len(search_results) > 0:
                    new_id = search_results[0].get("source_id")
                    if new_id and new_id != source_id:
                        event2 = threading.Event()

                        def cb2(*args):
                            nonlocal url
                            try:
                                url = args[0] if args else None
                            finally:
                                event2.set()

                        try:
                            self.app_core.youtube.get_stream_url(new_id, cb2, lambda e: event2.set())
                        except Exception:
                            event2.set()
                        event2.wait(timeout=8)

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