"""A WebM audio file is not a Mutagen-supported container, not a corrupt file."""
import json
from types import SimpleNamespace

import pytest

from utils.audio_validation import audio_duration


@pytest.mark.parametrize('bad', [False, 'video', 'empty', 'truncated', 'failed', 'duration'])
@pytest.mark.parametrize('container', ['webm', 'm4a'])
def test_webm_probe_requires_audio_packets_and_valid_duration(tmp_path, monkeypatch, bad, container):
    file = tmp_path / ('audio.' + container)
    header = b'\x1a\x45\xdf\xa3' if container == 'webm' else b'\0\0\0\x18ftypisom\0\0\0\0'
    file.write_bytes(header + b'\0' * 8192)
    monkeypatch.setattr('mutagen.File', lambda path: None)
    monkeypatch.setattr('utils.audio_validation.ffprobe_path', lambda: 'ffprobe.exe')
    data = {'streams': [{'codec_type': 'video' if bad == 'video' else 'audio',
                         'nb_read_packets': '0' if bad == 'empty' else '100'}],
            'format': {'duration': 'nan' if bad == 'duration' else '180.2'}}
    def probe(args, **kwargs):
        assert '-count_packets' in args and kwargs['timeout'] == 12
        return SimpleNamespace(returncode=1 if bad == 'failed' else 0,
                               stderr='File ended prematurely' if bad == 'truncated' else '',
                               stdout=json.dumps(data))
    monkeypatch.setattr('utils.audio_validation.subprocess.run', probe)
    if bad:
        with pytest.raises(ValueError):
            audio_duration(str(file))
    else:
        assert audio_duration(str(file)) == 180.2


def test_invalid_file_is_not_sent_to_external_probe(tmp_path, monkeypatch):
    file = tmp_path / 'bad.webm'
    file.write_bytes(b'not audio')
    monkeypatch.setattr('utils.audio_validation.ffprobe_path', lambda: pytest.fail('Not an EBML container'))
    with pytest.raises(ValueError):
        audio_duration(str(file))


def test_real_fragmented_mp4_with_unsupported_mutagen_is_validated(tmp_path, monkeypatch):
    import shutil
    import subprocess
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        pytest.skip('Actual FFmpeg/FFprobe needed for fragmented MP4 integrity check')
    file = tmp_path / 'fragmented.m4a'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=2', '-c:a', 'aac',
                    '-movflags', 'empty_moov+frag_keyframe', str(file)],
                   check=True, capture_output=True, timeout=10)
    monkeypatch.setattr('mutagen.File', lambda path: None)
    monkeypatch.setattr('utils.audio_validation.ffprobe_path', lambda: ffprobe)
    assert 2 <= audio_duration(str(file)) <= 2.1
    from core.downloader import _downloaded_file_defect
    assert _downloaded_file_defect(str(file), expected_duration=2) == ''
