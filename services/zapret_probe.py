"""Verify the real YouTube audio transfer used by strategy selection.

Uses the application's downloader, anonymous access and a temporary directory.
No library/history, configured cookies, explicit proxy or user files are used.
The VPN remains under the user's control: a TUN VPN still carries this traffic.
"""
import tempfile
import time


def probe_youtube_audio(cancelled):
    from services.youtube_service import YouTubeService

    deadline = time.monotonic() + 30

    class ProbeContext:
        def checkpoint(self):
            if cancelled() or time.monotonic() >= deadline:
                raise TimeoutError('YouTube strategy probe cancelled or timed out')

        def ydl_options(self, directory):
            return {'socket_timeout': 4, 'retries': 0, 'fragment_retries': 0,
                    'extractor_retries': 0, 'proxy': '', 'cachedir': False,
                    'progress_hooks': [lambda data: self.checkpoint()]}

    context = ProbeContext()
    try:
        context.checkpoint()
        provider = YouTubeService(settings=None)
        with tempfile.TemporaryDirectory(prefix='nedotify-zapret-probe-') as directory:
            # A stable public recording. The provider checks the downloaded
            # container/audio before returning its path, not just HTTP 200.
            provider.download_audio_sync('dQw4w9WgXcQ', directory, download_context=context)
            context.checkpoint()
        return True
    except Exception:
        return False
