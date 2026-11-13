import json
import socket
import sqlite3
import threading
import time
from contextlib import closing
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services import recommendation_events
from tools.recommendation_event_server import make_server


def rows(path, table):
    with closing(sqlite3.connect(path)) as db:
        return db.execute(f'SELECT payload FROM {table}').fetchall()


def test_opt_in_impression_and_outcome_deliver_to_loopback(api, tmp_path, monkeypatch):
    monkeypatch.setenv('NEDOTIFY_DISCOVERY_PREVIEW_CATALOG', 'preview.json')
    server_db = tmp_path / 'server.db'
    server = make_server(server_db, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = f'http://127.0.0.1:{server.server_port}/v1/events'
    monkeypatch.setattr(recommendation_events, 'ENDPOINT', endpoint)
    track = dict(source='local', source_id='test-source', title='Private title', artist='Private artist',
                 file_path='C:/Music/private.wav', recommendation_recording_id='demo:1')
    mix = dict(tracks=[track], recommendation_event_context=dict(catalog_version='demo', ranker_version='mlp_preview'))
    try:
        assert api.get_recommendation_collection() == {'available': True, 'enabled': True, 'remote': False}
        assert not api.set_recommendation_collection(False)['enabled']
        assert not api.report_recommendation_impression('unknown')
        assert rows(server_db, 'events') == []
        assert api.set_recommendation_collection(True)['enabled']
        installation = api._recommendation_events.installation()
        registered = api._register_recommendation_impressions([mix], installation)[0]
        impression = registered['recommendation_impression_id']
        assert api.report_recommendation_impression(impression)
        assert api.report_recommendation_impression(impression)
        recommended = registered['tracks'][0]
        api._record_recommendation_outcome(recommended, 'started')
        api._record_recommendation_outcome(recommended, 'completed', .72)
        api._record_recommendation_outcome(recommended, 'completed', .99)
        deadline = time.monotonic() + 5
        while len(rows(server_db, 'events')) < 3 and time.monotonic() < deadline:
            time.sleep(.02)
        received = [json.loads(payload) for (payload,) in rows(server_db, 'events')]
        assert [event['kind'] for event in received] == ['shown', 'started', 'completed']
        assert received[-1]['listened_fraction'] == .72
        assert 'Private' not in json.dumps(received) and 'private.wav' not in json.dumps(received)

        body = json.dumps({'installation': installation, 'events': received}).encode()
        request = Request(endpoint, data=body, headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=2) as response:
            assert response.status == 204
        assert len(rows(server_db, 'events')) == 3
        request.add_header('Origin', 'https://example.com')
        with pytest.raises(HTTPError) as exc:
            urlopen(request, timeout=2)
        assert exc.value.code == 415

        assert not api.set_recommendation_collection(False)['enabled']
        assert not api.report_recommendation_impression(impression)
        api._record_recommendation_outcome(recommended, 'liked')
        assert rows(api._recommendation_events.path, 'pending') == []
        assert len(rows(server_db, 'events')) == 3
    finally:
        api.shutdown()
        server.shutdown()
        server.server_close()
        worker.join()


def test_offline_outbox_survives_restart_and_is_cleared_on_disable(tmp_path, monkeypatch):
    with closing(socket.socket()) as unavailable:
        unavailable.bind(('127.0.0.1', 0))
        port = unavailable.getsockname()[1]
        monkeypatch.setattr(recommendation_events, 'ENDPOINT', f'http://127.0.0.1:{port}/v1/events')
        path = tmp_path / 'outbox.db'
        original = recommendation_events.RecommendationEvents(path)
        try:
            assert original.set_enabled(True)
            installation = original.installation()
            assert original.enqueue(installation, [dict(kind='shown')])
            assert len(rows(path, 'pending')) == 1
        finally:
            original.close()
        resumed = recommendation_events.RecommendationEvents(path)
        try:
            assert resumed.installation() == installation
            assert len(rows(path, 'pending')) == 1
            resumed.set_enabled(False)
            assert rows(path, 'pending') == []
            resumed.set_enabled(True)
            assert resumed.installation() != installation
            assert not resumed.enqueue(installation, [dict(kind='shown')])
        finally:
            resumed.close()
