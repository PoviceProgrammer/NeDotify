"""Download integrity gates (youtube_service / cache_manager / downloader).

Pins the failure where a broken download was accepted as a good one. yt-dlp
leaves 0-byte files, `.part` fragments and non-media artefacts (e.g.
`sb0.mhtml` when it lands on a consent/gate page), and every path that
followed only asked `os.path.exists()` - so the track was marked
is_downloaded=1, download_complete fired, and the user got a silent library.

  - _require_audio_file / _downloaded_file_defect reject each broken shape
  - a real audio file passes
  - the 4 KiB floor is a floor, not the real minimum (killall.py lesson):
    any zapret-style binary here is not audio and must be rejected by
    extension anyway
  - download_audio() is gone: it is dead code with a broken success contract
"""

import os

import pytest

from services.youtube_service import _require_audio_file


def _audio(directory, name="track.m4a", size=8 * 1024):
    path = os.path.join(str(directory), name)
    with open(path, "wb") as f:
        f.write(b"\x00" * size)
    return path


# ─── _require_audio_file ────────────────────────────────────────────────

def test_empty_file_is_rejected(tmp_path):
    p = os.path.join(str(tmp_path), "track.m4a")
    open(p, "wb").close()
    with pytest.raises(Exception, match="повреждён|не найден|минимум"):
        _require_audio_file(p)


def test_part_file_is_rejected(tmp_path):
    p = os.path.join(str(tmp_path), "yt_x.part")
    with open(p, "wb") as f:
        f.write(b"\x00" * 4096)
    with pytest.raises(Exception, match="part|не завер"):
        _require_audio_file(p)


def test_tiny_file_is_rejected(tmp_path):
    p = os.path.join(str(tmp_path), "track.m4a")
    with open(p, "wb") as f:
        f.write(b"\x00" * 1024)
    with pytest.raises(Exception, match="повреждён|минимум"):
        _require_audio_file(p)


def test_non_audio_extension_is_rejected(tmp_path):
    p = os.path.join(str(tmp_path), "sb0.mhtml")
    with open(p, "wb") as f:
        f.write(b"\x00" * 64 * 1024)
    with pytest.raises(Exception, match="не аудиофайл"):
        _require_audio_file(p)


def test_mhtml_gate_artefact_is_rejected(tmp_path):
    """yt-dlp writes a consent/gate page under a media-sounding name."""
    p = os.path.join(str(tmp_path), "yt_abc.mhtml")
    with open(p, "wb") as f:
        f.write(b"\x00" * 16 * 1024)
    with pytest.raises(Exception):
        _require_audio_file(p)


def test_real_audio_file_passes(tmp_path):
    p = _audio(tmp_path)
    assert _require_audio_file(p) == p


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(Exception, match="не найден"):
        _require_audio_file(os.path.join(str(tmp_path), "nope.m4a"))


@pytest.mark.parametrize("name", ["a.m4a", "a.mp3", "a.opus", "a.webm",
                                  "a.aac", "a.ogg", "a.flac", "a.wav"])
def test_every_audio_extension_passes(tmp_path, name):
    p = _audio(tmp_path, name=name)
    assert _require_audio_file(p) == p


# ─── download_audio() is gone ───────────────────────────────────────────

def test_download_audio_is_deprecated(tmp_path):
    """Dead code with a broken contract: it called callback() even after a
    failed download, so a failure looked like a success."""
    from services.youtube_service import YouTubeService

    with pytest.raises(NotImplementedError):
        YouTubeService().download_audio("https://youtube.com/watch?v=x", "out.mp3")


def test_no_caller_of_download_audio_remains():
    """The whole repo went through download_audio_sync."""
    import subprocess
    out = subprocess.run(
        ["git", "grep", "-n", r"\.download_audio(", "HEAD"],
        capture_output=True, text=True,
    )
    assert ".download_audio(" not in (out.stdout or ""), (
        "something still calls the deprecated download_audio()"
    )


# ─── the downloader's own gate ──────────────────────────────────────────

def test_downloader_gate_rejects_a_bad_file(tmp_path):
    from core.downloader import _downloaded_file_defect

    p = os.path.join(str(tmp_path), "x.m4a")
    with open(p, "wb") as f:
        f.write(b"\x00" * 100)
    assert _downloaded_file_defect(p)


def test_downloader_gate_accepts_a_good_file(tmp_path):
    from core.downloader import _downloaded_file_defect

    p = _audio(tmp_path)
    assert _downloaded_file_defect(p) == ""


def test_downloader_gate_rejects_part_and_mhtml(tmp_path):
    from core.downloader import _downloaded_file_defect

    part = os.path.join(str(tmp_path), "x.part")
    with open(part, "wb") as f:
        f.write(b"\x00" * 4096)
    assert _downloaded_file_defect(part)

    mhtml = os.path.join(str(tmp_path), "x.mhtml")
    with open(mhtml, "wb") as f:
        f.write(b"\x00" * 4096)
    assert _downloaded_file_defect(mhtml)
