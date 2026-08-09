import os
import sqlite3
from pathlib import Path

# Поиск всех .db файлов в проекте и типичных местах
search_paths = [
    Path.cwd(),
    Path.cwd() / 'core',
    Path.cwd() / 'data',
    Path.home() / 'AppData' / 'Roaming' / 'NeDotify',
    Path.home() / 'AppData' / 'Local' / 'NeDotify',
    Path.home() / '.nedotify',
]

print("Searching for .db files...\n")
for base in search_paths:
    if base.exists():
        for db_file in base.rglob('*.db'):
            print(f"Found: {db_file}")
            try:
                conn = sqlite3.connect(str(db_file))
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                print(f"  Tables: {tables}")
                
                if 'tracks' in tables:
                    cursor.execute("SELECT COUNT(*) FROM tracks WHERE is_favorite = 1")
                    print(f"  Favorites: {cursor.fetchone()[0]}")
                    cursor.execute("SELECT COUNT(*) FROM tracks WHERE is_downloaded = 1")
                    print(f"  Downloaded: {cursor.fetchone()[0]}")
                
                conn.close()
            except Exception as e:
                print(f"  Error: {e}")
            print()