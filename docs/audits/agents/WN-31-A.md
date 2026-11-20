## AREA WN-31 — UI search, discovery, home, particles — ROLE A

### 1. Scope reviewed

**Files opened (path : line ranges actually read)**

- `ui/web_new_v2/js/search.js` — 1–1250 (full)
- `ui/web_new_v2/js/search-discovery.js` — 1–127 (full)
- `ui/web_new_v2/js/home.js` — 1–1049 (full)
- `ui/web_new_v2/js/home-shell.js` — 1–119 (full)
- `ui/web_new_v2/js/particles.js` — 1–557 (full)

**Callees / collaborators traced (read-only, for contract verification)**

- `core/api.py` — 585–624 (`_on_minimized`/`_on_restored` → `window_visibility`), 1437–1546 (`play_track`), 2077–2232 (`search`), 2250–2265 (`get_album_details`), 2273–2292 (`get_favorites`/`get_downloaded_tracks`), 2513–2543 (`get_playlists`), 2545–2613 (`get_playlist_tracks`), 3156–3175 (`get_wrapped_stats`), 3227–3265 (`fetch_missing_covers`), 3293–3313 (`get_home_data`), 3315–3335 (`get_popular_tracks`), 3465–3513 (`get_artist_profile`), 3515–3535 (`get_artists_avatars`), 3735–3794 (`get_feed`/`get_home_artists`/`get_home_releases`/`get_home_mixes`), 4219–4221 (`get_search_suggestions`), L61/L67 (`PROVIDER_SEARCH_TIMEOUT`, `BRIDGE_SYNC_BUDGET`), L363–365 (`_search_executor`, `_search_generation`)
- `core/database.py` — 1366–1479 (`search_tracks`/`search_artists`/`search_albums`/`search_playlists`), 1695–1721 (`get_most_played`/`get_top_artists`), 1723–1834 (`get_wrapped_stats`), 1931–1943 (`get_playlists`), L231 (`year INTEGER`)
- `services/youtube_service.py` — 370–513 (`search` + `result_type` handling)
- `services/spotify_service.py` — 110–173 (`search` + `result_type` handling)
- `services/soundcloud_service.py` — 295–330 (`search` signature — **no `result_type`**)
- `services/catalog_service.py` — 168–251 (`album_details`)
- `utils/search_query.py` — 1–101 (`suggest_search_queries`)
- `ui/web_new_v2/js/events.js` — 1–259 (event → renderer contract)
- `ui/web_new_v2/js/utils.js` — 1–70, 515–774, 955–994 (`escapeHtml`, `coverImgHtml`, `getCoverUrl`, `createTrackElement`, `getSourceIcon`, DPR helpers)
- `ui/web_new_v2/js/main.js` — 1–134, 180–259, 480–599 (`awaitBridge`, `window.NeDotify`, init order)
- `ui/web_new_v2/js/pages.js` — 1–198 (`showPage`)
- `ui/web_new_v2/js/efficiency.js` — 80–159 (efficiency state → particles)
- `ui/web_new_v2/js/artist_profile.js` — 1–209, 716–765 (`artist_ref`/`context` contract)
- `ui/web_new_v2/index.html` — L10 (CSP), L68–87 (`#particles-bg`), L211–253, L268, L286–334, L343, L353–403, L1493–1505, L1985–2007, L2314 (markup/ID contract)
- `ui/web_new_v2/css/components/base.css` — 1715–1744 (`#particles-bg`, reduced-motion)

**Callees traced into other areas (root cause owner named where relevant)**

- `core/api.py::search` → **WN-06** (bridge search) / **WX-05** (search fan-out) — owns the missing cancellation of superseded provider searches (see F-WN-31-1).
- `utils/search_query.py::suggest_search_queries` → **WN-27**.
- `services/{youtube,spotify,soundcloud}_service.py::search` → **WN-19 / WN-21** (the `result_type` contract mismatch behind F-WN-31-2).
- `ui/web_new_v2/js/utils.js::createTrackElement` → **WN-28** (same CSP/`onerror` class of bug; only the `search.js` instances are reported here).
- `ui/web_new_v2/js/artist_profile.js` → **WN-32** (artist profile rendering).
- `ui/web_new_v2/js/library.js::selectSection` → **WN-32**.
- `core/api.py::get_artist_profile` → **WN-09**.

---

### 2. Findings

#### F-WN-31-1  [P1] — The 200 ms search debounce fires on essentially every keystroke, so each character of a query starts a full 4-provider fan-out; the shared 6-worker search executor saturates and the final query's results are delayed until the earliest stale provider request times out (6 s / 8 s for SoundCloud)

- **File:** `ui/web_new_v2/js/search.js:95-118` (debounce), `ui/web_new_v2/js/search.js:1075-1090` (`runSearchQuery`), `ui/web_new_v2/js/search.js:1092-1096` (`api`), `core/api.py:2090-2096` (generation counter), `core/api.py:2100` (`requested_providers = ["local","youtube","soundcloud","spotify"]`), `core/api.py:2161` + `core/api.py:2230` (one executor task per provider), `core/api.py:363` (`ThreadPoolExecutor(max_workers=6)`), `core/api.py:2197` (`_timeout = 8.0 if name == "soundcloud" else PROVIDER_SEARCH_TIMEOUT`, `PROVIDER_SEARCH_TIMEOUT = 6.0` at `core/api.py:61`)
- **Confirmed:** yes
- **Description:** Typing a query at a normal human speed (≈250–400 ms between keystrokes) is **slower than the debounce**, so the 200 ms timer expires between every pair of keystrokes and a complete search is started for every character typed. A 12-character query therefore starts 12 full fan-outs (≈48 provider requests). The backend's generation counter only **suppresses the results** of superseded generations (`core/api.py:2094-2096`, `emit_results` → `if not is_current(): return`); it never cancels the already-running provider HTTP requests. With only 6 workers in the shared `_search_executor`, the stale generations hold 3–4 workers for up to 6 s (YouTube/Spotify) or 8 s (SoundCloud), and the *current* generation's provider tasks sit at the back of the FIFO queue. The user stares at "Поиск..." for up to ~6 s after finishing the word.
- **Cause:** Two cooperating gaps. (a) The frontend debounce (200 ms) is below the average inter-keystroke interval, so it provides no batching at all for a human typist. (b) The backend has no cancellation: `search()` bumps `_search_generation` but the previously submitted `_run_provider` tasks keep running to completion — and `_run_provider` checks `is_current()` only at task *start* (`core/api.py:2169-2171`), so a task that was current when it started runs the full network request even if it is superseded a millisecond later.
- **Trigger conditions:** Any query typed at human speed in the Search page (default source "Все площадки"). Worse with a slow/losing network (the 6–8 s timeouts dominate), and it also delays `get_album_details` (`core/api.py:2264`) and artist-profile previews (`core/api.py:3508`), which share the same 6-worker executor.
- **User impact:** Search appears to hang for seconds on a normal query; the app also issues a burst of provider traffic per keystroke (YouTube Music / Spotify / SoundCloud API calls), which is both slow and a rate-limit risk for the provider accounts.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/search.js:109-113
  searchDebounce = setTimeout(() => {
      allResults = [];
      currentSearchQuery = query;
      runSearchQuery(query);
  }, 200);
  ```
  ```python
  # core/api.py:2094-2096  — generation only suppresses RESULTS, not work
  def is_current():
      with self._search_lock:
          return generation == self._search_generation
  ```
  ```python
  # core/api.py:2168-2171  — a task that was current when it STARTED runs to completion
  def _run_provider(name):
      if not is_current():
          mark_done(name)
          return
  ```
  ```python
  # core/api.py:363 / 2197
  self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")
  _timeout = 8.0 if name == "soundcloud" else PROVIDER_SEARCH_TIMEOUT   # 6.0 s
  ```
- **Reproduction / verification:** Open the Search page, ensure the source is "Все площадки", and type "radiohead" at a human cadence (≈300 ms/keystroke). In DevTools → Network, observe one `search` bridge call **per character**. In `~/.nedotify/logs/app.log` the provider requests for the intermediate generations are still running after the final keystroke. With a throttled/slow network the "Поиск..." spinner in `#search-results` stays for ~6 s after the last character. Instrumented alternative: count `_run_provider` entries in `core/api.py` for one typed query — the count equals the number of characters, not 1.
- **Suggested fix:** Two directions, both needed. (i) Backend (owner: **WN-06**): give each search generation a cancellation token and have `_run_provider`/the provider HTTP calls abort when their generation is superseded, and/or use a per-request executor that can be drained. (ii) Frontend (this area): raise the debounce to a value above the human inter-keystroke interval (≈350–450 ms) and/or require an explicit submit (Enter) for the full fan-out while keeping a cheap local-only preview.
- **Fix side effects:** A longer debounce makes the results feel laggier for fast typists; cancelling provider requests may change provider-side cache/latency behaviour and could interact with `BaseMusicService._join_request` single-flight bookkeeping (rule #2 of the codebase brief) — the cancellation must not leave `_search_cache`/`_stream_cache` in an inconsistent state.
- **Discovered by:** A

---

#### F-WN-31-2  [P2] — The "Плейлисты" type filter fabricates playlist tiles out of plain track results (hard-coded "10 треков"), and the play button on those tiles is a dead end

- **File:** `ui/web_new_v2/js/search.js:406-434` (fabrication), `ui/web_new_v2/js/search.js:415-424` (synthetic object), `ui/web_new_v2/js/search.js:818-856` (`playPlaylist`), `ui/web_new_v2/js/search.js:841-847` (dead fallback), `ui/web_new_v2/js/search.js:351-353` (the query guard that swallows the fallback), `core/api.py:2219-2223` (the `TypeError` fallback that drops `result_type`), `services/spotify_service.py:124` (`is_album_search` only special-cases albums), `services/soundcloud_service.py:295` (no `result_type` parameter at all)
- **Confirmed:** yes
- **Description:** The backend only honours `result_type='playlists'` for the local provider (`core/database.py:1445-1468`, rows carry `type: 'playlist'`) and for YouTube (`services/youtube_service.py:408-426`, rows carry `type: 'playlist'`). Spotify ignores the flag (`services/spotify_service.py:124` tests only `("albums","album")`, so `'playlists'` falls into the **track** branch) and SoundCloud does not even accept the keyword (`services/soundcloud_service.py:295` has no `result_type` parameter → `core/api.py:2222-2223` catches the `TypeError` and re-issues the search **without** it, returning plain tracks). The frontend's `currentType === 'playlists'` branch then *converts every non-playlist result* into a synthetic playlist object with `track_count: t.track_count || 10` and renders it as a playlist tile. The `albums` branch right below it (`search.js:436-447`) does the right thing — it filters on `item.type !== 'album'` and drops foreign rows — so the two branches disagree.
- **Cause:** The frontend assumes the backend honours `result_type` for every provider and compensates by inventing data instead of discarding it. The `resultKey`/`data.type` guard (`search.js:355`) compares the *request-level* `result_type` ("playlists") against `currentType` ("playlists") and therefore lets Spotify/SoundCloud **track** rows through.
- **Trigger conditions:** Search page → source "Все площадки" (the default) → type filter "Плейлисты" → any query. Requires the Spotify or SoundCloud provider to answer (they are in `requested_providers`, `core/api.py:2100`).
- **User impact:** The tab shows tiles that look like playlists but are actually songs, each labelled "10 треков" (fabricated). Clicking ▶ on such a tile calls `get_playlist_tracks(<track source_id>, 'spotify')` → `core/api.py:2576-2577` returns `{"success": false, ...}` → `tracks` is empty → the fallback `window.pywebview.api.search(playlist.title, source)` (`search.js:845`) is issued → the backend answers through the `search_results` event, and `onSearchResults` **drops it** because `data.query !== currentSearchQuery` (the playlist title is not the current query). Net effect: **absolutely nothing happens** — no playback, no toast, no error.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/search.js:413-425
  const key = String(t.source_id || t.id || idx);
  if (!playlistMap.has(key)) {
      playlistMap.set(key, {
          id: t.id || `playlist_${idx}`,
          title: t.title || 'Плейлист',
          ...
          type: 'playlist',
          track_count: t.track_count || 10      // <-- fabricated
      });
  }
  ```
  ```js
  // ui/web_new_v2/js/search.js:841-847  — the fallback result is unreachable
  } else {
      // Fallback: search query for playlist title
      const q = (playlist.title || playlist.name || '').trim();
      if (q && window.pywebview?.api?.search) {
          window.pywebview.api.search(q, source);
      }
  }
  ```
  ```js
  // ui/web_new_v2/js/search.js:351-353  — why the fallback never shows up
  if (data.query && data.query !== currentSearchQuery) {
      return; // Stale result — ignore
  }
  ```
  ```python
  # core/api.py:2219-2223  — SoundCloud loses result_type and returns tracks
  elif result_type:
      try:
          srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error)
      except TypeError:
          srv.search(query, callback=_on_success, error_callback=_on_error)
  ```
- **Reproduction / verification:** Search page → source "Все площадки" → filter "Плейлисты" → search e.g. "rock". Observe tiles whose titles are song titles and whose subtitle reads "10 треков" (count of the tracks). Click ▶ on one: no playback starts and no toast appears (the fallback search's results are dropped by the query guard). Cross-check with the backend: in the same session, set the source to "YouTube Music" — the same filter then shows only real playlist tiles, because only YouTube honours `result_type='playlists'`.
- **Suggested fix:** In `renderResults`, mirror the `albums` branch: drop rows whose `type !== 'playlist'` instead of synthesising them, and never invent `track_count`. Separately, make `playPlaylist` show a toast when the playlist resolves to zero tracks (and, if the fallback search is kept, give it a request id so `onSearchResults` can accept it). Backend-side (owner **WN-21**): teach Spotify/SoundCloud `result_type='playlists'`, or have `core/api.py` filter the provider rows by `type` before emitting them for `result_type in ('playlists','albums')`.
- **Fix side effects:** The Плейлисты tab will show fewer results until the providers learn `result_type='playlists'`; users who relied on the (broken) tile → search fallback would see an explicit "плейлист недоступен" message instead of silence.
- **Discovered by:** A

---

#### F-WN-31-3  [P2] — "Топ исполнителей" tiles navigate to the Search page but never run the artist search (the click handler writes `window.appConfig.searchQuery`, which nothing reads)

- **File:** `ui/web_new_v2/js/home.js:869-881`
- **Confirmed:** yes
- **Description:** `renderTopArtists` wires the artist tile click to a handler that stores the artist name in `window.appConfig.searchQuery` and navigates to the Search page. A grep over the whole `ui/web_new_v2` tree finds **only the two writes** (`home.js:870-871`) and **no reader** — `window.appConfig.searchQuery` is dead state. The sibling implementation in the same file, `renderArtists` (`home.js:673-680`), does it correctly: it sets `#search-input`.value and dispatches an `input` event, which makes the search actually run.
- **Cause:** The two home sections that display artist names were implemented separately; the "Топ исполнителей" one was never wired to the search input and relies on a config field that no consumer reads.
- **Trigger conditions:** Home page → "Топ исполнителей (Local Last.fm)" section → click any artist tile. The section is populated from `data.analytics.top_artists` (`core/api.py:3301`, `core/database.py:1708-1721`), so at least one played track is required.
- **User impact:** The user clicks an artist, the app switches to the Search page, and the search box is **empty** with the "Введите запрос для поиска музыки" placeholder — the artist is not searched at all. The action looks broken.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/home.js:869-881
  card.onclick = () => {
      window.appConfig = window.appConfig || {};
      window.appConfig.searchQuery = artistName;          // <-- written, never read
      document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
      const searchNav = document.querySelector('[data-page="search"]');
      if (searchNav) searchNav.classList.add('active');
      if (window.NeDotify && window.NeDotify.showPage) {
          window.NeDotify.showPage('search');
      } else {
          const searchTab = document.getElementById('tab-search');
          if (searchTab) searchTab.click();
      }
  };
  ```
  ```js
  // ui/web_new_v2/js/home.js:673-680  — the correct sibling implementation
  card.addEventListener('click', () => {
      const input = document.getElementById('search-input');
      if (input) {
          input.value = artistName;
          if (window.showPage) window.showPage('search');
          input.dispatchEvent(new Event('input', { bubbles: true }));
      }
  });
  ```
  ```powershell
  # grep -rn "appConfig" ui/web_new_v2
  ui/web_new_v2/js/home.js:870:            window.appConfig = window.appConfig || {};
  ui/web_new_v2/js/home.js:871:            window.appConfig.searchQuery = artistName;
  # -> no reader anywhere
  ```
- **Reproduction / verification:** Play at least one track so `get_top_artists` returns a row, open Home, scroll to "Топ исполнителей (Local Last.fm)" and click a tile. The app navigates to Search with an empty input. Cross-check: the "Исполнители" section further down the same page (`renderArtists`) *does* populate and run the search when its tile is clicked — same page, two different behaviours.
- **Suggested fix:** Replace the `appConfig` write with the `renderArtists` pattern (set `#search-input`.value + dispatch `input`), and route both sections through one shared "open artist in search" helper so they cannot drift again.
- **Fix side effects:** None — the tile currently does nothing useful, so wiring it up can only add behaviour. Note that the artist tile will then start a track search for the artist name (not an artist profile), which is what the "Исполнители" section already does.
- **Discovered by:** A

---

#### F-WN-31-4  [P2] — Inline `onerror` handlers on the album/playlist cover images are dead under the app's CSP, so broken covers render as broken-image icons instead of the intended fallback

- **File:** `ui/web_new_v2/js/search.js:546`, `ui/web_new_v2/js/search.js:769`, `ui/web_new_v2/js/search.js:682`, `ui/web_new_v2/js/search.js:879`; CSP at `ui/web_new_v2/index.html:10`
- **Confirmed:** yes
- **Description:** The four cover `<img>` elements emitted by `renderAlbumGrid`, `renderPlaylistGrid`, `openAlbumModal` and `openPlaylistModal` carry an inline `onerror="this.onerror=null;this.style.display='none'"` attribute. The app's Content-Security-Policy is `script-src 'self'` **without** `'unsafe-inline'`, so inline event-handler attributes are blocked and the handler never runs. The codebase already knows this — `utils.js:545-548` states it explicitly ("It replaces inline onload/onerror attributes, which `script-src 'self'` (no 'unsafe-inline') silently blocks") and replaced them with the delegated capture-phase `error` listener (`utils.js:533-543`) plus `coverImgHtml()` (`utils.js:522-530`). `search.js` was never migrated.
- **Cause:** The CSP forbids inline handlers; only the centralised helper honours that constraint. The album/playlist renderers still hand-write raw `<img>` markup.
- **Trigger conditions:** Any album or playlist card whose cover URL fails to load — a stale local `cover_path` after a library move, a dead YouTube thumbnail, an expired CDN URL, or simply an offline machine (`core/proxy.py` cover endpoint unreachable).
- **User impact:** Instead of the image being hidden, the browser paints its broken-image glyph: a small torn-image icon over the gradient fallback in the album/playlist grid, and a 110×110 broken icon in the album/playlist detail modal. The code also emits `src=""` when there is no cover (`escapeHtml('')`), which under CSP/`img-src` triggers a same-page request — the exact problem `coverImgHtml` documents at `utils.js:520-521`.
- **Evidence:**
  ```html
  <!-- ui/web_new_v2/index.html:10 -->
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; ...">
  ```
  ```js
  // ui/web_new_v2/js/search.js:546  (and :769, :682, :879)
  ${cover ? `<img src="${escapeHtml(cover)}" alt="" onerror="this.onerror=null;this.style.display='none'" style="width:100%;height:100%;object-fit:cover;...">` : ''}
  ```
  ```js
  // ui/web_new_v2/js/utils.js:545-548  — the codebase's own statement of the rule
  // 'load' also does not bubble, so it needs the same capture-phase delegation.
  // It replaces inline onload/onerror attributes, which `script-src 'self'`
  // (no 'unsafe-inline') silently blocks: #mp-cover ships with display:none and
  // an inline onload that could never run.
  ```
- **Reproduction / verification:** Search page → filter "Альбомы" → pick an album whose `cover_url` 404s (or block `i.ytimg.com` in DevTools → Network). The broken-image glyph appears in the grid; the WebView2 console logs "Refused to execute inline event handler because it violates the following Content Security Policy directive: script-src 'self'". Same for a playlist card and for both detail modals.
- **Suggested fix:** Replace the four hand-written `<img>` elements with `coverImgHtml()` from `utils.js` (it escapes the URL, skips an empty `src`, and wires the delegated error fallback through `data-cover-url`/`data-source-id`/`data-source`).
- **Fix side effects:** `coverImgHtml` adds the remote-cover fallback chain, which means a broken local cover will now try the remote URL before hiding — a small extra network request in the failure path. The `data-cover-url` attribute must remain populated for the fallback to work.
- **Discovered by:** A

---

#### F-WN-31-5  [P3] — `api()` resolves with `undefined` when the bridge is absent, so the search spinner never resolves and no error is shown

- **File:** `ui/web_new_v2/js/search.js:1092-1096` (`api`), `ui/web_new_v2/js/search.js:1083-1089` (the only error handler), `ui/web_new_v2/js/search.js:947-956` (`showLoading`)
- **Confirmed:** yes (code path); low reachability in the current boot order
- **Description:** `api()` returns `undefined` when `window.pywebview` or `window.pywebview.api` is missing. `runSearchQuery` wraps the call in `Promise.resolve().then(() => api(...)).catch(...)`, so the promise **fulfils** with `undefined` and the `.catch()` that renders "Не удалось выполнить поиск / Проверьте подключение" never runs. The backend was never called, so the `search_completed` sentinel is never emitted either and the `__completion__` branch of `onSearchResults` never runs — the spinner installed by `showLoading()` stays on screen forever with no error, no retry button and no console message.
- **Cause:** A missing bridge is treated as a successful, empty result instead of an error. `search.js` is the only bridge consumer in this area that does **not** wait for the bridge: `home.js:111`, `home.js:896` and `search-discovery.js:71` all `await window.awaitBridge()` first, and `main.js:29-31` documents that "Cold WebView2 starts can take ~16 s to inject the bridge".
- **Trigger conditions:** The Search page being used before `window.pywebview.api` is injected, or after the bridge object is replaced/reset. In the current boot order `initSearch()` runs after `awaitBridge()` (`main.js:353-354` → `main.js:533`), so the window is narrow — but the failure mode is silent and unrecoverable, and `initSearch()` can also be reached from a hot-reloaded/dev-preview WebView where the bridge never appears at all.
- **User impact:** An eternal "Поиск..." spinner. The user cannot tell that anything went wrong and there is no way to retry.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/search.js:1092-1096
  function api(method, ...args) {
      if (window.pywebview && window.pywebview.api) {
          return window.pywebview.api[method](...args);
      }
      // <-- falls through with `undefined` when the bridge is missing
  }
  ```
  ```js
  // ui/web_new_v2/js/search.js:1083-1089
  Promise.resolve().then(()=>api('search',query,source,type==='all'?null:type)).catch(()=>{
      if(query!==currentSearchQuery || type!==currentType || source!==currentSource) return;
      ... container.innerHTML='<div class="search-discovery-empty"><strong>Не удалось выполнить поиск</strong>...'
  });
  ```
- **Reproduction / verification:** In the WebView2 DevTools console run `delete window.pywebview;` (or `window.pywebview = {}`), then type a query in the Search box. The container keeps the "Поиск..." spinner indefinitely; the console shows no error and no "Не удалось выполнить поиск" banner. (In a normal install the bridge is present, so this must be simulated.)
- **Suggested fix:** Make `api()` throw (or return `Promise.reject`) when the bridge is missing, and/or `await window.awaitBridge()` at the top of `runSearchQuery` before calling the bridge, exactly like `home.js` does.
- **Fix side effects:** With a missing bridge the user would see the error banner and a "Повторить" button instead of an endless spinner — strictly better. The retry handler calls `runSearchQuery(query)` again, so it must also work when the bridge appears later.
- **Discovered by:** A

---

#### F-WN-31-6  [P3] — `openAlbumModal` interpolates `album.year` into `innerHTML` without escaping — the only unescaped field in that template; the value originates from a third-party provider and is persisted unvalidated

- **File:** `ui/web_new_v2/js/search.js:686` (unescaped), `ui/web_new_v2/js/search.js:682-685` (the escaped siblings), `ui/web_new_v2/js/search.js:883` (same pattern for `playlist.track_count`), `core/database.py:1427` (`MAX(year) as year` returned by `search_albums`), `core/database.py:1275` (`year=track_data.get("year")` — no coercion), `services/youtube_service.py:440`, `services/spotify_service.py:69` + `:134`, `services/artist_service.py:376`
- **Confirmed:** yes for the unescaped interpolation; **hypothesis** for exploitability
- **Description:** In the album detail modal every interpolated value is passed through `escapeHtml()` (`cover_url` at :682, `title` at :684, `artist` at :685) — except `album.year` and `album.track_count`, which are interpolated raw at :686. `album.year` is provider-supplied: `services/youtube_service.py:440` (`year = item.get("year") or ""`), `services/spotify_service.py:69` (`:134`), `services/artist_service.py:376`; it is persisted verbatim by `core/database.py:1275` (`year=track_data.get("year")`, no `int()` coercion) into the `tracks.year` column and returned by `db.search_albums` as `MAX(year) as year` (`core/database.py:1427`). The column is declared `year INTEGER` (`core/database.py:231`), but SQLite's INTEGER affinity keeps a non-numeric TEXT value as TEXT.
- **Cause:** A single field was missed when the template was converted to `escapeHtml()`; the rest of the template is correct, which is why this is an inconsistency rather than a pattern.
- **Trigger conditions:** A provider (or a local file tag, via `utils/tag_parser.py:76`, which does coerce to `int`) supplies a non-numeric year string for an album that has rows in the local library.
- **User impact:** Markup inside the year string is parsed as HTML in the album modal (e.g. it can inject elements / event handlers into the app document). With today's providers the observable year values are 4-digit strings, so the practical exposure is low — the defect is the missing escape, not a proven live injection.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/search.js:684-686
  <div style="font-size:20px; font-weight:800; color:#fff; ...">${escapeHtml(album.title || 'Альбом')}</div>
  <div style="font-size:14px; color:var(--text-sec);">${escapeHtml(album.artist || 'Исполнитель')}</div>
  <div style="font-size:12px; color:var(--text-sec); opacity:0.8;">${album.year ? album.year + ' г. • ' : ''}${album.track_count ? album.track_count + ' треков' : 'Альбом'}</div>
  ```
  ```python
  # core/database.py:1275 — provider value stored without coercion
  year=track_data.get("year"),
  # core/database.py:1427 — read back into the album row the UI renders
  SELECT album as title, artist, cover_path, cover_url, COUNT(id) as track_count, MAX(year) as year, 'local' as source, 'album' as type
  ```
- **Reproduction / verification:** Insert a library row whose `year` is a string (e.g. `UPDATE tracks SET year='<img src=x onerror=alert(1)>' WHERE id=<n>` in a copy of the DB), then search that album in the Albums tab and open the detail modal — the injected element is created in the document. This proves the missing escape; proving that a live provider can supply such a value would require a provider that returns a non-numeric `year`/`releaseDate` prefix (the currently observed values are `"2019"`-style).
- **Suggested fix:** Wrap `album.year` and `album.track_count` in `escapeHtml()` like every sibling field (same for `playlist.track_count` at `search.js:883`). Optionally coerce `year` to an integer in the provider normalisers (`services/youtube_service.py:440`, `services/spotify_service.py:69`).
- **Fix side effects:** None — the rendered text is identical for numeric values.
- **Discovered by:** A

---

#### F-WN-31-7  [P3] — The decorative particle layer is not hidden from assistive technology, unlike the other decorative layers in the same document

- **File:** `ui/web_new_v2/js/particles.js:301-305` (canvas creation), `ui/web_new_v2/index.html:76` (`<div id="particles-bg"></div>`), `ui/web_new_v2/index.html:77-78` (the decorated siblings), `ui/web_new_v2/css/components/base.css:1722-1731`
- **Confirmed:** yes
- **Description:** The particle canvas is created at runtime and carries no `aria-hidden` / `role="presentation"`, and its container `#particles-bg` has no `aria-hidden` either. The two immediately adjacent decorative layers in the same document — `#macos-backdrop` and `#macos-drag-region` — both carry `aria-hidden="true"` (`index.html:77-78`), so this is an inconsistency with the document's own convention. The canvas is also not focusable, but screen readers still announce a non-labelled graphic region inside the application landmark.
- **Cause:** The container was added to the markup without the `aria-hidden` attribute and the runtime-created canvas inherits the omission.
- **Trigger conditions:** Always (whenever particles are enabled).
- **User impact:** Screen-reader users hear an unlabelled graphic/canvas element at the top of every page.
- **Evidence:**
  ```html
  <!-- ui/web_new_v2/index.html:76-78 -->
  <div id="particles-bg"></div>
  <div id="macos-backdrop" aria-hidden="true"></div>
  <div id="macos-drag-region" class="pywebview-drag-region" aria-hidden="true"></div>
  ```
  ```js
  // ui/web_new_v2/js/particles.js:301-305
  canvas = document.createElement('canvas');
  canvas.id = 'particles-canvas';
  canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none !important;display:block;';
  ```
- **Reproduction / verification:** Enable particles, open the app with a screen reader (or inspect the accessibility tree in DevTools → Elements → Accessibility): the canvas appears as a graphic node with no name, whereas `#macos-backdrop` is hidden.
- **Suggested fix:** Add `aria-hidden="true"` to `#particles-bg` in `index.html` and set `canvas.setAttribute('aria-hidden','true')` when the canvas is created.
- **Fix side effects:** None — the layer is purely decorative and already `pointer-events: none`.
- **Discovered by:** A

---

#### F-WN-31-8  [P3] — The particle count is a fixed cap, independent of the canvas area and of `devicePixelRatio`, so the effect is effectively invisible on a large display and over-dense in a small window

- **File:** `ui/web_new_v2/js/particles.js:385` (count), `ui/web_new_v2/js/particles.js:309-331` (canvas sizing), `ui/web_new_v2/js/particles.js:36` (`isLowEndDevice`), `ui/web_new_v2/index.html:1493` (slider `min=5 max=80 value=30`)
- **Confirmed:** yes
- **Description:** The particle budget is chosen purely from the device's core count:
  `particleCount = isLowEndDevice() ? Math.min(rawCount, 25) : Math.min(rawCount, 80);`
  It is never scaled by the canvas area (`cssW * cssH`) or by `devicePixelRatio`. The backing store *is* DPR-correct (`sizeCanvasForDpr`, `utils.js:382`) and the sprites are re-rasterised per DPR (`registerCanvasDprListener`, `particles.js:344-347`), so the *rendering* is sharp — but the *density* is not.
- **Cause:** The count is a user setting (slider 5–80) treated as an absolute number rather than a density.
- **Trigger conditions:** Always; the effect is most visible on 4K/large displays (the same 30–80 particles spread over 3840×2160 CSS px, i.e. 7680×4320 device px, are effectively invisible) and on small windows (the same 80 particles in a 500×400 window are a blizzard).
- **User impact:** The decorative background either disappears on large monitors or dominates small ones; the particle count slider has an inconsistent meaning across window sizes.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/particles.js:385
  particleCount = isLowEndDevice() ? Math.min(rawCount, 25) : Math.min(rawCount, 80);
  ```
  ```js
  // ui/web_new_v2/js/particles.js:309-318  — the AREA is known, the count does not use it
  const performResize = () => {
      ...
      const newW = window.innerWidth;
      const newH = window.innerHeight;
      sizeCanvasForDpr(canvas, ctx, newW, newH);
      cssW = newW;
      cssH = newH;
  ```
- **Reproduction / verification:** Open the app on a 4K display with particles at the default 30 → the background is visually empty; then resize the window to 500×400 → the same 30 particles fill it densely. The count in `particles.length` (devtools) is unchanged across the resize.
- **Suggested fix:** Derive the effective count from the canvas area (e.g. `clamp(round(cssW * cssH / AREA_PER_PARTICLE), min, max)`) and re-derive it in `performResize()`; keep the slider as a density multiplier.
- **Fix side effects:** More particles on large displays increases the per-frame draw cost; the existing `targetFps` throttle (24 fps) and the low-end-device cap would need to be reconciled with the new density.
- **Discovered by:** A

---

#### F-WN-31-9  [P3] — The search results have no pagination and no "load more": `core/api.py::search` accepts no offset/limit and `search.js` installs no scroll handler, so results are hard-capped at the provider's first page

- **File:** `ui/web_new_v2/js/search.js:1075-1090` (`runSearchQuery` — the request carries only `query`, `source`, `result_type`), `ui/web_new_v2/js/search.js:470-506` (`SEARCH_BATCH_SIZE = 30` — a *render* batch, not a page), `core/api.py:2077` (`def search(self, query, source="all", result_type=None)`), `services/youtube_service.py:370` (`max_results=20`), `services/spotify_service.py:110` (`limit=20`), `core/database.py:1366` (`search_tracks(..., limit=50)`)
- **Confirmed:** yes
- **Description:** The search request carries no pagination parameters and the backend exposes none, so a search returns at most one page per provider (≈20 YouTube + 20 Spotify + 20 SoundCloud + 50 local rows). `renderSearchResultsBatch` (`search.js:472-506`) renders the collected rows in rAF-sized chunks of 30 — that is a *rendering* batch to avoid a long synchronous layout, **not** pagination: there is no sentinel, no "Показать ещё" button, and no scroll listener anywhere in `search.js`/`home.js` (grep for `scroll` in the area's files returns only the CSS class `feed-scroll`).
- **Cause:** Pagination was never implemented on either side of the bridge; the UI renders whatever the first page contains.
- **Trigger conditions:** Any search whose result set exceeds the provider page size (very common for broad queries).
- **User impact:** The user cannot reach results beyond the first page of each provider and has no indication that more exist — the list simply ends. There is also no way to refine into the tail of a result set.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/search.js:1083
  Promise.resolve().then(()=>api('search',query,source,type==='all'?null:type)).catch(...)
  // -> only 3 arguments; no offset / limit / page
  ```
  ```python
  # core/api.py:2077
  def search(self, query: str, source: str = "all", result_type: str = None):
  ```
  ```js
  // ui/web_new_v2/js/search.js:470-472  — a render batch, not a page
  const SEARCH_BATCH_SIZE = 30;
  function renderSearchResultsBatch(container, displayTracks) { ... }
  ```
- **Reproduction / verification:** Search for a very broad term (e.g. "rock") with the source "Все площадки". Count the rendered rows: it saturates at the sum of the provider page sizes; scrolling to the end of `#search-results` never loads more, and no "more" affordance exists. Cross-check the backend logs: exactly one `search` round per provider is performed.
- **Suggested fix:** Add `offset`/`limit` to `core/api.py::search` and a "Показать ещё"/infinite-scroll trigger in `search.js` that appends the next page (the frontend already has the machinery: `allResults` accumulates and `renderResults` re-renders).
- **Fix side effects:** `core/api.py::search` is used by WX-05 and by `artist_profile.js::fetchArtistTracks` (`artist_profile.js:118`, `api.search(artistName,'all')`), which relies on the current one-shot behaviour; adding pagination must not break the artist-track collection that listens to `app:search_results`.
- **Discovered by:** A

---

#### F-WN-31-10  [P3] — Every navigation back to the Home page re-runs the full external feed fan-out, and `get_playlists()` is fetched twice per Home load

- **File:** `ui/web_new_v2/js/home.js:110-213` (`loadHome`), `ui/web_new_v2/js/home.js:176-193` (the staggered feed requests), `ui/web_new_v2/js/pages.js:166` (`if (pageId === 'home' && window.NeDotify.loadHome) window.NeDotify.loadHome();`), `ui/web_new_v2/js/main.js:85` (`loadHome` exposed as `window.NeDotify.loadHome`), `ui/web_new_v2/js/home.js:144` (direct `get_playlists()`), `core/api.py:3307` (`get_home_data()` already calls `self.get_playlists()`)
- **Confirmed:** yes
- **Description:** `showPage('home')` calls `loadHome()` **without** the `isTrackChange` argument, so `shouldLoadFeeds` is `true` and all four external feeds (`get_popular_tracks`, `get_feed`, `get_home_releases`, `get_home_mixes`) are re-requested on every single navigation to the Home page. In addition, `loadHome` calls `window.pywebview.api.get_playlists()` explicitly (`home.js:144`) although `get_home_data()` — which it has already awaited at `home.js:118` — already returns `playlists` (`core/api.py:3307`).
- **Cause:** The `isTrackChange` flag exists to suppress feed refreshes, but only the event-driven path (`events.js:229`, `loadHome(nextTrackChange)`) uses it; the page-navigation path does not. The second `get_playlists()` is a leftover from before `get_home_data()` started returning playlists.
- **Trigger conditions:** Any navigation to Home (sidebar click, `window.showPage('home')`), and any `library_updated`/`favorites_updated`/`playlists_changed` burst.
- **User impact:** Each Home visit issues 4 extra provider round-trips that are thrown away and re-rendered a moment later; on a slow connection the Home page re-populates its feed sections from scratch every time, and the recommendation service is polled far more often than needed.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/pages.js:166
  if (pageId === 'home' && window.NeDotify.loadHome) window.NeDotify.loadHome();
  ```
  ```js
  // ui/web_new_v2/js/home.js:166-193
  let shouldLoadFeeds = !isTrackChange;
  if (isTrackChange) { trackChangeCount++; if (trackChangeCount >= 10) { trackChangeCount = 0; shouldLoadFeeds = true; } }
  if (shouldLoadFeeds) {
      requestHomeSection('home-popular', 'get_popular_tracks');
      ...
      requestHomeSection('home-mixes', 'get_home_mixes', [10]);
  }
  ```
  ```python
  # core/api.py:3307  — get_home_data already fetches the playlists
  "playlists": self.get_playlists(),
  ```
- **Reproduction / verification:** Open Home, navigate to Library and back to Home; in DevTools → Network (or by instrumenting `window.pywebview.api`) count `get_popular_tracks` / `get_feed` / `get_home_releases` / `get_home_mixes` calls — one full set per visit. In the same session count `get_playlists` calls per `loadHome` — two.
- **Suggested fix:** Drop the redundant `get_playlists()` call at `home.js:144` (use `data.playlists` from `get_home_data()`), and let the Home navigation path reuse the previously rendered feeds (e.g. only reload them when stale or when explicitly refreshed via `app:refresh_home`), or pass `isTrackChange=true` from `showPage`.
- **Fix side effects:** The Home page would show slightly staler feed sections between visits; the explicit refresh affordances (`app:refresh_home`, the "Повторить" buttons) must still force a reload.
- **Discovered by:** A

---

### 3. Clean areas

Checked and found **correct** — no findings raised:

- **Search debounce cancellation.** `clearTimeout(searchDebounce)` is executed on every path that supersedes a pending search: the `input` handler (`search.js:100`), the Enter handler (`search.js:83`), the clear button (`search.js:123`), the type-filter handler (`search.js:214`), `searchArtistProfile` (`search.js:303`) and `startSuggestedSearch` (`search.js:1036`). No orphaned timer can fire a stale query.
- **Stale-result rejection.** `onSearchResults` rejects on three independent axes: the query string (`search.js:332` and `search.js:351-353`), the artist-profile mode (`search.js:348-350`) and the `resultKey` reset (`search.js:361-365`, which deliberately uses `currentSource` and not `data.source` so that the per-provider chunks of a `source='all'` search accumulate instead of clearing each other). The backend adds a second, independent layer: `core/api.py:2090-2096` keeps a `_search_generation` and `emit_results`/`mark_done` drop superseded generations. The `resultKey` comment at `search.js:356-360` documents exactly this and matches the implementation.
- **Empty / loading / "no results" / error states.** Empty query → `showPlaceholder()` (`search.js:987-998`, with the discovery panel restored). Loading → `showLoading()` (`search.js:947-956`). "No results" → the `__completion__` sentinel branch (`search.js:334-346`) replaces the spinner only when `container.querySelector('.spinner')` is present and `allResults.length === 0`; a partial result set keeps the list. Error → the `.catch()` in `runSearchQuery` (`search.js:1083-1089`) renders "Не удалось выполнить поиск" **with a working "Повторить" button** (F-WN-31-5 covers the one gap: a *missing* bridge, not a *failing* call).
- **The `search_completed` sentinel contract.** `core/api.py:2129` emits `{"query", "source"}`; `events.js:135` rewrites `source` to `'__completion__'` and sets `type: data?.type || null`. `onSearchResults` handles the sentinel in its **first** branch (`search.js:334`), before the source/type filters — so the sentinel is never dropped by the per-provider filters. The backend guarantees exactly one completion per search (`core/api.py:2123-2129`, `completion_emitted` latch) and emits one immediately for the empty-provider case (`core/api.py:2131-2135`).
- **Filter / sort semantics vs the backend.** The type filter re-queries the backend (not a client-side filter) with `result_type` = `null | 'tracks' | 'playlists' | 'albums'`, matching `core/api.py:2143-2148` (`albums`→`db.search_albums`, `playlists`→`db.search_playlists`, otherwise `db.search_tracks`) and `services/youtube_service.py:381` (`playlists`/`albums` filters). The platform dropdown re-queries with `source`, matching `core/api.py:2099-2106`. The `albums` branch of `renderResults` correctly filters on `item.type === 'album'` (`search.js:439`), which is what the `playlists` branch fails to do (F-WN-31-2). The offline-mode filter `!(data.offline === true && data.source === 'local')` (`search.js:354`) matches `core/api.py:2085-2086` (offline forces `source='local'`).
- **Search suggestions.** `get_search_suggestions` is **not** fired per keystroke: it is called once per *completed* search from the sentinel branch (`search.js:344` → `offerSearchCorrections`, `search.js:1046-1073`) and is additionally guarded by `suggestionRequestKey` (`search.js:1049-1051`), so the request rate is bounded by the number of searches, not by typing. Its source can legitimately be empty — `utils/search_query.py:32-33` returns `[]` for queries shorter than 3 or longer than 120 characters, and `:85-86` returns `[]` when the query is an exact library title — and the frontend handles the empty case explicitly (`search.js:1057`). The returned shape `[{query, reason}]` matches `utils/search_query.py:51` and the JS reads `suggestion.query` / `suggestion.reason === 'layout'` (`search.js:1064-1067`). Stale suggestion responses are rejected on four axes (`search.js:1055`).
- **Correction-context banner.** `correctionContext` is set/cleared consistently (`search.js:1033-1044`), preserved across the suggested search via the `keepCorrection` flag (`search.js:1079`), and rendered only when it matches the current query (`search.js:1018`).
- **Result rendering vs `core/api.py::search` output.** The `search_results` payload is `{query, source, type, tracks, offline}` (`core/api.py:2111-2117`). The fields the UI reads from a track — `title`, `artist`, `album`, `duration`, `source`, `source_id`, `cover_url`, `cover_path`, `is_favorite`, `is_downloaded`, `file_path`, `track_id` — are all present in the provider rows (`services/youtube_service.py:490-498`, `services/spotify_service.py:152-161`) and in the local rows (`core/database.py:1366-1404` = `SELECT * FROM tracks`). `createTrackElement` (`utils.js:688-762`) escapes the title and the artist and uses the delegated `coverImgHtml` helper.
- **`play_track` contract.** `play_track(track, track_list, index)` (`core/api.py:1437`) itself performs the `track_id → id` normalisation for both the single track and every queue entry (`core/api.py:1455-1462`) and re-resolves a wrong index by `source_id` → `id` → title/artist (`core/api.py:1473-1500`), so the redundant normalisation in `home.js:779-780` is harmless and the index passed by `createFeedCard` is correct (`home.js:262-264` slices and indexes the *same* array it passes).
- **`get_playlist_tracks` return shape.** The method returns a **dict** `{"success": bool, "tracks": [...]}`, never a bare list (`core/api.py:2565`, `:2568`, `:2577`, `:2609`). All six call sites in this area handle that shape correctly (`search.js:832`, `search.js:911`, `home.js:238`, `home.js:475`, `home.js:550`, `home.js:386-389`). `home.js:386` is the only site that checks `res.success`, which is the stricter and correct form.
- **Home feed failure isolation.** Every external section is requested through `requestHomeSection` (`home.js:63-88`), which renders a skeleton, arms a 20 s watchdog, and on failure/timeout replaces the section with its own "Повторить" button (`home.js:53-61`) — one failing section never breaks the page. `loadHome` wraps `get_playlists` and `get_downloaded_tracks` in their own `try/catch` (`home.js:142-163`) and the whole function in a `try/catch` that surfaces `#home-error` (`home.js:208-212`). The `homeLoadGeneration` counter (`home.js:7`, `:114`, `:119`) discards a superseded load's results, including the cover-backfill re-render (`home.js:98-105`).
- **Home "play" action.** `createFeedCard` (`home.js:776-787`) calls `play_track(trackObj, trackList, trackIndex)` with the correct track dict and the correct list/index; `renderQuickAccess` (`home.js:230`) and `home-shell.js:33` normalise `track_id → id`; `renderTopTracks` (`home.js:838`) passes `(track, tracks, i)` correctly.
- **Home carousels / scroll.** The carousels are pure CSS (`#home-popular`, `#home-releases`, `#home-mixes`, `#home-artists`, `#home-history` are `.feed-scroll` in `index.html:226-334`); **there is no JS scroll listener in this area at all**, so there is nothing to throttle. The only window-level listener, `home.js:1008-1013`, is correctly throttled with `requestAnimationFrame` (`cancelAnimationFrame` + a single pending frame).
- **Particles — rAF lifecycle (the "background-tab CPU burn" question).** The loop **is** cancelled. `syncParticleAnimation` (`particles.js:51-61`) cancels the pending frame when the window is hidden, and it is wired to `visibilitychange` (`particles.js:63`) and to `nedotify:window_visibility_changed` (`particles.js:64`), which the backend emits from `_on_minimized` / `_on_restored` (`core/api.py:599-603`) and which `events.js:89-95` turns into the `window-hidden` class that `isWindowHidden()` reads (`particles.js:47-49`). The `animate` callback also self-terminates and clears `animFrameId` (`particles.js:475-478`) so it can be restarted. The efficiency module (`efficiency.js:98-159`) additionally pauses the effect when the window is unfocused, and the mini-player and macOS UI styles stop it too (`particles.js:52`, `:357`, `:475`).
- **Particles — canvas sizing / resize / DPR.** The backing store is DPR-scaled via `sizeCanvasForDpr` (`particles.js:317`, `utils.js:382`), the resize handler is debounced by 100 ms and rescales the particle coordinates (`particles.js:309-339`), the listener is removed by `cleanupListeners()` in `stopParticles()` (`particles.js:246-249`, `:373-380`), and a DPR change without a resize event re-rasterises the sprites and the backing store (`particles.js:344-347`).
- **Particles — `prefers-reduced-motion`.** Honoured twice: the JS returns early and never starts the loop (`particles.js:276-279`) and the CSS hides the layer entirely (`base.css:1733-1737`).
- **Particles — pointer events.** The canvas sets `pointer-events: none !important` inline (`particles.js:303`) and the container has `pointer-events: none !important` in CSS (`base.css:1725`), so the background cannot intercept clicks on the content.
- **XSS — text fields.** Every third-party string that reaches `innerHTML` in this area is escaped: `escapeHtml()` for titles, artists, playlist/album names and counts (`search.js:457`, `:554-556`, `:777-779`, `:684-685`, `:881-882`), `textContent` for the correction banner and the suggestions (`search.js:1024`, `:1027`, `:1061`, `:1067`), `escapeHtml()` for the search history and the genre chips (`search.js:1162-1175`), `coverImgHtml()` (escaped `src`) for all cover images, `artistAvatarHtml()` (`utils.js:574-579`), `getSourceIcon()` returns only constant SVG literals (`utils.js:960-969`), and `home.js` escapes every interpolated title/artist (`home.js:348-349`, `:378-379`, `:410-411`, `:738-739`, `:759-760`, `:834-835`, `:865-866`, `:934-935`). `search-discovery.js:38` escapes both the name and the cover URL. `home-shell.js:30` escapes the title and the artist. The **only** unescaped interpolation found in this area is `album.year` (F-WN-31-6).
- **CSS/URL injection.** `home.js:16-25` (`applyCoverBackground`) validates the scheme (`https:`/`data:` only) and assigns through the CSSOM `style.backgroundImage` property, so no HTML parsing is involved; `utils.js:40-50` (`safeCssImageUrl`) does the same for the `url()` grammar.
- **Bridge-method existence.** Every bridge method called from the five files of this area exists in `core/api.py` with a compatible signature — full cross-check table in the condensed report below. No call to a non-existent method was found.
- **`search-discovery.js` / `home-shell.js` ownership.** They do not duplicate the search-result rendering path: `search-discovery.js` owns the "Уже прослушано" discovery cards (a bespoke `search-listened-card`, not a track row) and `home-shell.js` owns the Home dialog/quick-access/continue-listening chrome. The shared track-row renderer is `createTrackElement` from `utils.js`, used by both (`search-discovery.js` does not use it, but `home-shell.js:56` and `search.js:729`/`:927` do), so there is no second, drifting implementation of the *same* track card. The three different visual presentations of history data (`home.js:262` feed card, `search-discovery.js:31` discovery card, `home-shell.js:56` track row) are three different UI contexts, not three implementations of one card. The genuine drift found in this area is between the two *artist* tiles (F-WN-31-3).
- **`artist_ref` / `context` plumbing.** `search.js:315` passes `context ? {context} : null` and `search-discovery.js:41` passes the history track; `core/api.py:3498-3501` and `services/catalog_service.py:105-107` expect exactly `artist_ref['context']` to be a track-like dict with `source`/`source_id` (`core/api.py:3470-3471`) — which a history row is. The contract holds.
- **Dead-but-harmless code.** `home.js:801-804` listens for `app:artists_ready`, which is never dispatched (the `artists_ready` Python event is handled directly in `events.js:179-185`); `home.js:292-431` (`renderAuthenticHome`) is reachable only through the `authentic_home_ready` event, and the producer `get_authentic_home_feed` (`core/api.py:3337`) is never called from the frontend. Neither causes a runtime error.

---

### 4. Coverage gaps

- **pywebview's bridge threading model could not be verified locally.** `pywebview` is not installed in `.venv_win` (the `pywebview` package directory is absent), so I could not read `pywebview/js/api.js` to confirm whether `window.pywebview.api` methods depend on `this`. `home.js:76` (`const method = window.pywebview?.api?.[methodName]; ... method(...args)`) detaches the method from its owner; if pywebview's api object were `this`-dependent this would break the whole Home feed, which strongly suggests it is not — but this remains unverified. It is also why F-WN-31-1 is phrased around the *observable* delay rather than around a UI-thread freeze.
- **The exact thread on which a synchronous `js_api` method runs was not confirmed.** `core/api.py` comments refer to a "JS bridge thread" distinct from the WinForms UI thread (`:738`, `:784-785`), and `get_search_suggestions` (`core/api.py:4219-4221`) runs an unbounded synchronous scan (up to 600 library rows → up to 4000 candidate strings → pure-Python Levenshtein in `utils/search_query.py:92-98`) with no `BRIDGE_SYNC_BUDGET`, unlike `get_playlist_tracks` which caps its wait at 6 s (`core/api.py:2605`). I estimated the cost at tens of milliseconds and therefore did **not** raise it as a numbered finding, but the missing time budget is a latent risk if the library grows.
- **No runtime execution.** Per the audit ground rules the real app was not launched and no network provider was contacted, so the provider-specific behaviours asserted in F-WN-31-1 and F-WN-31-2 (Spotify/SoundCloud ignoring `result_type`) were verified by reading `services/spotify_service.py:110-173` and `services/soundcloud_service.py:295-330` plus the `TypeError` fallback at `core/api.py:2219-2223` — not by observing live responses. A live check would be: run a "Плейлисты" search and confirm that Spotify/SoundCloud rows lack a `type` field in the emitted `search_results` payload.
- **`artist_profile.js` (WN-32) was read only as far as the `artist_ref`/`context` contract required.** Its own render path, the `fetchArtistTracks` 5-second timeout and the `app:search_results` listener were not audited.
- **`js/utils.js` (WN-28) was read only for the helpers this area consumes** (`escapeHtml`, `coverImgHtml`, `getCoverUrl`, `createTrackElement`, `filterVisibleTracks`, `getSourceIcon`, the DPR helpers). The identical CSP/`onerror` problem exists inside `createTrackElement` (`utils.js:721`) — that instance belongs to WN-28 and is deliberately not reported here.
- **CSS was not audited** (WN-33). `#particles-bg` (`base.css:1722-1737`) was read only for the `pointer-events` and `prefers-reduced-motion` behaviour that the JS depends on.
- **`core/proxy.py` (WN-11) was not read**, so cover-image 404 behaviour (used as the trigger for F-WN-31-4) is inferred from the callers rather than verified at the proxy.
