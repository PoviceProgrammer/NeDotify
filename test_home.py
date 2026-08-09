import os
import sys
from ytmusicapi import YTMusic

app_data = os.path.join(os.path.expanduser("~"), ".nedotify")
oauth_file = os.path.join(app_data, 'oauth.json')

if not os.path.exists(oauth_file):
    print("oauth.json not found")
    sys.exit(1)

try:
    from ytmusicapi.auth.oauth import OAuthCredentials
    import requests
    session = requests.Session()
    creds = OAuthCredentials('DUMMY_CLIENT_ID', 'DUMMY_CLIENT_SECRET', session)
    # Actually wait, I need the REAL client secret. Let me query DB.
    import sqlite3
    c = sqlite3.connect(os.path.join(app_data, "nedotify_storage.db"))
    cid = c.execute("SELECT value FROM settings WHERE key='auth.oauth_client_id'").fetchone()[0]
    csec = c.execute("SELECT value FROM settings WHERE key='auth.oauth_client_secret'").fetchone()[0]
    creds = OAuthCredentials(cid, csec, session)

    yt = YTMusic(auth=oauth_file, oauth_credentials=creds)
    print("Testing search()...")
    try:
        res = yt.search("hello")
        print("Success! Got search results:", len(res))
    except Exception as e:
        print("Exception type:", type(e))
        print("Exception vars:", vars(e))
        print("Exception type:", type(e))
        print("Exception vars:", vars(e))
        import traceback
        traceback.print_exc()
except Exception as e:
    print("Outer Error:", repr(e))
