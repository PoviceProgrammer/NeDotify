"""Receive opt-in recommendation beta events on this Windows PC."""

import argparse
import json
import re
import sqlite3
import sys
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __name__ == '__main__':
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from services.recommendation_events import BATCH_SIZE, EVENT_KINDS, PORT


TOKEN = re.compile(r'[a-f0-9]{32}')
KEY = re.compile(r'[A-Za-z0-9_.:-]{1,128}')
RETENTION_MINUTES = 90 * 24 * 60


def _token(value):
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def _key(value):
    return isinstance(value, str) and KEY.fullmatch(value) is not None


def validated_batch(payload):
    if not isinstance(payload, dict) or set(payload) != {'installation', 'events'} or not _token(payload['installation']):
        raise ValueError('Invalid installation')
    batch = payload['events']
    if not isinstance(batch, list) or not 1 <= len(batch) <= BATCH_SIZE:
        raise ValueError('Invalid batch size')
    now = int(time.time()) // 60
    fields = {'event_id', 'kind', 'impression_id', 'recording_id', 'position', 'ranker_version',
              'catalog_version', 'timestamp_min'}
    for event in batch:
        if not isinstance(event, dict) or not fields <= event.keys() <= fields | {'listened_fraction'}:
            raise ValueError('Invalid event fields')
        if (not _token(event['event_id']) or not _token(event['impression_id'])
                or not all(_key(event[key]) for key in ('recording_id', 'ranker_version', 'catalog_version'))
                or not isinstance(event['kind'], str) or event['kind'] not in EVENT_KINDS
                or type(event['position']) is not int or not 1 <= event['position'] <= 20
                or type(event['timestamp_min']) is not int or not 0 <= event['timestamp_min'] <= now + 5):
            raise ValueError('Invalid event values')
        if 'listened_fraction' in event:
            fraction = event['listened_fraction']
            if type(fraction) not in (int, float) or not 0 <= fraction <= 1:
                raise ValueError('Invalid listened fraction')
    return payload['installation'], batch


def make_server(path, port=PORT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS events (installation TEXT NOT NULL, event_id TEXT NOT NULL, '
                   'timestamp_min INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (installation, event_id))')
        db.execute('CREATE INDEX IF NOT EXISTS events_by_time ON events(timestamp_min)')

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/v1/events':
                self.send_error(404)
                return
            if self.headers.get('Origin') or self.headers.get_content_type() != 'application/json':
                self.send_error(415)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536:
                    raise ValueError('Invalid request size')
                self.connection.settimeout(3)
                installation, batch = validated_batch(json.loads(self.rfile.read(size)))
            except (ValueError, OSError):
                self.send_error(400)
                return
            cutoff = int(time.time()) // 60 - RETENTION_MINUTES
            try:
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('DELETE FROM events WHERE timestamp_min < ?', (cutoff,))
                    db.executemany('INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?)',
                                   [(installation, event['event_id'], event['timestamp_min'], json.dumps(event))
                                    for event in batch if event['timestamp_min'] >= cutoff])
            except sqlite3.Error:
                self.send_error(503)
                return
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            if self.path != '/health':
                self.send_error(404)
                return
            self.send_response(204)
            self.end_headers()

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--summary', action='store_true', help='Read event counts without starting the server')
    args = parser.parse_args()
    if args.summary:
        with closing(sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            counts = db.execute("SELECT json_extract(payload, '$.kind'), COUNT(*) FROM events GROUP BY 1")
            print(json.dumps(dict(counts), indent=2))
        return
    with make_server(args.db) as server:
        print(f'Listening on http://127.0.0.1:{PORT}', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
