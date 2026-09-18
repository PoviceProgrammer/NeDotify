"""
AURA Music - MusicBrainz & Open Discography Service
Provides official MusicBrainz open catalogue querying, release group categorization
(albums, singles, EPs, compilations), rate limiting (1 req/sec), Cover Art Archive URLs,
and encyclopedic Wikipedia biography extraction.
"""

import os
import json
import time
import sqlite3
import logging
import threading
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Any
from services.base_service import BaseMusicService

logger = logging.getLogger(__name__)

MB_BASE_URL = "https://musicbrainz.org/ws/2"
CAA_BASE_URL = "https://coverartarchive.org/release-group"
USER_AGENT = "AURA-Music/1.0.0 ( https://github.com/aura-music/aura ; contact@aura-music.org )"

MB_CACHE_TTL = 7 * 86400  # 7 days


class MusicBrainzService(BaseMusicService):
    """Client for MusicBrainz REST API & Wikipedia Biography integration."""

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self.logger = logging.getLogger(self.__class__.__name__)

        # Rate limiting: MusicBrainz enforces strictly max 1 req/sec without auth
        self._rate_lock = threading.Condition()
        self._rate_capacity = 1.0
        self._rate_tokens = 1.0
        self._rate_last_refill = time.time()

        # Caching
        self._cache: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()
        self._mem_conn = None
        self._db_path = self._init_sqlite_cache_path()
        self._init_sqlite_cache_db()

    def _init_sqlite_cache_path(self) -> str:
        base_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "cache")
        try:
            os.makedirs(base_dir, exist_ok=True)
            return os.path.join(base_dir, "musicbrainz_cache.db")
        except Exception as e:
            self.logger.warning(f"Cannot create MusicBrainz cache dir {base_dir} ({e}); using memory")
            return ":memory:"

    def _get_db_connection(self):
        if self._db_path == ":memory:":
            if self._mem_conn is None:
                self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            return self._mem_conn
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        return conn

    def _init_sqlite_cache_db(self):
        try:
            conn = self._get_db_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS mb_response_cache (
                            cache_key TEXT PRIMARY KEY,
                            json_data TEXT,
                            timestamp REAL,
                            ttl REAL
                        )
                    """)
            finally:
                if self._db_path != ":memory:":
                    conn.close()
        except Exception as e:
            self.logger.warning(f"Failed to initialize MusicBrainz SQLite cache: {e}")

    def _get_cached(self, cache_key: str) -> Optional[Any]:
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry and time.time() - entry["ts"] <= entry["ttl"]:
                return entry["data"]

        try:
            conn = self._get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT json_data, timestamp, ttl FROM mb_response_cache WHERE cache_key = ?",
                    (cache_key,)
                )
                row = cursor.fetchone()
                if row:
                    json_str, ts, ttl = row
                    if time.time() - ts <= ttl:
                        data = json.loads(json_str)
                        with self._cache_lock:
                            if len(self._cache) >= 300:
                                self._cache.pop(next(iter(self._cache)), None)
                            self._cache[cache_key] = {"data": data, "ts": ts, "ttl": ttl}
                        return data
            finally:
                if self._db_path != ":memory:":
                    conn.close()
        except Exception as e:
            self.logger.debug(f"MusicBrainz cache read error: {e}")
        return None

    def _set_cached(self, cache_key: str, data: Any, ttl: float = MB_CACHE_TTL):
        now = time.time()
        with self._cache_lock:
            if len(self._cache) >= 300:
                self._cache.pop(next(iter(self._cache)), None)
            self._cache[cache_key] = {"data": data, "ts": now, "ttl": ttl}

        try:
            json_str = json.dumps(data)
            conn = self._get_db_connection()
            try:
                with conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO mb_response_cache (cache_key, json_data, timestamp, ttl) VALUES (?, ?, ?, ?)",
                        (cache_key, json_str, now, ttl)
                    )
            finally:
                if self._db_path != ":memory:":
                    conn.close()
        except Exception as e:
            self.logger.debug(f"MusicBrainz cache write error: {e}")

    def _acquire_rate_token(self):
        """Token-bucket rate limiter ensuring max 1 request per second to MusicBrainz."""
        with self._rate_lock:
            while True:
                now = time.time()
                elapsed = now - self._rate_last_refill
                self._rate_tokens = min(self._rate_capacity, self._rate_tokens + elapsed * 1.0)
                self._rate_last_refill = now
                if self._rate_tokens >= 1.0:
                    self._rate_tokens -= 1.0
                    return
                wait_for = (1.0 - self._rate_tokens) / 1.0
                self._rate_lock.wait(timeout=min(wait_for, 1.2))

    def _http_get_json(self, url: str, timeout: float = 6.0, is_mb: bool = True) -> Optional[Any]:
        """Perform an HTTP GET request with User-Agent and JSON decoding."""
        if is_mb:
            self._acquire_rate_token()

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    raw = resp.read().decode("utf-8", errors="replace")
                    return json.loads(raw)
        except Exception as exc:
            self.logger.debug("HTTP GET failed for %s: %s", url, exc)
        return None

    def search_artist(self, artist_name: str) -> Optional[Dict[str, Any]]:
        """Search MusicBrainz for artist by name and return best matched artist dict."""
        name = (artist_name or "").strip()
        if not name:
            return None

        cache_key = f"mb_artist_search:{name.lower()}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        escaped_name = name.replace('"', '\\"')
        encoded_query = urllib.parse.quote(f'artist:"{escaped_name}"')
        url = f"{MB_BASE_URL}/artist/?query={encoded_query}&fmt=json&limit=5"

        data = self._http_get_json(url)
        if not data or not isinstance(data.get("artists"), list) or not data["artists"]:
            encoded_query = urllib.parse.quote(name)
            url = f"{MB_BASE_URL}/artist/?query={encoded_query}&fmt=json&limit=5"
            data = self._http_get_json(url)

        best_artist = None
        if data and isinstance(data.get("artists"), list):
            artists = data["artists"]
            target = name.lower()
            for a in artists:
                if not isinstance(a, dict):
                    continue
                a_name = (a.get("name") or "").lower()
                if a_name == target:
                    best_artist = a
                    break
                if best_artist is None:
                    best_artist = a

        if best_artist:
            res = {
                "id": best_artist.get("id"),
                "name": best_artist.get("name") or name,
                "sort_name": best_artist.get("sort-name"),
                "type": best_artist.get("type"),
                "disambiguation": best_artist.get("disambiguation", ""),
                "country": best_artist.get("country", ""),
                "tags": [t.get("name") for t in (best_artist.get("tags") or []) if isinstance(t, dict) and t.get("name")],
            }
            self._set_cached(cache_key, res)
            return res

        return None

    def get_artist_release_groups(self, mbid: str, artist_name: str = "", limit: int = 100) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch artist release groups categorized into albums, singles, eps, and compilations."""
        if not mbid or not str(mbid).strip():
            return {"albums": [], "singles": [], "eps": [], "compilations": []}

        cache_key = f"mb_release_groups:{mbid}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{MB_BASE_URL}/release-group?artist={mbid}&limit={limit}&fmt=json"
        data = self._http_get_json(url)

        albums: List[Dict[str, Any]] = []
        singles: List[Dict[str, Any]] = []
        eps: List[Dict[str, Any]] = []
        compilations: List[Dict[str, Any]] = []

        seen_titles = set()

        if data and isinstance(data.get("release-groups"), list):
            for rg in data["release-groups"]:
                if not isinstance(rg, dict):
                    continue
                rg_id = rg.get("id")
                title = (rg.get("title") or "").strip()
                if not rg_id or not title:
                    continue

                norm_title = title.lower()
                if norm_title in seen_titles:
                    continue
                seen_titles.add(norm_title)

                primary_type = (rg.get("primary-type") or "").strip()
                secondary_types = [str(s).strip() for s in (rg.get("secondary-types") or []) if s]

                # Year parsing
                rel_date = str(rg.get("first-release-date") or "")
                year = 0
                if len(rel_date) >= 4:
                    try:
                        year = int(rel_date[:4])
                    except ValueError:
                        year = 0

                # Cover Art Archive URLs
                caa = rg.get("cover-art-archive")
                has_caa = True
                if isinstance(caa, dict):
                    if caa.get("artwork") is False and caa.get("front") is False:
                        has_caa = False

                cover_url = f"{CAA_BASE_URL}/{rg_id}/front-500" if has_caa else ""
                thumb_url = f"{CAA_BASE_URL}/{rg_id}/front-250" if has_caa else ""

                # Classify type
                is_compilation = "Compilation" in secondary_types or primary_type.lower() == "compilation"
                is_single = primary_type.lower() == "single"
                is_ep = primary_type.lower() == "ep" or "ep" in title.lower()
                is_album = primary_type.lower() == "album" and not is_compilation

                item_type = "album"
                if is_compilation:
                    item_type = "compilation"
                elif is_single:
                    item_type = "single"
                elif is_ep:
                    item_type = "ep"

                entry = {
                    "id": f"mb_{rg_id}",
                    "source": "musicbrainz",
                    "source_id": rg_id,
                    "title": title,
                    "album": title,
                    "artist": artist_name,
                    "year": year,
                    "release_date": rel_date,
                    "cover": cover_url,
                    "cover_url": cover_url,
                    "thumbnail_url": thumb_url,
                    "type": item_type,
                    "album_type": item_type,
                    "primary_type": primary_type,
                    "secondary_types": secondary_types,
                }

                if is_compilation:
                    compilations.append(entry)
                elif is_single:
                    singles.append(entry)
                elif is_ep:
                    eps.append(entry)
                else:
                    albums.append(entry)

        # Sort by year DESC
        albums.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))
        singles.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))
        eps.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))
        compilations.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))

        result = {
            "albums": albums,
            "singles": singles,
            "eps": eps,
            "compilations": compilations,
        }
        self._set_cached(cache_key, result)
        return result

    def get_artist_bio(self, mbid: Optional[str], artist_name: str) -> Dict[str, str]:
        """Fetch artist biography from Wikipedia via MusicBrainz relations or direct REST summary."""
        name = (artist_name or "").strip()
        if not name:
            return {"bio": "", "bio_ru": "", "bio_en": "", "bio_original": "", "avatar_url": "", "source": ""}

        cache_key = f"mb_bio:{mbid or ''}_{name.lower()}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        ru_title = None
        en_title = None
        avatar_url = ""

        # Step 1: Check MusicBrainz relations for Wikipedia links if mbid is provided
        if mbid:
            url = f"{MB_BASE_URL}/artist/{mbid}?inc=url-rels+annotation&fmt=json"
            data = self._http_get_json(url)
            if data and isinstance(data.get("relations"), list):
                for rel in data["relations"]:
                    if not isinstance(rel, dict):
                        continue
                    url_obj = rel.get("url") or {}
                    href = url_obj.get("resource", "")
                    if "wikipedia.org/wiki/" in href:
                        parts = href.split("wikipedia.org/wiki/")
                        if len(parts) == 2:
                            wiki_title = parts[1]
                            if "ru.wikipedia.org" in href:
                                ru_title = wiki_title
                            elif "en.wikipedia.org" in href:
                                en_title = wiki_title

        # Step 2: Fetch Wikipedia summaries
        def _fetch_wiki(title_or_name: str, lang: str = "ru") -> Dict[str, str]:
            if not title_or_name:
                return {}
            encoded = urllib.parse.quote(title_or_name.replace(" ", "_"))
            w_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
            w_data = self._http_get_json(w_url, timeout=4.0, is_mb=False)
            if w_data and isinstance(w_data, dict):
                extract = (w_data.get("extract") or "").strip()
                thumb = (w_data.get("thumbnail") or {}).get("source", "")
                orig_img = (w_data.get("originalimage") or {}).get("source", "")
                return {"extract": extract, "image": orig_img or thumb}
            return {}

        # Fetch RU
        ru_res = _fetch_wiki(ru_title or name, "ru")
        if not ru_res.get("extract") and ru_title != f"{name}_(музыкант)":
            ru_res2 = _fetch_wiki(f"{name}_(музыкант)", "ru")
            if ru_res2.get("extract"):
                ru_res = ru_res2
        if not ru_res.get("extract"):
            ru_res3 = _fetch_wiki(f"{name}_(группа)", "ru")
            if ru_res3.get("extract"):
                ru_res = ru_res3

        ru_bio = ru_res.get("extract", "")
        if ru_res.get("image"):
            avatar_url = ru_res["image"]

        # Fetch EN
        en_res = _fetch_wiki(en_title or name, "en")
        if not en_res.get("extract") and en_title != f"{name}_(musician)":
            en_res2 = _fetch_wiki(f"{name}_(musician)", "en")
            if en_res2.get("extract"):
                en_res = en_res2
        if not en_res.get("extract"):
            en_res3 = _fetch_wiki(f"{name}_(band)", "en")
            if en_res3.get("extract"):
                en_res = en_res3

        en_bio = en_res.get("extract", "")
        if not avatar_url and en_res.get("image"):
            avatar_url = en_res["image"]

        best_bio = ru_bio or en_bio

        result = {
            "bio": best_bio,
            "bio_ru": ru_bio,
            "bio_en": en_bio,
            "bio_original": en_bio or ru_bio,
            "avatar_url": avatar_url,
            "source": "musicbrainz/wikipedia" if best_bio else "",
        }
        self._set_cached(cache_key, result)
        return result
