from services.soundcloud_service import SoundCloudService
sc = SoundCloudService()

def cb(url, metadata):
    print("SUCCESS")
    print(url)
    print(metadata)
    
def err_cb(err):
    print("ERROR")
    print(err)

import time
sc.get_stream_url("https://soundcloud.com/postmalone/rockstar-feat-21-savage", callback=cb, error_callback=err_cb)
time.sleep(5)
