"""Verified recording selection — the single gate for every fallback path.

Every fallback used to accept the provider's first hit (BUG-A1-001/002/003/
004/005/010/012, S4-006): the engine's Spotify branch, the engine's SoundCloud
and YouTube tiers, the app's ytsearch/SoundCloud cascade, the downloader's
Spotify fallback and the proxy's self-heal. This module is the one place that
turns a candidate list into the recording that actually matches the requested
track — or reports that none does, so callers fail with a correct error
instead of playing a remix, a live take or another artist's upload.

Verification reuses :func:`core.playback_recovery.same_recording` (similarity
>= 0.88, version via ``music_matching.VERSION_PATTERNS``, duration within
max(4s, 2.5%), artist credits) — there is deliberately no second implementation
of the comparison rules.
"""

import logging
import re
import threading

from core.playback_recovery import same_recording

logger = logging.getLogger(__name__)

#: Fallback searches must look past the top hit to find a verifiable recording.
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_SEARCH_TIMEOUT = 6.0

# youtube_service._YT_VIDEO_ID_RE is private to that module; the check is
# duplicated here (a compiled constant, not behaviour) so this module does not
# import the whole yt-dlp-backed service.
_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')

#: SettingsManager category that persists the resolved recording identity.
_RESOLUTION_CATEGORY = 'resolution'


def select_recording(track, candidates):
    """Return the best candidate dict matching *track*, or None.

    A candidate is considered only when ``same_recording`` accepts it. Among
    the accepted ones the preferred recording is a provider-native "song"
    result whose duration is closest to the requested one.
    """
    if not isinstance(track, dict) or not str(track.get('title') or '').strip():
        return None
    best = None
    best_key = None
    for item in candidates or []:
        if not isinstance(item, dict) or not str(item.get('title') or '').strip():
            continue
        if not same_recording(track, item):
            continue
        try:
            expected = float(track.get('duration') or 0)
            actual = float(item.get('duration') or 0)
        except (TypeError, ValueError):
            expected = actual = 0.0
        delta = abs(expected - actual) if expected > 0 and actual > 0 else 0.0
        result_type = str(item.get('resultType') or item.get('result_type') or 'song').lower()
        song_penalty = 0 if result_type == 'song' else 1
        key = (song_penalty, delta)
        if best_key is None or key < best_key:
            best, best_key = item, key
    return best


def search_verified(provider, track, query=None, limit=DEFAULT_SEARCH_LIMIT,
                    timeout=DEFAULT_SEARCH_TIMEOUT):
    """Search *provider* and return the best verified candidate, or None.

    The provider is the service object with the standard async ``search``
    interface (callback / error_callback). No network call is made when the
    provider is missing or the track has no title to verify against.
    """
    if provider is None or not isinstance(track, dict) or not str(track.get('title') or '').strip():
        return None
    text = query or f"{track.get('artist') or ''} {track.get('title') or ''}".strip()
    if not text:
        return None
    results = []
    done = threading.Event()

    def on_results(items):
        if isinstance(items, list):
            results.extend(items)
        done.set()

    try:
        provider.search(text, max_results=limit, callback=on_results,
                        error_callback=lambda _error: done.set())
    except Exception as exc:
        logger.debug('Verified search failed for %r: %s', text, exc)
        return None
    done.wait(timeout=max(0.5, float(timeout)))
    return select_recording(track, results)


def stream_matches(track, metadata, requested_id=None):
    """True when an extracted stream's metadata may be accepted for *track*.

    When the provider resolved exactly the identifier we addressed (a direct
    video/track id, not a search expression), the recording is the requested
    one by construction and metadata comparison is skipped. Otherwise the
    stream's metadata must pass ``same_recording`` — mirroring
    playback_recovery, a response without any metadata is not rejected.
    """
    if not isinstance(metadata, dict) or not metadata.get('title'):
        return True
    resolved = str(metadata.get('source_id') or '')
    if requested_id and resolved and resolved == str(requested_id):
        return True
    return same_recording(track, metadata)


def remember_video_id(settings, source, source_id, video_id):
    """Persist the verified recording id for a search-identity track.

    Spotify/iTunes catalogue rows carry a textual source_id
    (``ytsearch1: Artist - Title``); every re-resolve from that string must
    return the SAME recording, so the first verified video id is remembered
    in the settings store (durable, no expiry) and all later cascades address
    the recording directly.
    """
    vid = str(video_id or '').strip()
    if not settings or not vid or not _VIDEO_ID_RE.fullmatch(vid):
        return
    if str(source or '') != 'spotify':
        return
    key = _recording_key(source, source_id)
    if not key:
        return
    try:
        settings.set(_RESOLUTION_CATEGORY, key, vid)
    except Exception:
        logger.debug('remember_video_id failed for %s:%s', source, source_id, exc_info=True)


def remembered_video_id(settings, source, source_id):
    """Return the persisted recording id for (source, source_id), or ''. """
    key = _recording_key(source, source_id)
    if not settings or not key:
        return ''
    try:
        vid = str(settings.get(_RESOLUTION_CATEGORY, key, '') or '').strip()
    except Exception:
        return ''
    return vid if _VIDEO_ID_RE.fullmatch(vid) else ''


def _recording_key(source, source_id):
    source_id = str(source_id or '').strip()
    if not source_id:
        return ''
    return f'recording:{source}:{source_id}'
