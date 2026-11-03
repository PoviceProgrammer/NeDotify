"""Safety and metadata regressions for local audio tag handling."""

import base64
import wave

import pytest

from tests.audio_helpers import wave_bytes
from utils import tag_parser


def test_write_tags_replaces_only_after_a_complete_wav_write(tmp_path):
    path = tmp_path / "track.wav"
    original = wave_bytes()
    path.write_bytes(original)

    assert tag_parser.write_tags(str(path), title="Tagged title", artist="Artist")

    parsed = tag_parser.parse_tags(str(path))
    assert parsed["title"] == "Tagged title"
    assert parsed["artist"] == "Artist"
    with wave.open(str(path), "rb") as audio:
        with wave.open(str(tmp_path / "original.wav"), "wb") as reference:
            reference.setparams(audio.getparams())
            reference.writeframes(audio.readframes(audio.getnframes()))
    with wave.open(str(tmp_path / "original.wav"), "rb") as audio:
        assert audio.readframes(audio.getnframes()) == original[44:]


def test_write_tags_failure_keeps_original_file_bytes(tmp_path, monkeypatch):
    import mutagen.wave

    path = tmp_path / "track.wav"
    original = wave_bytes()
    path.write_bytes(original)
    monkeypatch.setattr(mutagen.wave.WAVE, "save", lambda *_a, **_k: (_ for _ in ()).throw(OSError("write failed")))

    with pytest.raises(RuntimeError, match="write failed"):
        tag_parser.write_tags(str(path), title="new title")

    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".nedotify_tags_*"))


def test_ogg_cover_picture_block_returns_image_bytes(monkeypatch):
    from mutagen.flac import Picture

    image = b"\x89PNG\r\n\x1a\n" + b"image-bytes"
    picture = Picture()
    picture.type = 3
    picture.mime = "image/png"
    picture.data = image
    encoded = base64.b64encode(picture.write()).decode("ascii")

    class FakeOgg(dict):
        pass

    monkeypatch.setattr(tag_parser, "OggVorbis", lambda *_a, **_k: FakeOgg(metadata_block_picture=[encoded]))
    data, mime = tag_parser._extract_cover("track.ogg")

    assert data == image
    assert mime == "image/png"


def test_mp3_cover_prefers_front_image_and_sniffs_mime(monkeypatch):
    class Frame:
        def __init__(self, kind, data):
            self.type = kind
            self.data = data

    front = Frame(3, b"\xff\xd8\xfffront")
    back = Frame(4, b"\x89PNG\r\n\x1a\nback")

    class FakeID3:
        def __init__(self, *_a, **_k): pass
        def getall(self, _key): return [back, front]

    monkeypatch.setattr(tag_parser, "ID3", FakeID3)
    data, mime = tag_parser._extract_cover("track.mp3")

    assert data is front.data
    assert mime == "image/jpeg"


def test_junk_patterns_do_not_remove_words_containing_hd_or_hq(tmp_path, monkeypatch):
    path = tmp_path / "Ashdown.wav"
    path.write_bytes(wave_bytes())
    monkeypatch.setattr(tag_parser, "HAS_MUTAGEN", False)

    parsed = tag_parser.parse_tags(str(path))

    assert parsed["title"] == "Ashdown"
