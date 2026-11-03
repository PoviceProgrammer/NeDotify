"""Optional, bounded disk cache for identity-checked lyrics, separate from the library.

Connections are short-lived and thread-local to an operation. A cache failure is
always a miss: offline library/playback must not depend on this expendable file.
"""
import hashlib
from contextlib import closing
import json
import logging
import math
import os
import re
import sqlite3
import time

logger = logging.getLogger(__name__)


class LyricsDiskCache:
    MAX_ENTRIES = 20_000
    MAX_PAYLOAD_BYTES = 96 * 1024 * 1024
    MAX_FILE_BYTES = 128 * 1024 * 1024
    MAX_RECORD_BYTES = 512 * 1024
    SCHEMA_VERSION = 1

    def __init__(self, path, *, max_entries=None, max_bytes=None):
        self.path = os.fspath(path)
        self.max_entries = self.MAX_ENTRIES if max_entries is None else max(1, int(max_entries))
        self.max_bytes = self.MAX_PAYLOAD_BYTES if max_bytes is None else max(1, int(max_bytes))

    @classmethod
    def _key(cls, key):
        # Versioning prevents old acceptance/timing rules surviving a future
        # matcher change. The full identity includes duration, edition and file mtime.
        raw = json.dumps([cls.SCHEMA_VERSION, key], ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @staticmethod
    def valid(result):
        if not isinstance(result, dict) or result.get('status') != 'found':
            return False
        if result.get('match_type') not in ('exact', 'base') or not isinstance(result.get('source'), str):
            return False
        confidence = result.get('confidence')
        if not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not .85 <= confidence <= 1:
            return False
        synced, plain = result.get('syncedLyrics'), result.get('plainLyrics')
        if (synced is not None and not isinstance(synced, str)) or (plain is not None and not isinstance(plain, str)):
            return False
        if not (synced or plain or result.get('instrumental') is True):
            return False
        # A base recording can never supply karaoke timing to a remix/slowed edit.
        if result.get('match_type') == 'base' and synced:
            return False
        if synced and not re.search(r'\[\d+:\d{2}(?:[.:]\d+)?\]', synced):
            return False
        if 'syncType' in result or 'lines' in result:
            from services.lyrics_formats import validate_lyrics
            if result.get('instrumental') and result.get('syncType') == 'plain' and result.get('lines') == []:
                return True
            if not validate_lyrics({'syncType': result.get('syncType'), 'lines': result.get('lines')}):
                return False
            if result.get('match_type') == 'base' and result.get('syncType') != 'plain':
                return False
        return True

    def get(self, key, *, with_ttl=False):
        # Reading a missing cache must not create a database or profile directory.
        if not os.path.isfile(self.path):
            return None
        try:
            with closing(sqlite3.connect(self.path, timeout=.05)) as conn:
                row = conn.execute('SELECT payload, expires FROM lyrics_cache WHERE identity = ?', (self._key(key),)).fetchone()
            if not row or row[1] <= time.time() or len(row[0]) > self.MAX_RECORD_BYTES:
                return None
            result = json.loads(row[0])
            if not self.valid(result):
                return None
            return (result, row[1] - time.time()) if with_ttl else result
        except (OSError, sqlite3.Error, ValueError, TypeError):
            logger.debug('Lyrics disk cache read failed', exc_info=True)
            return None

    def put(self, key, result, ttl):
        if not self.valid(result):
            return
        try:
            value = {k: v for k, v in result.items() if k not in ('revision', 'phase')}
            payload = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            if len(payload) > min(self.MAX_RECORD_BYTES, self.max_bytes):
                return
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=.1)) as conn, conn:
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA synchronous=NORMAL')
                page_size = conn.execute('PRAGMA page_size').fetchone()[0]
                conn.execute(f'PRAGMA max_page_count={self.MAX_FILE_BYTES // page_size}')
                conn.execute('PRAGMA journal_size_limit=4194304')
                conn.execute('CREATE TABLE IF NOT EXISTS lyrics_cache (identity TEXT PRIMARY KEY, payload BLOB NOT NULL, expires REAL NOT NULL, updated REAL NOT NULL)')
                conn.execute('CREATE INDEX IF NOT EXISTS lyrics_cache_updated ON lyrics_cache(updated)')
                now = time.time()
                conn.execute('DELETE FROM lyrics_cache WHERE expires <= ?', (now,))
                conn.execute('INSERT OR REPLACE INTO lyrics_cache VALUES (?, ?, ?, ?)', (self._key(key), payload, now + ttl, now))
                count, size = conn.execute('SELECT COUNT(*), COALESCE(SUM(length(payload)), 0) FROM lyrics_cache').fetchone()
                # Only inspect evictees when a limit is exceeded; normal writes
                # use one aggregate over at most 20k small cache rows.
                if count > self.max_entries or size > self.max_bytes:
                    victims = []
                    for identity, length in conn.execute('SELECT identity, length(payload) FROM lyrics_cache ORDER BY updated'):
                        if count <= self.max_entries and size <= self.max_bytes:
                            break
                        victims.append((identity,))
                        count -= 1
                        size -= length
                    conn.executemany('DELETE FROM lyrics_cache WHERE identity = ?', victims)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            logger.debug('Lyrics disk cache write failed', exc_info=True)
