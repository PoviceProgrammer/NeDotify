"""Native analysis must support Windows user/library names in Cyrillic."""
import math
import struct
import wave

from services.lufs_scanner import analyze_lufs


def test_real_wav_under_unicode_path(tmp_path):
    path = tmp_path / 'Музыка проверка.wav'
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        audio.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(2 * math.pi * 440 * i / 44100)))
                                   for i in range(44100)))
    loudness, peak, error = analyze_lufs(str(path))
    assert error is None
    assert math.isfinite(loudness) and 0 < peak < 1
