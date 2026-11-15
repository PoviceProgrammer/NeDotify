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
    from core.download_processing import ToolExecutionError
    from core.download_transfer import DownloadContext

    def transfer(*args, **kwargs):
        raise ToolExecutionError(1, 'Requested format is not available')

    monkeypatch.setattr(DownloadContext, 'download_executable', transfer)
    svc = YouTubeService()
    with pytest.raises(RuntimeError, match='SoundCloud'):
        svc.download_audio_sync('jNQXAC9IVRw', str(tmp_path))
