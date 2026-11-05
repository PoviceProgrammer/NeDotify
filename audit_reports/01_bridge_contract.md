# Audit Report 01: JS <-> Python Bridge Contract Audit

**Project**: AURA Music (Linux)  
**Target Frontend**: `ui/web_new_v2/` (`js/`)  
**Target Backend Bridge**: `core/api.py` (`class AppApi`)  
**Date**: 2026-09-21  
**Auditor**: Bridge Contract Auditor  
**Integrity Mode**: Static Read-Only Investigation (Evidence Rule R2)

---

## 1. Executive Summary & Metrics

Static audit analyzed every bridge call between the Vanilla JavaScript frontend and the Python backend bridge (`AppApi` exposed via PyWebView `create_window(js_api=...)`). All calls across 23 JS files and all 134 methods of `AppApi` were cataloged and cross-verified.

### Summary Metrics Table

| Metric | Count | Details |
|---|---|---|
| **Total Bridge Call Sites in JS** | **200** | Direct `window.pywebview.api.*` (173) + local `api()` wrappers in `player.js` (22) and `search.js` (5) |
| **Unique Methods Called by JS** | **81** | All 81 method names exist on `AppApi` |
| **Missing / Ghost Methods in Python** | **0** | No unknown method names called from JS |
| **Total Methods in `core/api.py` (`AppApi`)** | **134** | 113 public methods, 21 private (`_`-prefixed) methods |
| **Public Backend Methods Never Called by JS** | **32** | 4 internal lifecycle, 3 empty stubs, 8 redundant aliases, 2 feature-flagged, 15 orphaned |
| **Argument Count / Arity Mismatches** | **0** | Positional argument counts match method signatures |
| **Return Type Contract Mismatches** | **1** | `open_local_file()`: Py returns `bool`, JS expects `{success: bool, count: int}` (P1) |
| **Dead Controls / Stubs in JS** | **4** | Context menu `cache` (P2), context menu `dislike` (P3), missing `showPlaylistContextMenu` (P2), `import_external_playlist` fire-and-forget in settings (P2) |
| **Dead Controls / Setting Key Mismatches** | **2** | `pinned_track` saved to `'profile'` but read from `'personalization'`/`'app'` (P2); `save_theme` bypassed (P3) |
| **Backend -> Frontend Event Disconnects** | **2** | `api_error` (P1) and `track_updated` (P2) emitted by Python but unhandled in JS `events.js` |
| **Call Sites Lacking `try/catch` / `.catch()`** | **110** | Unhandled Promise Rejections when Python re-raises exceptions (P2) |
| **Backend Methods Without DB `try/except`** | **4** | `get_home_data`, `get_profile_stats`, `create_playlist`, `get_queue` (P2) |

---

## 2. Complete Inventory of JS -> Python Bridge Calls

Bridge calls are organized below by functional domain, listing the method, callers, argument count, and line references.

### 2.1 Audio Playback & Transport (38 calls)

| Method | JS Call Sites (file:line) | Args Passed | Python Signature (`core/api.py`) | Status |
|---|---|---|---|---|
| `play_track` | `artist_profile.js:320, 339, 961, 976, 987`<br>`events.js:85`<br>`home.js:232, 270, 532, 555, 583, 705, 883, 920, 922, 975`<br>`library.js:228, 258`<br>`main.js:90, 118`<br>`player.js:379, 681, 1485`<br>`queue.js:162`<br>`search.js:571, 660, 760, 854`<br>`utils.js:363` | `(track, [track_list], [index])` (1–3 args) | `play_track(self, track: dict, track_list: list = None, index: int = 0)` (L883) | **VERIFIED** |
| `play_pause` | `library.js:226, 256`<br>`player.js:526, 527` | `()` (0 args) | `play_pause(self)` (L1170) | **VERIFIED** (Dispatches tray event) |
| `next_track` | `hotkeys.js:187, 225`<br>`player.js:490, 493, 529, 722, 759, 802, 833, 1370` | `()` (0 args) | `next_track(self)` (L1182) | **VERIFIED** |
| `prev_track` | `hotkeys.js:188, 229`<br>`player.js:528, 723, 760, 805, 837` | `()` (0 args) | `prev_track(self)` (L1188) | **VERIFIED** |
| `play_next` | `main.js:97` | `(track)` (1 arg) | `play_next(self, track: dict)` (L1208) | **VERIFIED** |
| `report_position`| `player.js:470, 665` | `(pos_ms, dur_ms)` (2 args) | `report_position(self, pos_ms: int, dur_ms: int = 0, duration_ms: int = 0)` (L869) | **VERIFIED** |
| `report_state` | `player.js:476, 482` | `(state)` (1 arg) | `report_state(self, state: str, elapsed_ms: int = 0)` (L827) | **VERIFIED** |
| `set_volume` | `player.js:31` | `(volume)` (1 arg) | `set_volume(self, volume: int)` (L1348) | **VERIFIED** |
| `toggle_shuffle` | `player.js:726, 763` | `()` (0 args) | `toggle_shuffle(self)` (L1611) | **VERIFIED** |
| `toggle_repeat` | `player.js:733, 769` | `()` (0 args) | `toggle_repeat(self)` (L1617) | **VERIFIED** |
| `get_next_track`| `player.js:1223` | `()` (0 args) | `get_next_track(self, *args, **kwargs)` (L1623) | **VERIFIED** |
| `prefetch_track`| `player.js:1229` | `(track)` (1 arg) | `prefetch_track(self, track_data: dict)` (L2802) | **VERIFIED** |
| `get_waveform` | `player.js:1985` | `(track)` (1 arg) | `get_waveform(self, track_data: dict)` (L2745) | **VERIFIED** |
| `get_flow_tracks`| `player.js:1267, 1336` | `(currentTrack, 6, excludeIds)` (3 args) | `get_flow_tracks(self, seed_track: dict, limit: int = 6, exclude_ids: list = None)` (L3170) | **VERIFIED** |
| `get_proxy_info`| `main.js:30, 46` | `()` (0 args) | `get_proxy_info(self)` (L860) | **VERIFIED** |

### 2.2 Queue Management (16 calls)

| Method | JS Call Sites (file:line) | Args Passed | Python Signature (`core/api.py`) | Status |
|---|---|---|---|---|
| `get_queue` | `player.js:1261, 1332`<br>`queue.js:80`<br>`utils.js:795` | `()` (0 args) | `get_queue(self)` (L1193) | **VERIFIED** |
| `add_to_queue` | `main.js:102, 139`<br>`player.js:1294, 1362`<br>`utils.js:1108` | `(track)` (1 arg) | `add_to_queue(self, track: dict)` (L1218) | **VERIFIED** |
| `add_tracks_to_queue` | `main.js:136`<br>`player.js:1291, 1359`<br>`utils.js:1106` | `(tracks)` (1 arg) | `add_tracks_to_queue(self, tracks: list)` (L1228) | **VERIFIED** |
| `remove_from_queue` | `queue.js:151`<br>`utils.js:808, 818` | `(index)` (1 arg) | `remove_from_queue(self, index)` (L1240) | **VERIFIED** |
| `reorder_queue` | `queue.js:228` | `(oldIndex, newIndex)` (2 args) | `reorder_queue(self, old_index: int, new_index: int)` (L1203) | **VERIFIED** |

### 2.3 Library, Favorites & Playlists (34 calls)

| Method | JS Call Sites (file:line) | Args Passed | Python Signature (`core/api.py`) | Status |
|---|---|---|---|---|
| `get_favorites` | `home.js:203`<br>`library.js:323, 482` | `()` (0 args) | `get_favorites(self)` (L1877) | **VERIFIED** |
| `toggle_favorite`| `player.js:743, 778, 809, 844`<br>`utils.js:454, 750` | `(track)` (1 arg) | `toggle_favorite(self, track_data: dict)` (L2134) | **VERIFIED** |
| `get_downloaded_tracks` | `library.js:340, 522` | `()` (0 args) | `get_downloaded_tracks(self)` (L1881) | **VERIFIED** |
| `download_track`| `main.js:108`<br>`player.js:1798`<br>`utils.js:385, 768, 1128` | `(track)` (1 arg) | `download_track(self, track_data: dict)` (L1885) | **VERIFIED** |
| `download_all_favorites` | `library.js:38` | `()` (0 args) | `download_all_favorites(self)` (L2827) | **VERIFIED** |
| `cancel_batch_download` | `library.js:62` | `()` (0 args) | `cancel_batch_download(self)` (L2867) | **VERIFIED** |
| `get_playlists` | `home.js:218, 692`<br>`library.js:614, 944`<br>`player.js:1036` | `()` (0 args) | `get_playlists(self)` (L2034) | **VERIFIED** |
| `create_playlist` | `library.js:201, 1007` | `(name)` (1 arg) | `create_playlist(self, name: str, description: str = "")` (L2019) | **VERIFIED** |
| `delete_playlist` | `library.js:685` | `(playlist_id)` (1 arg) | `delete_playlist(self, playlist_id: int)` (L2025) | **VERIFIED** |
| `add_to_playlist` | `library.js:954, 1009`<br>`player.js:1045` | `(plId, track)` (2 args) | `add_to_playlist(self, playlist_id: int, track_data: dict)` (L2038) | **VERIFIED** |
| `get_playlist_tracks` | `home.js:229, 552, 632, 702`<br>`library.js:558`<br>`search.js:754, 830` | `(id, [source], [limit])` (1–3 args) | `get_playlist_tracks(self, playlist_id, source: str = "local", limit: int = 50)` (L2066) | **VERIFIED** |
| `import_external_playlist` | `library.js:164`<br>`onboarding.js:188`<br>`settings.js:309` | `(url, [name])` (1–2 args) | `import_external_playlist(self, url: str, name: str | None = None)` (L1905) | **DEFECT (settings.js)** |
| `export_playlist` | `library.js:278` | `(id, 'm3u8')` (2 args) | `export_playlist(self, playlist_id: int, format: str = "m3u8", target_path: str = None)` (L1952) | **VERIFIED** |
| `create_local_playlist` | `main.js:809` | `("Локальные")` (1 arg) | `create_local_playlist(self, name: str, tracks: list = None)` (L2612) | **VERIFIED** |
| `open_local_file` | `library.js:105` | `()` (0 args) | `open_local_file(self)` (L2628) | **DEFECT (Contract Mismatch)** |

### 2.4 Search & Discovery (16 calls)

| Method | JS Call Sites (file:line) | Args Passed | Python Signature (`core/api.py`) | Status |
|---|---|---|---|---|
| `search` | `artist_profile.js:125`<br>`search.js:55, 75, 151, 200, 577, 768, 1065` | `(query, [source], [type])` (2–3 args) | `search(self, query: str, source: str = "all", result_type: str = None)` (L1668) | **VERIFIED** |
| `get_album_tracks` | `artist_profile.js:969`<br>`search.js:566, 636` | `(album_data)` (1 arg) | `get_album_tracks(self, album_data: dict)` (L1800) | **VERIFIED** |
| `get_artist_profile` | `artist_profile.js:199` | `(artist_name)` (1 arg) | `get_artist_profile(self, artist_name: str)` (L2653) | **VERIFIED** |
| `get_track_wave` | `main.js:155` | `(seedTrack, 15, excludeIds)` (3 args) | `get_track_wave(self, track_data: dict, limit: int = 15, exclude_ids: list = None)` (L2727) | **VERIFIED** |

### 2.5 Home Page & Feed Feeds (12 calls)

| Method | JS Call Sites (file:line) | Args Passed | Python Signature (`core/api.py`) | Status |
|---|---|---|---|---|
| `get_home_data` | `home.js:83` | `()` (0 args) | `get_home_data(self)` (L2487) | **VERIFIED** |
| `get_popular_tracks` | `home.js:108` | `()` (0 args) | `get_popular_tracks(self, region: str = "US")` (L2509) | **VERIFIED** |
| `get_feed` | `home.js:115` | `(10)` (1 arg) | `get_feed(self, max_results: int = 20)` (L2877) | **VERIFIED** |
| `get_home_releases` | `home.js:122` | `(10)` (1 arg) | `get_home_releases(self, max_results: int = 10)` (L2899) | **VERIFIED** |
| `get_home_mixes` | `home.js:129` | `(10)` (1 arg) | `get_home_mixes(self, max_results: int = 10)` (L2910) | **VERIFIED** |
| `get_authentic_home_feed` | `home.js:136` | `(5)` (1 arg) | `get_authentic_home_feed(self, limit: int = 20)` (L2531) | **VERIFIED** |
| `get_home_artists` | `home.js:146, 150` | `(15)` (1 arg) | `get_home_artists(self, max_results: int = 10)` (L2889) | **VERIFIED** |
| `get_artists_avatars` | `home.js:767` | `(missing_names)` (1 arg) | `get_artists_avatars(self, names)` (L2690) | **VERIFIED** |
| `get_wrapped_stats` | `home.js:1030` | `(period)` (1 arg) | `get_wrapped_stats(self, period: str = "week")` (L2412) | **VERIFIED** |

### 2.6 Settings, Audio Hardware & System (23 calls)

| Method | JS Call Sites (file:line) | Args Passed | Python Signature (`core/api.py`) | Status |
|---|---|---|---|---|
| `get_settings` | `main.js:393`<br>`visualizer.js:143` | `()` (0 args) | `get_settings(self, category: str = None)` (L2275) | **VERIFIED** |
| `get_settings_by_category` | `hotkeys.js:131` | `('hotkeys')` (1 arg) | `get_settings_by_category(self, category: str)` (L2312) | **VERIFIED** |
| `save_setting` | `hotkeys.js:160`<br>`lyrics.js:79, 110`<br>`main.js:749, 792`<br>`settings.js:953`<br>`utils.js:777`<br>`visualizer.js:115` | `(key, value, category)` (3 args) | `save_setting(self, key: str, value, category: str = "app")` (L2298) | **DEFECT (utils.js:777)** |
| `set_setting` | `settings.js:1725, 1739, 1761` | `('zapret', key, val)` (3 args) | `set_setting(self, section: str, key=None, value=None)` (L1273) | **VERIFIED** |
| `get_storage_info` | `library.js:112, 175`<br>`settings.js:212, 964` | `()` (0 args) | `get_storage_info(self)` (L2331) | **VERIFIED** |
| `clear_storage_cache` | `settings.js:203` | `()` (0 args) | `clear_storage_cache(self)` (L3157) | **VERIFIED** |
| `clear_storage` | `settings.js:211` | `('all')` (1 arg) | `clear_storage(self, storage_type: str = "cache")` (L2402) | **VERIFIED** |
| `set_cache_quota` | `settings.js:226` | `(val)` (1 arg) | `set_cache_quota(self, quota_gb: int)` (L3137) | **VERIFIED** |
| `find_duplicate_tracks` | `settings.js:242` | `()` (0 args) | `find_duplicate_tracks(self)` (L3002) | **VERIFIED** |
| `delete_duplicate_track` | `settings.js:3034` | `(trackId, true)` (2 args) | `delete_duplicate_track(self, track_id: int, delete_file: bool = False)` (L3010) | **VERIFIED** |
| `update_track_tags` | `utils.js:942` | `(trackId, tagsData)` (2 args) | `update_track_tags(self, track_id: int, tags: dict)` (L3021) | **VERIFIED** |
| `choose_cover_image` | `utils.js:907` | `()` (0 args) | `choose_cover_image(self)` (L3108) | **VERIFIED** |
| `get_audio_devices` | `settings.js:1503` | `()` (0 args) | `get_audio_devices(self)` (L1356) | **VERIFIED** |
| `set_audio_device` | `settings.js:1525` | `(devName)` (1 arg) | `set_audio_device(self, device_name: str)` (L1463) | **VERIFIED** |
| `get_equalizer` | `equalizer.js:171` | `()` (0 args) | `get_equalizer(self)` (L2429) | **VERIFIED** |
| `set_equalizer` | `equalizer.js:284` | `(preamp, bands)` (2 args) | `set_equalizer(self, preamp: float = 0, bands: list = None)` (L2436) | **VERIFIED** |
| `toggle_discord_rpc` | `settings.js:183` | `(isOn)` (1 arg) | `toggle_discord_rpc(self, enabled: bool)` (L2944) | **VERIFIED** |
| `toggle_zapret` | `settings.js:1696` | `(enable, mode, args, bin)` (4 args) | `toggle_zapret(self, enabled: bool, mode: str = "general", custom_args: str = "", binary_path: str = "")` (L2922) | **VERIFIED** |
| `get_zapret_status` | `settings.js:1807` | `()` (0 args) | `get_zapret_status(self)` (L2972) | **VERIFIED** |
| `update_zapret` | `settings.js:1774` | `(true)` (1 arg) | `update_zapret(self, force: bool = False)` (L2993) | **VERIFIED** |
| `yandex_device_auth` | `settings.js:389` | `()` (0 args) | `yandex_device_auth(self)` (L1294) | **VERIFIED** |
| `complete_onboarding` | `onboarding.js:180` | `(settingsData)` (1 arg) | `complete_onboarding(self, settings_data: dict)` (L2159) | **VERIFIED** |
| `get_profile_stats` | `main.js:644` | `()` (0 args) | `get_profile_stats(self)` (L2580) | **VERIFIED** |
| `select_avatar` | `main.js:773` | `()` (0 args) | `select_avatar(self)` (L2591) | **VERIFIED** |

### 2.7 Lyrics & Translation (2 calls)

| Method | JS Call Sites (file:line) | Args Passed | Python Signature (`core/api.py`) | Status |
|---|---|---|---|---|
| `get_lyrics` | `lyrics.js:295` | `(title, artist, durMs, file_path)` (4 args) | `get_lyrics(self, track_name: str, artist_name: str, duration_ms: int = 0, file_path: str = None)` (L2448) | **VERIFIED** |
| `get_lyrics_translation`| `lyrics.js:36` | `(rawText, 'ru')` (2 args) | `get_lyrics_translation(self, lyrics_text: str, target_lang: str = "ru")` (L2480) | **VERIFIED** |

### 2.8 Window Geometry & Lifecycle (9 calls)

| Method | JS Call Sites (file:line) | Args Passed | Python Signature (`core/api.py`) | Status |
|---|---|---|---|---|
| `minimize_window` | `main.js:433`<br>`player.js:858` | `()` (0 args) | `minimize_window(self)` (L538) | **VERIFIED** |
| `minimize` | `player.js:860` | `()` (0 args) | `minimize(self)` (L533) | **VERIFIED** |
| `maximize` | `hotkeys.js:180`<br>`main.js:436` | `()` (0 args) | `maximize(self)` (L612) | **VERIFIED** |
| `close_window` | `main.js:440`<br>`player.js:876` | `()` (0 args) | `close_window(self)` (L529) | **VERIFIED** |
| `close` | `player.js:878` | `()` (0 args) | `close(self)` (L502) | **VERIFIED** |
| `toggle_mini_player` | `main.js:174` | `(targetState)` (1 arg) | `toggle_mini_player(self, enable: bool)` (L393) | **VERIFIED** |
| `set_mini_player_position` | `settings.js:2366` | `(pos)` (1 arg) | `set_mini_player_position(self, pos: str)` (L464) | **VERIFIED** |

---

## 3. Signature & Contract Verification

### 3.1 IPC Mechanism
PyWebView transfers calls from JS to Python by serializing them over IPC:
`{"func": "<method_name>", "params": [arg1, arg2, ...]}`.
On Python side, `pywebview` executes:
`getattr(js_api, func)(*params)`
All parameters passed from JavaScript are unpacked strictly as **positional arguments** (`*args`). Keyword arguments (`**kwargs`) cannot be passed directly across the bridge boundary from JS unless packaged in a dictionary object as a single positional parameter.

### 3.2 Arity Matching
Every JS call site was tested against the corresponding Python `inspect.signature`:
- **0 arity errors found**: All calls satisfy `len(required_args) <= len(passed_args) <= len(total_args)`.
- Methods with optional parameters (`default=...`) correctly receive optional arguments or fall back to defaults.

---

## 4. Return Value & Payload Schema Verification

### 4.1 Defect: `open_local_file` Return Type Incompatibility (P1)
- **File & Line**: `ui/web_new_v2/js/library.js:105-114` vs `core/api.py:2628-2651`
- **Frontend Code**:
  ```javascript
  const res = await window.pywebview.api.open_local_file();
  if (res && (res.success || res.count > 0)) {
      const count = typeof res === 'object' && res.count !== undefined ? res.count : 1;
      window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Импортировано треков: ${count}`, type: 'success' } }));
      loadLibrary();
      refreshActiveLibraryView();
      if (window.pywebview.api.get_storage_info) {
          window.pywebview.api.get_storage_info();
      }
  }
  ```
- **Backend Code**:
  ```python
  if imported:
      self._emit("library_updated", True)
      self.play_track(imported[0], track_list=imported, index=0)
      return True
  return False
  ```
- **Mechanism**: Python returns boolean primitive `True`. In JavaScript, `(true && (true.success || true.count > 0))` evaluates:
  - `true.success` -> `undefined`
  - `true.count` -> `undefined`
  - `undefined || (undefined > 0)` -> `false`
  The condition evaluates to `false`. The entire block is bypassed.
- **Impact**: When importing local files through the sidebar button, files are scanned and start playing, but the UI **never** displays the import confirmation toast, **never** reloads the library list, and **never** refreshes storage info.
- **Classification**: `DEAD_CONTROL` subtype **d** (Payload type mismatch).
- **Severity**: **P1**.

### 4.2 Defect: `pinned_track` Setting Category Drift (P2)
- **File & Line**: `ui/web_new_v2/js/utils.js:777` vs `ui/web_new_v2/js/main.js:657`
- **Writer Code (`utils.js:777`)**:
  ```javascript
  window.pywebview.api.save_setting('pinned_track', track, 'profile');
  ```
- **Reader Code (`main.js:657`)**:
  ```javascript
  const pinnedTrack = window.settings?.personalization?.pinned_track || window.settings?.app?.pinned_track;
  ```
- **Mechanism**: The track context menu pins a track into category `'profile'`. But the user profile renderer looks only in categories `'personalization'` and `'app'`. Because settings categories are isolated in SQLite (`settings` table `category` column), the query for `personalization.pinned_track` returns `null`.
- **Impact**: Clicking "Закрепить в профиле" (Pin to profile) displays a success toast, but the pinned track never renders in `#profile-pinned-section`.
- **Classification**: `DEAD_CONTROL` subtype **d** (Saved data never reaches consumer UI due to key category mismatch).
- **Severity**: **P2**.

---

## 5. Exception Handling & Promise Rejection Architecture

### 5.1 PyWebView Error Propagation Mechanics
In `core/api.py:152-192`, `_install_bridge_error_logging()` dynamically wraps all exposed bridge methods:
```python
def _wrapped(inner_self, *args, **kwargs):
    try:
        return func(inner_self, *args, **kwargs)
    except Exception as exc:
        logger.error("bridge call %s() failed: %s: %s", method_name, type(exc).__name__, exc, exc_info=True)
        try:
            inner_self._emit("api_error", {"method": method_name, "error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            pass
        raise
```
**Key observation**: The wrapper **re-raises** `exc`. Under PyWebView, a re-raised Python exception automatically rejects the JavaScript Promise on the frontend.

### 5.2 Defect: Unhandled `api_error` Event in Event Router (P1)
- **File & Line**: `core/api.py:182` vs `ui/web_new_v2/js/events.js:292-294`
- **Mechanism**: The backend specifically emits `api_error` with `{"method": method_name, "error": ...}` so the frontend can display a user-friendly error toast. However, `ui/web_new_v2/js/events.js` has **no case for `api_error`** in its switch statement. It falls into `default: console.log('Unknown event:', eventName)`.
- **Impact**: Any Python exception in a bridge call is silently logged to the JS console as an "unknown event". The user receives no visual feedback, leaving buttons stuck with spinners or disabled states.
- **Classification**: `DEAD_CONTROL` subtype **d** (Bridge error event discarded by frontend router).
- **Severity**: **P1**.

### 5.3 Defect: 110 Call Sites Without Promise Rejection Catching (P2)
- **Call Sites Sample**:
  - `ui/web_new_v2/js/home.js:702`: `const res = await window.pywebview.api.get_playlist_tracks(pl.id);` (in playlist click listener, no try/catch)
  - `ui/web_new_v2/js/settings.js:3034`: `await window.pywebview.api.delete_duplicate_track(trackId, true);` (no try/catch)
  - `ui/web_new_v2/js/main.js:773`: `await window.pywebview.api.select_avatar();` (no try/catch)
  - `ui/web_new_v2/js/visualizer.js:143`: `await window.pywebview.api.get_settings();` (no try/catch)
  - `ui/web_new_v2/js/library.js:62`: `await window.pywebview.api.cancel_batch_download();` (no try/catch)
- **Impact**: Any unhandled rejection in modern WebKit/WebView2 logs an unhandled promise rejection error and aborts subsequent JavaScript execution in the enclosing event turn.
- **Classification**: `DEAD_CONTROL` subtype **f** (Throws/rejects, breaking control flow).
- **Severity**: **P2**.

### 5.4 Backend Methods Lacking Defensive `try/except` (P2)
The following public methods directly invoke SQLite database operations or engine attributes without internal `try/except` boundaries:
1. `get_home_data` (`core/api.py:2487-2508`): Directly queries `self._core.db.get_history()`, `get_tracks_count()`, etc.
2. `get_profile_stats` (`core/api.py:2580-2590`): Directly queries `self._core.db.get_tracks_count()`, `get_history()`, etc.
3. `create_playlist` (`core/api.py:2019-2023`): Directly queries `self._core.db.create_playlist(name, description)`.
4. `get_queue` (`core/api.py:1193-1201`): Directly accesses `self._core.engine.queue.tracks` without verifying engine state.

If SQLite encounters a busy/locked state or an engine queue operation is interrupted, these methods raise unhandled exceptions that cascade into rejected promises on the frontend.
- **Classification**: Robustness defect / `DEAD_CONTROL` subtype **f**.
- **Severity**: **P2**.

---

## 6. Python -> JS Event Contract Analysis

The backend dispatches events to the frontend via `window.onPythonEvent(eventName, data)`.

### 6.1 Disconnects Summary

- **Total Python `_emit` calls in codebase**: 72
- **Unique event names emitted by Python**: 40
- **Total `case` branches in `events.js`**: 84
- **Events emitted by Python but NOT handled in `events.js`**:
  1. `api_error` (`core/api.py:182`) — Critical bridge error notification (P1).
  2. `track_updated` (`core/api.py:3100`) — Emitted after physical ID3/Vorbis tag updates via `update_track_tags()` (P2).
- **Events in `events.js` never emitted by Python (Dead/Phantom listeners)**:
  - `authentic_home_error` (`events.js:92`)
  - `mood_playlists_ready` (`events.js:144`)
  - `recommendations_ready` (`events.js:108` — backend emits `feed_ready`)
  - `track_downloaded` (`events.js:196` — backend emits `download_complete`)
  - `storage_info_updated` (`events.js:223` — backend emits `storage_info` and `storage_updated`)
  - `smart_home_ready` (`events.js:287`)
  - `yandex_auth_error` (`events.js:288`)
  - `yt_playlist_ready` (`events.js:82`)

---

## 7. Inventory of Uncalled Backend Methods (32 Methods)

The following 32 public methods in `core/api.py` are never called by the active `ui/web_new_v2` frontend:

| Category | Method | Line | Signature | Explanation / Reason |
|---|---|---|---|---|
| **Lifecycle Hooks** | `cleanup` | L193 | `()` | Process exit cleanup, called from `main.py` (in `_UNWRAPPED`). |
| | `set_window` | L212 | `(window)` | Sets main webview instance, called from `main.py:355`. |
| | `set_windows` | L495 | `(main, mini)` | Sets window pair, called from `main.py:377`. |
| | `emit_event` | L697 | `(name, data=None)` | Python-internal helper to trigger JS events. |
| **Empty Stubs** | `stop_track` | L1166 | `()` | Contains `pass # Handled by frontend`. Audio is stopped via HTML5 audio in JS. |
| | `toggle_mute` | L1603 | `()` | Contains `return False # Handled by frontend`. Mute is toggled on `<audio>`. |
| | `set_position` | L1607 | `(pos_ms)` | Contains `pass # Handled by frontend`. Seeking is done via `audio.currentTime`. |
| **Internal Helpers**| `restore` | L563 | `()` | Called internally by `maximize()` (L620) when unmaximizing. |
| | `maybe_log_history` | L800 | `()` | Called internally by `report_state("playing")` (L830). Should be private `_maybe_log_history`. |
| | `update_autostart` | L2186 | `(enabled)` | Called internally by `save_setting("autostart")` (L2303) and `complete_onboarding` (L2181). |
| **Redundant Aliases**| `shutdown` | L523 | `()` | Redundant exit hook (`close_window` is used instead). |
| | `toggle_fullscreen`| L684 | `()` | Calls `self.maximize()`. F11 in `hotkeys.js:180` calls `maximize()` directly. |
| | `open_url` | L688 | `(url)` | Opens browser safely with SSRF check. Unused by frontend. |
| | `open_external_url`| L693 | `(url)` | Alias for `open_url`. Unused by frontend. |
| | `get_setting` | L1259 | `(key, default=None)` | Frontend uses `get_settings()` to load categories in batch. |
| | `get_favorite_tracks`| L2149| `()` | Duplicate of `get_favorites()` (L1877). |
| | `get_all_settings` | L2309 | `()` | Duplicate of `get_settings()` without category filter. |
| | `update_setting` | L2315 | `(cat, key, val)` | Alias for `save_setting(key, val, cat)`. |
| | `get_yt_playlist_tracks`| L2130| `(pl_id, limit=50)` | Alias for `get_playlist_tracks(pl_id, source="youtube")`. |
| **Feature Flags / Dead Code**| `validate_subscription_key` | L2252 | `(key)` | Disabled via `LICENSE_VALIDATION_ENABLED = False`. |
| | `get_subscription_info` | L2266 | `()` | Disabled via `LICENSE_VALIDATION_ENABLED = False`. |
| | `save_theme` | L2153 | `(theme)` | Bypassed by frontend calling `save_setting('theme', t.id, 'theme')`. |
| | `get_personalization`| L2318| `()` | Frontend calls `get_settings()` and reads `.personalization`. |
| | `save_personalization`| L2321| `(data)` | Frontend calls `save_setting` per individual key. |
| | `get_volume` | L1352 | `()` | JS tracks volume locally in state to avoid RPC polling. |
| | `get_library` | L1873 | `()` | UI only exposes Favorites and Downloads; no general library view exists. |
| | `get_track_info` | L2053 | `(track_id)` | DB lookup method, uncalled by frontend. |
| | `get_artist_discography` | L2680 | `(artist_name)` | `get_artist_profile` already returns discography. |
| | `get_recommendations`| L2712 | `(track_data, max=10)`| Synchronous blocking recommendation lookup; frontend uses async `get_feed`. |
| | `get_discord_rpc_status`| L2966 | `()` | Frontend saves RPC toggle to settings without querying live status. |
| | `check_zapret_update`| L2986 | `()` | Frontend directly invokes `update_zapret(true)`. |
| | `get_storage_details`| L3127 | `()` | Returns cache metrics; frontend calls `get_storage_info()`. |

---

## 8. Comprehensive Defect Catalog

### Defect Table

| ID | Severity | Area | Subtype | Symptom | Evidence (file:line) | Proposed Fix |
|---|---|---|---|---|---|---|
| **BC-001** | **P1** | Library / Local Import | **DEAD_CONTROL d** | Importing local audio files plays the file but never displays success toast, never reloads library view, and never refreshes storage counters. | `ui/web_new_v2/js/library.js:106`<br>`core/api.py:2648` | Change `core/api.py:2648` to return `{"success": True, "count": len(imported)}`, or update `library.js:106` to `if (res === true \|\| (res && res.success))`. |
| **BC-002** | **P1** | Error Handling / Bridge | **DEAD_CONTROL d** | When any bridge call throws in Python, `api_error` is emitted to notify the UI, but `events.js` lacks an event case, leaving UI stuck with unhandled rejection and no toast. | `core/api.py:182`<br>`ui/web_new_v2/js/events.js:292` | Add `case 'api_error':` in `ui/web_new_v2/js/events.js` to show error toast and clear pending button spinners. |
| **BC-003** | **P2** | Settings / Playlist Import | **DEAD_CONTROL d/f** | In Settings panel, playlist import is fired asynchronously without `await`/`.catch()`. Errors (SSRF blocks, invalid links, timeouts) are swallowed; inputs are blindly cleared after 4s. | `ui/web_new_v2/js/settings.js:308-316`<br>`core/api.py:1905` | Match `library.js:164`: `await` the call, check `res.success`, and display `res.error` or success toast. |
| **BC-004** | **P2** | Profile / Context Menu | **DEAD_CONTROL d** | "Закрепить в профиле" (Pin to profile) displays success toast, but pinned track never renders in `#profile-pinned-section`. | `ui/web_new_v2/js/utils.js:777`<br>`ui/web_new_v2/js/main.js:657` | In `utils.js:777`, change category from `'profile'` to `'personalization'`, matching `main.js:657`. |
| **BC-005** | **P2** | Context Menu / Cache | **DEAD_CONTROL b** | "Кэшировать" (Cache track) in track context menu displays placeholder toast "Функция пока недоступна (Кэшировать)", despite `prefetch_track` being implemented in backend. | `ui/web_new_v2/js/utils.js:772-774`<br>`core/api.py:2802` | Connect `case 'cache':` in `utils.js` to call `window.pywebview.api.prefetch_track(track)`. |
| **BC-006** | **P2** | Metadata / Tag Editor | **DEAD_CONTROL d** | Saving track tags emits `track_updated` from backend, but `events.js` lacks an event case, leaving track titles and metadata outdated in active views. | `core/api.py:3100`<br>`ui/web_new_v2/js/events.js:292` | Add `case 'track_updated':` in `events.js` to update track DOM elements and dispatch `nedotify:track_updated`. |
| **BC-007** | **P2** | Playlist Context Menu | **DEAD_CONTROL a** | Right-clicking on any playlist card (`.playlist-card, .sidebar-playlist-item, .lib-playlist-item`) does nothing because `showPlaylistContextMenu` is not defined anywhere in the codebase. | `ui/web_new_v2/js/contextmenu.js:34-40` | Implement `showPlaylistContextMenu` or bind playlist context menu to `window.NeDotify.showPlaylistContextMenu`. |
| **BC-008** | **P2** | UI / Robustness | **DEAD_CONTROL f** | Over 100 bridge calls lack `try/catch` or `.catch()`. When backend re-raises exceptions, unhandled promise rejections occur in WebView. | `ui/web_new_v2/js/home.js:702`<br>`ui/web_new_v2/js/settings.js:3034`<br>`ui/web_new_v2/js/main.js:773`<br>`core/api.py:188` | Add safety wrappers (`try/catch` or `.catch()`) or wrap `window.pywebview.api` in a defensive proxy that intercepts rejections. |
| **BC-009** | **P2** | Database / Bridge | **DEAD_CONTROL f** | Public bridge methods `get_home_data`, `get_profile_stats`, `create_playlist`, `get_queue` perform direct DB/engine calls without `try/except`. | `core/api.py:2019, 2487, 2580, 1193` | Enclose database and engine queries in defensive `try/except` returning `{..., "error": str(e)}` instead of crashing. |
| **BC-010** | **P3** | Context Menu / Dislike | **DEAD_CONTROL b** | "Не интересно" (Dislike) in track context menu is a placeholder stub with "Функция пока недоступна (Не интересно)". | `ui/web_new_v2/js/utils.js:754-756` | Implement track disliking (blacklist from flow/recommendations) or hide the menu option. |
| **BC-011** | **P3** | API Architecture / Stubs | **DEAD_CONTROL b** | Methods `stop_track`, `toggle_mute`, `set_position` in `core/api.py` are empty stubs (`pass` / `return False`). | `core/api.py:1166, 1603, 1607` | Either implement backend logic (e.g. stop engine audio) or mark as deprecated/internal. |
| **BC-012** | **P3** | Theme Architecture | **DEAD_CONTROL c** | `save_theme` in `core/api.py` writes to `theme.selected` and emits `theme_changed`, but frontend bypasses it and saves to `theme.theme` via `save_setting`. | `core/api.py:2153`<br>`ui/web_new_v2/js/settings.js:589` | Align theme persistence keys between `save_theme` and frontend `settings.js`. |
| **BC-013** | **P3** | Code Hygiene | **Dead Code** | 32 public methods in `core/api.py` are never invoked by the frontend (redundant aliases, forgotten features, or internal methods lacking `_` prefix). | `core/api.py` (32 locations) | Prefix internal methods with `_`, deprecate unused aliases, or prune dead endpoints. |

---

## 9. Verification & Independent Reproducibility

To independently verify all findings in this audit report, execute the following commands in the repository root:

```bash
# 1. Verify open_local_file return signature vs JS check:
python3 -c "
import ast
with open('core/api.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'open_local_file':
        print('open_local_file returns:', [ast.unparse(r.value) for r in ast.walk(node) if isinstance(r, ast.Return)])
"
# Result: ['False', 'False', 'True', 'False'] (booleans only!)
# In JS: ui/web_new_v2/js/library.js:106 checks `res && (res.success || res.count > 0)` -> false!

# 2. Verify pinned_track category mismatch:
grep -n "pinned_track" ui/web_new_v2/js/utils.js ui/web_new_v2/js/main.js
# Result: utils.js:777 saves to 'profile', main.js:657 reads 'personalization' and 'app'

# 3. Verify missing api_error in events.js switch:
grep -n "case 'api_error':" ui/web_new_v2/js/events.js
# Result: empty (no results found)

# 4. Verify showPlaylistContextMenu is never defined:
grep -rn "function showPlaylistContextMenu" ui/web_new_v2/
# Result: empty (never defined)

# 5. Run Python test suite:
pytest tests/ -q
```
