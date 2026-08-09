import os
import sys
import time
import urllib.request
from core.app import AppCore

def main():
    app = AppCore()
    tracks = app.db.get_all_tracks()
    
    # find a yandex track
    yandex_track = next(t for t in tracks if t['source'] == 'yandex')
    print(f"Testing Yandex track: {yandex_track['title']}")
    
    url = app.proxy.get_proxy_url(yandex_track['source'], yandex_track['source_id'], yandex_track.get('url'), track_id=yandex_track['id'])
    print("Proxy URL:", url)
    
    try:
        req = urllib.request.Request(url)
        req.add_header('Range', 'bytes=0-')
        resp = urllib.request.urlopen(req)
        print("Response Code:", resp.getcode())
        print("Headers:", resp.headers)
        data = resp.read(1024)
        print("Got data bytes:", len(data))
    except Exception as e:
        print("Error fetching stream:", e)
        if hasattr(e, 'read'):
            print("Error body:", e.read().decode('utf-8', errors='ignore'))
    
    app.cleanup()

if __name__ == '__main__':
    main()
