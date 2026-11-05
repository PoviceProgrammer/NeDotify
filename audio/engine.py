"""
NeDotify - Audio Engine (Frontend-driven)
Manages the playback queue and track resolution. 
Playback is handled entirely by HTML5 Audio on the frontend.
"""

import os
import time
import logging
import threading
from functools import wraps
from typing import Optional, Callable
from audio.queue import PlaybackQueue
from utils.url_safety import is_safe_media_url

logger = logging.getLogger(__name__)

def _playback_command(method):
    @wraps(method)
    def serialized(self, *args, **kwargs):
        with self.command_lock:
            return method(self, *args, **kwargs)
    return serialized





class AudioEngine:
    """
    Queue manager and state coordinator for the JS-based audio player.
    """



    def __init__(self):
        self.command_lock = threading.RLock()
        self.queue = PlaybackQueue()
        self.proxy = None
        self._on_track_changed = None
        self._on_queue_end = None

        self.app_core = None

    @_playback_command
    def play_track(self, track: dict) -> None:
        if not track:
            return None
        self.queue.set_tracks([track], start_index=0)
        self._notify_track_changed()

    @_playback_command
    def play_queue(self, track_list: Optional[list] = None, index: int = 0) -> None:
        if track_list is not None:
            # An empty replacement is commonly produced by transient UI state
            # (for example, an unhydrated playlist). Do not silently erase the
            # active queue without a corresponding playback transition.
            if not track_list:
                return None
            safe_index = max(0, min(index, len(track_list) - 1)) if track_list else 0
            self.queue.set_tracks(track_list, start_index=safe_index)
        if not self.queue.tracks:
            return None
        self._notify_track_changed()

    @_playback_command
    def add_to_queue(self, track: dict, play_next: bool = False) -> None:
        self.queue.add_track(track, play_next=play_next)

    @_playback_command
    def add_tracks_to_queue(self, tracks: list) -> None:
        self.queue.add_tracks(tracks)

    @_playback_command
    def next_track(self, force_advance: bool = False):
        """Advance the queue and notify the UI. Returns the new track or None at the end."""
        if force_advance:
            try:
                track = self.queue.next_track(force_advance=True)
            except TypeError:
                track = self.queue.next_track()
        else:
            track = self.queue.next_track()
        if track:
            self._notify_track_changed()
            return track
        if self._on_queue_end:
            self._on_queue_end()
        return None

    @_playback_command
    def prev_track(self):
        """Step back in the queue and notify the UI. Returns the new track or None."""
        track = self.queue.previous_track()
        if track:
            self._notify_track_changed()
        return track

    @_playback_command
    def toggle_shuffle(self) -> bool:
        return self.queue.toggle_shuffle()

    @_playback_command
    def toggle_repeat(self) -> str:
        return self.queue.toggle_repeat()

    def _notify_track_changed(self):
        current = self.queue.current_track
        if self._on_track_changed and current:
            track = current.copy()
            if not track.get("stream_url"):
                import urllib.parse as urllib_parse
                fp = track.get("file_path")
                if not fp and track.get("source") == "local":
                    fp = track.get("url")
                fp = str(fp) if fp else fp
                if fp and (fp.startswith("http://") or fp.startswith("https://")):
                    # Remote stream URL: serve through proxy (SSRF-guarded), never expose raw URL
                    if self.proxy and getattr(self.proxy, "port", None):
                        src = urllib_parse.quote(str(track.get("source") or "youtube"), safe="")
                        src_id = urllib_parse.quote(str(track.get("source_id") or ""))
                        title = urllib_parse.quote(str(track.get("title") or ""))
                        artist = urllib_parse.quote(str(track.get("artist") or ""))
                        if not any(d in fp for d in ("youtube.com", "youtu.be", "soundcloud.com", "music.yandex.ru")):
                            quoted_url = urllib_parse.quote(fp)
                            proxy_url = (f"http://127.0.0.1:{self.proxy.port}/?url={quoted_url}&source={src}"
                                         f"&source_id={src_id}&title={title}&artist={artist}"
                                         f"{self.proxy.auth_query()}")
                        else:
                            t_id = urllib_parse.quote(str(track.get("id") or 0), safe="")
                            proxy_url = (f"http://127.0.0.1:{self.proxy.port}/api/stream?track_id={t_id}&source={src}"
                                         f"&source_id={src_id}&title={title}&artist={artist}"
                                         f"{self.proxy.auth_query()}")
                        track["stream_url"] = proxy_url
                elif fp and os.path.exists(fp):
                    # Local cached file: always serve through proxy - browsers cannot play raw fs paths
                    if self.proxy and getattr(self.proxy, "port", None):
                        t_id = track.get("id") or 0
                        src = track.get("source") or "local"
                        src_id = urllib_parse.quote(str(track.get("source_id") or ""))
                        title = urllib_parse.quote(str(track.get("title") or ""))
                        artist = urllib_parse.quote(str(track.get("artist") or ""))
                        quoted_fp = urllib_parse.quote(str(fp))
                        track["stream_url"] = (f"http://127.0.0.1:{self.proxy.port}/api/stream?url={quoted_fp}"
                                               f"&track_id={t_id}&source={src}&source_id={src_id}"
                                               f"&title={title}&artist={artist}{self.proxy.auth_query()}")
                # else: stream not resolved yet - leave stream_url empty; frontend shows loading state
            self._on_track_changed(track)

    def _source_enabled(self, source):
        settings = getattr(self.app_core, 'settings', None)
        return not settings or settings.get('services', str(source) + '_enabled', True) is not False

    def resolve_stream_url(self, track: dict, cancel_token: Optional[Callable[[], bool]] = None) -> Optional[str]:
        if not track or (cancel_token and cancel_token()):
            return None
        source = track.get("source")
        # `id` is a local database row id, never a provider identifier.
        source_id = track.get("source_id")
        if not source_id and track.get("title"):
            # Use metadata only as a resolver cache/single-flight key. The
            # network resolver still sees the original track and must search.
            source_id = f"{track.get('artist') or ''} {track.get('title') or ''}".strip()
        if not source:
            if track.get("file_path") or track.get("url"):
                source = "local"
            else:
                source = "youtube"
        if source == "local":
            return track.get("file_path") or track.get("url")
        local_file = track.get('file_path')
        if local_file and os.path.isfile(str(local_file)):
            return str(local_file)
        if not self._source_enabled(source):
            return None

        # C-3: cache layer + single-flight in front of the network cascade
        resolver = getattr(self.app_core, "resolver", None) if self.app_core else None
        # Legacy resolver entries do not record which fallback produced a URL.
        # With a provider opted out, verify through the guarded cascade instead
        # of reusing an unlabelled cross-provider result.
        if resolver is not None and self._source_enabled('youtube') and self._source_enabled('soundcloud'):
            cached = resolver.get_cached_url(source, source_id)
            if cached:
                return cached

            def _network():
                if cancel_token and cancel_token():
                    return None, "cancelled"
                try:
                    return self._resolve_via_network(track, cancel_token=cancel_token), None
                except Exception as e:
                    return None, str(e)

            return resolver.resolve(source, source_id, _network)

        return self._resolve_via_network(track, cancel_token=cancel_token)

    def _resolve_via_network(self, track: dict, cancel_token: Optional[Callable[[], bool]] = None) -> Optional[str]:
        """Full network resolution cascade: source service -> search fallbacks (C-3)."""
        if not track or (cancel_token and cancel_token()):
            return None
        source = track.get("source")
        # `id` is a local database row id, never a provider identifier.
        source_id = track.get("source_id")
        if not source:
            if track.get("file_path") or track.get("url"):
                source = "local"
            else:
                source = "youtube"
        if source == "local":
            return track.get("file_path") or track.get("url")
        if not self._source_enabled(source):
            return None

        def _wait(evt, timeout: float) -> bool:
            if not cancel_token:
                return evt.wait(timeout=timeout)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cancel_token():
                    return False
                rem = deadline - time.monotonic()
                if evt.wait(timeout=min(0.15, rem)):
                    return True
            return evt.is_set()
        if source == "youtube":
            import threading
            url = None
            # ``source_id`` above falls back to ``track['id']`` (a row id), so it
            # is not necessarily a str: len()/"in" on an int raised TypeError and
            # killed the whole cascade before the fallbacks could run. A row id is
            # not a video id either, so only a real string qualifies here.
            direct_id = source_id if isinstance(source_id, str) else ""
            if direct_id.startswith("http") and not is_safe_media_url(direct_id):
                direct_id = ""
            if len(direct_id) > 3 and " " not in direct_id:
                event = threading.Event()

                def cb(*args):
                    nonlocal url
                    try:
                        url = args[0] if args else None
                        if len(args) > 1 and isinstance(args[1], dict) and args[1] and track.get("id"):
                            info = args[1]
                            try:
                                dur = float(info.get("duration") or 0)
                            except (TypeError, ValueError):
                                dur = 0
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
                _wait(event, 10)

            if cancel_token and cancel_token():
                return None
            if url:
                return url

            # A database row without a provider ID can only be resolved through
            # a metadata-verified search. Never turn the local row ID into a
            # YouTube video ID, and never accept the first search hit blindly.
            if not direct_id and track.get("title"):
                query = f"{track.get('artist') or ''} {track.get('title') or ''}".strip()
                search_event = threading.Event()
                search_results = []

                def metadata_search_done(results):
                    if isinstance(results, list):
                        search_results.extend(results)
                    search_event.set()

                try:
                    self.app_core.youtube.search(
                        query, max_results=5, callback=metadata_search_done,
                        error_callback=lambda _error: search_event.set(),
                    )
                except Exception:
                    search_event.set()
                _wait(search_event, 6)
                if cancel_token and cancel_token():
                    return None

                from core.playback_recovery import same_recording

                candidate = next((item for item in search_results
                                  if isinstance(item, dict)
                                  and str(item.get("source") or "").lower() == "youtube"
                                  and item.get("source_id")
                                  and same_recording(track, item)), None)
                candidate_id = candidate.get("source_id") if candidate else None
                if isinstance(candidate_id, str) and candidate_id.strip():
                    candidate_url = candidate.get("source_url") or candidate_id
                    if candidate_url.startswith("http") and not is_safe_media_url(candidate_url):
                        candidate_url = None
                    if candidate_url:
                        candidate_event = threading.Event()
                        candidate_stream = None

                        def metadata_stream_done(stream_url, metadata=None):
                            nonlocal candidate_stream
                            try:
                                if (stream_url and isinstance(metadata, dict) and metadata.get("title")
                                        and not same_recording(track, metadata)):
                                    return
                                candidate_stream = stream_url
                            finally:
                                candidate_event.set()

                        try:
                            self.app_core.youtube.get_stream_url(
                                candidate_url, metadata_stream_done,
                                lambda _error: candidate_event.set(),
                            )
                        except Exception:
                            candidate_event.set()
                        _wait(candidate_event, 8)
                        if cancel_token and cancel_token():
                            return None
                        if candidate_stream:
                            return candidate_stream
                # With no source ID there is no trustworthy direct target.
                # Do not let the later legacy fallback tiers accept their
                # first, unverified result after this metadata check failed.
                return None

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

            # Whole-cascade wall-clock budget: every stage below shares it.
            # Previously only the SoundCloud loop was bounded while the Tier-2
            # YouTube retries could add another ~14s inside a proxy thread.
            cascade_deadline = time.monotonic() + 20.0
            candidates = _build_queries(track_artist, track_title)[:3]
            for sc_query in candidates if self._source_enabled('soundcloud') else []:
                if (cancel_token and cancel_token()) or time.monotonic() >= cascade_deadline:
                    break
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
                    else:
                        # No provider: no callback will ever arrive, so waiting
                        # below would burn min(2.5, budget) per candidate on a
                        # stage that cannot run at all.
                        sc_event.set()
                except Exception as ex:
                    logger.debug(f"SoundCloud fallback search error: {ex}")
                    sc_event.set()

                remaining = max(0.5, cascade_deadline - time.monotonic())
                _wait(sc_event, min(2.5, remaining))
                if cancel_token and cancel_token():
                    return None

                # BUG-A1-005: never take the first SoundCloud hit blindly —
                # verify it against the requested recording before extraction.
                from services.recording_selection import select_recording, stream_matches
                sc_candidate = select_recording(track, sc_results)
                if sc_candidate:
                    target_sc = sc_candidate.get("source_url") or sc_candidate.get("source_id")
                    sc_stream_event = threading.Event()

                    def _sc_done(s_url, s_meta=None):
                        nonlocal url
                        if stream_matches(track, s_meta,
                                          requested_id=str(sc_candidate.get('source_id') or '')):
                            url = s_url
                        sc_stream_event.set()

                    try:
                        self.app_core.soundcloud.get_stream_url(target_sc, _sc_done, lambda e: sc_stream_event.set())
                    except Exception:
                        sc_stream_event.set()

                    remaining_stream = max(0.5, cascade_deadline - time.monotonic())
                    _wait(sc_stream_event, min(3.0, remaining_stream))
                    if cancel_token and cancel_token():
                        return None
                    if url:
                        logger.info(f"SoundCloud fallback stream resolved successfully: {url[:50]}...")
                        if track.get("id"):
                            try:
                                self.app_core.db.cache_stream(source, source_id, url)
                            except Exception:
                                logger.debug("_sc_done: suppressed exception", exc_info=True)
                        return url

            # Tier 2 Fallback: YouTube Search Alternative (shares the cascade budget)
            search_query = f"{track_artist} {track_title} audio".strip()
            if search_query and time.monotonic() < cascade_deadline:
                search_event = threading.Event()
                search_results = []

                def s_cb(res):
                    if res:
                        search_results.extend(res)
                    search_event.set()

                try:
                    self.app_core.youtube.search(search_query, max_results=5, callback=s_cb, error_callback=lambda e: search_event.set())
                except Exception:
                    search_event.set()

                remaining_search = max(0.5, cascade_deadline - time.monotonic())
                _wait(search_event, min(6.0, remaining_search))
                if cancel_token and cancel_token():
                    return None
                if search_results and len(search_results) > 0 and time.monotonic() < cascade_deadline:
                    # BUG-A1-005: the alternative video must be the same
                    # recording (and never the very video that just failed).
                    from services.recording_selection import select_recording, stream_matches
                    candidates = [item for item in search_results
                                  if isinstance(item, dict)
                                  and str(item.get("source_id") or "") not in ("", str(source_id))]
                    verified = select_recording(track, candidates)
                    new_id = (verified or {}).get("source_id")
                    if new_id:
                        event2 = threading.Event()

                        def cb2(*args):
                            nonlocal url
                            try:
                                s_url = args[0] if args else None
                                metadata = args[1] if len(args) > 1 else None
                                if stream_matches(track, metadata, requested_id=str(new_id)):
                                    url = s_url
                            finally:
                                event2.set()

                        try:
                            self.app_core.youtube.get_stream_url(new_id, cb2, lambda e: event2.set())
                        except Exception:
                            event2.set()
                        remaining_stream = max(0.5, cascade_deadline - time.monotonic())
                        _wait(event2, min(8.0, remaining_stream))
                        if cancel_token and cancel_token():
                            return None

            return url
        if source == 'deezer':
            import threading
            service = getattr(self.app_core, 'deezer', None)
            if service is None:
                return None
            event = threading.Event()
            streams = []
            def resolved_deezer(url, *_args):
                streams.append(url)
                event.set()
            try:
                service.get_stream_url(source_id, callback=resolved_deezer,
                                       error_callback=lambda _error: event.set())
            except Exception:
                return None
            _wait(event, 25)
            if cancel_token and cancel_token():
                return None
            return streams[0] if streams else None
        if source == "spotify":
            if not self._source_enabled('youtube'):
                return None
            import threading
            url = None
            artist = track.get("artist", "")
            title = track.get("title", "")
            settings = getattr(self.app_core, "settings", None)

            # BUG-A1-001/002/S4-006: a Spotify row's source_id is a search
            # expression, so the recording it maps to must be verified, and the
            # first verified video id is persisted so every later resolve (and
            # the self-heal cascade) returns the SAME recording.
            from services.recording_selection import (
                remembered_video_id, remember_video_id, search_verified, stream_matches,
            )

            identity_keys = [source_id, f"ytsearch1: {artist} - {title}".strip()]
            persisted = ''
            for key in identity_keys:
                persisted = remembered_video_id(settings, source, key)
                if persisted:
                    break

            if persisted:
                event = threading.Event()

                def on_persisted_stream(s_url, metadata=None):
                    nonlocal url
                    try:
                        if stream_matches(track, metadata, requested_id=persisted):
                            url = s_url
                    finally:
                        event.set()

                try:
                    self.app_core.youtube.get_stream_url(
                        f"https://www.youtube.com/watch?v={persisted}",
                        on_persisted_stream, lambda _error: event.set(),
                    )
                except Exception:
                    event.set()
                event.wait(timeout=10)
                if url:
                    return url

            search_query = f"{artist} {title}".strip()
            candidate = search_verified(self.app_core.youtube, track, query=search_query,
                                        timeout=8.0) if search_query else None
            candidate_id = str((candidate or {}).get("source_id") or "")
            if not candidate_id:
                # No verifiable recording: report failure instead of playing
                # whatever the provider ranked first (BUG-A1-001).
                return None
            candidate_url = candidate.get("source_url") or candidate_id
            if str(candidate_url).startswith("http") and not is_safe_media_url(candidate_url):
                return None

            event = threading.Event()

            def on_stream(s_url, metadata=None):
                nonlocal url
                try:
                    if stream_matches(track, metadata, requested_id=candidate_id):
                        url = s_url
                        for key in identity_keys:
                            if key:
                                remember_video_id(settings, source, key, candidate_id)
                finally:
                    event.set()

            def on_err(_error):
                event.set()

            try:
                self.app_core.youtube.get_stream_url(candidate_url, on_stream, on_err)
            except Exception:
                event.set()
            _wait(event, 10)
            if cancel_token and cancel_token():
                return None
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
                    if len(args) > 1 and isinstance(args[1], dict) and args[1] and track.get("id"):
                        info = args[1]
                        try:
                            dur = float(info.get("duration") or 0)
                        except (TypeError, ValueError):
                            dur = 0
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
                if sc_target.startswith("http") and not is_safe_media_url(sc_target):
                    logger.warning("Rejected unsafe SoundCloud URL in resolve")
                    event.set()
                else:
                    self.app_core.soundcloud.get_stream_url(sc_target, cb, err_cb)
            except Exception:
                event.set()
            _wait(event, 15)
            if cancel_token and cancel_token():
                return None
            if url or not track.get("title"):
                return url
            search_query = f"{track.get('artist', '')} {track.get('title')}".strip()
            logger.info(f"SoundCloud direct stream failed, performing YouTube fallback search for: {search_query}")

            # Same verification rule as every other fallback: the top hit is
            # only a candidate until it matches the requested recording.
            from services.recording_selection import search_verified, stream_matches
            youtube_service = getattr(self.app_core, 'youtube', None) if self._source_enabled('youtube') else None
            candidate = search_verified(youtube_service, track, query=search_query,
                                        timeout=8.0) if search_query and youtube_service else None
            candidate_id = str((candidate or {}).get("source_id") or "")
            if not candidate_id:
                return url
            candidate_url = candidate.get("source_url") or candidate_id
            if str(candidate_url).startswith("http") and not is_safe_media_url(candidate_url):
                return url
            event2 = threading.Event()

            def cb2(*args):
                nonlocal url
                try:
                    s_url = args[0] if args else None
                    metadata = args[1] if len(args) > 1 else None
                    if stream_matches(track, metadata, requested_id=candidate_id):
                        url = s_url
                finally:
                    event2.set()

            try:
                self.app_core.youtube.get_stream_url(candidate_url, cb2, lambda e: event2.set())
            except Exception:
                event2.set()
            _wait(event2, 10)
            if cancel_token and cancel_token():
                return None
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
            _wait(event, 10)
            if cancel_token and cancel_token():
                return None
            return url
        if source == "vk":
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
                    logger.error(f"VK stream resolution error: {e}")
                finally:
                    event.set()

            try:
                vk_service = getattr(self.app_core, "vk", None) if self.app_core else None
                if vk_service and hasattr(vk_service, "get_stream_url"):
                    vk_target = str(source_id).strip() if str(source_id).strip().startswith(("http://", "https://")) else f"https://vk.com/audio?id={source_id}"
                    vk_service.get_stream_url(vk_target, cb, err_cb)
                else:
                    event.set()
            except Exception as ex:
                logger.debug(f"VK stream error: {ex}")
                event.set()
            _wait(event, 10)
            if cancel_token and cancel_token():
                return None
            if url:
                return url

            # Fallback to YouTube search for VK track if direct resolution fails
            artist = track.get("artist", "")
            title = track.get("title", "")
            search_query = f"{artist} {title}".strip()
            youtube_service = getattr(self.app_core, "youtube", None) if self._source_enabled("youtube") else None
            if search_query and youtube_service:
                from services.recording_selection import search_verified, stream_matches
                candidate = search_verified(youtube_service, track, query=search_query, timeout=8.0)
                candidate_id = str((candidate or {}).get("source_id") or "")
                if candidate_id:
                    candidate_url = candidate.get("source_url") or candidate_id
                    if not (str(candidate_url).startswith("http") and not is_safe_media_url(candidate_url)):
                        event2 = threading.Event()

                        def cb2(*args):
                            nonlocal url
                            try:
                                s_url = args[0] if args else None
                                metadata = args[1] if len(args) > 1 else None
                                if stream_matches(track, metadata, requested_id=candidate_id):
                                    url = s_url
                            finally:
                                event2.set()

                        try:
                            youtube_service.get_stream_url(candidate_url, cb2, lambda e: event2.set())
                        except Exception:
                            event2.set()
                        _wait(event2, 10)
                        if cancel_token and cancel_token():
                            return None
            return url
        return None
