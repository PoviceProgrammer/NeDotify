"""
AURA Music - Lyrics Service
Fetches synced and plain lyrics using 6 databases with a race condition weight system.
"""

import atexit
import concurrent.futures
import html
import json
import logging
import os
import re
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Verified TLS context (default). Certificate checks are restored for all
# metadata/lyrics requests; stream extraction is handled by yt-dlp separately.
ssl_ctx = ssl.create_default_context()

# Every outbound lyrics request gets this ceiling so a hung host cannot pin a worker.
HTTP_TIMEOUT = 6.0


class _LyricsSharedExecutor:
    """Lazy, bounded, shutdown-safe ThreadPoolExecutor for lyrics fetching."""

    def __init__(self, max_workers: int = 4, thread_name_prefix: str = "LyricsPool"):
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix
        self._lock = threading.Lock()
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._shutdown = False

    def submit(self, fn: Callable, *args, **kwargs) -> Optional[concurrent.futures.Future]:
        """Schedule `fn`; return its Future, or None when scheduling is impossible."""
        if self._shutdown or sys.is_finalizing():
            logger.debug(
                "Lyrics executor unavailable (shutdown=%s); dropping task %r",
                self._shutdown,
                getattr(fn, "__name__", fn),
            )
            return None
        pool = self._pool
        if pool is None:
            with self._lock:
                if self._shutdown:
                    logger.debug(
                        "Lyrics executor shut down while acquiring lock; dropping task %r",
                        getattr(fn, "__name__", fn),
                    )
                    return None
                if self._pool is None:
                    self._pool = concurrent.futures.ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix=self._thread_name_prefix,
                    )
                pool = self._pool
        try:
            return pool.submit(fn, *args, **kwargs)
        except RuntimeError as e:
            self._shutdown = True
            logger.debug("Lyrics executor refused task %r: %s", getattr(fn, "__name__", fn), e)
            return None

    def shutdown(self, wait: bool = False, cancel_futures: bool = True) -> None:
        """Stop accepting work and tear the pool down without blocking."""
        with self._lock:
            self._shutdown = True
            pool, self._pool = self._pool, None
        if pool is None:
            return
        try:
            pool.shutdown(wait=wait, cancel_futures=cancel_futures)
        except Exception as e:
            logger.debug("Lyrics executor shutdown error: %s", e, exc_info=True)


_lyrics_pool = _LyricsSharedExecutor(max_workers=4, thread_name_prefix="LyricsPool")
atexit.register(_lyrics_pool.shutdown, wait=False, cancel_futures=True)


class LyricsService:
    def __init__(self, settings=None):
        self.settings = settings
        self._cache = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def submit(cls, fn: Callable, *args, **kwargs) -> Optional[concurrent.futures.Future]:
        """Submit a task to the shared bounded lyrics thread pool."""
        return _lyrics_pool.submit(fn, *args, **kwargs)

    @classmethod
    def shutdown_executor(cls, wait: bool = False, cancel_futures: bool = True) -> None:
        """Shut down the shared bounded lyrics thread pool."""
        _lyrics_pool.shutdown(wait=wait, cancel_futures=cancel_futures)

    def _clean_track_and_artist(self, track_name: str, artist_name: str):
        track = track_name.strip() if track_name else ""
        artist = artist_name.strip() if artist_name else ""

        # Remove video/audio suffixes and junk common in streaming and YouTube titles
        junk_patterns = [
            r'\s*[\(\[](official\s*(music\s*)?(video|audio|lyrics?|visualizer|track)?|lyric\s*video|audio|video|visualizer|clip|клип|премьера(\s*трека|\s*клипа)?)[\)\]]',
            r'\s*[\(\[](feat|ft)\.?\s+[^\)\]]+[\)\]]',
            r'\s*[\(\[](prod|produced)\.?\s+by\s+[^\)\]]+[\)\]]',
            r'\s*[\(\[](remix|slowed(\s*\+\s*reverb)?|speed\s*up|sped\s*up)[\)\]]',
            r'\s*[\(\[]\d{4}[\)\]]',
            r'\s*[\(\[](hd|hq|4k|1080p)[\)\]]',
            r'\s*\|\s*.*$',
        ]
        for p in junk_patterns:
            track = re.sub(p, '', track, flags=re.IGNORECASE)

        track = track.replace('"', '').replace("'", "").strip()

        # If artist is provided and is inside track title, remove it from track
        if artist:
            art_esc = re.escape(artist)
            track = re.sub(rf'^{art_esc}\s*[\-—–:]\s*', '', track, flags=re.IGNORECASE).strip()
            track = re.sub(rf'\s*[\-—–:]\s*{art_esc}$', '', track, flags=re.IGNORECASE).strip()
        elif not artist:
            # Try splitting "Artist - Title" or "Title — Artist"
            parts = re.split(r'\s*[\-—–]\s*', track, maxsplit=1)
            if len(parts) == 2 and parts[0] and parts[1]:
                artist = parts[0].strip()
                track = parts[1].strip()

        track = track.strip(' -—–:;.,|')
        artist = artist.strip(' -—–:;.,|')
        return track or track_name.strip(), artist or (artist_name.strip() if artist_name else "")

    def _open_url(self, req_or_url, headers=None, timeout=3.5):
        if isinstance(req_or_url, str):
            req = urllib.request.Request(req_or_url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
        else:
            req = req_or_url
        return urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)

    def translate_lyrics(self, lyrics: str, target_lang="ru") -> str:
        if not lyrics:
            return ""
        try:
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(lyrics)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                return "".join([x[0] for x in data[0] if x[0]])
        except Exception as e:
            logger.debug(f"Translation error: {e}")
            return lyrics

    def get_lyrics(self, track_name: str, artist_name: str = "", duration_ms: int = 0, file_path: str = None) -> dict:
        if file_path and os.path.exists(file_path):
            try:
                from utils.tag_parser import parse_audio_file
                tags = parse_audio_file(file_path)
                if tags and tags.get("lyrics"):
                    raw_lyr = str(tags["lyrics"]).strip()
                    if raw_lyr:
                        is_synced = bool(re.search(r'\[\d+:\d+', raw_lyr))
                        return self._make_result(raw_lyr if is_synced else None, raw_lyr)
            except Exception as e:
                logger.debug("Embedded lyrics lookup error for %s: %s", file_path, e)

        track_name_str = str(track_name).strip() if track_name is not None else ""
        artist_name_str = str(artist_name).strip() if artist_name is not None else ""
        if not track_name_str:
            return {"syncedLyrics": None, "plainLyrics": None, "instrumental": False, "weight": 3}

        track, artist = self._clean_track_and_artist(track_name_str, artist_name_str)

        # Check in-memory lyrics cache
        cache_key = (track.lower(), artist.lower())
        with self._cache_lock:
            if cache_key in self._cache:
                hit = self._cache[cache_key]
                if hit.get("weight", 3) < 3:
                    return hit

        # Define 6 fetcher methods to run concurrently in the shared bounded pool
        fetchers = [
            self._fetch_lrclib,
            self._fetch_netease,
            self._fetch_qqmusic,
            self._fetch_megalobiz,
            self._fetch_genius,
            self._fetch_duckduckgo,
        ]

        def _execute_cascade(t, a, max_timeout=3.5):
            futures = {}
            for f in fetchers:
                future = _lyrics_pool.submit(f, t, a)
                if future is not None:
                    futures[future] = getattr(f, '__name__', str(f))
            if not futures:
                return None

            not_done = set(futures.keys())
            best_weight_2 = None
            weight2_found_time = None
            start_time = time.time()

            while not_done:
                elapsed = time.time() - start_time
                if elapsed >= max_timeout:
                    break

                if best_weight_2 and weight2_found_time:
                    fast_exit_remaining = 0.6 - (time.time() - weight2_found_time)
                    if fast_exit_remaining <= 0:
                        return best_weight_2
                    time_left = min(0.2, max_timeout - elapsed, max(0.01, fast_exit_remaining))
                else:
                    time_left = min(0.2, max_timeout - elapsed)

                if time_left <= 0:
                    break

                done, not_done = concurrent.futures.wait(
                    not_done,
                    timeout=time_left,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for fut in done:
                    try:
                        res = fut.result()
                        if res and isinstance(res, dict):
                            w = res.get('weight', 3)
                            if w == 1:
                                return res  # Immediate WIN
                            elif w == 2 and not best_weight_2:
                                best_weight_2 = res
                                weight2_found_time = time.time()
                    except Exception as e:
                        logger.debug(f"Lyrics fetcher {futures.get(fut, '?')} failed: {e}", exc_info=True)

            return best_weight_2

        result = _execute_cascade(track, artist, max_timeout=3.5)

        # If not found and artist was inferred from track title, try flipped (artist, track)
        if (not result or result.get("weight", 3) >= 3) and not artist_name and artist and track != artist:
            alt_res = _execute_cascade(artist, track, max_timeout=2.0)
            if alt_res and alt_res.get("weight", 3) < 3:
                result = alt_res

        if result and result.get("weight", 3) < 3:
            with self._cache_lock:
                if len(self._cache) > 500:
                    self._cache.clear()
                self._cache[cache_key] = result
                if track_name and (track_name.lower(), (artist_name or "").lower()) != cache_key:
                    self._cache[(track_name.lower(), (artist_name or "").lower())] = result
            return result

        return {"syncedLyrics": None, "plainLyrics": None, "instrumental": False, "weight": 3}

    @staticmethod
    def parse_lrc(lrc_text: str, offset_ms: int = 0) -> list:
        """
        Parse raw LRC text into a list of timed lyrics dictionaries:
        [{ 'timeMs': <int>, 'text': <str> }, ...]
        
        Handles:
        - [offset: +/-ms] tags in metadata header
        - 1-digit, 2-digit, and 3-digit minutes ([1:23.45], [01:23.45], [120:00.00])
        - Centiseconds and milliseconds ([mm:ss.xx], [mm:ss.xxx])
        - Colon-separated milliseconds ([mm:ss:xx])
        - Multiple timestamps on the same line ([00:10.00][00:20.00]Chorus)
        - Metadata headers ([ti:], [ar:], [al:], etc.) filtered out
        - Empty/malformed strings and timestamp clamping to >= 0
        """
        if not lrc_text or not isinstance(lrc_text, str):
            return []

        lines = lrc_text.splitlines()
        result = []
        header_offset = 0

        # Pass 1: find [offset: +/-milliseconds] tag
        offset_re = re.compile(r'^\[offset:\s*([+-]?\d+)\]', re.IGNORECASE)
        for line in lines:
            trimmed = line.strip()
            m = offset_re.match(trimmed)
            if m:
                try:
                    header_offset = int(m.group(1))
                except (ValueError, TypeError):
                    pass
                break

        total_offset = int(offset_ms) + header_offset

        # Pass 2: parse timestamps
        time_reg = re.compile(r'\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]')
        meta_reg = re.compile(r'^\[(ti|ar|al|by|offset|length|re|ve):', re.IGNORECASE)

        for line in lines:
            trimmed = line.strip()
            if not trimmed or meta_reg.match(trimmed):
                continue

            matches = list(time_reg.finditer(trimmed))
            if matches:
                text = time_reg.sub('', trimmed).strip()
                if not text:
                    text = '♪'
                for m in matches:
                    try:
                        minute = int(m.group(1))
                        second = int(m.group(2))
                        ms_str = m.group(3) or '0'
                        if len(ms_str) == 1:
                            ms = int(ms_str) * 100
                        elif len(ms_str) == 2:
                            ms = int(ms_str) * 10
                        else:
                            ms = int(ms_str[:3])
                        time_ms = minute * 60000 + second * 1000 + ms
                        final_time = max(0, time_ms + total_offset)
                        result.append({'timeMs': final_time, 'text': text})
                    except (ValueError, TypeError):
                        continue

        result.sort(key=lambda x: x['timeMs'])
        return result

    def _make_result(self, synced, plain):
        c_synced = str(synced).strip() if synced is not None else ""
        c_plain = str(plain).strip() if plain is not None else ""

        if not c_synced and not c_plain:
            return None

        # Check if synced contains valid parsed timestamps
        if c_synced:
            parsed = self.parse_lrc(c_synced)
            if len(parsed) > 0:
                return {
                    "syncedLyrics": c_synced,
                    "plainLyrics": c_plain or c_synced,
                    "weight": 1,
                }

        # Fallback to plain lyrics if text is non-empty
        lyrics_text = c_plain or c_synced
        if lyrics_text and len(lyrics_text.strip()) > 0:
            return {
                "syncedLyrics": None,
                "plainLyrics": lyrics_text,
                "weight": 2,
            }

        return None

    def _clean_str(self, text):
        if not text:
            return ""
        text = re.sub(r'\(feat\.[^\)]+\)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[[^\]]+\]', '', text)
        text = re.sub(r'\(prod\.[^\)]+\)', '', text, flags=re.IGNORECASE)
        return text.strip()

    def _fetch_lrclib(self, track, artist):
        c_track = self._clean_str(track)
        c_artist = artist.split(',')[0].split('&')[0].strip() if artist else ""

        # 1. Try exact /api/get
        try:
            url = f"https://lrclib.net/api/get?artist_name={urllib.parse.quote(c_artist)}&track_name={urllib.parse.quote(c_track)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'AURA-Music/1.0'})
            with self._open_url(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                res = self._make_result(data.get("syncedLyrics"), data.get("plainLyrics"))
                if res:
                    return res
        except Exception as e:
            logger.debug(f"lrclib exact lookup failed for '{c_artist} - {c_track}': {e}", exc_info=True)

        # 2. Fallback to /api/search
        try:
            q = f"{c_artist} {c_track}".strip()
            url = f"https://lrclib.net/api/search?q={urllib.parse.quote(q)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'AURA-Music/1.0'})
            with self._open_url(req, timeout=3.5) as resp:
                results = json.loads(resp.read().decode('utf-8', errors='ignore'))
                if isinstance(results, list) and results:
                    for item in results:
                        res = self._make_result(item.get("syncedLyrics"), item.get("plainLyrics"))
                        if res and res.get('weight') == 1:
                            return res
                    first_res = self._make_result(results[0].get("syncedLyrics"), results[0].get("plainLyrics"))
                    if first_res:
                        return first_res
        except Exception as e:
            logger.debug(f"lrclib search lookup failed for '{c_artist} {c_track}': {e}", exc_info=True)

        return None

    def _fetch_netease(self, track, artist):
        try:
            query = f"{artist} {track}".strip()
            url = f"http://music.163.com/api/search/pc?type=1&offset=0&limit=1&s={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                songs = data.get('result', {}).get('songs', [])
                if not songs:
                    return None
                sid = songs[0]['id']

            l_url = f"http://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1"
            l_req = urllib.request.Request(l_url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(l_req, timeout=3.5) as l_resp:
                l_data = json.loads(l_resp.read().decode('utf-8', errors='ignore'))
                lrc = l_data.get('lrc', {}).get('lyric')
                return self._make_result(lrc, lrc)
        except Exception as e:
            logger.debug(f"netease lookup failed for '{artist} {track}': {e}", exc_info=True)
            return None

    def _fetch_qqmusic(self, track, artist):
        try:
            query = f"{artist} {track}".strip()
            url = f"https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={urllib.parse.quote(query)}&format=json&n=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                songs = data.get('data', {}).get('song', {}).get('list', [])
                if not songs:
                    return None
                songmid = songs[0]['songmid']

            l_url = f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={songmid}&format=json&nobase64=1"
            l_req = urllib.request.Request(l_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://y.qq.com/'})
            with self._open_url(l_req, timeout=3.5) as l_resp:
                l_data = json.loads(l_resp.read().decode('utf-8', errors='ignore'))
                lrc = l_data.get('lyric')
                lrc = html.unescape(lrc) if lrc else None
                return self._make_result(lrc, lrc)
        except Exception as e:
            logger.debug(f"qqmusic lookup failed for '{artist} {track}': {e}", exc_info=True)
            return None

    def _fetch_genius(self, track, artist):
        try:
            query = f"{artist} {track}".strip()
            url = f"https://genius.com/api/search/multi?per_page=1&q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                sections = data.get('response', {}).get('sections') or [{}]
                hits = sections[0].get('hits', []) if sections else []
                if not hits:
                    return None
                s_url = hits[0]['result']['url']

            s_req = urllib.request.Request(s_url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(s_req, timeout=3.5) as s_resp:
                html_content = s_resp.read().decode('utf-8', errors='ignore')
                lyrics_parts = re.findall(r'<div data-lyrics-container="true"[^>]*>(.*?)</div>', html_content)
                if lyrics_parts:
                    txt = "\n".join(lyrics_parts)
                    txt = re.sub(r'<br/?>', '\n', txt)
                    txt = re.sub(r'<[^>]+>', '', txt)
                    txt = html.unescape(txt)
                    return self._make_result(None, txt)
        except Exception as e:
            logger.debug(f"genius lookup failed for '{artist} {track}': {e}", exc_info=True)
            return None
        return None

    def _fetch_megalobiz(self, track, artist):
        try:
            query = f"{artist} {track}".strip()
            url = f"https://www.megalobiz.com/search/all?qry={urllib.parse.quote(query)}&searchButton.x=0&searchButton.y=0"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=3.5) as resp:
                html_content = resp.read().decode('utf-8', errors='ignore')
                link = re.search(r'href="(/lrc/maker/[^"]+)"', html_content)
                if not link:
                    return None

            l_url = "https://www.megalobiz.com" + link.group(1)
            l_req = urllib.request.Request(l_url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(l_req, timeout=3.5) as l_resp:
                l_html = l_resp.read().decode('utf-8', errors='ignore')
                lrc_match = re.search(r'<div id="lrc_[^"]*"[^>]*>(.*?)</div>', l_html, re.S)
                if not lrc_match:
                    lrc_match = re.search(r'<span id="lrc_[^"]*"[^>]*>(.*?)</span>', l_html, re.S)
                if lrc_match:
                    txt = lrc_match.group(1).replace('<br>', '\n').strip()
                    return self._make_result(txt, txt)
        except Exception as e:
            logger.debug(f"megalobiz lookup failed for '{artist} {track}': {e}", exc_info=True)
            return None
        return None

    def _fetch_duckduckgo(self, track, artist):
        try:
            query = f"{artist} {track} lyrics".strip()
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with self._open_url(req, timeout=3.5) as resp:
                html_content = resp.read().decode('utf-8', errors='ignore')
                snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html_content, re.S)
                if snippets:
                    txt = "\n".join(snippets).replace('<b>', '').replace('</b>', '').strip()
                    txt = html.unescape(txt)
                    return self._make_result(None, txt)
        except Exception as e:
            logger.debug(f"duckduckgo lookup failed for '{artist} {track}': {e}", exc_info=True)
            return None
        return None
