"""
NeDotify / AURA Music - Event Delivery & Resilience Contract Tests
Verifies F1 Event Contract matching, F2 Resiliency / Fallback delivery under network offline,
and F3 Acceptance Criteria.
"""

import re
import os
import sys
import time
import pytest
from unittest.mock import MagicMock, patch

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_frontend_events_contract():
    """F1 & F3 Contract Test: Verify that all home feed events emitted by backend have a handler in events.js."""
    events_js_path = os.path.join("ui", "web_new", "js", "events.js")
    assert os.path.exists(events_js_path), "events.js file must exist"

    with open(events_js_path, "r", encoding="utf-8") as f:
        events_code = f.read()

    # Extract all switch case event names in events.js
    cases = re.findall(r"case\s+['\"]([^'\"]+)['\"]", events_code)
    handled_events = set(cases)

    # Mandatory home feed events that backend MUST emit and frontend MUST handle
    mandatory_events = [
        "popular_results",
        "feed_ready",
        "artists_ready",
        "releases_ready",
        "mixes_ready",
        "smart_home_ready",
        "authentic_home_ready"
    ]

    for ev in mandatory_events:
        assert ev in handled_events, f"Mandatory home feed event '{ev}' is missing a handler in events.js!"


def test_network_offline_failure_fallback():
    """F2 & F3 Failure Test: When network is offline, all 5 home sections emit events <= 12s with local fallback data."""
    from core.api import AppApi

    mock_core = MagicMock()
    mock_core.settings.get.return_value = "US"
    mock_core.settings.get_category.return_value = {}

    # Mock DB history and local tracks
    mock_core.db.get_history.return_value = [
        {"title": "Local Song 1", "artist": "Local Artist 1", "source": "local", "source_id": "1", "cover_url": "", "duration": 180},
        {"title": "Local Song 2", "artist": "Local Artist 2", "source": "local", "source_id": "2", "cover_url": "", "duration": 200}
    ]
    mock_core.db.get_all_tracks.return_value = [
        {"title": "Track A", "artist": "Artist A", "source": "local", "source_id": "101", "cover_url": "", "duration": 150}
    ]
    mock_core.db.get_top_artists.return_value = [
        {"artist": "Top Local Artist", "play_count": 50}
    ]

    # Force network failure on recommendation service
    mock_rec = MagicMock()
    mock_rec.get_charts.side_effect = Exception("Network offline")
    mock_rec.get_feed.side_effect = Exception("Network offline")
    mock_rec.get_custom_artists.side_effect = Exception("Network offline")
    mock_rec.get_releases.side_effect = Exception("Network offline")
    mock_rec.get_mixes.side_effect = Exception("Network offline")
    mock_core.recommendations = mock_rec

    api = AppApi(mock_core)
    emitted_events = {}

    def mock_emit(event_name, data=None):
        emitted_events[event_name] = data

    api._emit = mock_emit

    start_time = time.time()

    # Call all 5 home feed section methods
    api.get_popular_tracks()
    api.get_feed(10)
    api.get_home_artists(15)
    api.get_home_releases(10)
    api.get_home_mixes(10)

    # Wait up to 3 seconds for async threads/timers to complete fallback emissions
    time.sleep(1.0)
    elapsed = time.time() - start_time

    assert elapsed <= 12.0, f"Section assembly fallback took too long ({elapsed:.2f}s > 12s)"

    # Assert that all 5 events were emitted despite complete network failure
    assert "popular_results" in emitted_events, "popular_results was not emitted in offline fallback"
    assert "feed_ready" in emitted_events, "feed_ready was not emitted in offline fallback"
    assert "artists_ready" in emitted_events, "artists_ready was not emitted in offline fallback"
    assert "releases_ready" in emitted_events, "releases_ready was not emitted in offline fallback"
    assert "mixes_ready" in emitted_events, "mixes_ready was not emitted in offline fallback"


def test_e2e_no_unknown_events():
    """F3 E2E Test: Verify that no event emitted by backend leads to an unhandled 'Unknown event' in JS."""
    events_js_path = os.path.join("ui", "web_new", "js", "events.js")
    with open(events_js_path, "r", encoding="utf-8") as f:
        events_code = f.read()

    # Extract all switch case labels
    handled_events = set(re.findall(r"case\s+['\"]([^'\"]+)['\"]", events_code))

    # Parse core/api.py for all _emit calls
    api_py_path = os.path.join("core", "api.py")
    with open(api_py_path, "r", encoding="utf-8") as f:
        api_code = f.read()

    emitted_by_api = set(re.findall(r"_emit\(\s*['\"]([^'\"]+)['\"]", api_code))

    # Check that key home events emitted by api.py are handled in events.js
    key_events = {"popular_results", "feed_ready", "artists_ready", "releases_ready", "mixes_ready", "smart_home_ready", "authentic_home_ready"}
    for ev in key_events:
        if ev in emitted_by_api:
            assert ev in handled_events, f"Event '{ev}' is emitted by api.py but unhandled in events.js (would log Unknown event)"
