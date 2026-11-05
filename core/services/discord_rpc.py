"""Non-blocking Discord IPC for NeDotify Windows.

Riff's last-track cache, ready restoration, reconnect scheduling and activity
fallback informed this native Python adaptation (copyright 2026 rootscripts).
Reference MIT notice: licenses/riff-MIT.txt. No Riff Application ID is used.
"""
import asyncio
import copy
import ipaddress
import inspect
import logging
import math
import random
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit, urlunsplit

logger = logging.getLogger(__name__)
_Presence = None


def _load_presence():
    global _Presence
    if _Presence is None:
        try:
            from pypresence import Presence
            _Presence = Presence
        except ImportError:
            _Presence = False
    return _Presence or None


def _number(value, default=0., maximum=864000.):
    try:
        value = float(value)
        return min(maximum, max(0., value)) if math.isfinite(value) else default
    except (ValueError, TypeError):
        return default


def _public_https(value):
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 for c in value):
        return None
    try:
        p = urlsplit(value)
        host = (p.hostname or '').lower().rstrip('.')
        if p.scheme != 'https' or not host or p.username or p.password or p.port not in (None, 443):
            return None
        if host == 'localhost' or '.' not in host or host.endswith(('.localhost', '.local', '.internal', '.lan')) or p.fragment:
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return p
    except (ValueError, TypeError):
        return None


def public_track_url(track):
    """Canonical provider track pages only; never publish a proxy/stream URL."""
    source = str(track.get('source') or track.get('platform') or '').lower()
    sid = str(track.get('source_id') or '')
    if source in ('youtube', 'ytmusic') and re.fullmatch(r'[A-Za-z0-9_-]{11}', sid):
        return f'https://www.youtube.com/watch?v={sid}'
    if source == 'spotify' and re.fullmatch(r'[A-Za-z0-9]{22}', sid):
        return f'https://open.spotify.com/track/{sid}'
    for field in ('webpage_url', 'permalink_url', 'public_url', 'external_url', 'url'):
        p = _public_https(track.get(field))
        if not p:
            continue
        host, path, query = p.hostname.lower(), p.path, parse_qs(p.query)
        if host in ('www.youtube.com', 'youtube.com', 'music.youtube.com') and path == '/watch':
            video = query.get('v', [''])[0]
            if set(query) <= {'v'} and re.fullmatch(r'[A-Za-z0-9_-]{11}', video) and (not sid or video == sid):
                return f'https://www.youtube.com/watch?v={video}'
        elif host == 'youtu.be' and not p.query and re.fullmatch(r'/[A-Za-z0-9_-]{11}', path):
            if not sid or path[1:] == sid:
                return f'https://www.youtube.com/watch?v={path[1:]}'
        elif not p.query and host == 'open.spotify.com' and re.fullmatch(r'/track/[A-Za-z0-9]{22}', path):
            if not sid or path.rsplit('/', 1)[-1] == sid:
                return urlunsplit(p)
        elif not p.query and host in ('soundcloud.com', 'www.soundcloud.com') and re.fullmatch(r'/[\w-]+/[\w-]+/?', path):
            if not path.startswith(('/you/', '/discover/', '/search/')):
                return urlunsplit(p)
        elif not p.query and host in ('music.yandex.ru', 'music.yandex.com') and re.fullmatch(r'/(?:album/\d+/)?track/\d+/?', path):
            return urlunsplit(p)
    return None


def public_cover_url(value):
    p = _public_https(value)
    if not p or p.query:
        return None
    host = p.hostname.lower()
    suffixes = ('ytimg.com', 'sndcdn.com', 'scdn.co', 'mzstatic.com', 'dzcdn.net')
    if host in ('img.youtube.com', 'avatars.mds.yandex.net', 'avatars.yandex.net') or any(host == s or host.endswith('.' + s) for s in suffixes):
        return urlunsplit(p)
    return None


class DiscordRPCService:
    """One daemon owns all IPC and its asyncio loop; callers only publish facts."""
    IO_TIMEOUT = 2.
    MIN_UPDATE_INTERVAL = 2.
    HEARTBEAT_INTERVAL = 15.
    RETRY_BASE = 15.
    RETRY_MAX = 60.
    FALLBACK_ASSET = 'aura_logo'  # Existing NeDotify registered application asset.

    def __init__(self, settings=None, client_id='1329524021200158781', *, clock=time.monotonic, wall_clock=time.time, jitter=random.random):
        self.client_id, self.settings = client_id, settings
        self.rpc, self.connected = None, False
        self._lock, self._wake = threading.RLock(), threading.Event()
        self._worker, self._active, self._generation = None, False, 0
        self._stopped = False
        self._snapshot, self._snapshot_provider = None, None
        self._revision, self._sent_revision = 0, -1
        self._last_sent, self._retry_at, self._attempts = -math.inf, 0., 0
        self._last_error = None
        self._clock, self._wall_clock, self._jitter = clock, wall_clock, jitter
        self.state = 'DISABLED' if not self.is_enabled() else 'DISCONNECTED'

    def _option(self, key, default=True):
        return bool(self.settings.get('app', key, default)) if self.settings else default

    def is_enabled(self):
        return self.settings is not None and self.settings.get('app', 'discord_rpc_enabled', False) is True

    def get_status(self):
        with self._lock:
            return dict(enabled=self.is_enabled(), connected=self.connected, state=self.state, error=self._last_error,
                        retry_in=round(max(0, self._retry_at-self._clock()), 1) if self._active and not self.connected else 0)

    def set_snapshot_provider(self, provider):
        with self._lock:
            self._snapshot_provider = provider

    def start(self, *, _automatic=False):
        with self._lock:
            if _automatic and self._stopped:
                return
            if not self.is_enabled():
                self.state = 'DISABLED'
                return
            already_active = self._active
            self._active = True
            self._stopped = False
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name='DiscordRPC', daemon=True)
                self._worker.start()
        # A snapshot provider runs on this worker. Repeated automatic start()
        # calls must not wake its own wait and turn the scheduler into a spin.
        if not _automatic or not already_active:
            self._wake.set()

    def stop(self):
        """Request bounded clear/close; no IPC or joins on the calling UI thread."""
        with self._lock:
            self._active = False
            self._stopped = True
            self._generation += 1
            self._retry_at, self._attempts = 0, 0
            self.state = 'SHUTTING_DOWN' if self._worker and self._worker.is_alive() else 'DISABLED'
            if not self._worker or not self._worker.is_alive():
                client, self.rpc = self.rpc, None
                was_connected, self.connected = self.connected, False
                if client:
                    self._close(client, clear=was_connected)
        self._wake.set()

    def refresh(self):
        with self._lock:
            self._revision += 1
        self._wake.set()

    def shutdown(self):
        """Final cleanup may wait briefly; ordinary UI disable/close never waits."""
        self.stop()
        worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=self.IO_TIMEOUT * 2 + .5)

    @staticmethod
    def _position(snapshot, now):
        if not snapshot:
            return 0
        pos = snapshot['position_sec']
        if snapshot['state'] == 'playing':
            pos += max(0, now-snapshot['updated_at']) * snapshot['playback_rate']
        return min(snapshot['duration_sec'], pos) if snapshot['duration_sec'] else pos

    def update_snapshot(self, track=None, state='stopped', position_sec=0, duration_sec=0, playback_rate=1, *, updated_at=None):
        track = dict(track or {})
        stamp = self._clock() if updated_at is None else updated_at
        snapshot = dict(track=track, state=state, position_sec=_number(position_sec), duration_sec=_number(duration_sec or track.get('duration')),
                        playback_rate=max(.25, _number(playback_rate, 1, 4)), updated_at=stamp)
        with self._lock:
            old = self._snapshot
            expected = self._position(old, stamp) if old else 0
            changed = not old or any(old[k] != snapshot[k] for k in ('track', 'state', 'duration_sec', 'playback_rate')) or abs(expected-snapshot['position_sec']) > 1
            self._snapshot = snapshot
            if changed:
                self._revision += 1
        if changed:
            self._wake.set()
        if self.is_enabled():
            self.start(_automatic=True)

    def update_presence(self, track_title, track_artist='', is_playing=True, duration_sec=0, current_pos_sec=0, **metadata):
        track = dict(metadata.pop('track', None) or {})
        track.update(title=track_title, artist=track_artist)
        track.update({k:v for k,v in metadata.items() if k in ('id','source','source_id','cover_url','url','webpage_url','permalink_url')})
        self.update_snapshot(track, 'playing' if is_playing else 'paused', current_pos_sec, duration_sec)

    def clear_presence(self):
        self.update_snapshot(state='stopped')

    def _payload(self, snapshot, *, fallback=False):
        if not snapshot or not snapshot['track'] or snapshot['state'] not in ('playing','paused'):
            return None if self._option('discord_clear_on_stop') else dict(details='NeDotify', state='Воспроизведение остановлено')
        track = snapshot['track']
        def text(value, default):
            cleaned = str(value or '').strip()
            return (default if cleaned.lower() in ('','null','undefined','none') else cleaned)[:128].ljust(2)
        payload = dict(large_image=self.FALLBACK_ASSET, large_text='NeDotify Player')
        try:
            from pypresence.types import ActivityType
            payload['activity_type'] = ActivityType.LISTENING
        except ImportError:
            pass  # Older optional clients can still publish compatible metadata.
        payload['details'] = text(track.get('title'), 'Неизвестный трек') if self._option('discord_show_title') else 'NeDotify'
        if self._option('discord_show_artist'):
            artist = text(track.get('artist'), 'Неизвестный исполнитель')
            payload['state'] = (artist + (' · На паузе' if snapshot['state']=='paused' else ''))[:128]
        elif snapshot['state']=='paused':
            payload['state'] = 'На паузе'
        if not fallback:
            if self._option('discord_show_cover'):
                payload['large_image'] = public_cover_url(track.get('cover_url') or track.get('artwork_url') or track.get('og_image')) or self.FALLBACK_ASSET
            if self._option('discord_show_listen'):
                link = public_track_url(track)
                if link:
                    payload['buttons'] = [dict(label='Слушать', url=link)]
            if self._option('discord_show_time') and snapshot['state']=='playing' and snapshot['duration_sec']:
                pos = self._position(snapshot, self._clock())
                remaining = snapshot['duration_sec']-pos
                if remaining > 0:
                    now = int(self._wall_clock())
                    payload.update(start=now-int(pos/snapshot['playback_rate']), end=now+max(1,int(remaining/snapshot['playback_rate'])))
        return payload

    def _bound_io(self, client):
        # pypresence's timeout only covers pipe creation, not its raw READY read.
        for name in ('handshake','read_output'):
            original = getattr(client, name, None)
            if original and inspect.iscoroutinefunction(original):
                async def bounded(*args, _original=original, **kwargs):
                    return await asyncio.wait_for(_original(*args, **kwargs), self.IO_TIMEOUT)
                setattr(client, name, bounded)

    def _close(self, client, *, clear=False):
        if not client:
            return
        try:
            if clear:
                try:
                    client.clear()
                except Exception:
                    pass
            client.close()
        except Exception:
            pass
        finally:
            loop = getattr(client, 'loop', None)
            if loop and not loop.is_closed():
                try:
                    loop.close()
                except Exception:
                    pass

    def _disconnect(self, error=None):
        with self._lock:
            client, self.rpc = self.rpc, None
            self.connected = False
            self._attempts += 1
            delay = min(self.RETRY_MAX, self.RETRY_BASE * 2 ** min(self._attempts-1,4))
            retry = self._active and self.is_enabled() and not self._stopped
            self._retry_at = self._clock() + min(self.RETRY_MAX, delay*(.9+.2*self._jitter())) if retry else 0
            self.state = 'RECONNECTING' if retry else 'DISABLED'
            self._last_error = 'discord_unavailable' if error and retry else None
        self._close(client)
        if error:
            logger.debug('Discord IPC unavailable (%s); retry scheduled', type(error).__name__)

    def _run_cycle(self):
        with self._lock:
            active, generation, provider = self._active and self.is_enabled(), self._generation, self._snapshot_provider
        if not active:
            with self._lock:
                client, self.rpc = self.rpc, None
                was_connected, self.connected = self.connected, False
            self._close(client, clear=was_connected)
            with self._lock:
                self.state = 'DISABLED'
            return None
        if provider:
            try:
                snapshot = provider()
                if snapshot:
                    self.update_snapshot(**snapshot)
            except Exception:
                logger.debug('Discord playback snapshot unavailable')
        if not self.connected:
            if self._clock() < self._retry_at:
                return min(1, self._retry_at-self._clock())
            with self._lock:
                self.state = 'RECONNECTING' if self._attempts else 'CONNECTING'
            candidate, loop = None, None
            try:
                presence_cls = _load_presence()
                if not presence_cls:
                    with self._lock:
                        self.state, self._last_error = 'DISCONNECTED', 'missing_dependency'
                        self._retry_at = self._clock()+self.RETRY_MAX
                    return self.RETRY_MAX
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                candidate = presence_cls(self.client_id, loop=loop, connection_timeout=self.IO_TIMEOUT, response_timeout=self.IO_TIMEOUT)
                self._bound_io(candidate)
                candidate.connect()
                with self._lock:
                    valid = generation==self._generation and self._active and self.is_enabled()
                    if valid:
                        self.rpc, self.connected = candidate, True
                        self.state, self._last_error = 'CONNECTED', None
                        self._retry_at, self._attempts, self._sent_revision, self._last_sent = 0,0,-1,-math.inf
                if not valid:
                    self._close(candidate, clear=True)
                    return 0
                logger.info('Discord IPC connected')
                # READY may arrive after a track change. Re-read the actual selected deck.
                if provider:
                    snapshot = provider()
                    if snapshot:
                        self.update_snapshot(**snapshot)
            except Exception as error:
                self._close(candidate)
                if loop and not loop.is_closed():
                    loop.close()
                self._disconnect(error)
                return 1
        with self._lock:
            if not self._active or not self.is_enabled() or generation != self._generation:
                return 0
            revision, snapshot, due = self._revision, copy.deepcopy(self._snapshot), self._clock()-self._last_sent
        if due < self.MIN_UPDATE_INTERVAL or (revision==self._sent_revision and due<self.HEARTBEAT_INTERVAL):
            return 1
        try:
            payload = self._payload(snapshot)
            if payload is None:
                self.rpc.clear()
            else:
                try:
                    self.rpc.update(**payload)
                except Exception as error:
                    if type(error).__name__ not in ('ServerError','InvalidArgument','ArgumentError','TypeError'):
                        raise
                    fallback = self._payload(snapshot, fallback=True)
                    fallback.pop('large_image', None)
                    fallback.pop('large_text', None)
                    if isinstance(error, TypeError):
                        fallback.pop('activity_type', None)
                    try:
                        self.rpc.update(**fallback)
                    except Exception as fallback_error:
                        if type(fallback_error).__name__ not in ('ServerError','InvalidArgument','ArgumentError'):
                            raise
                        with self._lock:
                            self._last_error = 'activity_rejected'
            with self._lock:
                self._sent_revision, self._last_sent = revision, self._clock()
        except Exception as error:
            self._disconnect(error)
        return 1

    def _run(self):
        try:
            while True:
                self._wake.clear()
                delay = self._run_cycle()
                if delay is None:
                    with self._lock:
                        if self._active and self.is_enabled():
                            continue
                    return
                self._wake.wait(delay)
        except Exception:
            logger.error('Discord worker stopped unexpectedly', exc_info=False)
            self._disconnect()
            with self._lock:
                self._active = False
        finally:
            with self._lock:
                client, self.rpc = self.rpc, None
                self.connected = False
            self._close(client, clear=bool(client))
            with self._lock:
                self._worker = None
                restart = self._active and self.is_enabled()
            if restart:
                self.start(_automatic=True)
