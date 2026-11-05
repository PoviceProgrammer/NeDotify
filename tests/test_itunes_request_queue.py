"""Global iTunes rate control, transient errors and cancellable queued work."""
from collections import deque, OrderedDict
from types import SimpleNamespace

import pytest

import services.itunes_gateway as module
from services.itunes_gateway import ITunesGateway as Gateway, CatalogueUnavailable


@pytest.fixture
def queue(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(Gateway, '_recent', deque())
    monkeypatch.setattr(Gateway, '_entries', OrderedDict())
    monkeypatch.setattr(Gateway, '_flights', {})
    monkeypatch.setattr(Gateway, '_next_at', 0.0)
    monkeypatch.setattr(Gateway, '_active', False)
    monkeypatch.setattr(Gateway._condition, 'wait', lambda seconds: now.__setitem__(0, now[0] + seconds))
    starts = []
    def get(url, **kwargs):
        starts.append(now[0])
        return SimpleNamespace(status_code=200, json=lambda: {'results': [{'artistId': 1}]})
    return now, starts, SimpleNamespace(get=get)


def test_spacing_and_rolling_limit_apply_to_all_unique_requests(queue):
    now, starts, session = queue
    for index in range(25):
        Gateway.get(f'url-{index}', session=session, deadline=now[0] + 65)
    assert all(b - a >= .099 for a, b in zip(starts, starts[1:]))
    assert max(sum(0 <= point - other < 60 for other in starts) for point in starts) <= 18


def test_cached_lookup_does_not_consume_quota_and_expires(queue):
    now, starts, session = queue
    Gateway.get('same', session=session)
    Gateway.get('same', session=session)
    assert len(starts) == 1
    now[0] += 901
    Gateway.get('same', session=session)
    assert len(starts) == 2


def test_network_failure_is_not_cached(queue):
    now, starts, session = queue
    broken = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=503))
    with pytest.raises(CatalogueUnavailable):
        Gateway.get('recovery', session=broken)
    assert not Gateway._entries
    assert Gateway.get('recovery', session=session)['results']


def test_stale_queued_request_is_removed_without_http_or_quota(queue):
    now, starts, session = queue
    with pytest.raises(CatalogueUnavailable):
        Gateway.get('obsolete', session=session, is_current=lambda: False)
    assert not starts and not Gateway._recent and not Gateway._flights


def test_retry_after_does_not_turn_rate_limit_into_not_found(queue):
    now, starts, session = queue
    rate_limited = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=429, headers={'Retry-After': '30'}))
    with pytest.raises(CatalogueUnavailable):
        Gateway.get('limited', session=rate_limited)
    with pytest.raises(CatalogueUnavailable):
        Gateway.get('next', session=session)
    assert not starts and not Gateway._entries
