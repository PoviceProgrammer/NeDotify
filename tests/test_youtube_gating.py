"""YouTube anti-bot gating: storyboard-only responses map to an actionable error."""

import pytest

from services.youtube_service import (
    YouTubeService,
    _is_storyboards_only,
    _yt_gating_error,
    _YT_GATED_MSG,
)


def _storyboard_info():
    return {
        "id": "vid1",
        "formats": [
            {"format_id": "sb0", "ext": "mhtml"},
            {"format_id": "sb1", "ext": "mhtml"},
        ],
    }


def test_gating_error_marks():
    err = _yt_gating_error(Exception("Requested format is not available"))
    assert str(err) == _YT_GATED_MSG
    err = _yt_gating_error(Exception("The page needs to be reloaded"))
    assert str(err) == _YT_GATED_MSG
    plain = Exception("plain network timeout")
    assert _yt_gating_error(plain) is plain


def test_is_storyboards_only():
    assert _is_storyboards_only(_storyboard_info()) is True
    playable = {"id": "v", "formats": [{"format_id": "251", "url": "http://x",
                                        "acodec": "opus"}]}
    assert _is_storyboards_only(playable) is False
    assert _is_storyboards_only({}) is False
    assert _is_storyboards_only({"_type": "playlist",
                                 "entries": [_storyboard_info()]}) is True


def test_download_maps_gated_extraction_error(tmp_path, monkeypatch):
    import services.youtube_service as ys

    class ExplodingYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            raise Exception("Requested format is not available")

    monkeypatch.setattr(ys, "yt_dlp",
                        type("M", (), {"YoutubeDL": ExplodingYDL}))
    svc = YouTubeService()
    with pytest.raises(Exception, match="SoundCloud"):
        svc.download_audio_sync("vid1", str(tmp_path))
