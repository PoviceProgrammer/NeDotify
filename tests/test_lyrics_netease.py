"""Regression tests for the Netease lyrics fetcher.

Two bugs are covered:

1. The fetcher queried ``/api/search/pc``, which now answers ``code=-462`` with
   zero songs for *every* query, so Netease was silently dead and no Russian
   track ever found lyrics. It must use ``/api/cloudsearch/pc``.
2. Netease's search is fuzzy: asking for "бойсбенд" returned a completely
   different song. Accepting ``songs[0]`` would have displayed the wrong
   lyrics, so a candidate must pass a title-match check first.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.lyrics_service import LyricsService  # noqa: E402


@pytest.fixture(scope="module")
def svc():
    return LyricsService()


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- endpoint selection -------------------------------------------------

def test_netease_uses_working_cloudsearch_endpoint(svc, monkeypatch):
    """Must hit the endpoint that still resolves.

    /api/search/pc answers code=-462 with zero songs for every query, and
    /api/search returns an empty body, so Netease was silently dead.
    """
    seen = {}

    def fake_open(req, timeout=None, context=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in (req.header_items() if hasattr(req, "header_items") else [])}
        return FakeResp(b'{"code":200,"result":{"songs":[]}}')

    monkeypatch.setattr(svc, "_open_url", fake_open)
    svc._fetch_netease("Yesterday", "The Beatles")

    assert "cloudsearch/pc" in seen["url"], seen["url"]
    assert "/api/search" not in seen["url"], seen["url"]
    # A Referer is required for the music.163.com endpoints to answer at all.
    assert seen["headers"].get("referer"), f"no Referer sent: {seen['headers']}"


def test_netease_fetches_several_candidates(svc, monkeypatch):
    """A single fuzzy hit is not enough to trust, so limit must be > 1."""
    seen = {}

    def fake_open(req, timeout=None, context=None):
        seen["url"] = req.full_url
        return FakeResp(b'{"code":200,"result":{"songs":[]}}')

    monkeypatch.setattr(svc, "_open_url", fake_open)
    assert svc._fetch_netease("бойсбенд", "Фараон") is None
    limit = re.search(r"limit=(\d+)", seen["url"])
    assert limit and int(limit.group(1)) > 1


# --- title matching -----------------------------------------------------

@pytest.mark.parametrize(
    "want,got,minimum",
    [
        ("бойсбенд", "Бойсбенд", 0.6),
        ("Yesterday", "Yesterday", 0.6),
        ("Ванава", "ВАНАВА", 0.6),
        ("Мой кайф (Remix)", "Мой кайф", 0.6),
        ("бойсбенд", "Прощай навеки последняя любовь", 1.1),  # must be rejected
        ("Yesterday", "Comfortably Numb", 1.1),               # must be rejected
        ("", "anything", 1.1),
        ("something", "", 1.1),
    ],
)
def test_title_match_score(svc, want, got, minimum):
    score = svc._title_match_score(want, got)
    if minimum > 1.0:
        assert score < svc._TITLE_MATCH_MIN, (
            f"{got!r} should not be accepted as {want!r} (score={score})"
        )
    else:
        assert score >= svc._TITLE_MATCH_MIN, (
            f"{got!r} should be accepted as {want!r} (score={score})"
        )


def test_wrong_song_is_rejected_even_when_lyrics_exist(svc, monkeypatch):
    """A mismatched hit must return None rather than someone else's lyrics."""
    wrong = {
        "code": 200,
        "result": {"songs": [{"id": 1, "name": "Прощай навеки последняя любовь"}]},
    }
    calls = {"n": 0}

    def fake_open(req, timeout=None, context=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(json.dumps(wrong).encode("utf-8"))
        raise AssertionError("lyric fetch must not run for a mismatched song")

    monkeypatch.setattr(svc, "_open_url", fake_open)
    assert svc._fetch_netease("бойсбенд", "Фараон") is None
    assert calls["n"] == 1, "should stop after the title check failed"


def test_matching_song_returns_lyrics(svc, monkeypatch):
    search = {"code": 200, "result": {"songs": [
        {"id": 42, "name": "Прощай навеки"},
        {"id": 99, "name": "Бойсбенд"},
    ]}}
    lyric = {"lrc": {"lyric": "[00:12.00] тест"}, "tlyric": {"lyric": ""}}
    asked = []

    def fake_open(req, timeout=None, context=None):
        if "cloudsearch" in req.full_url:
            return FakeResp(json.dumps(search).encode("utf-8"))
        asked.append(req.full_url)
        return FakeResp(json.dumps(lyric).encode("utf-8"))

    monkeypatch.setattr(svc, "_open_url", fake_open)
    res = svc._fetch_netease("бойсбенд", "Фараон")

    # Assertions live outside the mock: _fetch_netease swallows every
    # exception, so an assert raising inside the fake would be invisible.
    assert asked, "lyric endpoint was never called"
    assert "id=99" in asked[0], f"picked the wrong candidate: {asked[0]}"
    assert res and res["weight"] == 1
    assert "тест" in res["plainLyrics"]


def test_cascade_budget_covers_netease_latency():
    """Netease's working endpoint needs seconds; the cascade must wait for it."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "services", "lyrics_service.py"), encoding="utf-8").read()
    body = src[src.index("result = _execute_cascade(track, artist") :]
    budget = float(re.search(r"max_timeout=([\d.]+)", body).group(1))
    assert budget >= 5.0, (
        "cascade budget is below the ~2-6s Netease latency, so its result "
        "would always be discarded"
    )


# --- variant / remix title cleanup -------------------------------------
#
# Providers index the BASE recording. If a title like "Track (Hardstyle
# Bootleg)" is queried verbatim nothing matches, and the app claims the lyrics
# are missing for a song whose words are indexed fine. Verified against the live
# APIs: after stripping, several of these went from "not found" to synced
# lyrics (Firestarter, Disarm You, Bad Blood, Life, Yesterday).

@pytest.mark.parametrize(
    "raw,expected",
    [
        # variant / genre qualifiers get removed
        ("Some Track (Hardstyle Bootleg)", "Some Track"),
        ("Sandstorm (Radio Edit)", "Sandstorm"),
        ("Track [Extended Mix]", "Track"),
        ("Track (Remix)", "Track"),
        ("Track (Slowed + Reverb)", "Track"),
        ("Song (Sped Up)", "Song"),
        ("Song (Club Mix)", "Song"),
        ("Song (Bass Boosted)", "Song"),
        ("Song (Nightcore)", "Song"),
        ("Song (8D Audio)", "Song"),
        ("Song (1.5x)", "Song"),
        ("Song (VIP)", "Song"),
        ("Song (Mashup)", "Song"),
        ("Song (Remastered 2009)", "Song"),
        # the remixer's name inside the group: a strong marker still carries it
        ("Замигает свет (SWEEQTY hardstyle remix)", "Замигает свет"),
        ("Song (SomeProducer VIP edit)", "Song"),
        # genre words alone are not a version marker, real titles survive
        ("Love (Hardstyle)", "Love (Hardstyle)"),
        ("Song (House)", "Song (House)"),
        ("Song (Radio Ga Ga)", "Song (Radio Ga Ga)"),
        ("Song (Live)", "Song"),
        # trailing-dash form
        ("Song - Extended Mix", "Song"),
        ("Song – Radio Edit", "Song"),
        # real titles must survive untouched
        ("(I Love You)", "(I Love You)"),
        ("Song (Acoustic)", "Song (Acoustic)"),
        ("Song (Radio Ga Ga)", "Song (Radio Ga Ga)"),
        ("The Remix Album", "The Remix Album"),
        # feat was already stripped by the pre-existing patterns
        ("Song (feat. Someone)", "Song"),
    ],
)
def test_variant_qualifiers_are_stripped(svc, raw, expected):
    cleaned, _artist = svc._clean_track_and_artist(raw, "Someone")
    assert cleaned == expected


def test_instrumental_is_not_stripped(svc):
    """An instrumental has no sung lyrics; do not silently show the original's."""
    cleaned, _ = svc._clean_track_and_artist("Song (Instrumental)", "Someone")
    assert "Instrumental" in cleaned


def test_embedded_artist_is_tried_as_a_fallback_query(svc, monkeypatch):
    """A remix upload names the REMIXER as artist and hides the real one in the title.

    SoundCloud reports the uploader, so a bootleg arrives as artist="SWEEQTY"
    with title "KENTUKKI - Замигает свет (SWEEQTY hardstyle remix)". Providers
    index the original under the ORIGINAL artist, so the primary query misses
    and the "A - B" split of the title is the candidate that resolves.
    """
    seen = []

    def fake_lrclib(track, artist):
        seen.append((artist, track))
        if artist == "KENTUKKI" and track == "Замигает свет":
            return {"syncedLyrics": "[00:01.00] Фонари", "plainLyrics": "Фонари", "weight": 1}
        return None

    def nothing(track, artist):
        seen.append((artist, track))
        return None

    monkeypatch.setattr(svc, "_fetch_lrclib", fake_lrclib)
    for name in ("_fetch_netease", "_fetch_qqmusic", "_fetch_megalobiz",
                 "_fetch_genius", "_fetch_duckduckgo"):
        monkeypatch.setattr(svc, name, nothing)

    res = svc.get_lyrics("KENTUKKI - Замигает свет (SWEEQTY hardstyle remix)", "SWEEQTY")

    assert ("KENTUKKI", "Замигает свет") in seen, f"fallback never ran: {seen}"
    assert res.get("weight") == 1, "fallback query should have resolved the lyrics"
    assert "Фонари" in (res.get("plainLyrics") or "")
