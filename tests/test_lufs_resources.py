"""Background loudness analysis keeps PCM values and bounds decoded storage."""

from array import array
import threading
import weakref

import miniaudio
import numpy as np
import pyloudnorm
import pytest

from services.lufs_scanner import LufsScannerService, analyze_lufs


@pytest.mark.parametrize("channels", [1, 2, 5])
def test_analysis_streams_native_channels_without_whole_file_decode(monkeypatch, channels):
    from types import SimpleNamespace
    rate = 48000
    t = np.arange(rate, dtype=np.float32) / rate
    samples = np.repeat((np.sin(2*np.pi*440*t)*12000).astype(np.int16)[:, None], channels, axis=1)
    expected = samples.astype(np.float32) / 32768.0
    baseline = pyloudnorm.Meter(rate).integrated_loudness(expected[:,0] if channels == 1 else expected)
    monkeypatch.setattr(miniaudio, 'get_file_info', lambda path: SimpleNamespace(nchannels=channels, sample_rate=rate))
    def stream(path, **options):
        assert options['nchannels'] == channels and options['frames_to_read'] == rate
        for offset in range(0, rate, 1024):
            yield array('h', samples[offset:offset+1024].reshape(-1))
    monkeypatch.setattr(miniaudio, 'stream_file', stream)
    monkeypatch.setattr(miniaudio, 'decode_file', lambda *a, **k: pytest.fail('whole-file decode'))
    loudness, peak, error = analyze_lufs('test.wav')
    assert error is None
    assert loudness == pytest.approx(baseline, abs=2e-5)
    assert peak == float(np.max(np.abs(expected)))


def test_analysis_matches_existing_loudness_and_peak_for_local_wav(tmp_path, monkeypatch):
    import wave

    sample_rate = 44100
    timeline = np.arange(sample_rate, dtype=np.float64) / sample_rate
    samples = np.column_stack([
        np.sin(2 * np.pi * 440 * timeline) * 16000,
        np.sin(2 * np.pi * 880 * timeline) * 8000,
    ]).astype(np.int16)
    filepath = tmp_path / "stereo.wav"
    with wave.open(str(filepath), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())
    decoded = miniaudio.decode(filepath.read_bytes())
    baseline = np.array(decoded.samples, dtype=np.float32) / 32768.0
    baseline = baseline.reshape(-1, decoded.nchannels)
    expected_loudness = pyloudnorm.Meter(decoded.sample_rate).integrated_loudness(baseline)
    expected_peak = float(np.max(np.abs(baseline)))
    monkeypatch.setattr(miniaudio, "decode_file", lambda path: miniaudio.decode(filepath.read_bytes()))

    loudness, peak, error = analyze_lufs(str(filepath))

    assert error is None
    assert loudness == pytest.approx(expected_loudness, abs=2e-5)
    assert peak == expected_peak


def test_scanner_runs_one_background_analysis_at_a_time():
    scanner = LufsScannerService(object())
    started = threading.Event()
    release = threading.Event()
    second_started = threading.Event()

    def block_first():
        started.set()
        release.wait(timeout=5)

    first = scanner._pool.submit(block_first)
    try:
        assert started.wait(timeout=2)
        second = scanner._pool.submit(second_started.set)
        assert not second_started.wait(timeout=0.1)
        release.set()
        first.result(timeout=2)
        second.result(timeout=2)
        assert second_started.is_set()
    finally:
        release.set()
        scanner._pool.shutdown(wait=True, cancel_futures=True)


def test_streaming_analysis_yields_and_cancels_before_processing_more_pcm(monkeypatch):
    from types import SimpleNamespace
    cancel = threading.Event()
    closed, chunks = [], []
    monkeypatch.setattr(miniaudio, 'get_file_info', lambda path: SimpleNamespace(nchannels=1, sample_rate=48000))
    def stream(path, **options):
        try:
            for index in range(5):
                chunks.append(index)
                yield array('h', [100] * 48000)
        finally:
            closed.append(True)
    monkeypatch.setattr(miniaudio, 'stream_file', stream)
    loudness, peak, error = analyze_lufs('test.wav', cancel, yield_callback=cancel.set)
    assert loudness is None and peak is None and error == 'Analysis cancelled'
    assert chunks == [0] and closed == [True]
