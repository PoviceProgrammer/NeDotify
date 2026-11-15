"""Verify the real YouTube audio transfer used by strategy selection.

Uses the application's downloader, anonymous access and a temporary directory.
No library/history, configured cookies, explicit proxy or user files are used.
The VPN remains under the user's control: a TUN VPN still carries this traffic.
"""
import tempfile
import time


def probe_youtube_audio(cancelled):
    from core.download_transfer import DownloadContext
    from services.youtube_service import YouTubeService

    deadline = time.monotonic() + 30

    def checkpoint():
        if cancelled() or time.monotonic() >= deadline:
            raise TimeoutError('YouTube strategy probe cancelled or timed out')

    source_id = 'dQw4w9WgXcQ'
    context = DownloadContext('probe', 'youtube', source_id, checkpoint, lambda done, total: None, probe=True)
    try:
        context.checkpoint()
        provider = YouTubeService(settings=None)
        with tempfile.TemporaryDirectory(prefix='nedotify-zapret-probe-') as directory:
            # A stable public recording. The provider checks the downloaded
            # container/audio before returning its path, not just HTTP 200.
            provider.download_audio_sync(source_id, directory, download_context=context)
            context.checkpoint()
        return True
    except Exception:
        return False
