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
import concurrent.futures

logger = logging.getLogger(__name__)

class LyricsService:
    def __init__(self, settings=None):
        self.settings = settings
        
    def translate_lyrics(self, lyrics: str, target_lang="ru") -> str:
        if not lyrics:
            return ""
        try:
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(lyrics)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
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
        
        best_weight_2 = None
        timeout = 4.0 # Wait up to 4 seconds for a Weight 1 result
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(fetchers)) as executor:
            future_to_name = {executor.submit(f, track, artist): f.__name__ for f in fetchers}
            not_done = set(future_to_name.keys())
            
            while not_done:
                elapsed = time.time() - start_time
                time_left = timeout - elapsed
                
                if time_left <= 0:
                    break # Timeout reached
                    
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
                                return res # Immediate WIN, threads will gracefully die in background
                            elif w == 2 and not best_weight_2:
                                best_weight_2 = res # Save best weight 2 and keep waiting
                    except Exception as e:
                        pass
                        
        if best_weight_2:
            return best_weight_2
            
        return {"syncedLyrics": None, "plainLyrics": None, "instrumental": False, "weight": 3}

    def _make_result(self, synced, plain):
        if synced and '[00:' in synced:
            return {"syncedLyrics": synced, "plainLyrics": plain or synced, "weight": 1}
        elif plain or synced:
            return {"syncedLyrics": None, "plainLyrics": plain or synced, "weight": 2}
        return None

    def _fetch_lrclib(self, track, artist):
        url = f"https://lrclib.net/api/get?artist_name={urllib.parse.quote(artist)}&track_name={urllib.parse.quote(track)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'AURA-Music/1.0'})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return self._make_result(data.get("syncedLyrics"), data.get("plainLyrics"))

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
