"""
AURA Music - Lyrics Service
Fetches synced and plain lyrics using 6 databases with a race condition weight system.
"""

import logging
import urllib.parse
import urllib.request
import json
import time
import re
import html
import ssl
import concurrent.futures

from services.base_service import BaseMusicService

logger = logging.getLogger(__name__)

# Verified TLS context (default). Certificate checks are restored for all
# metadata/lyrics requests; stream extraction is handled by yt-dlp separately.
ssl_ctx = ssl.create_default_context()

# Every outbound lyrics request gets this ceiling so a hung host cannot pin a worker.
HTTP_TIMEOUT = 6.0

class LyricsService:
    def __init__(self, settings=None):
        self.settings = settings

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
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return "".join([x[0] for x in data[0] if x[0]])
        except Exception as e:
            logger.debug(f"Translation error: {e}")
            return lyrics

    def get_lyrics(self, track_name: str, artist_name: str = "", duration_ms: int = 0, file_path: str = None) -> dict:
        if not track_name:
            return {"syncedLyrics": None, "plainLyrics": None, "instrumental": False, "weight": 3}

        track = track_name.strip()
        artist = artist_name.strip() if artist_name else ""

        # Define 6 fetcher methods to run concurrently
        fetchers = [
            self._fetch_lrclib,
            self._fetch_netease,
            self._fetch_qqmusic,
            self._fetch_megalobiz,
            self._fetch_genius,
            self._fetch_duckduckgo
        ]

        # Reuse the shared pool instead of building (and leaking) one per lookup.
        futures = {}
        for f in fetchers:
            future = BaseMusicService.submit(f, track, artist)
            if future is not None:
                futures[future] = f.__name__
        if not futures:
            logger.debug('Lyrics lookup skipped: shared executor unavailable')
            return {"syncedLyrics": None, "plainLyrics": None, "instrumental": False, "weight": 3}
        not_done = set(futures.keys())

        best_weight_2 = None
        weight2_found_time = None
        timeout = 2.5
        start_time = time.time()

        while not_done:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                break

            # Fast exit: If plain lyrics found (weight 2) and 0.6s passed with no synced lyrics, return immediately
            if best_weight_2 and (time.time() - weight2_found_time) >= 0.6:
                return best_weight_2

            time_left = min(0.2, timeout - elapsed)
            done, not_done = concurrent.futures.wait(
                not_done,
                timeout=time_left,
                return_when=concurrent.futures.FIRST_COMPLETED
            )

            for fut in done:
                try:
                    res = fut.result()
                    if res:
                        w = res.get('weight', 3)
                        if w == 1:
                            return res # Immediate WIN
                        elif w == 2 and not best_weight_2:
                            best_weight_2 = res
                            weight2_found_time = time.time()
                except Exception as e:
                    logger.debug(f"Lyrics fetcher {futures.get(fut, '?')} failed: {e}", exc_info=True)

        if best_weight_2:
            return best_weight_2

        return {"syncedLyrics": None, "plainLyrics": None, "instrumental": False, "weight": 3}

    def _make_result(self, synced, plain):
        if synced and re.search(r'\[\d{2}:\d{2}', synced):
            return {"syncedLyrics": synced, "plainLyrics": plain or synced, "weight": 1}
        elif plain or (synced and len(synced.strip()) > 0):
            return {"syncedLyrics": None, "plainLyrics": plain or synced, "weight": 2}
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
            with urllib.request.urlopen(req, timeout=3.5) as resp:
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
            with urllib.request.urlopen(req, timeout=3.5) as resp:
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
        query = f"{artist} {track}".strip()
        url = f"http://music.163.com/api/search/pc?type=1&offset=0&limit=1&s={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            songs = data.get('result', {}).get('songs', [])
            if not songs: return None
            sid = songs[0]['id']
            
        l_url = f"http://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1"
        l_req = urllib.request.Request(l_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(l_req, timeout=3.5) as l_resp:
            l_data = json.loads(l_resp.read().decode('utf-8'))
            lrc = l_data.get('lrc', {}).get('lyric')
            return self._make_result(lrc, lrc)

    def _fetch_qqmusic(self, track, artist):
        query = f"{artist} {track}".strip()
        url = f"https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={urllib.parse.quote(query)}&format=json&n=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            songs = data.get('data', {}).get('song', {}).get('list', [])
            if not songs: return None
            songmid = songs[0]['songmid']
            
        l_url = f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={songmid}&format=json&nobase64=1"
        l_req = urllib.request.Request(l_url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://y.qq.com/'})
        with urllib.request.urlopen(l_req, timeout=3.5) as l_resp:
            l_data = json.loads(l_resp.read().decode('utf-8'))
            lrc = l_data.get('lyric')
            lrc = html.unescape(lrc) if lrc else None
            return self._make_result(lrc, lrc)

    def _fetch_genius(self, track, artist):
        query = f"{artist} {track}".strip()
        url = f"https://genius.com/api/search/multi?per_page=1&q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            hits = data.get('response', {}).get('sections', [{}])[0].get('hits', [])
            if not hits: return None
            s_url = hits[0]['result']['url']
            
        s_req = urllib.request.Request(s_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(s_req, timeout=3.5) as s_resp:
            html_content = s_resp.read().decode('utf-8')
            lyrics_parts = re.findall(r'<div data-lyrics-container="true"[^>]*>(.*?)</div>', html_content)
            if lyrics_parts:
                txt = "\n".join(lyrics_parts)
                txt = re.sub(r'<br/?>', '\n', txt)
                txt = re.sub(r'<[^>]+>', '', txt)
                txt = html.unescape(txt)
                return self._make_result(None, txt)
        return None

    def _fetch_megalobiz(self, track, artist):
        query = f"{artist} {track}".strip()
        url = f"https://www.megalobiz.com/search/all?qry={urllib.parse.quote(query)}&searchButton.x=0&searchButton.y=0"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            html_content = resp.read().decode('utf-8')
            link = re.search(r'href="(/lrc/maker/[^"]+)"', html_content)
            if not link: return None
            
        l_url = "https://www.megalobiz.com" + link.group(1)
        l_req = urllib.request.Request(l_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(l_req, timeout=3.5) as l_resp:
            l_html = l_resp.read().decode('utf-8')
            lrc_match = re.search(r'<div id="lrc_[^"]*"[^>]*>(.*?)</div>', l_html, re.S)
            if not lrc_match:
                lrc_match = re.search(r'<span id="lrc_[^"]*"[^>]*>(.*?)</span>', l_html, re.S)
            if lrc_match:
                txt = lrc_match.group(1).replace('<br>', '\n').strip()
                return self._make_result(txt, txt)
        return None

    def _fetch_duckduckgo(self, track, artist):
        query = f"{artist} {track} lyrics".strip()
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            html_content = resp.read().decode('utf-8')
            snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html_content, re.S)
            if snippets:
                txt = "\n".join(snippets).replace('<b>', '').replace('</b>', '').strip()
                txt = html.unescape(txt)
                return self._make_result(None, txt)
        return None
