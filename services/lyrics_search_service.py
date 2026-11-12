"""
NeDotify - Lyrics Search Service
Independent multi-provider lyrics version search and resolution (LRCLIB, Kugou, NetEase, QQ Music, Genius).
"""

import base64
import concurrent.futures
import html
import json
import logging
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from services.lyrics_formats import parse_lyrics, plain_text, to_lrc
from services.music_matching import credits, normalize, similarity

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT = 4.5
HTTP_TIMEOUT = 3.5
USER_AGENT = "NeDotify/2.5.1 (Windows; desktop; +https://github.com/PoviceProgrammer/NeDotify)"


def format_duration(seconds: float) -> str:
    """Format seconds into mm:ss."""
    try:
        s = int(round(float(seconds or 0)))
        if s <= 0:
            return ""
        m = s // 60
        sec = s % 60
        return f"{m}:{sec:02d}"
    except (TypeError, ValueError):
        return ""


class LyricsSearchService:
    """Aggregates search candidates across independent public lyrics services."""

    def __init__(self, settings=None, lyrics_service=None):
        self.settings = settings
        self.lyrics_service = lyrics_service

    def _open_url(self, req_or_url, headers=None, timeout=HTTP_TIMEOUT):
        if self.lyrics_service and hasattr(self.lyrics_service, "_open_url"):
            return self.lyrics_service._open_url(req_or_url, headers=headers, timeout=timeout)
        if isinstance(req_or_url, str):
            req = urllib.request.Request(
                req_or_url, headers=headers or {"User-Agent": USER_AGENT}
            )
        else:
            req = req_or_url
        from utils.url_safety import guarded_open_url
        return guarded_open_url(req, timeout=timeout)

    def _json(self, url: str, headers: Optional[dict] = None, timeout: float = HTTP_TIMEOUT):
        req_headers = {"User-Agent": USER_AGENT}
        if headers:
            req_headers.update(headers)
        with self._open_url(url, headers=req_headers, timeout=timeout) as resp:
            raw = resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
            return json.loads(raw)

    def search_candidates(
        self,
        query: str,
        artist: str = "",
        title: str = "",
        album: str = "",
        duration_sec: float = 0.0,
        limit: int = 35,
    ) -> List[Dict[str, Any]]:
        """Search across all providers in parallel within a bounded deadline."""
        clean_query = str(query or "").strip()
        if not clean_query and (artist or title):
            clean_query = f"{artist} {title}".strip()
        if not clean_query:
            return []

        generated_query = clean_query in (f"{artist} - {title}", f"{artist} {title}".strip())
        clean_query = re.sub(r"\bf[*＊]{1,3}k\b", "fuck", clean_query, flags=re.IGNORECASE)
        lookup_title = re.sub(r"\bf[*＊]{1,3}k\b", "fuck", title or "", flags=re.IGNORECASE)
        if generated_query and lookup_title != title and lookup_title:
            artists = credits(artist)
            clean_query = f"{artists[0]} {lookup_title}" if artists else lookup_title
        title = lookup_title

        providers = [
            ("LRCLIB", self._search_lrclib),
            ("Kugou", self._search_kugou),
            ("NetEase", self._search_netease),
            ("QQ Music", self._search_qq),
            ("Genius", self._search_genius),
        ]

        from services.lyrics_service import LyricsService
        futures = {}
        deadline = time.monotonic() + SEARCH_TIMEOUT

        for name, fn in providers:
            fut = LyricsService.submit(
                fn, clean_query, artist=artist, title=title, duration_sec=duration_sec
            )
            if fut:
                futures[fut] = name

        all_candidates: List[Dict[str, Any]] = []
        if futures:
            done, not_done = concurrent.futures.wait(
                futures.keys(),
                timeout=max(0.1, deadline - time.monotonic()),
                return_when=concurrent.futures.ALL_COMPLETED,
            )
            for fut in done:
                try:
                    results = fut.result()
                    if isinstance(results, list):
                        all_candidates.extend(results)
                except Exception as ex:
                    logger.debug("Provider %s search failed: %s", futures.get(fut), ex)
            for fut in not_done:
                fut.cancel()

        # Score and deduplicate candidates
        scored = []
        for cand in all_candidates:
            score = self._calculate_score(cand, query, artist, title, duration_sec)
            cand["confidenceScore"] = round(score, 3)
            scored.append(cand)

        # Sort: higher confidence, then hasTiming, then duration match
        scored.sort(
            key=lambda c: (
                c.get("confidenceScore", 0),
                1 if c.get("hasTiming") else 0,
                -abs(c.get("durationSeconds", 0) - duration_sec) if duration_sec and c.get("durationSeconds") else 0,
            ),
            reverse=True,
        )

        # Deduplicate candidates with identical text preview or source identity
        deduped: List[Dict[str, Any]] = []
        seen_keys = set()
        for cand in scored:
            k = (
                normalize(cand.get("trackName", "")),
                normalize(cand.get("artistName", "")),
                cand.get("source", ""),
                cand.get("hasTiming", False),
            )
            if k in seen_keys:
                continue
            seen_keys.add(k)
            deduped.append(cand)
            if len(deduped) >= limit:
                break

        return deduped

    def _calculate_score(
        self, cand: dict, query: str, artist: str, title: str, duration_sec: float
    ) -> float:
        """Calculate match score from 0.0 to 1.0."""
        score = 0.5
        c_title = cand.get("trackName", "")
        c_artist = cand.get("artistName", "")

        if title and c_title:
            sim_title = similarity(normalize(title), normalize(c_title))
            score = max(score, sim_title)
        elif query and c_title:
            sim_q = similarity(normalize(query), normalize(f"{c_artist} {c_title}"))
            score = max(score, sim_q * 0.9)

        if artist and c_artist:
            sim_artist = similarity(normalize(artist), normalize(c_artist))
            score = (score * 0.6) + (sim_artist * 0.4)

        if duration_sec > 0 and cand.get("durationSeconds", 0) > 0:
            diff = abs(cand["durationSeconds"] - duration_sec)
            if diff <= 2.0:
                score += 0.1
            elif diff > 15.0:
                score -= min(0.3, (diff - 15.0) / 60.0)

        if cand.get("hasTiming"):
            score += 0.15

        return max(0.0, min(1.0, score))

    def _search_lrclib(
        self, query: str, artist: str = "", title: str = "", duration_sec: float = 0
    ) -> List[Dict[str, Any]]:
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode({"q": query})
        data = self._json(url)
        if not isinstance(data, list):
            return []
        results = []
        for item in data[:25]:
            if not isinstance(item, dict):
                continue
            synced = item.get("syncedLyrics")
            plain = item.get("plainLyrics")
            if not synced and not plain and not item.get("instrumental"):
                continue
            dur = float(item.get("duration") or 0)
            preview = ""
            if plain:
                preview = "\n".join(plain.strip().splitlines()[:3])
            elif synced:
                lines = [re.sub(r"\[[^\]]*\]", "", l).strip() for l in synced.splitlines() if l.strip()]
                preview = "\n".join(lines[:3])

            results.append({
                "id": f"lrclib:{item.get('id', '')}",
                "source": "LRCLIB",
                "trackName": item.get("trackName") or "",
                "artistName": item.get("artistName") or "",
                "albumName": item.get("albumName") or "",
                "durationSeconds": dur,
                "durationFormatted": format_duration(dur),
                "hasTiming": bool(synced),
                "syncType": "line" if synced else "plain",
                "preview": preview,
                "rawPayload": {
                    "source": "LRCLIB",
                    "id": item.get("id"),
                    "syncedLyrics": synced,
                    "plainLyrics": plain,
                    "instrumental": item.get("instrumental", False),
                },
            })
        return results

    def _search_kugou(
        self, query: str, artist: str = "", title: str = "", duration_sec: float = 0
    ) -> List[Dict[str, Any]]:
        dur_ms = round(duration_sec * 1000) if duration_sec else 0
        params = {"keyword": query, "client": "pc", "ver": 1, "man": "yes"}
        if dur_ms:
            params["duration"] = dur_ms
        url = "https://lyrics.kugou.com/search?" + urllib.parse.urlencode(params)
        data = self._json(url)
        if not isinstance(data, dict):
            return []
        candidates = data.get("candidates")
        if not isinstance(candidates, list):
            return []
        results = []
        for cand in candidates[:20]:
            if not isinstance(cand, dict):
                continue
            dur = float(cand.get("duration") or 0) / 1000.0 if cand.get("duration") else 0
            cid = str(cand.get("id") or "")
            access = str(cand.get("accesskey") or "")
            if not cid or not access:
                continue
            results.append({
                "id": f"kugou:{cid}",
                "source": "Kugou",
                "trackName": cand.get("song") or "",
                "artistName": cand.get("singer") or "",
                "albumName": "",
                "durationSeconds": dur,
                "durationFormatted": format_duration(dur),
                "hasTiming": True,
                "syncType": "line",
                "preview": f"{cand.get('singer', '')} — {cand.get('song', '')}",
                "rawPayload": {
                    "source": "Kugou",
                    "id": cid,
                    "accesskey": access,
                },
            })
        return results

    def _search_netease(
        self, query: str, artist: str = "", title: str = "", duration_sec: float = 0
    ) -> List[Dict[str, Any]]:
        url = f"https://music.163.com/api/cloudsearch/pc?type=1&offset=0&limit=15&s={urllib.parse.quote(query)}"
        data = self._json(url, headers={"Referer": "https://music.163.com/"})
        if not isinstance(data, dict):
            return []
        songs = (data.get("result") or {}).get("songs") or []
        results = []
        for song in songs[:15]:
            if not isinstance(song, dict):
                continue
            sid = song.get("id")
            if not sid:
                continue
            people = [a.get("name") for a in (song.get("ar") or song.get("artists") or []) if a.get("name")]
            dur = (float(song.get("dt") or song.get("duration") or 0)) / 1000.0
            album_name = (song.get("al") or {}).get("name") or ""
            results.append({
                "id": f"netease:{sid}",
                "source": "NetEase",
                "trackName": song.get("name") or "",
                "artistName": ", ".join(people),
                "albumName": album_name,
                "durationSeconds": dur,
                "durationFormatted": format_duration(dur),
                "hasTiming": True,
                "syncType": "line",
                "preview": f"{song.get('name', '')} ({album_name})" if album_name else song.get("name", ""),
                "rawPayload": {
                    "source": "NetEase",
                    "id": sid,
                },
            })
        return results

    def _search_qq(
        self, query: str, artist: str = "", title: str = "", duration_sec: float = 0
    ) -> List[Dict[str, Any]]:
        url = f"https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={urllib.parse.quote(query)}&format=json&p=1&n=12"
        data = self._json(url, headers={"Referer": "https://y.qq.com/"})
        if not isinstance(data, dict):
            return []
        songs = ((data.get("data") or {}).get("song") or {}).get("list") or []
        results = []
        for song in songs[:12]:
            if not isinstance(song, dict):
                continue
            mid = song.get("songmid")
            if not mid:
                continue
            people = [s.get("name") for s in (song.get("singer") or []) if s.get("name")]
            dur = float(song.get("interval") or 0)
            results.append({
                "id": f"qq:{mid}",
                "source": "QQ Music",
                "trackName": song.get("songname") or "",
                "artistName": ", ".join(people),
                "albumName": song.get("albumname") or "",
                "durationSeconds": dur,
                "durationFormatted": format_duration(dur),
                "hasTiming": True,
                "syncType": "line",
                "preview": f"{song.get('songname', '')} — {', '.join(people)}",
                "rawPayload": {
                    "source": "QQ Music",
                    "songmid": mid,
                },
            })
        return results

    def _search_genius(
        self, query: str, artist: str = "", title: str = "", duration_sec: float = 0
    ) -> List[Dict[str, Any]]:
        url = f"https://genius.com/api/search/multi?per_page=6&q={urllib.parse.quote(query)}"
        data = self._json(url)
        if not isinstance(data, dict):
            return []
        results = []
        sections = (data.get("response") or {}).get("sections") or []
        for sec in sections:
            for hit in (sec.get("hits") or [])[:5]:
                song = hit.get("result") or {}
                if not song or not song.get("url"):
                    continue
                artist_name = (song.get("primary_artist") or {}).get("name") or ""
                results.append({
                    "id": f"genius:{song.get('id', '')}",
                    "source": "Genius",
                    "trackName": song.get("title") or "",
                    "artistName": artist_name,
                    "albumName": "",
                    "durationSeconds": 0,
                    "durationFormatted": "",
                    "hasTiming": False,
                    "syncType": "plain",
                    "preview": f"Текст песни Genius: {song.get('title', '')}",
                    "rawPayload": {
                        "source": "Genius",
                        "url": song.get("url"),
                    },
                })
        return results

    def resolve_candidate_lyrics(self, raw_payload: dict) -> Optional[Dict[str, Any]]:
        """Download or expand full lyrics text from the chosen candidate payload."""
        if not isinstance(raw_payload, dict):
            return None
        source = raw_payload.get("source")

        # 1. LRCLIB already carries lyrics in rawPayload
        if source == "LRCLIB":
            synced = raw_payload.get("syncedLyrics")
            plain = raw_payload.get("plainLyrics")
            if not plain and synced:
                plain = "\n".join(
                    re.sub(r"\[[^\]]*\]", "", l).strip()
                    for l in synced.splitlines()
                    if l.strip()
                )
            return {
                "source": "LRCLIB",
                "syncedLyrics": synced,
                "plainLyrics": plain or "",
                "syncType": "line" if synced else "plain",
                "instrumental": raw_payload.get("instrumental", False),
            }

        # 2. Kugou
        if source == "Kugou":
            cid = raw_payload.get("id")
            access = raw_payload.get("accesskey")
            if cid and access:
                url = f"https://lyrics.kugou.com/download?ver=1&client=pc&id={cid}&accesskey={access}&fmt=lrc"
                data = self._json(url)
                if isinstance(data, dict) and data.get("content"):
                    try:
                        raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                        plain = "\n".join(
                            re.sub(r"\[[^\]]*\]", "", l).strip()
                            for l in raw.splitlines()
                            if l.strip() and not re.match(r"^\[(?:ti|ar|al|by|offset):", l, re.I)
                        )
                        return {
                            "source": "Kugou",
                            "syncedLyrics": raw,
                            "plainLyrics": plain,
                            "syncType": "line",
                        }
                    except Exception as ex:
                        logger.debug("Kugou decode error: %s", ex)

        # 3. NetEase
        if source == "NetEase":
            sid = raw_payload.get("id")
            if sid:
                url = f"https://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1&yv=1"
                data = self._json(url, headers={"Referer": "https://music.163.com/"})
                if isinstance(data, dict):
                    lrc = (data.get("lrc") or {}).get("lyric")
                    yrc = (data.get("yrc") or {}).get("lyric")
                    raw = yrc or lrc
                    if raw:
                        plain = "\n".join(
                            re.sub(r"\[[^\]]*\]", "", l).strip()
                            for l in raw.splitlines()
                            if l.strip() and not re.match(r"^\[(?:ti|ar|al|by|offset):", l, re.I)
                        )
                        return {
                            "source": "NetEase",
                            "syncedLyrics": raw,
                            "plainLyrics": plain,
                            "syncType": "word" if yrc else "line",
                        }

        # 4. QQ Music
        if source == "QQ Music":
            mid = raw_payload.get("songmid")
            if mid:
                url = f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={urllib.parse.quote(str(mid))}&format=json&nobase64=1"
                data = self._json(url, headers={"Referer": "https://y.qq.com/"})
                if isinstance(data, dict):
                    raw = html.unescape(data.get("lyric") or "")
                    if raw:
                        plain = "\n".join(
                            re.sub(r"\[[^\]]*\]", "", l).strip()
                            for l in raw.splitlines()
                            if l.strip() and not re.match(r"^\[(?:ti|ar|al|by|offset):", l, re.I)
                        )
                        return {
                            "source": "QQ Music",
                            "syncedLyrics": raw,
                            "plainLyrics": plain,
                            "syncType": "word" if "<" in raw else "line",
                        }

        # 5. Genius
        if source == "Genius":
            page_url = raw_payload.get("url")
            if page_url:
                try:
                    with self._open_url(page_url, timeout=4.0) as resp:
                        page = resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
                    parts = re.findall(
                        r'<div[^>]*data-lyrics-container="true"[^>]*>(.*?)</div>', page, re.S
                    )
                    if parts:
                        text = html.unescape(
                            re.sub(
                                r"<[^>]+>",
                                "",
                                re.sub(r"<br\s*/?>", "\n", "\n".join(parts), flags=re.I),
                            )
                        ).strip()
                        if text:
                            return {
                                "source": "Genius",
                                "syncedLyrics": None,
                                "plainLyrics": text,
                                "syncType": "plain",
                            }
                except Exception as ex:
                    logger.debug("Genius scrap error: %s", ex)

        return None
