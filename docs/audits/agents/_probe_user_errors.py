"""Scratch probe for core/user_errors.py::describe_error (read-only)."""
import sqlite3
import errno
import sys

sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

from core.user_errors import describe_error  # noqa: E402

try:
    import requests
    REQ = True
except Exception:
    REQ = False

try:
    from yt_dlp.utils import DownloadError
    YTDLP = True
except Exception:
    YTDLP = False

CASES = [
    ("sqlite3.OperationalError(locked)", sqlite3.OperationalError("database is locked")),
    ("sqlite3.IntegrityError", sqlite3.IntegrityError("UNIQUE constraint failed: tracks.title")),
    ("sqlite3.OperationalError(no db file)", sqlite3.OperationalError("unable to open database file")),
    ("sqlite3.OperationalError(disk io)", sqlite3.OperationalError("disk I/O error")),
    ("KeyError('title')", KeyError("title")),
    ("ValueError(path leak)", ValueError(r"Invalid audio file: C:\Users\Bob\AppData\Roaming\NeDotify\secret.mp3")),
    ("TypeError", TypeError("unsupported operand type(s) for +: 'int' and 'str'")),
    ("OSError(ENOSPC)", OSError(errno.ENOSPC, "No space left on device")),
    ("FileNotFoundError", FileNotFoundError(2, "No such file or directory")),
    ("PermissionError", PermissionError(13, "Permission denied")),
    ("RuntimeError(offline mode)", RuntimeError("Offline mode is enabled")),
    ("RuntimeError(random)", RuntimeError("boom 42")),
]

if REQ:
    CASES += [
        ("requests.ConnectionError", requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='api.example.com', port=443): Max retries exceeded with url: /search")),
        ("requests.Timeout", requests.exceptions.ReadTimeout("Read timed out. (read timeout=10)")),
        ("requests.HTTPError 404", requests.exceptions.HTTPError(
            "404 Client Error: Not Found for url: https://api.example.com/track")),
        ("requests.HTTPError 403", requests.exceptions.HTTPError(
            "403 Client Error: Forbidden for url: https://api.example.com/track")),
        ("requests.TooManyRedirects", requests.exceptions.TooManyRedirects("Exceeded 30 redirects.")),
    ]

if YTDLP:
    CASES += [
        ("yt-dlp DownloadError(unavailable)", DownloadError("ERROR: [youtube] abc: Video unavailable")),
        ("yt-dlp DownloadError(bot)", DownloadError("ERROR: Sign in to confirm you're not a bot")),
        ("yt-dlp DownloadError(private)", DownloadError("ERROR: [youtube] abc: Private video. Sign in if you've been granted access")),
        ("yt-dlp DownloadError(format)", DownloadError("ERROR: Requested format is not available. Use --list-formats")),
    ]

for label, exc in CASES:
    out = describe_error(exc, 'download')
    print(f"{label:38s} -> code={out['code']:14s} action={str(out['action']):8s} title={out['title']!r}")
    print(f"{'':38s}    message={out['message']!r}")

print()
print("--- operation title selection ---")
for op in ("download_track", "playback", "", "import_external_playlist"):
    print(repr(op), describe_error(RuntimeError("boom"), op))
