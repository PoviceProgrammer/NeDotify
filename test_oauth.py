import os
import sqlite3
import requests

app_data = os.path.join(os.path.expanduser("~"), ".nedotify")
db_path = os.path.join(app_data, "nedotify_storage.db")
c = sqlite3.connect(db_path)

row = c.execute("SELECT value FROM settings WHERE key='auth.oauth_client_id'").fetchone()
if not row:
    print("Client ID not found in DB")
    exit(1)

client_id = row[0].strip()
print(f"Testing Client ID: {client_id}")

OAUTH_CODE_URL = "https://oauth2.googleapis.com/device/code"
OAUTH_SCOPE = "https://www.googleapis.com/auth/youtube"
OAUTH_USER_AGENT = "ytmusicapi"

session = requests.Session()
data = {"scope": OAUTH_SCOPE, "client_id": client_id}
headers = {"User-Agent": OAUTH_USER_AGENT}

response = session.post(OAUTH_CODE_URL, data=data, headers=headers)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
