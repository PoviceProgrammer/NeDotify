"""Opt-in outbox for the local Windows recommendations beta."""

import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


PORT = 8765
ENDPOINT = f'http://127.0.0.1:{PORT}/v1/events'
BATCH_SIZE = 100
EVENT_KINDS = {'shown', 'started', 'completed', 'skipped', 'liked', 'added', 'hidden', 'playback_error'}
PROVIDER_ID = re.compile(r'[A-Za-z0-9_.-]{1,100}')


def configured_server():
    if 'NEDOTIFY_RECOMMENDATION_SERVER' in os.environ:
        return os.environ['NEDOTIFY_RECOMMENDATION_SERVER']
    if getattr(sys, 'frozen', False):
        path = Path(sys._MEIPASS) / 'recommendation-server.txt'
        if path.is_file():
            return path.read_text(encoding='utf-8').strip()
    return ''


def provider_recording_id(track):
    source = track.get('source')
    identifier = track.get('source_id')
    if source in ('youtube', 'soundcloud', 'deezer', 'yandex', 'spotify') and isinstance(identifier, str):
        if PROVIDER_ID.fullmatch(identifier):
            return f'{source}:{identifier}'
    return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RecommendationEvents:
    def __init__(self, path, server_url=None):
        self.path = path
        self.endpoint = ENDPOINT
        self.remote = bool(server_url)
        if server_url:
            url = urlsplit(server_url)
            if (url.scheme != 'https' or not url.hostname or url.username is not None
                    or url.path not in ('', '/') or url.query or url.fragment):
                raise ValueError('Expected a bare HTTPS server URL')
            self.endpoint = f'https://{url.netloc}/v1/events'
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._worker = None
        with closing(self._connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS consent (id INTEGER PRIMARY KEY CHECK (id = 1), installation TEXT)')
            db.execute('INSERT OR IGNORE INTO consent (id, installation) VALUES (1, ?)', (uuid.uuid4().hex,))
            db.execute('CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            self._installation = db.execute('SELECT installation FROM consent WHERE id = 1').fetchone()[0]
        if self._installation:
            self._start()

    def _connect(self):
        return sqlite3.connect(self.path, timeout=2)

    def _start(self):
        if self._worker is None:
            self._worker = threading.Thread(target=self._run, name='RecommendationEvents', daemon=True)
            self._worker.start()
        self._wake.set()

    def installation(self):
        with self._lock:
            return self._installation

    def set_enabled(self, enabled):
        with self._lock:
            previous = self._installation
            installation = (previous or uuid.uuid4().hex) if enabled else None
            with closing(self._connect()) as db, db:
                db.execute('UPDATE consent SET installation = ? WHERE id = 1', (installation,))
                if not enabled:
                    db.execute('DELETE FROM pending')
            self._installation = installation
            if enabled:
                self._start()
            return bool(installation)

    def enqueue(self, installation, events):
        with self._lock:
            if self._closed or not installation or installation != self._installation:
                return False
            minute = int(time.time()) // 60
            rows = [(json.dumps(dict(event, timestamp_min=minute, event_id=uuid.uuid4().hex)),) for event in events]
            with closing(self._connect()) as db, db:
                db.executemany('INSERT INTO pending (payload) VALUES (?)', rows)
            self._wake.set()
            return True

    def _run(self):
        opener = build_opener(ProxyHandler({}), NoRedirect())
        while True:
            self._wake.wait(5)
            self._wake.clear()
            try:
                with self._lock:
                    if self._closed:
                        return
                    if not self._installation:
                        continue
                    with closing(self._connect()) as db:
                        rows = db.execute('SELECT id, payload FROM pending ORDER BY id LIMIT ?', (BATCH_SIZE,)).fetchall()
                    if not rows:
                        continue
                    installation = self._installation
                body = json.dumps({'installation': installation,
                                   'events': [json.loads(row[1]) for row in rows]}).encode('utf-8')
                request = Request(self.endpoint, data=body, headers={'Content-Type': 'application/json'}, method='POST')
                with opener.open(request, timeout=1.5) as reply:
                    if reply.status != 204:
                        continue
                with self._lock:
                    if installation != self._installation:
                        continue
                    with closing(self._connect()) as db, db:
                        db.executemany('DELETE FROM pending WHERE id = ?', [(row[0],) for row in rows])
                    if len(rows) == BATCH_SIZE:
                        self._wake.set()
            except (OSError, sqlite3.Error):
                continue

    def close(self):
        with self._lock:
            self._closed = True
            self._wake.set()
