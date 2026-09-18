"""
AURA Music - Lyrics Service
Fetches synced and plain lyrics using 6 databases with a race condition weight system.
"""

import atexit
import concurrent.futures
import difflib
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

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize string for fuzzy comparison: lowercased, punctuation stripped, whitespace collapsed."""
        if not text:
            return ""
        s = re.sub(r'[^\w\s]', ' ', text.lower())
        return ' '.join(s.split())

    def _score_candidate(
        self,
        target_title: str,
        target_artist: str,
        target_dur_s: float,
        cand_title: str,
        cand_artist: str,
        cand_dur_s: float = 0.0,
    ) -> float:
        """
        Calculates similarity score (0.0 to 1.0) between target song and candidate match.
        Takes into account title overlap, artist match, and duration tolerance.
        """
        norm_t_title = self._normalize_text(target_title)
        norm_c_title = self._normalize_text(cand_title)
        if not norm_t_title or not norm_c_title:
            return 0.0

        # 1. Title Similarity (0.0 to 1.0)
        t_tokens = set(norm_t_title.split())
        c_tokens = set(norm_c_title.split())
        token_overlap = len(t_tokens & c_tokens) / max(1, len(t_tokens))
        seq_ratio = difflib.SequenceMatcher(None, norm_t_title, norm_c_title).ratio()
        title_score = 0.5 * seq_ratio + 0.5 * token_overlap
        # Boost if substring match
        if norm_t_title in norm_c_title or norm_c_title in norm_t_title:
            title_score = max(title_score, 0.85)

        # 2. Artist Similarity (0.0 to 1.0)
        norm_t_artist = self._normalize_text(target_artist)
        norm_c_artist = self._normalize_text(cand_artist)
        if not norm_t_artist:
            # If target artist is empty, rely mostly on title
            artist_score = 0.8
        else:
            ta_tokens = set(norm_t_artist.split())
            ca_tokens = set(norm_c_artist.split())
            a_overlap = len(ta_tokens & ca_tokens) / max(1, len(ta_tokens))
            a_seq = difflib.SequenceMatcher(None, norm_t_artist, norm_c_artist).ratio()
            artist_score = 0.5 * a_seq + 0.5 * a_overlap
            if norm_t_artist in norm_c_artist or norm_c_artist in norm_t_artist:
                artist_score = max(artist_score, 0.85)

            # Hard penalty if artists clearly contradict (long distinct names with 0 overlap)
            if len(norm_t_artist) >= 4 and len(norm_c_artist) >= 4 and not (ta_tokens & ca_tokens) and a_seq < 0.35:
                artist_score = -0.3

        # 3. Duration Match (-1.0 to 1.0)
        if target_dur_s > 0 and cand_dur_s > 0:
            delta = abs(target_dur_s - cand_dur_s)
            if delta <= 4.0:
                dur_score = 1.0
            elif delta <= 8.0:
                dur_score = 0.85
            elif delta <= 15.0:
                dur_score = 0.5
            elif delta <= 25.0:
                dur_score = 0.0
            else:
                # Discrepancy > 25 seconds: strong penalty proportional to mismatch
                penalty = min(1.5, (delta - 25.0) / 40.0)
                dur_score = -penalty
        else:
            dur_score = 0.7  # neutral when duration is unknown

        # Weighted composite score
        total_score = 0.45 * title_score + 0.35 * artist_score + 0.20 * dur_score
        return round(total_score, 3)

    def _clean_track_and_artist(self, track_name: str, artist_name: str):
        track = track_name.strip() if track_name else ""
        artist = artist_name.strip() if artist_name else ""

        # 1. Clean artist channel suffixes (VEVO, - Topic, Official, Records, etc.)
        if artist:
            had_vevo = bool(re.search(r'VEVO$', artist, flags=re.IGNORECASE))
            artist = re.sub(r'(VEVO|\s*-\s*Topic|\s+Official(\s+Channel)?|\s+Records|\s+Music|\s+TV)$', '', artist, flags=re.IGNORECASE).strip()
            if had_vevo:
                artist = re.sub(r'([a-z])([A-Z])', r'\1 \2', artist)

        # 2. Extract "Artist - Title" if embedded in track title
        split_match = re.split(r'\s*[\-—–]\s*', track, maxsplit=1)
        if len(split_match) == 2 and split_match[0] and split_match[1]:
            candidate_artist = split_match[0].strip()
            candidate_track = split_match[1].strip()
            # If current artist is empty or was a generic channel/VEVO, adopt parsed artist
            if not artist or 'vevo' in artist_name.lower() or 'topic' in artist_name.lower() or 'records' in artist_name.lower():
                artist = candidate_artist
                track = candidate_track
            elif candidate_artist.lower() in artist.lower() or artist.lower() in candidate_artist.lower():
                # Title starts with artist name: trim it off
                track = candidate_track

        # 3. Remove video/audio suffixes and junk common in streaming and YouTube titles
        junk_patterns = [
            r'\s*[\(\[](official\s*[^)\]]*|lyric\s*video|audio|video|visualizer|clip|клип|премьера[^)\]]*)[\)\]]',
            r'\s*[\(\[](remastered?(\s*\d{4})?|\d{4}\s*remaster)[\)\]]',
            r'\s*[\(\[](feat|ft)\.?\s+[^\)\]]+[\)\]]',
            r'\s*[\(\[](prod|produced)\.?\s+by\s+[^\)\]]+[\)\]]',
            r'\s*[\(\[](remix|slowed(\s*\+\s*reverb)?|speed\s*up|sped\s*up|acoustic|live)[\)\]]',
            r'\s*[\(\[]\d{4}[\)\]]',
            r'\s*[\(\[](hd|hq|4k|1080p|60fps|mv|ncs\s*release)[\)\]]',
            r'\s*\|\s*.*$',
        ]
        for p in junk_patterns:
            track = re.sub(p, '', track, flags=re.IGNORECASE)

        track = track.replace('"', '').replace("'", "").strip()

        # 4. Strip artist name from title edges if still present
        if artist:
            art_esc = re.escape(artist)
            track = re.sub(rf'^{art_esc}\s*[\-—–:]\s*', '', track, flags=re.IGNORECASE).strip()
            track = re.sub(rf'\s*[\-—–:]\s*{art_esc}$', '', track, flags=re.IGNORECASE).strip()

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

        def _execute_cascade(t, a, d_ms=0, max_timeout=3.5):
            futures = {}
            for f in fetchers:
                future = _lyrics_pool.submit(f, t, a, d_ms)
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

        result = _execute_cascade(track, artist, duration_ms, max_timeout=3.5)

        # If not found and artist was inferred from track title, try flipped (artist, track)
        if (not result or result.get("weight", 3) >= 3) and not artist_name and artist and track != artist:
            alt_res = _execute_cascade(artist, track, duration_ms, max_timeout=2.0)
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

    def _fetch_lrclib(self, track, artist, duration_ms=0):
        c_track = self._clean_str(track)
        c_artist = artist.split(',')[0].split('&')[0].strip() if artist else ""
        dur_s = int(round(duration_ms / 1000.0)) if duration_ms > 0 else 0

        # 1. Try exact /api/get (with duration if available for tightest match)
        if dur_s > 0 and c_artist and c_track:
            try:
                url = f"https://lrclib.net/api/get?artist_name={urllib.parse.quote(c_artist)}&track_name={urllib.parse.quote(c_track)}&duration={dur_s}"
                req = urllib.request.Request(url, headers={'User-Agent': 'AURA-Music/1.0'})
                with self._open_url(req, timeout=3.5) as resp:
                    data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                    res = self._make_result(data.get("syncedLyrics"), data.get("plainLyrics"))
                    if res:
                        return res
            except Exception:
                pass

        if c_artist and c_track:
            try:
                url = f"https://lrclib.net/api/get?artist_name={urllib.parse.quote(c_artist)}&track_name={urllib.parse.quote(c_track)}"
                req = urllib.request.Request(url, headers={'User-Agent': 'AURA-Music/1.0'})
                with self._open_url(req, timeout=3.5) as resp:
                    data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                    res = self._make_result(data.get("syncedLyrics"), data.get("plainLyrics"))
                    if res:
                        return res
            except Exception as e:
                logger.debug(f"lrclib exact lookup failed for '{c_artist} - {c_track}': {e}")

        # 2. Search endpoints with scoring
        search_urls = []
        if c_artist and c_track:
            search_urls.append(f"https://lrclib.net/api/search?track_name={urllib.parse.quote(c_track)}&artist_name={urllib.parse.quote(c_artist)}")
        search_urls.append(f"https://lrclib.net/api/search?q={urllib.parse.quote(f'{c_artist} {c_track}'.strip())}")

        best_candidate = None
        best_score = 0.55  # Minimum similarity threshold

        for s_url in search_urls:
            try:
                req = urllib.request.Request(s_url, headers={'User-Agent': 'AURA-Music/1.0'})
                with self._open_url(req, timeout=3.5) as resp:
                    results = json.loads(resp.read().decode('utf-8', errors='ignore'))
                    if isinstance(results, list) and results:
                        for item in results:
                            item_title = item.get("name") or item.get("trackName") or ""
                            item_artist = item.get("artistName") or ""
                            item_dur = float(item.get("duration") or 0.0)

                            score = self._score_candidate(
                                c_track, c_artist, float(dur_s),
                                item_title, item_artist, item_dur
                            )
                            if score < 0.55:
                                continue

                            res = self._make_result(item.get("syncedLyrics"), item.get("plainLyrics"))
                            if not res:
                                continue

                            # Prefer synced lyrics (weight 1), then higher similarity score
                            is_synced = (res.get('weight') == 1)
                            effective_score = score + (0.15 if is_synced else 0.0)

                            if effective_score > best_score:
                                best_score = effective_score
                                best_candidate = res
                                if is_synced and score >= 0.85:
                                    return best_candidate

                if best_candidate and best_candidate.get('weight') == 1:
                    return best_candidate
            except Exception as e:
                logger.debug(f"lrclib search failed for URL '{s_url}': {e}")

        return best_candidate

    def _fetch_netease(self, track, artist, duration_ms=0):
        try:
            query = f"{artist} {track}".strip()
            url = f"http://music.163.com/api/search/pc?type=1&offset=0&limit=5&s={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                songs = data.get('result', {}).get('songs', [])
                if not songs:
                    return None

                target_dur_s = float(duration_ms) / 1000.0 if duration_ms > 0 else 0.0
                best_id = None
                best_score = 0.55

                for s in songs:
                    s_name = s.get('name', '')
                    s_artists = " ".join([a.get('name', '') for a in s.get('artists', [])])
                    s_dur = float(s.get('dt', 0)) / 1000.0
                    score = self._score_candidate(track, artist, target_dur_s, s_name, s_artists, s_dur)
                    if score > best_score:
                        best_score = score
                        best_id = s.get('id')

                if not best_id:
                    return None

            l_url = f"http://music.163.com/api/song/lyric?id={best_id}&lv=1&kv=1&tv=-1"
            l_req = urllib.request.Request(l_url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(l_req, timeout=3.5) as l_resp:
                l_data = json.loads(l_resp.read().decode('utf-8', errors='ignore'))
                lrc = l_data.get('lrc', {}).get('lyric')
                return self._make_result(lrc, lrc)
        except Exception as e:
            logger.debug(f"netease lookup failed for '{artist} {track}': {e}", exc_info=True)
            return None

    def _fetch_qqmusic(self, track, artist, duration_ms=0):
        try:
            query = f"{artist} {track}".strip()
            url = f"https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={urllib.parse.quote(query)}&format=json&n=5"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                songs = data.get('data', {}).get('song', {}).get('list', [])
                if not songs:
                    return None

                target_dur_s = float(duration_ms) / 1000.0 if duration_ms > 0 else 0.0
                best_mid = None
                best_score = 0.55

                for s in songs:
                    s_name = s.get('songname', '')
                    s_singer = " ".join([sing.get('name', '') for sing in s.get('singer', [])])
                    s_dur = float(s.get('interval', 0))
                    score = self._score_candidate(track, artist, target_dur_s, s_name, s_singer, s_dur)
                    if score > best_score:
                        best_score = score
                        best_mid = s.get('songmid')

                if not best_mid:
                    return None

            l_url = f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={best_mid}&format=json&nobase64=1"
            l_req = urllib.request.Request(l_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://y.qq.com/'})
            with self._open_url(l_req, timeout=3.5) as l_resp:
                l_data = json.loads(l_resp.read().decode('utf-8', errors='ignore'))
                lrc = l_data.get('lyric')
                lrc = html.unescape(lrc) if lrc else None
                return self._make_result(lrc, lrc)
        except Exception as e:
            logger.debug(f"qqmusic lookup failed for '{artist} {track}': {e}", exc_info=True)
            return None

    def _fetch_genius(self, track, artist, duration_ms=0):
        try:
            query = f"{artist} {track}".strip()
            url = f"https://genius.com/api/search/multi?per_page=5&q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                sections = data.get('response', {}).get('sections') or [{}]
                hits = sections[0].get('hits', []) if sections else []
                if not hits:
                    return None

                best_url = None
                best_score = 0.55

                for h in hits:
                    result_info = h.get('result', {})
                    h_title = result_info.get('title', '')
                    h_artist = result_info.get('primary_artist', {}).get('name', '')
                    score = self._score_candidate(track, artist, 0.0, h_title, h_artist, 0.0)
                    if score > best_score:
                        best_score = score
                        best_url = result_info.get('url')

                if not best_url:
                    return None

            s_req = urllib.request.Request(best_url, headers={'User-Agent': 'Mozilla/5.0'})
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

    def _fetch_megalobiz(self, track, artist, duration_ms=0):
        try:
            query = f"{artist} {track}".strip()
            url = f"https://www.megalobiz.com/search/all?qry={urllib.parse.quote(query)}&searchButton.x=0&searchButton.y=0"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with self._open_url(req, timeout=3.5) as resp:
                html_content = resp.read().decode('utf-8', errors='ignore')
                # Find links with their anchor text to score relevance
                links = re.findall(r'href="(/lrc/maker/[^"]+)"[^>]*title="([^"]*)"', html_content)
                if not links:
                    # Fallback to simple href search
                    link_match = re.search(r'href="(/lrc/maker/[^"]+)"', html_content)
                    if not link_match:
                        return None
                    chosen_path = link_match.group(1)
                else:
                    best_path = None
                    best_score = 0.50
                    for path, title in links:
                        score = self._score_candidate(track, artist, 0.0, title, artist, 0.0)
                        if score > best_score:
                            best_score = score
                            best_path = path
                    chosen_path = best_path or links[0][0]

            l_url = "https://www.megalobiz.com" + chosen_path
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

    def _fetch_duckduckgo(self, track, artist, duration_ms=0):
        """
        Scrapes plain lyrics with strict validation to ensure search engine snippets
        are never mistaken for genuine song verses.
        """
        try:
            query = f"{artist} {track} lyrics".strip()
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with self._open_url(req, timeout=3.5) as resp:
                html_content = resp.read().decode('utf-8', errors='ignore')
                snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html_content, re.S)
                if not snippets:
                    return None

                # Search snippet text is NOT song lyrics! Reject search snippet descriptions.
                for snip in snippets:
                    clean_s = snip.replace('<b>', '').replace('</b>', '').strip()
                    clean_s = html.unescape(clean_s)
                    lines = [line.strip() for line in clean_s.splitlines() if line.strip()]
                    # Genuine lyrics will have multiple verses/lines and not look like SEO descriptions
                    if len(lines) >= 8 and not any(kw in clean_s.lower() for kw in [
                        "official music video", "album released", "listen to", "on spotify", "streaming on"
                    ]):
                        return self._make_result(None, clean_s)
        except Exception as e:
            logger.debug(f"duckduckgo lookup failed for '{artist} {track}': {e}")
            return None
        return None
