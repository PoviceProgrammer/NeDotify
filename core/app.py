"""
NeDotify - Application Core
Initializes and wires all application components.
"""

import logging
import os
import pathlib
import subprocess
import sys
import threading
import time

from audio.engine import AudioEngine
from core.database import DatabaseManager
from core.downloader import DownloadManager
from core.plugins import PluginManager
from core.proxy import LocalProxyManager
from core.resolver import StreamResolver
from core.session import SessionManager
from core.settings import SettingsManager
# офлайн-режим удалён: is_offline больше не существует
from services.lufs_scanner import LufsScannerService
from services.lyrics_service import LyricsService
from services.playlist_import_service import PlaylistImportService
from services.spotify_service import SpotifyService
from services.deezer_service import DeezerService
from services.vk_service import VKService
from services.watchdog_service import WatchdogService
from services.youtube_service import YouTubeService
from services.zapret_service import ZapretService
from services.artist_service import ArtistService
from services.audio_fingerprint_service import AudioFingerprintService
from core.services.discord_rpc import DiscordRPCService
from utils.cache_manager import CacheManager
from utils.file_scanner import FileScanner

logger = logging.getLogger(__name__)

# Wall-clock ceiling for the YouTube -> SoundCloud fallback cascade. Each
# candidate costs a SoundCloud search plus a stream extraction, and an
# unreachable SoundCloud burns a full socket_timeout per attempt; the total
# has to stay inside the frontend's stall window so the user gets an error
# instead of an endless spinner.
_SC_FALLBACK_BUDGET_S = 20.0


def finalize_process(shutdown, flush_logs, terminate, *, restart=None, exit_code=0):
    """Finalize the app and force-exit only after durable state is confirmed.

    `terminate` is injected so lifecycle tests can exercise the exact ordering
    without terminating the test runner. A restart callback is never invoked
    when the final synchronous flush failed.
    """
    result = shutdown()
    if not isinstance(result, dict) or not result.get('durable_flushed'):
        logger.error('Process finalization withheld: durable state flush was not confirmed')
        if restart is not None:
            return False
        # When terminating without restart, flush logs and force-exit so the process
        # does not hang in background on failed durable/WAL flush.
        try:
            flush_logs()
        finally:
            terminate(exit_code if exit_code != 0 else 1)
        return False
    if restart is not None:
        try:
            restart()
        except Exception:
            logger.exception('Process restart launch failed')
    remaining = tuple(result.get('remaining_workers') or ())
    if restart is None and not remaining:
        return True
    try:
        flush_logs()
    finally:
        terminate(exit_code)
    return True


def update_ytdlp_safely():
    """Keep dependency updates outside the process that has imported yt-dlp."""
    logger.info("yt-dlp automatic mutation disabled; update dependencies between app sessions.")


class AppCore:
    """Central application object that owns and initializes all sub-services."""

    def __init__(self):
        self.update_lock = threading.Lock()
        # RLock, not Lock: the lazy service properties below nest. `recommendations`
        # acquires this lock and then reads `self.soundcloud`, which acquires it
        # again. With a plain Lock that is a self-deadlock on the very first
        # access: the thread holds _service_lock forever, every later reader
        # (search, home feed) blocks on it, and no provider is ever dispatched.
        self._service_lock = threading.RLock()
        self._shutting_down = threading.Event()
        self._resolution_timers = set()
        self._resolve_threads = set()
        self._cleanup_done = threading.Event()
        self._cleanup_result = None
        self._soundcloud = None
        self._yandex = None
        self._recommendations = None

        # Database & Base Services
        self.db = DatabaseManager()
        self.settings = SettingsManager(self.db)
        from core.setup_engine import SetupEngine
        self.setup = SetupEngine(self.settings, emit=lambda name, payload: self.api._emit(name, payload) if getattr(self, 'api', None) else None)
        self.session = SessionManager(self.settings)
        self.cache = CacheManager(self.db, self.settings)
        self.scanner = FileScanner(self.db)

        # Set by cleanup() as its first act. The deferred zapret autostart runs
        # on its own thread (see start_zapret_if_enabled), so without this the
        # teardown could call zapret.stop() first and the in-flight start would
        # then launch the process anyway, leaving it orphaned for the rest of
        # the session. An Event, not a lock: it is set once and only read.
        self._zapret_start_thread = None

        # C-3: stream URL cache + single-flight coordinator
        self.resolver = StreamResolver(self.db, settings=self.settings)

        # Audio Playback
        self.engine = AudioEngine()
        self.engine.app_core = self

        # Streaming Services (eager: fast lightweight services)
        self.youtube = YouTubeService(self.settings)
        self.vk = VKService(self.settings)
        self.spotify = SpotifyService(self.settings)
        self.deezer = DeezerService(self.settings, providers=lambda source: getattr(self, source))
        self.lyrics = LyricsService(self.settings, cache_path=os.path.join(
            os.path.dirname(os.path.abspath(self.db.db_path)), 'lyrics_cache.db'))
        self.artists = ArtistService(youtube_service=self.youtube, settings=self.settings)

        # Proxy, Downloader & Plugins
        self.proxy = LocalProxyManager(self)
        self.engine.proxy = self.proxy
        self.downloader = DownloadManager(self)
        self.plugins = PluginManager(self)
        self.zapret = ZapretService(self.settings)
        self.playlist_importer = PlaylistImportService(settings=self.settings)
        self.watchdog = WatchdogService(self)
        self.lufs_scanner = LufsScannerService(self)
        self.audio_fingerprint = AudioFingerprintService()
        self.discord_rpc = DiscordRPCService(self.settings)
        self.discord_rpc.start()


        # Periodic background check for Zapret updates
        if hasattr(self, "zapret") and self.zapret \
                and hasattr(self.zapret, "auto_update_in_background"):
            self.zapret.auto_update_in_background()

        # Start Local Stream Proxy & Load Plugins
        self.proxy.start()

        # Watchdog: monitor playback health (O-13)
        try:
            self.watchdog.start()
        except Exception as we:
            logger.error(f"Failed to start watchdog: {we}")

        # M-9: LUFS/ReplayGain scanner was never started (ProcessPool was idle)
        try:
            self.lufs_scanner.start()
        except Exception as le:
            logger.warning(f"Failed to start LUFS scanner: {le}")

        # O-3: periodic DB cache cleanup by expires_at (every 10 minutes)
        self._cache_cleanup_stop = threading.Event()

        def _cache_cleanup_loop():
            while not self._cache_cleanup_stop.wait(600):
                try:
                    deleted = self.db.cleanup_expired_cache()
                    if deleted:
                        logger.info("[cache] cleaned %d expired stream_cache rows", deleted)
                except Exception as ce:
                    logger.debug("Cache cleanup error: %s", ce)

        self._cache_cleanup_thread = threading.Thread(target=_cache_cleanup_loop, name="CacheCleanup", daemon=True)
        self._cache_cleanup_thread.start()

    def warm_playback_sources(self):
        """Start the existing public-client warmup while the window is loading.

        It used to start on the first SoundCloud click, putting homepage and
        asset downloads on that track's critical path. Disabled sources stay
        lazy, and the lifecycle owns the small initialization worker.
        """
        with self._service_lock:
            if self._shutting_down.is_set():
                return
            if (not getattr(self, '_youtube_search_warmup_started', False)
                    and self.settings.get('services', 'youtube_enabled', True) is not False):
                warm_search = getattr(self.youtube, 'warm_search', None)
                if callable(warm_search):
                    self._youtube_search_warmup_started = True
                    warm_search()
            if (self._soundcloud is not None
                    or getattr(self, '_soundcloud_warmup_started', False)
                    or self.settings.get('services', 'soundcloud_enabled', True) is False):
                return
            self._soundcloud_warmup_started = True
            def warm():
                try:
                    with self._service_lock:
                        if not self._shutting_down.is_set():
                            self.soundcloud
                except Exception:
                    logger.debug('SoundCloud startup warmup could not initialize', exc_info=True)
                finally:
                    with self._service_lock:
                        self._resolve_threads.discard(threading.current_thread())
            worker = threading.Thread(target=warm, name='PlaybackWarmup', daemon=True)
            self._resolve_threads.add(worker)
            worker.start()

    @property
    def soundcloud(self):
        if self._soundcloud is None:
            with self._service_lock:
                if self._soundcloud is None:
                    from services.soundcloud_service import SoundCloudService
                    self._soundcloud = SoundCloudService(self.settings)
                    self._soundcloud.youtube_service = self.youtube
        return self._soundcloud

    @soundcloud.setter
    def soundcloud(self, val):
        self._soundcloud = val

    @property
    def yandex(self):
        if self._yandex is None:
            with self._service_lock:
                if self._yandex is None:
                    from services.yandex_service import YandexService
                    def auth_status(invalid):
                        self.settings.set('auth', 'yandex_token_valid',
                                          bool(self.settings.get('auth', 'yandex_token', '')) and not invalid)
                        api = getattr(self, 'api', None)
                        if api:
                            api._emit('yandex_auth_error', {'invalid': bool(invalid)})
                    def subscription_status(has_plus):
                        api = getattr(self, 'api', None)
                        if api:
                            api._emit('yandex_subscription_status', {'has_plus': bool(has_plus)})
                    self._yandex = YandexService(self.settings, on_auth_error=auth_status,
                                                on_subscription_status=subscription_status)
        return self._yandex

    @yandex.setter
    def yandex(self, val):
        self._yandex = val

    @property
    def recommendations(self):
        if self._recommendations is None:
            # Resolve dependencies BEFORE taking the lock: these constructors do
            # network I/O, and holding the lock across it would stall every other
            # lazy-property reader (search included) for the whole handshake.
            sc_service = self.soundcloud
            yt_service = self.youtube
            with self._service_lock:
                if self._recommendations is None:
                    from services.recommendation_service import RecommendationService
                    self._recommendations = RecommendationService(
                        settings=self.settings,
                        db=self.db,
                        soundcloud_service=sc_service,
                        youtube_service=yt_service
                    )
        return self._recommendations

    @recommendations.setter
    def recommendations(self, val):
        self._recommendations = val

    def start_zapret_if_enabled(self):
        """Start Zapret only if the user has it on. Called AFTER the WebView2
        window finished loading: a cold Zapret launch (winws DPI-desync) slows
        down WebView2 HTTPS handshakes and delays bridge injection."""
        try:
            def _flag(name, default=False):
                val = self.settings.get("zapret", name, default)
                if isinstance(val, str):
                    return val.strip().lower() in ("true", "1", "yes", "on")
                return bool(val)

            # `enabled` is what the UI toggle writes (AppApi.toggle_zapret).
            # Reading only `auto_start` here was why switching Zapret off in the
            # UI never stuck: the next launch read a different key and started
            # the bypass again.
            if not _flag("enabled"):
                logger.info("Zapret autostart skipped: disabled in settings")
                return
            if not _flag("auto_start"):
                logger.info("Zapret autostart skipped: auto_start is off")
                return

            if not getattr(self, "zapret", None):
                return

            mode = self.settings.get("zapret", "mode", "youtube_discord")
            custom_args = self.settings.get("zapret", "custom_args", "")
            bin_path = self.settings.get("zapret", "binary_path", "")

            def _start_worker():
                try:
                    # Re-checked on this thread: cleanup() may have started
                    # between the check below and here.
                    if self._shutting_down.is_set():
                        logger.info("Zapret autostart skipped: shutdown in progress")
                        return
                    # BUG-003: re-read the toggle right before start(). The
                    # worker used to trust a snapshot taken when it was queued,
                    # so a toggle-off during the (up to ~30s) binary download
                    # was followed by winws launching anyway.
                    if not _flag("enabled"):
                        logger.info("Zapret autostart skipped: disabled in settings (re-checked)")
                        return
                    try:
                        result = self.zapret.start(mode=mode, custom_args=custom_args,
                                                   binary_path=bin_path)
                    except Exception:
                        logger.exception("Zapret autostart start() failed")
                        result = (False, "autostart error")
                    success = bool(result[0]) if isinstance(result, tuple) and result else False
                    msg = str(result[1]) if isinstance(result, tuple) and len(result) > 1 else ""
                    if self._shutting_down.is_set():
                        # BUG-002: the attempt was cancelled by shutdown.
                        # Persisting the transient failure would flip the
                        # user's `enabled` off for the NEXT session.
                        logger.info("Zapret autostart result discarded (shutdown): %s", msg)
                        return
                    if success:
                        logger.info("Zapret autostart: %s", msg)
                    else:
                        logger.warning("Zapret autostart failed: %s", msg)
                        # BUG-033: mode/custom_args/binary_path stay persisted
                        # and autostart will retry next launch, so the user
                        # must learn why the bypass is off right now. The
                        # service's event hook already routes through the
                        # bridge (same channel as zapret_crashed).
                        try:
                            if hasattr(self.zapret, '_emit_event'):
                                self.zapret._emit_event('zapret_autostart_failed', {
                                    'message': msg or 'Не удалось автоматически запустить Zapret'})
                        except Exception:
                            logger.debug('zapret_autostart_failed emit failed', exc_info=True)
                    # BUG-022: the autostart used to discard the result
                    # entirely while toggle_zapret wrote `enabled`. One writer
                    # semantics: the flag mirrors the real process state, so a
                    # start cancelled by a newer toggle can never resurrect it.
                    try:
                        self.settings.set("zapret", "enabled", bool(self.zapret.is_running()))
                    except Exception:
                        logger.debug("Zapret autostart could not persist the enabled flag",
                                     exc_info=True)
                except Exception:
                    logger.exception("Zapret autostart worker failed")

            # NOTE: this block, and the worker.start() below it, sit at the same
            # indentation as `def _start_worker` - inside the method, outside
            # the worker body. They were briefly nested one level deeper, which
            # defined _start_worker but never called it, so autostart silently
            # did nothing while the settings read fine.
            with self._service_lock:
                if self._shutting_down.is_set():
                    logger.info("Zapret autostart skipped: shutdown in progress")
                    return
                # BUG-024: a repeated window `loaded` event (render-watchdog
                # reload) used to spawn a second autostart worker and overwrite
                # `self._zapret_start_thread`, losing cleanup's handle on the
                # live one. Never run two autostart workers concurrently.
                existing = getattr(self, "_zapret_start_thread", None)
                if existing is not None and existing.is_alive():
                    logger.info("Zapret autostart skipped: worker already running")
                    return
                worker = threading.Thread(
                    target=_start_worker,
                    name="ZapretAutostart",
                    daemon=True,
                )
                # Kept so cleanup() can wait for an in-flight start instead
                # of racing it (the thread is short-lived by design).
                self._zapret_start_thread = worker
            worker.start()
        except Exception as ze:
            logger.error(f"Failed to auto-start Zapret: {ze}")

    def re_resolve_stream_url_async(self, source, source_id, callback=None, on_error=None, quality="high", track=None):
        """Construct lookup URL, call get_stream_url asynchronously and trigger callbacks."""
        completion = threading.Event()
        original_callback, original_error = callback, on_error
        timer = None
        def finish(fn, *values):
            with self._service_lock:
                if completion.is_set():
                    return
                completion.set()
                if timer is not None:
                    timer.cancel()
                    self._resolution_timers.discard(timer)
            if callable(fn) and not self._shutting_down.is_set():
                try:
                    fn(*values)
                except Exception:
                    logger.warning('Stream completion callback failed', exc_info=True)
        callback = lambda url, metadata=None: finish(original_callback, url, metadata)
        on_error = lambda error: finish(original_error, error)
        def active():
            return not completion.is_set() and not self._shutting_down.is_set()
        timer = threading.Timer(35, lambda: on_error('Stream resolution timed out'))
        timer.daemon = True
        with self._service_lock:
            if self._shutting_down.is_set():
                return
            self._resolution_timers.add(timer)
        timer.start()
        def worker():
            if not active():
                return
            url = None
            # ID the cascade addressed directly (not through a search): when the
            # provider reports metadata for exactly this id, the recording is
            # the requested one by construction and needs no metadata check.
            direct_target_id = ''
            from services.recording_selection import select_recording, stream_matches
            if source in ("youtube", "spotify"):
                sid_str = str(source_id or "").strip()
                t_art = track.get("artist", "") if track and isinstance(track, dict) else ""
                t_tit = track.get("title", "") if track and isinstance(track, dict) else ""
                if source == "spotify":
                    # BUG-A1-002: the row's identity is a search expression, so
                    # a re-resolve must return the SAME recording the original
                    # cascade verified — start from the persisted video id.
                    from services.recording_selection import remembered_video_id
                    for key in (sid_str, f"ytsearch1: {t_art} - {t_tit}".strip()):
                        vid = remembered_video_id(self.settings, source, key)
                        if vid:
                            url = f"https://www.youtube.com/watch?v={vid}"
                            direct_target_id = vid
                            break
                    if not url:
                        if sid_str.startswith("http://") or sid_str.startswith("https://"):
                            url = sid_str
                        else:
                            # A search-derived target: its metadata is checked
                            # in _on_resolved before the stream is accepted.
                            url = f"ytsearch1: {t_art} - {t_tit}".strip() or sid_str
                elif sid_str.startswith("http://") or sid_str.startswith("https://"):
                    url = sid_str
                elif sid_str.startswith("ytsearch"):
                    url = sid_str
                elif track and (not sid_str or sid_str == "None" or sid_str.startswith("spotify_")):
                    url = f"ytsearch1: {t_art} - {t_tit}".strip()
                else:
                    url = f"https://www.youtube.com/watch?v={sid_str}"
                    direct_target_id = sid_str
                service = self.youtube
            elif source == "soundcloud":
                if str(source_id).startswith(("https://", "http://")):
                    url = str(source_id)
                elif "/" in str(source_id):
                    url = f"https://soundcloud.com/{source_id}"
                else:
                    url = f"https://api-v2.soundcloud.com/tracks/{source_id}"
                service = self.soundcloud
            elif source == "yandex":
                url = f"https://music.yandex.ru/track/{source_id}"
                service = self.yandex
            elif source == 'deezer':
                url = str(source_id)
                service = self.deezer
            else:
                if on_error:
                    on_error(f"Unsupported source: {source}")
                return

            def _on_resolved(stream_url, metadata=None):
                if not active():
                    return
                # BUG-A1-010: a re-resolved stream must belong to the recording
                # that is playing. A search-derived target is accepted only
                # when its metadata matches the track; a direct id needs no
                # comparison (the provider resolved exactly that recording).
                if stream_url and track and track.get('title') \
                        and not stream_matches(track, metadata, requested_id=direct_target_id):
                    logger.info('Re-resolved stream rejected: metadata does not match the playing track')
                    if on_error:
                        on_error('Резервная запись не прошла проверку соответствия')
                    return
                if stream_url:
                    # Refresh resolver caches so subsequent requests reuse the fresh URL
                    try:
                        self.resolver.refresh(source, source_id, stream_url)
                    except Exception:
                        try:
                            self.db.cache_stream(source, source_id, stream_url)
                        except Exception:
                            logger.debug("_on_resolved: suppressed exception", exc_info=True)

                    if self.settings and self.settings.get("storage", "auto_cache_streams", False):
                        def delayed_download():
                            with self._service_lock:
                                self._resolution_timers.discard(_t)
                            try:
                                if self._shutting_down.is_set():
                                    return
                                if getattr(self, "engine", None) and self.engine.queue.current_track:
                                    curr = self.engine.queue.current_track
                                    if curr.get("source_id") == source_id:
                                        self.cache.download_audio_stream(source, source_id, stream_url)
                            except Exception:
                                logger.debug("delayed_download: suppressed exception", exc_info=True)
                        _t = threading.Timer(5.0, delayed_download)
                        _t.daemon = True
                        with self._service_lock:
                            if not self._shutting_down.is_set():
                                self._resolution_timers.add(_t)
                                _t.start()

                if callback:
                    callback(stream_url, metadata or {"source": source, "source_id": source_id})

            def _on_err(err):
                if not active():
                    return
                if source == "youtube":
                    # Lazy provider construction belongs inside this guard.
                    try:
                        if not self.soundcloud:
                            raise RuntimeError('SoundCloud is unavailable')
                        import re
                        t_art = track.get('artist', '') if track and isinstance(track, dict) else ""
                        t_title = track.get('title', '') if track and isinstance(track, dict) else ""
                        t_duration = track.get('duration') or 0 if track and isinstance(track, dict) else 0
                        if not t_title:
                            try:
                                db_track = self.db.get_track_by_source_id(source, source_id)
                                if db_track:
                                    t_art = db_track.get('artist', '')
                                    t_title = db_track.get('title', '')
                                    t_duration = db_track.get('duration') or t_duration
                            except Exception:
                                logger.debug("_on_err: suppressed exception", exc_info=True)
                        # Full metadata for candidate verification (BUG-A1-004):
                        # the duration gates remix/live/extended substitutions
                        # even when the query text lost its version marker.
                        sc_track_meta = {'title': t_title, 'artist': t_art, 'duration': t_duration}

                        if not t_title or t_title == source_id or (len(t_title) == 11 and " " not in t_title):
                            try:
                                import urllib.request, json
                                oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={source_id}&format=json"
                                req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
                                with urllib.request.urlopen(req, timeout=3.0) as resp:
                                    o_data = json.loads(resp.read().decode('utf-8'))
                                    if o_data.get('title'):
                                        t_title = o_data['title']
                                    if o_data.get('author_name') and not t_art:
                                        t_art = o_data['author_name']
                            except Exception:
                                logger.debug("_on_err: suppressed exception", exc_info=True)

                        def clean_noise(text):
                            if not text: return ""
                            t = re.sub(r'[\(\[\{][^\)\]\}]*(?:official|video|audio|клип|релиз|remix|edit|lyric|prod|ft\.|feat\.|4k|hd|hq|live|topic)[^\)\]\}]*[\)\]\}]', '', text, flags=re.IGNORECASE)
                            t = re.sub(r'\b(official\s+video|official\s+audio|music\s+video|lyric\s+video|премьера\s+клипа|клип|релиз)\b', '', t, flags=re.IGNORECASE)
                            t = re.sub(r'[\(\[\{]\s*[\)\]\}]', '', t)
                            return ' '.join(t.split()).strip()

                        clean_t = clean_noise(t_title)
                        clean_a = clean_noise(t_art)
                        c_queries = []
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
                        raw = f"{t_art} {t_title}".strip()
                        if raw:
                            c_queries.append(raw)
                        c_queries.append(str(source_id).replace("https://www.youtube.com/watch?v=", ""))

                        candidates = []
                        for q in c_queries:
                            qn = ' '.join(q.split()).strip()
                            if qn and len(qn) > 1 and qn not in candidates:
                                candidates.append(qn)

                        def try_search_candidates(idx=0, _started=None):
                            # Hard budget: without it the chain was candidates x
                            # (SoundCloud socket_timeout + yt-dlp retries). When
                            # SoundCloud is unreachable that is minutes of silence
                            # and on_error never reached the UI, so the track sat
                            # in a permanent loading state.
                            if _started is None:
                                _started = time.monotonic()
                            elapsed = time.monotonic() - _started
                            if idx >= len(candidates) or elapsed > _SC_FALLBACK_BUDGET_S:
                                logger.warning(
                                    "SoundCloud fallback exhausted for %s "
                                    "(candidates=%d tried=%d elapsed=%.1fs)",
                                    source_id, len(candidates), idx, elapsed,
                                )
                                if on_error:
                                    on_error(err)
                                return

                            sq = candidates[idx]
                            logger.info(f"YouTube resolution failed; trying SoundCloud fallback ({idx+1}/{len(candidates)}) for: {sq}")

                            def on_sc_search_res(res):
                                if elapsed and (time.monotonic() - _started) > _SC_FALLBACK_BUDGET_S:
                                    if on_error:
                                        on_error(err)
                                    return
                                # BUG-A1-004: the provider's ranking is not
                                # trusted — take the first candidate that
                                # actually matches the requested recording.
                                candidate = select_recording(sc_track_meta, res or [])
                                if candidate:
                                    target_sc = candidate.get("source_url") or candidate.get("source_id")
                                    self.soundcloud.get_stream_url(target_sc, callback=_on_resolved, error_callback=lambda e: try_search_candidates(idx + 1, _started))
                                else:
                                    try_search_candidates(idx + 1, _started)

                            def on_sc_search_err(e):
                                if (time.monotonic() - _started) > _SC_FALLBACK_BUDGET_S:
                                    if on_error:
                                        on_error(err)
                                    return
                                try_search_candidates(idx + 1, _started)

                            self.soundcloud.search(sq, max_results=3, callback=on_sc_search_res, error_callback=on_sc_search_err)

                        try_search_candidates(0)
                        return
                    except Exception as fallback_ex:
                        logger.debug(f"SoundCloud fallback search error: {fallback_ex}")
                if on_error:
                    on_error(err)

            try:
                service.get_stream_url(url, callback=_on_resolved, error_callback=_on_err, quality=quality)
            except Exception as e:
                _on_err(str(e))

        def guarded_worker():
            try:
                worker()
            except Exception:
                logger.warning('Stream resolution worker failed', exc_info=True)
                on_error('Stream resolution failed')
            finally:
                self.db.close_thread_connection()
                with self._service_lock:
                    self._resolve_threads.discard(threading.current_thread())
        thread = threading.Thread(target=guarded_worker, name='StreamCascade', daemon=True)
        with self._service_lock:
            if not self._shutting_down.is_set():
                self._resolve_threads.add(thread)
                thread.start()

    def cleanup(self, wait_timeout=40.0):
        """Stop producers, flush durable state, and drain workers within a bound.

        Returns a stable result for the process finalizer. A live worker keeps
        SettingsManager and DatabaseManager open; callers may then choose a
        bounded process exit after the final synchronous flush has succeeded.
        """
        with self._service_lock:
            if getattr(self, '_cleanup_started', False):
                done = getattr(self, '_cleanup_done', None)
                result = getattr(self, '_cleanup_result', None)
                owner = False
            else:
                self._cleanup_started = True
                self._shutting_down.set()
                for timer in tuple(getattr(self, '_resolution_timers', ())):
                    timer.cancel()
                self._resolution_timers = set()
                self._cleanup_done = threading.Event()
                done = self._cleanup_done
                result = None
                owner = True
        if not owner:
            if result is not None:
                return result
            if done is not None:
                done.wait(max(0.0, float(wait_timeout)) + 5.0)
            with self._service_lock:
                return getattr(self, '_cleanup_result', None) or {
                    'durable_flushed': False, 'remaining_workers': (),
                    'error': 'cleanup did not finish before the wait bound',
                }
        logger.info('Cleaning up AppCore resources...')
        durable_flushed = True
        def step(name, callback, *, durable=False):
            nonlocal durable_flushed
            try:
                result = callback()
                if durable and result is False:
                    durable_flushed = False
                    logger.error('Cleanup durability step %s reported an incomplete flush', name)
                return result
            except Exception:
                if durable:
                    durable_flushed = False
                logger.warning('Cleanup step %s failed', name, exc_info=True)
                return None
        api = getattr(self, 'api', None)
        pools = []
        def remember(pool):
            if pool is None or any(pool is old for old in pools):
                return
            pools.append(pool)
        from services.base_service import BaseMusicService
        remember(getattr(BaseMusicService._executor, '_pool', None))
        remember(getattr(BaseMusicService._playback_executor, '_pool', None))
        from services.lyrics_service import _lyrics_pool
        remember(getattr(_lyrics_pool, '_pool', None))
        for owner in (api, getattr(self, 'downloader', None), getattr(self, 'cache', None),
                      getattr(self, 'youtube', None), getattr(self, '_soundcloud', None),
                      getattr(self, '_yandex', None), getattr(self, 'spotify', None),
                      getattr(self, '_recommendations', None)):
            if owner:
                for key in ('_pool', '_executor', '_candidate_executor', '_search_executor',
                            '_prefetch_executor', '_playback_executor', '_metadata_executor', '_lyrics_request_executor'):
                    remember(getattr(owner, key, None))
        if api:
            step('bridge', api.cleanup)
        stop = getattr(self, '_cache_cleanup_stop', None)
        if stop:
            stop.set()

        zapret = getattr(self, 'zapret', None)
        def stop_zapret_bounded(timeout=10.0):
            """BUG-007: the zapret stop step can legitimately take seconds
            (terminate + PID signature scans); it must never be able to stall
            the whole shutdown, so it runs bounded and reports when it does."""
            if zapret is None or not callable(getattr(zapret, 'stop', None)):
                return
            done = threading.Event()

            def _run():
                try:
                    zapret.stop()
                except Exception:
                    logger.warning('Zapret stop failed during cleanup', exc_info=True)
                finally:
                    done.set()

            threading.Thread(target=_run, name='ZapretStop', daemon=True).start()
            if not done.wait(timeout):
                logger.warning('Zapret stop exceeded %.0fs during cleanup; continuing shutdown', timeout)

        stop_zapret_bounded()
        for name, method in (('watchdog', 'stop'), ('scanner', 'stop'), ('lufs_scanner', 'stop'),
                             ('setup', 'shutdown'),
                             ('downloader', 'stop'), ('plugins', 'unload_all'),
                             ('discord_rpc', 'shutdown'), ('proxy', 'stop')):
            owner = getattr(self, name, None)
            fn = getattr(owner, method, None)
            if name == 'discord_rpc' and not callable(fn):
                fn = getattr(owner, 'stop', None)
            if callable(fn):
                step(name, fn)
        step('base_service pool', BaseMusicService.shutdown_executor)
        step('lyrics pool', LyricsService.shutdown_executor)
        threads = set(getattr(self, '_resolve_threads', ()))
        for pool in pools:
            actual = getattr(pool, '_pool', None) or pool
            threads.update(getattr(actual, '_threads', ()))
            shutdown = getattr(pool, 'shutdown', None)
            if callable(shutdown):
                step('worker pool', lambda fn=shutdown: fn(wait=False, cancel_futures=True))
        setup = getattr(self, 'setup', None)
        if setup:
            for name in ('_worker', '_maintenance_worker'):
                thread = getattr(setup, name, None)
                if thread:
                    threads.add(thread)
        for name in ('_cache_cleanup_thread', '_zapret_start_thread'):
            thread = getattr(self, name, None)
            if thread:
                threads.add(thread)
        threads.discard(threading.current_thread())
        deadline = time.monotonic() + max(0.0, float(wait_timeout))
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        # BUG-002: the autostart worker may have passed its shutdown check just
        # before cleanup() set the flag, so its start() can land after the stop
        # above ran into an empty field. stop() is idempotent: run it again now
        # that the worker has been joined, or its wait bound has expired.
        if getattr(self, '_zapret_start_thread', None) is not None:
            stop_zapret_bounded()
            zapret_running = False
            try:
                zapret_running = bool(zapret.is_running())
            except Exception:
                logger.debug('Zapret post-join liveness check failed', exc_info=True)
            if zapret_running:
                # BUG-009: a non-stoppable (elevated) winws survives the app.
                # Never leave that silent: it keeps machine-wide DPI filters.
                logger.warning('Zapret process is still running after shutdown stop '
                               '(likely elevated and not stoppable); it will keep the '
                               'WinDivert filters active until manually stopped')
                try:
                    if hasattr(zapret, '_emit_event'):
                        zapret._emit_event('zapret_still_running', {
                            'message': 'Zapret остался запущен после выхода из приложения '
                                       '(элевированный процесс нельзя остановить без прав администратора)'})
                except Exception:
                    logger.debug('zapret_still_running emit failed', exc_info=True)
        # This synchronous flush is the last durable checkpoint before a
        # watchdog or normal finalizer may have to terminate a process with a
        # stuck ThreadPoolExecutor worker. Keep it after producer shutdown and
        # the bounded drain so late work cannot be silently omitted.
        save_session = getattr(self, 'save_session', None)
        if callable(save_session):
            step('session', save_session, durable=True)
        if api:
            step('listening', api.flush_listening, durable=True)
        settings = getattr(self, 'settings', None)
        flush = getattr(settings, 'sync_flush_now', None)
        if callable(flush):
            step('settings flush', flush, durable=True)
        def close_state():
            settings = getattr(self, 'settings', None)
            close = getattr(settings, 'close', None)
            if callable(close):
                step('settings close', close, durable=True)
            close = getattr(getattr(self, 'db', None), 'close', None)
            if callable(close):
                step('database', close)
        remaining = [thread for thread in threads if thread.is_alive()]
        if remaining:
            # Preserve connections until late callbacks have finished. Closing them
            # under a live worker recreates the shutdown data-loss race.
            logger.warning('Deferring database close until %d workers finish', len(remaining))
            def finish():
                for thread in remaining:
                    thread.join()
                close_state()
            threading.Thread(target=finish, name='FinalStateClose', daemon=True).start()
        else:
            close_state()
        result = {
            'durable_flushed': durable_flushed,
            'remaining_workers': tuple(thread.name for thread in remaining),
        }
        with self._service_lock:
            self._cleanup_result = result
            self._cleanup_done.set()
        return result

    def save_session(self):
        """Persist one consistent queue snapshot, including the current playback position."""
        with self.engine.command_lock:
            state = self.engine.queue.snapshot()
            current = state.get('current_track') or {}
            self.session.save_session(
                track_id=current.get('id'), position=getattr(self.engine, '_last_reported_position', 0),
                volume=self.settings.get('audio', 'volume', 70), queue=state['tracks'],
                queue_index=state['current_index'], shuffle=state['shuffle'], repeat=state['repeat'],
            )
