# Investigation & Handoff Report — AURA Music Recommendation Engine

**Explorer:** Explorer M1  
**Working Directory:** `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m1`  
**Project Root:** `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music`  
**Date:** 2026-08-03  

---

## 1. Observation

### 1.1 Local SQLite Database Schema & User Taste Profile (`core/database.py`)

#### Database Schemas
The database manager (`DatabaseManager` in `core/database.py`) uses SQLite with thread-local connections (lines 29-39) and WAL mode.

1. **`tracks` table** (Lines 50-78, 177-183, 286-289):
   - `id`: `INTEGER PRIMARY KEY AUTOINCREMENT`
   - `title`: `TEXT NOT NULL`
   - `artist`: `TEXT DEFAULT 'Unknown Artist'`
   - `album`: `TEXT DEFAULT 'Unknown Album'`
   - `duration`: `REAL DEFAULT 0` (seconds)
   - `file_path`: `TEXT`
   - `source`: `TEXT DEFAULT 'local'` (e.g. `'youtube'`, `'soundcloud'`, `'local'`, `'yandex'`)
   - `source_id`: `TEXT` (platform-specific video ID / track ID)
   - `source_url`: `TEXT`
   - `cover_path`: `TEXT`
   - `cover_url`: `TEXT`
   - `bitrate`: `INTEGER DEFAULT 0`
   - `sample_rate`: `INTEGER DEFAULT 0`
   - `format`: `TEXT`
   - `file_size`: `INTEGER DEFAULT 0`
   - `loudness_lufs`: `REAL`
   - `genre`: `TEXT`
   - `year`: `INTEGER`
   - `track_number`: `INTEGER`
   - `added_at`: `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
   - `last_played`: `TIMESTAMP`
   - `play_count`: `INTEGER DEFAULT 0`
   - `is_favorite`: `INTEGER DEFAULT 0`
   - `is_cached`: `INTEGER DEFAULT 0`
   - `metadata_json`: `TEXT`
   - `is_downloaded`: `INTEGER DEFAULT 0`
   - `lufs`: `REAL DEFAULT NULL`
   - `peak_volume`: `REAL DEFAULT NULL`

2. **`history` table** (Lines 108-117):
   - `id`: `INTEGER PRIMARY KEY AUTOINCREMENT`
   - `track_id`: `INTEGER NOT NULL` (Foreign Key -> `tracks.id`)
   - `played_at`: `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
   - `duration_listened`: `REAL DEFAULT 0`
   - `completed`: `INTEGER DEFAULT 0`

3. **`playlists` & `playlist_tracks` tables** (Lines 81-105):
   - `playlists`: `id`, `name`, `description`, `cover_path`, `created_at`, `updated_at`, `is_smart`, `smart_rules_json`
   - `playlist_tracks`: `id`, `playlist_id`, `track_id`, `position`, `added_at`

4. **`settings` table** (Lines 120-127):
   - `key`: `TEXT PRIMARY KEY`
   - `value`: `TEXT`
   - `category`: `TEXT DEFAULT 'general'` (includes category `'personalization'` for onboarding data: `explicit_artists`, `favorite_genres`, `preferred_moods`)
   - `updated_at`: `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`

5. **`stream_cache` table** (Lines 131-146):
   - `id`: `INTEGER PRIMARY KEY AUTOINCREMENT`
   - `source`: `TEXT NOT NULL`
   - `source_id`: `TEXT NOT NULL`
   - `stream_url`: `TEXT`
   - `cached_file_path`: `TEXT`
   - `title`: `TEXT`, `artist`: `TEXT`, `cover_url`: `TEXT`, `duration`: `REAL`
   - `metadata_json`: `TEXT`
   - `cached_at`: `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
   - `expires_at`: `TIMESTAMP`
   - `UNIQUE(source, source_id)`

6. **`listening_stats` table** (Lines 158-165):
   - `id`: `INTEGER PRIMARY KEY AUTOINCREMENT`
   - `duration_ms`: `INTEGER NOT NULL`
   - `recorded_at`: `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`

7. **`tracks_fts` FTS5 table** (Lines 240-267):
   - Virtual full-text search table indexed on `title`, `artist`, `album`, `genre` with automatic triggers (`tracks_ai`, `tracks_ad`, `tracks_au`).

#### Existing DB Taste Profile Methods
- `get_top_artists(limit=10)` (Lines 628-640):
  ```sql
  SELECT t.artist, t.cover_url, t.cover_path
  FROM history h
  JOIN tracks t ON h.track_id = t.id
  WHERE t.artist IS NOT NULL AND t.artist != 'Unknown Artist' AND t.artist != ''
  GROUP BY t.artist
  ORDER BY MAX(h.played_at) DESC
  LIMIT ?
  ```
- `get_most_played(limit=20)` (Lines 617-626):
  ```sql
  SELECT * FROM tracks WHERE play_count > 0 ORDER BY play_count DESC LIMIT ?
  ```
- `get_history(limit=50)` (Lines 604-615):
  ```sql
  SELECT h.*, t.title, t.artist, t.album, t.cover_path, t.cover_url, t.duration, t.source, t.source_id, t.file_path, t.source_url
  FROM history h
  JOIN tracks t ON h.track_id = t.id
  ORDER BY h.played_at DESC LIMIT ?
  ```
- `get_favorite_tracks()` (Lines 418-422):
  ```sql
  SELECT * FROM tracks WHERE is_favorite = 1 ORDER BY added_at DESC
  ```
- `get_analytics_summary()` (Lines 642-677):
  - Returns dictionary with `total_time_seconds`, `top_tracks` (grouped by track id, count of history plays DESC), and `top_artists` (grouped by artist, count of history plays DESC).

#### Exact SQL Queries to Build a Comprehensive User Taste Profile
To eliminate external dependencies and construct a local User Taste Profile:
1. **Top Artists (weighted by plays & recency):**
   ```sql
   SELECT t.artist, COUNT(h.id) AS play_count, MAX(h.played_at) AS last_played
   FROM history h
   JOIN tracks t ON h.track_id = t.id
   WHERE t.artist IS NOT NULL AND t.artist NOT IN ('', 'Unknown Artist', 'Unknown')
   GROUP BY LOWER(t.artist)
   ORDER BY play_count DESC, last_played DESC
   LIMIT 15;
   ```
2. **Top Tracks (frequently played):**
   ```sql
   SELECT t.id, t.title, t.artist, t.play_count, t.source, t.source_id, t.cover_url
   FROM tracks t
   WHERE t.play_count > 0
   ORDER BY t.play_count DESC, t.last_played DESC
   LIMIT 20;
   ```
3. **Recent Listening History:**
   ```sql
   SELECT t.id, t.title, t.artist, h.played_at, t.source, t.source_id
   FROM history h
   JOIN tracks t ON h.track_id = t.id
   ORDER BY h.played_at DESC
   LIMIT 30;
   ```
4. **Genre Distribution:**
   ```sql
   SELECT t.genre, COUNT(h.id) AS play_count
   FROM history h
   JOIN tracks t ON h.track_id = t.id
   WHERE t.genre IS NOT NULL AND t.genre != ''
   GROUP BY LOWER(t.genre)
   ORDER BY play_count DESC;
   ```
5. **Time-of-Day Listening Patterns:**
   ```sql
   SELECT 
     CASE 
       WHEN CAST(strftime('%H', h.played_at) AS INTEGER) BETWEEN 5 AND 11 THEN 'morning'
       WHEN CAST(strftime('%H', h.played_at) AS INTEGER) BETWEEN 12 AND 17 THEN 'afternoon'
       WHEN CAST(strftime('%H', h.played_at) AS INTEGER) BETWEEN 18 AND 22 THEN 'evening'
       ELSE 'night'
     END AS time_slot,
     COUNT(h.id) AS count
   FROM history h
   GROUP BY time_slot;
   ```

---

### 1.2 Recommendation Services & YTMusic Call Locations

#### Files Analyzed
- `services/recommendation_service.py` (1001 lines)
- `core/services/recommendation.py` (234 lines)
- `core/api.py` (1961 lines)

#### All Recommendation Methods & Signatures

| Service Class / Module | Method Signature | Purpose & Arguments | Return Type |
|---|---|---|---|
| `RecommendationService` | `_fetch_recommendations(seed_track: dict, max_results: int)` | Fetches recommendations for a seed track. | `List[Dict]` (track dicts) |
| `RecommendationService` | `get_recommendations(seed_track: dict, max_results=20, callback=None, error_callback=None)` | Asynchronous wrapper around `_fetch_recommendations`. | `None` (emits via callback) |
| `RecommendationService` | `get_authentic_home(limit=5, callback=None, error_callback=None)` | Calls `ytmusic.get_home()`. | `None` (emits sections) |
| `RecommendationService` | `get_yt_playlist_tracks(playlist_id: str, limit=50, callback=None, error_callback=None)` | Fetches tracks from YT Music album/playlist. | `None` (emits tracks) |
| `RecommendationService` | `get_charts(region="US", max_results=20, callback=None, error_callback=None)` | Fetches top charts via YT Music. | `None` (emits tracks) |
| `RecommendationService` | `get_feed(history: List[dict], personalization: dict=None, max_results=20, callback=None, error_callback=None)` | Blends history & onboarding preferences into recommendation feed. | `None` (emits tracks) |
| `RecommendationService` | `get_custom_artists(history: List[dict], personalization: dict=None, max_results=15, callback=None)` | Blends history & onboarding to fetch artist recommendations. | `None` (emits artist dicts) |
| `RecommendationService` | `get_releases(favorite_artists: List[str]=None, max_results=10, callback=None, error_callback=None)` | Fetches new releases from YT Music explore feed. | `None` (emits tracks) |
| `RecommendationService` | `_generate_deep_mix(yt, artist_name, source_id=None)` | Generates 20% hits, 40% deep cuts, 40% related artists mix. | `Dict` (custom_playlist) |
| `RecommendationService` | `_generate_mood_mix(yt, personalization)` | Generates mood playlist mix via search. | `Dict` (custom_playlist) |
| `RecommendationService` | `get_mixes(history, personalization, max_results=10, callback=None, error_callback=None)` | Fetches curated mixes for target artists/moods. | `None` (emits mixes list) |
| `RecommendationService` | `get_smart_home_feed(history, personalization, callback=None, error_callback=None)` | Generates 4 parallel home sections (time_vibe, custom_mixes, releases, history). | `None` (emits `{greeting, sections}`) |
| `RecommendationEngine` | `generate_all()` | Local audio feature heuristic recommendation engine (`core/services/recommendation.py`). | `Dict` (mixes, recs, charts, spotlights) |
| `RecommendationEngine` | `build_real_engine(db, personalization=None)` | Factory function linking DB data to local `RecommendationEngine`. | `RecommendationEngine` |

#### Exact Lines Calling `ytmusicapi` (`YTMusic`)

1. **`services/recommendation_service.py`**:
   - Line 130: `watch = self._safe_call(watch_fn, videoId=source_id)` -> `YTMusic.get_watch_playlist`
   - Line 169: `deep_mix = self._generate_deep_mix(ytmusic, artist, source_id=source_id)` -> calls YTMusic artist search & album methods
   - Line 202: `s_res = self._safe_call(ytmusic.search, query=f"{s_name} top tracks", filter="songs", limit=3)` -> `YTMusic.search`
   - Line 337: `raw_home = yt.get_home(limit=limit)` -> `YTMusic.get_home`
   - Line 342: `raw_home = yt_fallback.get_home(limit=limit)` -> `YTMusic.get_home`
   - Line 421: `pl = self._safe_call(yt.get_album, playlist_id)` -> `YTMusic.get_album`
   - Line 423: `pl = self._safe_call(yt.get_playlist, playlist_id, limit=limit)` -> `YTMusic.get_playlist`
   - Line 453: `charts = yt.get_charts(country=region)` -> `YTMusic.get_charts`
   - Line 460: `pl = self._safe_call(yt.get_playlist, pl_id)` -> `YTMusic.get_playlist`
   - Line 543: `search_res = yt.search(query, filter="playlists", limit=2)` -> `YTMusic.search`
   - Line 548: `pl = self._safe_call(yt.get_playlist, pl_id, limit=max_results)` -> `YTMusic.get_playlist`
   - Line 594: `res = self._cached_api_call(f"artist_search_{a}", yt.search, a, filter="artists", limit=1)` -> `YTMusic.search`
   - Line 603: `res = self._cached_api_call(f"artist_search_{seed}", yt.search, seed, filter="artists", limit=1)` -> `YTMusic.search`
   - Line 605: `artist_data = self._cached_api_call(f"artist_data_{res[0]['browseId']}", yt.get_artist, res[0]['browseId'])` -> `YTMusic.get_artist`
   - Line 627: `explore = yt.get_explore()` -> `YTMusic.get_explore`
   - Line 645: `pl = self._safe_call(yt.get_playlist, pl_id)` -> `YTMusic.get_playlist`
   - Line 672: `search_res = self._cached_api_call(cache_key, yt.search, artist_name, filter="artists", limit=1)` -> `YTMusic.search`
   - Line 678: `artist_data = self._cached_api_call(artist_cache_key, yt.get_artist, browse_id)` -> `YTMusic.get_artist`
   - Line 686: `songs_res = self._cached_api_call(songs_cache, yt.get_watch_playlist, playlistId=artist_data['songs']['browseId'], limit=15)` -> `YTMusic.get_watch_playlist`
   - Line 700: `alb_data = self._cached_api_call(alb_cache, yt.get_album, alb['browseId'])` -> `YTMusic.get_album`
   - Line 716: `rel_data = self._cached_api_call(rel_cache, yt.get_artist, rel['browseId'])` -> `YTMusic.get_artist`
   - Line 792: `search_res = self._cached_api_call(cache_key, yt.search, query, filter="playlists", limit=5)` -> `YTMusic.search`
   - Line 802: `pl_data = self._cached_api_call(pl_cache, yt.get_playlist, pl_id, limit=30)` -> `YTMusic.get_playlist`
   - Line 924: `explore = yt.get_explore()` -> `YTMusic.get_explore`
   - Line 930: `pl = self._safe_call(yt.get_playlist, pl_id)` -> `YTMusic.get_playlist`
   - Line 939: `search_res = self._cached_api_call(f"mood_{mood_query}", yt.search, mood_query, filter="playlists", limit=2)` -> `YTMusic.search`
   - Line 944: `pl = self._safe_call(yt.get_playlist, pl_id, limit=10)` -> `YTMusic.get_playlist`

2. **`core/api.py`**:
   - Line 535: `from core.services.recommendation import build_real_engine` (in `_on_queue_end` autoplay)
   - Line 1272: `search_res = yt.search(f"{mood} playlist", filter="playlists", limit=10)` -> `YTMusic.search` (in `get_mood_playlists`)
   - Line 1492: `pl_data = self._core.recommendations._safe_call(yt.get_playlist, pl_id_str, limit=200)` -> `YTMusic.get_playlist` (in `import_external_playlist`)
   - Line 1662: `from core.services.recommendation import build_real_engine` (in `get_authentic_home_feed`)

---

### 1.3 Frontend Interface Expectations (`ui/web_new/js/main.js`, `home.js`, `events.js`)

#### Events and JSON Structure Expected by UI

1. **`smart_home_ready` / `authentic_home_ready` Event Payload**:
   The primary feed renderer `renderAuthenticHome(sections)` in `ui/web_new/js/home.js` (lines 171-286) expects:
   ```json
   {
     "greeting": "Доброе утро, User",
     "sections": [
       {
         "title": "Утренний вайб",
         "items": [
           {
             "type": "track",
             "title": "Song Name",
             "artist": "Artist Name",
             "cover_url": "https://...",
             "source": "youtube",
             "source_id": "video_id_123",
             "source_url": "https://www.youtube.com/watch?v=video_id_123",
             "duration": 210
           },
           {
             "type": "custom_playlist",
             "title": "Микс: The Weeknd",
             "artist": "Специально для вас",
             "cover_url": "https://...",
             "tracks": [
               {
                 "title": "Blinding Lights",
                 "artist": "The Weeknd",
                 "cover_url": "https://...",
                 "source": "youtube",
                 "source_id": "4NRXx6U8ABQ",
                 "source_url": "https://www.youtube.com/watch?v=4NRXx6U8ABQ",
                 "duration": 200
               }
             ]
           }
         ]
       }
     ]
   }
   ```

2. **Standard Section Events (`feed_ready`, `recommendations_ready`, `releases_ready`, `mixes_ready`, `popular_results`)**:
   - `feed_ready` & `recommendations_ready`: Array of track dictionaries.
   - `releases_ready`: Array of track dictionaries.
   - `mixes_ready`: Array of track or `custom_playlist` dictionaries.
   - `popular_results`: Payload `{ "tracks": [ ...track dicts... ] }`.
   - `artists_ready`: Array of `{ "artist": "Artist Name", "cover_url": "https://..." }`.

3. **Required Track Dictionary Keys across UI**:
   Every track object passed to the UI player, queue, context menus, or cards MUST contain:
   - `title` (string)
   - `artist` (string)
   - `cover_url` (string: HTTP image URL or local file URI)
   - `source` (string: `'youtube'`, `'soundcloud'`, `'local'`, `'yandex'`)
   - `source_id` (string: unique identifier on source platform)
   - `source_url` (string: URL to track page)
   - `duration` (number: duration in seconds)
   - `id` (int/string: database row ID when present)
   - `is_favorite` (boolean)
   - `is_downloaded` (boolean)

---

### 1.4 Audio Provider Track Resolution (`services/soundcloud_service.py` & `services/youtube_service.py`)

#### SoundCloud Track Resolution (`SoundCloudService`)
- **Query Search**: `search(query, max_results, callback, error_callback)` (lines 162-256):
  1. Direct REST API v2: `https://api-v2.soundcloud.com/search/tracks?q={encoded}&client_id={cid}&limit={max_results}`. Scrapes or rotates valid `client_id`. Returns track items formatted into track dictionaries with `source: 'soundcloud'`, `source_id: str(id)`, `cover_url: artwork.replace('large.jpg', 't500x500.jpg')`.
  2. Fallback: `scsearch{max_results}:{query}` via `yt_dlp`.
  3. Ultimate fallback: routes query to `YouTubeService.search()`, remapping `source` to `'soundcloud'`.
- **Stream Resolution**: `get_stream_url(track_url, callback, error_callback)` (lines 258-415):
  1. Direct REST API v2: `https://api-v2.soundcloud.com/tracks/{track_id}?client_id={cid}`, fetches media transcodings, selecting progressive MP3 URLs over HLS `.m3u8` streams.
  2. Fallback: `yt_dlp.YoutubeDL().extract_info()`.
  3. Preview/Missing Fallback: if SoundCloud returns a 30-second preview, automatically queries YouTube for `f"{search_artist} - {search_title}"` and extracts YouTube audio stream.

#### YouTube Track Resolution (`YouTubeService`)
- **Query Search**: `search(query, max_results, callback, error_callback)` (lines 163-246):
  - Queries `self._ytmusic.search(query, filter=None, limit=max_results)`. Filters for resultTypes `'song'` or `'video'`. Formats results into track dicts with `source: 'youtube'`, `source_id: vid`, `source_url: f"https://www.youtube.com/watch?v={vid}"`.
- **Stream Resolution**: `get_stream_url(video_url, callback, error_callback, quality)` (lines 296-395):
  - Uses `yt_dlp.YoutubeDL()` with `format: 'bestaudio/best'`, age-gate bypass via multiple browser cookies, IPv4 forcing (`source_address: '0.0.0.0'`). Returns direct HTTPS audio stream URL + metadata.

#### Playback Resolution Flow in Backend (`core/api.py:_resolve_track`)
When a user clicks play on any recommended track (lines 551-657):
1. Checks SQLite `stream_cache` table for cached local file path or non-expired stream URL.
2. If cache miss, routes based on `track.source`:
   - `'youtube'`: `self._core.youtube.get_stream_url(url, callback)`
   - `'soundcloud'`: `self._core.soundcloud.get_stream_url(url, callback)`
3. On resolution error: triggers fallback search `query = f"{track_title} {track_artist} audio"` via `self._core.youtube.search`, retrieves top result, updates track's `source_id` & `source_url`, and extracts stream.

---

### 1.5 Last.fm API Specification & Endpoint Details

#### Base Configuration & Open Endpoints
- **Base URL**: `https://ws.audioscrobbler.com/2.0/`
- **Format**: `format=json`
- **Default API Key in Codebase**: `b25b959554ed76058ac220b7b2e0a026` (found in `services/recommendation_service.py:190`)
- **Fallback API Keys**:
  - Key 1: `b25b959554ed76058ac220b7b2e0a026`
  - Key 2: `2c8038f0d5757d5f0426315220c8f133`
  - Key 3: `4cb0edd8ea11e4f641723f031a770edc`

#### Required Open Endpoints Specification

1. **`artist.getSimilar`**:
   - Request: `GET https://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist={artist}&limit={limit}&api_key={api_key}&format=json&autocorrect=1`
   - Response Path: `similarartists.artist[]` -> `{ name, match, mbid, url, image[] }`
   - Usage: Seed artist graph expansion for similar artists recommendations & artist radio.

2. **`artist.getTopTracks`**:
   - Request: `GET https://ws.audioscrobbler.com/2.0/?method=artist.gettoptracks&artist={artist}&limit={limit}&api_key={api_key}&format=json&autocorrect=1`
   - Response Path: `toptracks.track[]` -> `{ name, playcount, listeners, artist: { name }, image[] }`
   - Usage: Retrieve top hit tracks for an artist when building Deep Mixes or Artist Radio.

3. **`artist.getTopTags`**:
   - Request: `GET https://ws.audioscrobbler.com/2.0/?method=artist.gettoptags&artist={artist}&api_key={api_key}&format=json&autocorrect=1`
   - Response Path: `toptags.tag[]` -> `{ name, count, url }`
   - Usage: Derive genre and mood tags for artists in user history to build local taste profile tag vectors.

4. **`track.getSimilar`**:
   - Request: `GET https://ws.audioscrobbler.com/2.0/?method=track.getsimilar&artist={artist}&track={track}&limit={limit}&api_key={api_key}&format=json&autocorrect=1`
   - Response Path: `similartracks.track[]` -> `{ name, playcount, match, duration, artist: { name }, image[] }`
   - Usage: Track-level seed recommendation ("Because you listened to Track X").

5. **`chart.getTopTracks`**:
   - Request: `GET https://ws.audioscrobbler.com/2.0/?method=chart.gettoptracks&limit={limit}&api_key={api_key}&format=json`
   - Response Path: `tracks.track[]` -> `{ name, playcount, listeners, artist: { name }, image[] }`
   - Usage: Global popular tracks chart for recommendations feed fallback.

6. **`chart.getTopArtists`**:
   - Request: `GET https://ws.audioscrobbler.com/2.0/?method=chart.gettopartists&limit={limit}&api_key={api_key}&format=json`
   - Response Path: `artists.artist[]` -> `{ name, playcount, listeners, url, image[] }`
   - Usage: Global top artists chart for discovering trending artists.

#### Caching Strategy & Rate Limit Mitigation
- **Cache Table in SQLite**: Store raw Last.fm JSON responses in SQLite `stream_cache` or dedicated `lastfm_cache` table.
- **TTL Policies**:
  - `artist.getSimilar`, `artist.getTopTracks`, `artist.getTopTags`: 7 days (604,800s).
  - `track.getSimilar`: 7 days (604,800s).
  - `chart.getTopTracks`, `chart.getTopArtists`: 24 hours (86,400s).
- **Key Rotation**: Maintain array of API keys. If Last.fm returns HTTP 429, 403, or connection failure, automatically rotate to the next key.

---

## 2. Logic Chain

1. **Local Taste Profile Generation**:
   - SQLite `history` and `tracks` tables store exact play timestamps (`played_at`), listen durations (`duration_listened`), total play counts (`play_count`), and track metadata (`artist`, `genre`).
   - By querying SQL aggregates (Top Artists by play count/recency, Top Tracks by play count, Recent History, Genre distribution, Time-of-day listening patterns), we build an in-memory `UserTasteProfile` without any dependency on YTMusic API.

2. **Last.fm Generative Recommendation Engine**:
   - Given a `UserTasteProfile`:
     - Top artists from user history are used as seed inputs to `artist.getSimilar` -> retrieves similar artists.
     - Top tracks from user history are used as seed inputs to `track.getSimilar` -> retrieves similar track names & artists.
     - Top artists are queried via `artist.getTopTracks` -> retrieves deep cut hits.
     - Global fallback uses `chart.getTopTracks` and `chart.getTopArtists`.
   - The resulting recommendations consist of track metadata pairs: `(title, artist)`.

3. **Track Resolution Pipeline (Last.fm -> Playable Track Dict)**:
   - For each recommended `(title, artist)` pair:
     1. **Step 1 (Local DB Lookup)**: Query `tracks` table by `LOWER(title)` and `LOWER(artist)`. If match exists, use existing track dictionary (with local file path or existing `source_id`).
     2. **Step 2 (SoundCloud Resolution)**: Call `SoundCloudService.search(f"{title} {artist}")`. If a matching track is found, format into track dictionary with `source: 'soundcloud'`, `source_id`, `cover_url`, `source_url`.
     3. **Step 3 (YouTube Resolution Fallback)**: If SoundCloud search returns no result or fails, call `YouTubeService.search(f"{artist} - {title}")` or use `yt-dlp` `ytsearch1:`. Format result into track dictionary with `source: 'youtube'`, `source_id`, `cover_url`, `source_url`.
     4. **Step 4 (Stream Cache)**: Pass track dictionary to UI. When played, `_resolve_track` resolves the direct stream URL and caches it in SQLite `stream_cache`.

4. **Frontend Compatibility**:
   - The UI expects sections with titles (e.g. "Утренний вайб", "Микс: The Weeknd", "Новые релизы") emitted via `smart_home_ready` or `authentic_home_ready`.
   - By wrapping resolved tracks into section objects containing `type: "track"`, `type: "playlist"`, or `type: "custom_playlist"`, the existing UI in `ui/web_new/js/home.js` will render cards seamlessly without requiring UI changes.

---

## 3. Caveats

1. **Last.fm Image Deprecation**:
   - Last.fm API image URLs in `image[]` arrays are frequently blank or returning placeholders due to licensing changes. Cover art must be sourced from SoundCloud track artwork (`artwork_url.replace('large', 't500x500')`) or YouTube thumbnails (`https://img.youtube.com/vi/{source_id}/hqdefault.jpg`).
2. **SoundCloud API Rate Limits & Client ID Expiration**:
   - SoundCloud public `client_id`s scraped from soundcloud.com web app bundle scripts can expire. The implementation must include automatic scraping fallback and fallback to YouTube search if SoundCloud stream resolution fails.
3. **No Direct Code Modifications Undertaken**:
   - As an Explorer agent operating under read-only investigation rules, no application source code files outside `.agents/explorer_m1/` were altered.

---

## 4. Conclusion

Replacing YTMusic generative recommendations with Last.fm + local DB taste profile + SoundCloud/YouTube track resolution is fully feasible and directly compatible with the current architecture.

### Implementation Architecture Summary:
1. **Taste Profile**: Query local SQLite `history` and `tracks` tables for top artists, top tracks, recent history, genre distribution, and time-of-day listening patterns.
2. **Recommendation Engine**: Call Last.fm open API endpoints (`artist.getSimilar`, `artist.getTopTracks`, `artist.getTopTags`, `track.getSimilar`, `chart.getTopTracks`, `chart.getTopArtists`) using API key rotation and SQLite response caching.
3. **Track Resolution**: Map `(title, artist)` recommendations to playable track dictionaries via SoundCloud REST API / `scsearch`, falling back to YouTube search / `ytsearch`.
4. **UI Delivery**: Emit `{ greeting, sections }` via `smart_home_ready` and `authentic_home_ready` events matching exact JS expectations in `ui/web_new/js/home.js`.

---

## 5. Verification Method

To verify these findings independently:
1. **Inspect DB Schema & Queries**:
   - Read `core/database.py` lines 50-183 for `tracks`, `history`, `stream_cache` table schemas.
   - Read lines 604-677 for existing history and analytics queries.
2. **Inspect Recommendation Service Calls**:
   - View `services/recommendation_service.py` lines 130, 202, 337, 421, 453, 543, 627, 672, 792, 924 for YTMusic call locations.
3. **Inspect Frontend UI Contracts**:
   - View `ui/web_new/js/home.js` lines 171-286 (`renderAuthenticHome`) and 397-404 (`createFeedCard`) for expected JSON keys.
4. **Inspect Provider Track Resolution**:
   - View `services/soundcloud_service.py` lines 162-256 (`search`) and 258-415 (`get_stream_url`).
   - View `services/youtube_service.py` lines 163-246 (`search`) and 296-395 (`get_stream_url`).
