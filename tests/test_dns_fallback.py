"""Hermetic contracts for the bounded DNS-over-HTTPS fallback."""

from __future__ import annotations

from collections import OrderedDict
import socket
import threading
import urllib.request

import pytest

import core.dns_fallback as dns_module
from core.dns_fallback import DnsFallback, _NoRedirect


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


def failing_resolver(host, port, family, socktype, proto, flags):
    if host == "203.0.113.7":
        return [(family, socktype, proto, "", (host, port))]
    raise socket.gaierror("fixture lookup failure")


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size):
        assert size == 65_537
        return self.body


def test_doh_opener_disables_proxy_and_redirects(monkeypatch):
    captured = []
    fake_opener = object()
    monkeypatch.setattr(dns_module.urllib.request, "build_opener",
                        lambda *handlers: captured.extend(handlers) or fake_opener)
    fallback = DnsFallback(failing_resolver)
    proxy = next(handler for handler in captured if isinstance(handler, urllib.request.ProxyHandler))
    assert fallback._opener is fake_opener
    assert proxy.proxies == {}
    assert any(isinstance(handler, _NoRedirect) for handler in captured)


def test_failed_lookup_is_negative_cached_then_retried_after_short_ttl():
    clock = Clock()

    class Opener:
        calls = 0

        def open(self, _request, timeout):
            self.calls += 1
            assert timeout <= 0.9
            raise OSError("fixture transport failure")

    opener = Opener()
    fallback = DnsFallback(failing_resolver, opener=opener, clock=clock, budget=1.2)
    for _ in range(2):
        with pytest.raises(socket.gaierror):
            fallback.getaddrinfo("negative.example", 443)
    assert opener.calls == 2

    clock.value += 5.01
    with pytest.raises(socket.gaierror):
        fallback.getaddrinfo("negative.example", 443)
    assert opener.calls == 4


def test_parallel_misses_share_one_singleflight_query():
    fallback = DnsFallback(failing_resolver)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def query(host, record_type):
        calls.append((host, record_type))
        entered.set()
        assert release.wait(2)
        return "203.0.113.7"

    fallback._query = query
    results = []
    errors = []

    def resolve():
        try:
            results.append(fallback.getaddrinfo("flight.example", 443))
        except Exception as exc:  # collected from worker threads for assertion
            errors.append(exc)

    owner = threading.Thread(target=resolve)
    owner.start()
    assert entered.wait(1)
    waiters = [threading.Thread(target=resolve) for _ in range(4)]
    for waiter in waiters:
        waiter.start()
    release.set()
    owner.join(2)
    for waiter in waiters:
        waiter.join(2)

    assert not owner.is_alive()
    assert all(not waiter.is_alive() for waiter in waiters)
    assert errors == []
    assert len(results) == 5
    assert calls == [("flight.example", 1)]


def test_query_bounds_total_transport_budget_and_response_size():
    clock = Clock()

    class Opener:
        def __init__(self):
            self.timeouts = []

        def open(self, _request, timeout):
            self.timeouts.append(timeout)
            clock.value += timeout * 0.75
            raise OSError("slow fixture")

    opener = Opener()
    fallback = DnsFallback(failing_resolver, opener=opener, clock=clock, budget=1.2)
    assert fallback._query("bounded.example", 1) is None
    assert len(opener.timeouts) == 2
    assert all(0 < timeout <= 0.9 for timeout in opener.timeouts)
    assert clock.value - 100.0 <= 1.2

    class OversizeOpener:
        calls = 0

        def open(self, _request, timeout):
            self.calls += 1
            return Response(b"x" * 65_537)

    oversized = OversizeOpener()
    fallback = DnsFallback(failing_resolver, opener=oversized, clock=Clock())
    assert fallback._query("large.example", 1) is None
    assert oversized.calls == 2


def test_cache_is_bounded_and_lru_evicts_the_oldest_entry():
    clock = Clock()
    fallback = DnsFallback(failing_resolver, clock=clock)
    fallback._query = lambda _host, _record_type: "203.0.113.7"

    for index in range(257):
        fallback.getaddrinfo(f"host-{index}.example", 443)

    assert isinstance(fallback._cache, OrderedDict)
    assert len(fallback._cache) == 256
    assert ("host-0.example", 1) not in fallback._cache
    assert ("host-256.example", 1) in fallback._cache


def test_inflight_lookup_limit_fails_closed_without_opening_more_queries():
    fallback = DnsFallback(failing_resolver)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def query(host, record_type):
        calls.append(host)
        entered.set()
        assert release.wait(3)
        return None

    fallback._query = query
    errors = []

    def resolve(host):
        try:
            fallback.getaddrinfo(host, 443)
        except socket.gaierror as exc:
            errors.append(exc)

    threads = [threading.Thread(target=resolve, args=(f"parallel-{i}.example",))
               for i in range(8)]
    for thread in threads:
        thread.start()
    assert entered.wait(1)
    deadline = threading.Event()
    for _ in range(100):
        if len(fallback._flights) == 8:
            break
        deadline.wait(0.005)
    assert len(fallback._flights) == 8
    with pytest.raises(socket.gaierror):
        fallback.getaddrinfo("overflow.example", 443)
    release.set()
    for thread in threads:
        thread.join(2)
    assert all(not thread.is_alive() for thread in threads)
    assert len(calls) == 8
    assert len(errors) == 8
