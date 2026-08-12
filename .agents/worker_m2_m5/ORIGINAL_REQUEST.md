## 2026-07-12T15:09:03Z
Implement the fixes for AURA Music app as described in our plan.

MANDATORY INTEGRITY WARNING:
> DO NOT CHEAT. All implementations must be genuine. DO NOT
> hardcode test results, create dummy/facade implementations, or
> circumvent the intended task. A Forensic Auditor will independently
> verify your work. Integrity violations WILL be detected and your
> work WILL be rejected.

Your working directory is c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\ . Write your handoff to c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\worker_m2_m5\handoff.md.

Here are the specific implementation requirements:

1. **R1 Custom Window Controls & R2 Profile Stats** in `ui/web_new/js/main.js`:
   - Change `loadProfile` to call `window.pywebview.api.get_profile_stats()` instead of `get_home_data()`.
   - Update text fields to map the new payload:
     - `data.total_tracks` (profile-stat-tracks)
     - `data.total_listening_time_ms` (profile-stat-time) formatted using `formatListeningTimeShort`
     - `data.favorite_count` (profile-stat-favorites)
     - `data.most_played` (profile-top-tracks)
     - `data.recently_played` (profile-recent)
   - Import `loadSettings` from `./settings.js` and expose it under the `window.AURA` object as `loadSettings`.

2. **R2 Cache Settings Event** in `ui/web_new/js/events.js`:
   - In `initEvents()`, update the switch-case for `storage_info` to also handle `storage_info_updated` (fall-through to `onStorageInfo(data)`).

3. **R2 Settings Cache Size Initialization** in `ui/web_new/js/pages.js` and `ui/web_new/js/settings.js`:
   - In `pages.js`, inside `showPage()`, trigger `window.AURA.loadSettings()` if `pageId === 'settings'`.
   - In `settings.js`, define and export `loadSettings()` function that calls `window.pywebview.api.get_storage_info()`.

4. **R2 Local Cover Paths** in `ui/web_new/js/utils.js` and `ui/web_new/js/home.js`:
   - In `utils.js`, export a helper function `getCoverUrl(track)`:
     ```javascript
     export function getCoverUrl(track) {
         if (!track) return '';
         if (track.cover_path) {
             return 'file:///' + track.cover_path.replace(/\\/g, '/');
         }
         return track.cover_url || '';
     }
     ```
     Use `getCoverUrl(track)` to set `coverSrc` inside `createTrackElement`.
   - In `home.js`, import `getCoverUrl` from `./utils.js` and use it inside `createFeedCard(track)` to set the `cover` variable.

5. **R3 Search Race Condition** in `ui/web_new/js/search.js` and `core/api.py`:
   - In `search.js`, inside `onSearchResults(data)`, verify that the query in `data.query` matches the current value of the search input `#search-input` before processing and appending the results. Ignore obsolete queries.
   - In `core/api.py`, modify `search(self, query, source="all")` to include `"query": query` in the payload of the emitted `"search_results"` event for all search sources (local, artists, youtube, soundcloud).
   - In `core/api.py`, add support for `"vk"` source in `search()` so that it queries `self._core.vk.search(query, callback=on_vk_results, error_callback=on_vk_error)` and emits VK search results with the query parameter.

6. **R3 Audio Visualizer volume & track reactive** in `core/api.py`, `ui/web_new/js/player.js` and `ui/web_new/js/visualizer.js`:
   - In `core/api.py`, implement `get_volume(self)` to return `self._core.engine.get_volume()`.
   - In `player.js`, maintain variables `let currentVolume = 70;` and `let isMuted = false;`. Update `currentVolume` on `applySettings` and slider drag (`onDrag`/`onRelease` for `pb-volume-track`). Update `isMuted` on mute button click using the resolved value from `toggle_mute`. Export `getVolume()` function returning `isMuted ? 0 : currentVolume`.
   - In `visualizer.js`, import `getVolume`, `getIsPlaying`, and `getCurrentTrack` from `player.js`.
   - In `draw()`, retrieve `volScale = getVolume() / 100` and scale the height of active bars. Compute a track-specific seed from `track.title` to procedurally adjust wave frequencies, so different tracks render visually distinct wave patterns.
