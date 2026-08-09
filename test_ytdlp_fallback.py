import yt_dlp
opts = {
    'quiet': False,
    'format': 'bestaudio/best',
    'youtube_include_dash_manifest': False,
    'youtube_include_hls_manifest': False,
    'extractor_args': {'youtube': ['player_client=ios,tv,web']},
    'ignoreerrors': True
}
try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info("https://www.youtube.com/watch?v=_qq6aGkHKHc", download=False)
        print("Success:", info.get('format_id') if info else 'None')
except Exception as e:
    print("Error:", e)
