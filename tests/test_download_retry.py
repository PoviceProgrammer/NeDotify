"""Download retries (core/downloader.py).

A single attempt per track meant a transient glitch - a PO token that had not
refreshed, a 429, a read timeout - permanently failed the download. The worker
now retries transient marks with backoff, but permanent ones (DRM, a bad
source, an unsupported provider) must fail immediately: waiting for those just
burns the same request again.

  - a transient error is retried up to _RETRY_ATTEMPTS
  - the delay backs off and can be cancelled during the wait
  - a permanent error is not retried at all
  - an unsupported source keeps its own message
  - a provider returning no file is permanent, not transient
"""

import time

import pytest


def test_transient_marks_are_retried(downloader):
    assert downloader._is_retryable_error("The page needs to be reloaded.") is True


def test_permanent_marks_are_not_retried(downloader):
    assert downloader._is_retryable_error("This video is DRM protected") is False
    assert downloader._is_retryable_error("") is False
    assert downloader._is_retryable_error(None) is False


def test_transient_failure_is_retried(downloader, monkeypatch):
    """429 twice, then success: the third attempt must be reached."""
    attempts = {"n": 0}

    def _fake_fetch(source, source_id, download_dir, track_id):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Exception("HTTP Error 429: Too Many Requests")
        return "ok.mp3"

    monkeypatch.setattr(downloader, "_fetch_from_provider", _fake_fetch)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    path = downloader._fetch_with_retry("youtube", "v1", "/tmp", 1, 0)

    assert path == "ok.mp3"
    assert attempts["n"] == 3


def test_retries_stop_after_the_cap(downloader, monkeypatch):
    attempts = {"n": 0}

    def _always_fail(source, source_id, download_dir, track_id):
        attempts["n"] += 1
        raise Exception("The page needs to be reloaded.")

    monkeypatch.setattr(downloader, "_fetch_from_provider", _always_fail)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    with pytest.raises(Exception, match="reloaded"):
        downloader._fetch_with_retry("youtube", "v1", "/tmp", 1, 0)

    assert attempts["n"] == downloader._RETRY_ATTEMPTS


def test_permanent_failure_is_not_retried(downloader, monkeypatch):
    attempts = {"n": 0}

    def _drm(source, source_id, download_dir, track_id):
        attempts["n"] += 1
        raise Exception("This video is DRM protected")

    monkeypatch.setattr(downloader, "_fetch_from_provider", _drm)

    with pytest.raises(Exception, match="DRM"):
        downloader._fetch_with_retry("youtube", "v1", "/tmp", 1, 0)

    assert attempts["n"] == 1, "a permanent error must fail on the first attempt"


def test_backoff_grows(downloader):
    """20s then 40s: the delay must double, not stay fixed."""
    delay = downloader._RETRY_BASE_DELAY
    seen = [delay]
    for _ in range(2):
        delay *= 2
        seen.append(delay)
    assert seen == [20.0, 40.0, 80.0]


def test_cancel_is_honoured_during_the_retry_wait(downloader, monkeypatch):
    """A cancel_batch() must interrupt the wait, not be noticed after it."""
    attempts = {"n": 0}

    def _always_fail(source, source_id, download_dir, track_id):
        attempts["n"] += 1
        raise Exception("timed out")

    monkeypatch.setattr(downloader, "_fetch_from_provider", _always_fail)

    def _fake_sleep(seconds):
        # A cancel_batch() lands mid-wait: epoch 0 becomes stale.
        downloader._cancel_epoch += 1

    monkeypatch.setattr(time, "sleep", _fake_sleep)

    result = downloader._fetch_with_retry("youtube", "v1", "/tmp", 1, 0)

    assert result is None, "the wait must be abandoned, not run to completion"
    assert attempts["n"] == 1, "no second attempt may start after a cancel"


def test_a_provider_returning_no_file_is_permanent(downloader, monkeypatch):
    """No file means unavailable: waiting would only postpone the same result."""
    monkeypatch.setattr(downloader._core.youtube, "download_audio_sync",
                        lambda s, d: None)
    with pytest.raises(Exception, match="не вернул файл"):
        downloader._fetch_from_provider("youtube", "v1", "/tmp", 1)


def test_unsupported_source_keeps_its_message(downloader):
    with pytest.raises(Exception, match="No download provider for source 'vk'"):
        downloader._fetch_from_provider("vk", "x", "/tmp", 1)


def test_unsupported_source_is_permanent(downloader):
    """vk must not be retried either: it would fail the same way 3 times."""
    assert downloader._is_retryable_error("No download provider for source 'vk'.") is False
