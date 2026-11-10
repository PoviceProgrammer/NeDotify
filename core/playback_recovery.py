"""Bounded stream renewal without changing the queue or listening session."""

import math
import os
import re
import threading
import time
from urllib.parse import urlparse

from services.music_matching import VERSION_PATTERNS, artist_matches, normalize, similarity, title_metadata
from utils.stream_urls import stream_url_expired


def _remix_titles_match(requested, candidate):
    """Allow a shared artist credit inside an otherwise identical named mix.

    Catalogues sometimes include the remixer's name in only one qualifier.
    Remove at most that shared credit on one side; never remove the mix name,
    year, or different credits on both sides. A generic 'Remix' is insufficient.
    """
    left, right = normalize(requested['title']), normalize(candidate['title'])
    if left == right:
        return True
    common = ({normalize(a) for a in requested['artists']}
              & {normalize(a) for a in candidate['artists']}) - {''}
    for metadata, target in ((requested, right), (candidate, left)):
        text = metadata['title']
        for match in re.finditer(r'[\[(]([^\])]+)[\])]', text):
            qualifier = normalize(match.group(1))
            if not re.search(VERSION_PATTERNS['remix'], qualifier, re.I):
                continue
            for credit in common:
                shortened = re.sub(r'(?<!\w)' + re.escape(credit) + r'(?!\w)', ' ', qualifier)
                if shortened == qualifier:
                    continue
                if not re.sub(VERSION_PATTERNS['remix'], '', shortened, flags=re.I).strip():
                    continue
                variant = text[:match.start(1)] + shortened + text[match.end(1):]
                if normalize(variant) == target:
                    return True
    return False


def same_recording(wanted, offered):
    if not isinstance(offered, dict):
        return False
    requested = title_metadata(wanted.get("title"), wanted.get("artist"))
    candidate = title_metadata(offered.get("title"), offered.get("artist") or offered.get("uploader"))
    embedded = title_metadata(offered.get("title"))
    if requested["artists"] and artist_matches(requested["artists"], embedded["artists"]):
        candidate = embedded
    if not requested["base_title"] or similarity(requested["base_title"], candidate["base_title"]) < 0.88:
        return False
    if requested["version"] != candidate["version"]:
        return False
    if requested["version"] == "remix" and not _remix_titles_match(requested, candidate):
        return False
    if requested["artists"] and not artist_matches(requested["artists"], candidate["artists"]):
        return False
    try:
        expected = float(wanted.get("duration") or 0)
        actual = float(offered.get("duration") or 0)
    except (ValueError, TypeError):
        return False
    if not math.isfinite(expected) or not math.isfinite(actual) or (expected > 0 and actual <= 0):
        return False
    if expected and actual and abs(expected - actual) > max(4.0, expected * 0.025):
        return False
    return True


def _callback_result(invoke, timeout):
    completed = threading.Event()
    result = {}

    def success(value, metadata=None):
        if completed.is_set():
            return
        result.update(value=value, metadata=metadata or {})
        completed.set()

    def failure(error):
        if completed.is_set():
            return
        result["error"] = str(error)
        completed.set()

    def run():
        try:
            invoke(success, failure)
        except Exception as error:
            failure(error)
    threading.Thread(target=run, name="PlaybackRecovery", daemon=True).start()
    if not completed.wait(max(0, timeout)):
        completed.set()
        return None, {}
    return result.get("value"), result.get("metadata", {})


def _target(source, track):
    identifier = str(track.get("source_id") or "").strip()
    if source == 'deezer':
        return identifier
    if source == "youtube":
        return identifier if identifier.startswith("https://") else f"https://www.youtube.com/watch?v={identifier}"
    if source == "soundcloud":
        if identifier.startswith("https://") or identifier.isdigit():
            return identifier
        return f"https://soundcloud.com/{identifier}" if "/" in identifier else identifier
    return str(track.get("source_url") or identifier)


def _invalidate(core, source, track, target):
    from services.base_service import BaseMusicService

    identifier = str(track.get("source_id") or "")
    resolver = getattr(core, "resolver", None)
    cached = resolver.get_cached_url(source, identifier) if resolver else None
    if resolver:
        resolver.invalidate(source, identifier)
        resolver.clear_unavailable(source, identifier)
    dead_urls = {cached, track.get("file_path"), track.get("stream_url")}
    with BaseMusicService._cache_lock:
        entries = tuple(BaseMusicService._stream_cache.items())
    for key, entry in entries:
            data = entry.get("data", entry) if isinstance(entry, dict) else {}
            url = data.get("stream_url") if isinstance(data, dict) else None
            if key in (f"{source}:{identifier}", f"{source}:{target}") or (url and url in dead_urls):
                with BaseMusicService._cache_lock:
                    if BaseMusicService._stream_cache.get(key) is entry:
                        BaseMusicService._stream_cache.pop(key, None)


def recover_stream(core, track, position_ms=0):
    """Return a renewed playable URL; providers use their existing bounded pools."""
    if not isinstance(track, dict):
        return {"ok": False, "code": "invalid_track", "error": "Трек не выбран"}
    try:
        position = float(position_ms)
        if not math.isfinite(position):
            raise ValueError
    except (ValueError, TypeError):
        position = 0
    position = max(0, round(position))
    source = str(track.get("source") or "local")
    identifier = str(track.get("source_id") or "")
    local_file = track.get("file_path")
    if local_file and os.path.isfile(str(local_file)):
        return {"ok": True, "stream_url": str(local_file), "position_ms": position,
                "source": source, "source_id": identifier}
    settings = getattr(core, "settings", None)
    def source_enabled(name):
        return not settings or settings.get('services', name + '_enabled', True) is not False
    if source == "local":
        return {"ok": False, "code": "file_missing", "error": "Файл перемещён или удалён. Выберите его заново"}
    if source not in ("youtube", "soundcloud", "spotify", "yandex", "deezer"):
        return {"ok": False, "code": "source_unavailable", "error": "Источник не поддерживает восстановление"}
    target = _target(source, track)
    if source_enabled(source):
        _invalidate(core, source, track, target)
    deadline = time.monotonic() + 18.0
    stream = None
    selected_source = source
    selected_id = identifier
    service = getattr(core, source, None) if source != "spotify" and source_enabled(source) else None
    if service and identifier:
        stream, metadata = _callback_result(
            lambda done, failed: service.get_stream_url(target, callback=done, error_callback=failed),
            min(8.0, deadline - time.monotonic()),
        )
        if stream and metadata and metadata.get("title") and not same_recording(track, metadata):
            stream = None
    if not stream and track.get("title"):
        for fallback in ("youtube", "soundcloud"):
            if time.monotonic() >= deadline:
                break
            if not source_enabled(fallback):
                continue
            provider = getattr(core, fallback, None)
            if not provider:
                continue
            query = f"{track.get('artist') or ''} {track['title']}".strip()
            candidates, _ = _callback_result(
                lambda done, failed: provider.search(query, max_results=5, callback=done, error_callback=failed),
                min(3.0, deadline - time.monotonic()),
            )
            candidate = next((item for item in (candidates or []) if same_recording(track, item)), None)
            if not candidate:
                continue
            candidate_target = _target(fallback, candidate)
            _invalidate(core, fallback, candidate, candidate_target)
            stream, metadata = _callback_result(
                lambda done, failed: provider.get_stream_url(candidate_target, callback=done, error_callback=failed),
                min(4.0, deadline - time.monotonic()),
            )
            if stream and metadata and metadata.get("title") and not same_recording(track, metadata):
                stream = None
            if stream:
                selected_source = fallback
                selected_id = str(candidate.get("source_id") or "")
                break
    if not stream or stream_url_expired(stream):
        return {"ok": False, "code": "source_unavailable", "error": "Не удалось восстановить эту запись. Повторите позже или выберите скачанный трек"}
    parsed = urlparse(str(stream))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"ok": False, "code": "invalid_stream", "error": "Источник вернул некорректный адрес"}
    if source == "soundcloud" and "googlevideo" in parsed.hostname and selected_source == source:
        metadata_source = metadata.get("resolved_source") if isinstance(metadata, dict) else None
        if metadata_source != "youtube":
            return {"ok": False, "code": "version_mismatch", "error": "Резервная запись не прошла проверку версии"}
    resolver = getattr(core, "resolver", None)
    if resolver:
        resolver.refresh(selected_source, selected_id, stream)
    proxy = getattr(core, "proxy", None)
    playback_url = proxy.get_proxy_url(selected_source, selected_id, stream, track_id=track.get("id")) if proxy else stream
    return {"ok": True, "stream_url": playback_url, "position_ms": position,
            "source": selected_source, "source_id": selected_id}
