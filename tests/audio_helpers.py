"""Small valid audio fixtures; media integrity tests must not use fake ID3."""
import io
import wave


def wave_bytes(size=16384):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0' * (size - 44))
    return output.getvalue()
