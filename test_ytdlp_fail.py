import yt_dlp
opts = {
    'quiet': False,
    'format': 'nonexistent_format',
    'ignoreerrors': True
}
try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info("https://www.youtube.com/watch?v=_qq6aGkHKHc", download=False)
        print("Success, url is:", info.get('url') if info else 'None')
except Exception as e:
    print("Error:", e)
