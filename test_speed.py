import time
from services.youtube_service import YouTubeService
import logging
logging.basicConfig(level=logging.DEBUG)

def test_yt():
    yt = YouTubeService()
    start = time.time()
    print("Extracting...")
    def on_success(url, meta):
        print(f"Success in {time.time()-start:.2f}s! URL length: {len(url)}")
    def on_error(err):
        print(f"Error in {time.time()-start:.2f}s: {err}")
    yt.get_stream_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ", callback=on_success, error_callback=on_error)

if __name__ == "__main__":
    test_yt()
    time.sleep(10) # wait for threads
