## AREA WN-31 — UI search, discovery, home, particles — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read | Notes |
|---|---|---|
| `ui/web_new_v2/js/search.js` | 1–1250 (full) | 1250 physical lines (area map says 1122) |
| `ui/web_new_v2/js/search-discovery.js` | 1–127 (full) | |
| `ui/web_new_v2/js/home.js` | 1–1049 (full) | 1049 physical lines (area map says 955) |
| `ui/web_new_v2/js/home-shell.js` | 1–119 (full) | |
| `ui/web_new_v2/js/particles.js` | 1–557 (full) | 557 physical lines (area map says 479) |
| `ui/web_new_v2/js/utils.js` | 1–120, 440–509, 505–704, 705–834, 935–994, 1460–1499 | `escapeHtml`, `coverImgHtml`, `getCoverUrl`, `createTrackElement`, `artistAvatarHtml`, `renderPlaylistCoverCollage`, `filterVisibleTracks`, `renderIcons`, `safeCssImageUrl`, `offlineImageUrl`, `registerCanvasDprListener` |
| `ui/web_new_v2/js/lucide.min.js` | 110–164 | custom icon shim (`createIcons` semantics) |
| `ui/web_new_v2/js/events.js` | 130–209, 220–239 | bridge-event handlers that fill the home feed + `loadHome` re-entry |
| `ui/web_new_v2/js/pages.js` | 145–174 | `showPage` → `loadHome()` re-entry |
| `ui/web_new_v2/js/main.js` | grep only | `init()`/`safeInit` call sites (L533 `initSearch()`, L535 `initHomeShell()`, L540 `initParticles()`) |
| `ui/web_new_v2/js/efficiency.js` | 1–192 (full) | `nedotify:efficiency_state`, `window-hidden` |
| `ui/web_new_v2/index.html` | 1–40, 60–119 | CSP meta (L10), `#particles-bg` (L76) |
| `ui/web_new_v2/css/components/base.css` | 1715–1744 | `#particles-bg` rule (L1722–1731) |
| `core/api.py` | 1122–1181, 1437–1546, 2077–2266, 2513–2572, 3156–3195, 3293–3354, 3735–3814, 3910–3999, 4219–4228 | bridge contract for every method the 5 modules call |
| `core/database.py` | 1516–1555, grep on `year` | `update_track_metadata`, `tracks.year` column type |
| `services/spotify_service.py` | 55–154 | iTunes album search payload (`year`, `track_count`) |
| `services/youtube_service.py` | 400–469 | YT album/playlist payload (`year`, `track_count`) |
| `utils/tag_parser.py` | 55–94 | year coercion |
| `tests/test_search_discovery_ui.py` | 1–47 (full) | |
| `tests/test_search_query_suggestions.py` | 1–54 (full) | |
| `tests/test_frontend_js.py` | 1–318 (full) | |
| `tests/test_visual_effects_lifecycle.py` | 1–306 (full) | |

**Callees traced into other areas**

- `core/api.py` (WN-06 search, WN-09 home feed / albums / artists, WN-10 recommendations) — attributed to WN-06/WN-09/WN-10, not double-reported here.
- `core/database.py` (WN-12) — `tracks.year` column, `search_albums`, `get_playlists`.
- `services/spotify_service.py` / `services/youtube_service.py` (WN-21 / WN-19) — the *shape* of the album/playlist payloads.
- `js/utils.js` (WN-28) — `createTrackElement`, `coverImgHtml`, `escapeHtml`, `renderIcons`. This is the **shared component** the 5 modules should be using.
- `js/events.js` (WN-28) — the `search_results` / `search_completed` / `feed_ready` / `releases_ready` / `mixes_ready` / `popular_results` / `artists_ready` handlers.
- `js/pages.js` (WN-28) — `loadHome()` on every navigation to the home page.
- `js/artist_profile.js` (WN-32) — `loadArtistProfile` / `cancelArtistProfileRequests`, called by `search.js`.
- `js/library.js`, `js/library-view.js`, `js/smart-playlists.js` (WN-32) — read for the card-component duplication analysis only.
- `js/queue.js` (WN-29) — a further copy of the track row, for the duplication count.

**Explicitly not opened:** `android/**` (out of scope). `js/artist_profile.js` was not read in full (WN-32 owns it).

---

### 2. Findings

#### F-WN-31-1  [P2] — The whole search result list is rebuilt from scratch on every provider chunk (~2.5× the necessary DOM work)

- **File:** `ui/web_new_v2/js/search.js:378`, `ui/web_new_v2/js/search.js:399`, `ui/web_new_v2/js/search.js:472-506`
- **Confirmed:** yes
- **Description:** `onSearchResults()` accumulates results into the module-level `allResults` array and then calls `renderResults(allResults)` — i.e. it re-renders the *entire accumulated list* every time a new provider chunk arrives, not just the new rows. `renderResults` throws the container away (`container.innerHTML = ''`) and rebuilds every row from scratch.
- **Cause:** the renderer has no notion of "append the delta". `allResults` is push-ordered, so appending the new chunk would produce exactly the same DOM order as the full rebuild — the rebuild is pure waste.
- **Trigger conditions:** any search with `source='all'` (the default). The backend emits one `search_results` event per provider (`core/api.py:2108-2117`), each carrying up to 20 tracks (`services/spotify_service.py:110` → `limit: int = 20`; same default in `services/youtube_service.py`).
- **User impact:** for a 4-provider search that returns 80 rows, the UI constructs 20 → 40 → 60 → 80 rows, i.e. **200 `createTrackElement()` calls for 80 tracks**. Each call parses ~1.5 KB of `innerHTML` and installs 5 event listeners (`js/utils.js:718-748` + 751/767/795/818), and every rebuild also re-runs `renderIcons(list)` → `lucide.createIcons({root:list})` → a full `querySelectorAll('[data-lucide]')` subtree scan (`js/lucide.min.js:150`). Every `<img>` element is destroyed and re-created, so the browser re-issues the cover requests and re-does layout. The visible symptom is the list "jumping"/re-flickering as providers answer one after another.
- **Evidence:**
  ```js
  // search.js:366-380
  const incoming = Array.isArray(data.tracks) ? data.tracks : [];
  if (incoming.length > 0) {
      const filteredTracks = filterVisibleTracks(incoming);
      if (filteredTracks.length > 0) {
          const seen = new Set(allResults.map(trackDedupKey));
          for (const t of filteredTracks) { ...; allResults.push(t); }
          renderResults(allResults);      // <-- full rebuild, not the delta
          return;
      }
  }
  ```
  ```js
  // search.js:394-399
  if (!tracks || tracks.length === 0) { container.innerHTML = '...'; return; }
  container.innerHTML = '';              // <-- the whole list is thrown away
  ```
- **Reproduction / verification:** 1) start the app; 2) search for a popular term with the platform filter left at "Все площадки"; 3) open the WebView2 devtools (F12) → Performance → record while the results arrive; 4) observe 4 full `renderResults` passes and ~200 `createTrackElement` DOM subtrees. A DOM-mutation counter (`MutationObserver` on `#search-results`) reports the same 4× rebuild.
- **Suggested fix:** keep the rendered rows and append only the newly accepted chunk (the batch renderer already exists — `renderSearchResultsBatch`); render the artist-suggest banner / correction context once per request, not per chunk.
- **Fix side effects:** the batch renderer is currently tied to "render the whole list"; it would need a start index. The "Ничего не найдено" empty state and the offline note are also keyed off the container contents and would need to move to the completion sentinel.
- **Discovered by:** B

---

#### F-WN-31-2  [P2] — The 200 ms debounce guards only the network call; the results pane is destroyed on *every* keystroke

- **File:** `ui/web_new_v2/js/search.js:95-118` (handler), `ui/web_new_v2/js/search.js:108` (`showLoading()`), `ui/web_new_v2/js/search.js:947-956` (`showLoading`)
- **Confirmed:** yes
- **Description:** on every `input` event the module calls `showLoading()` **synchronously**, before the debounce timer is armed. `showLoading()` replaces the entire results container with a spinner. Only the *network* call is debounced (200 ms).
- **Cause:** the debounce was applied to `runSearchQuery` but the "show a spinner" side effect was left outside it, so the UI reacts to every character even though the query is not yet final.
- **Trigger conditions:** typing any query of 2+ characters, or editing an existing query.
- **User impact:** (a) a visible spinner flash per character, even though the previous results were still perfectly valid for the 200 ms window; (b) the previously rendered result list (up to 80 rows) and its **in-flight cover image loads are cancelled and thrown away on every keystroke**, then re-requested (from cache) and re-decoded when the final search returns; (c) combined with F-WN-31-1, the final list is then rebuilt again from scratch.
- **Evidence:**
  ```js
  // search.js:105-113
  if (query.length > 0) {
      const sugg = document.getElementById('search-suggestions-dropdown');
      if (sugg) sugg.classList.add('hidden');
      showLoading();                        // <-- runs on EVERY keystroke
      searchDebounce = setTimeout(() => {
          allResults = [];
          currentSearchQuery = query;
          runSearchQuery(query);
      }, 200);
  }
  ```
  ```js
  // search.js:947-956
  function showLoading() {
      if (searchBatchRafId) { cancelAnimationFrame(searchBatchRafId); searchBatchRafId = null; }
      const container = document.getElementById('search-results');
      if (container) { container.innerHTML = '<div class="empty-state"><div class="spinner"></div><span>Поиск...</span></div>'; }
  }
  ```
- **Reproduction / verification:** type a 10-character query slowly; watch the spinner appear/disappear once per character in the results pane, and watch the WebView2 Network panel re-request the cover images of the previously displayed rows after the final search completes.
- **Suggested fix:** move `showLoading()` (and the `allResults = []` reset) inside the debounce callback, or debounce the whole "query changed → UI reacts" transition; keep the *input* handler limited to the header layout / clear-button state.
- **Fix side effects:** the results of the previous query would stay visible for up to 200 ms — arguably better UX, but the user may briefly see stale results next to the new query text. The offline-mode note and the correction banner are re-rendered by `renderResults`, so they must still be cleared on the first keystroke.
- **Discovered by:** B

---

#### F-WN-31-3  [P2] — The album/playlist card grids hand-roll their `<img>` tags and therefore load every cover eagerly (no `loading="lazy"`)

- **File:** `ui/web_new_v2/js/search.js:546`, `ui/web_new_v2/js/search.js:682`, `ui/web_new_v2/js/search.js:769`, `ui/web_new_v2/js/search.js:879`
- **Confirmed:** yes
- **Description:** the shared helper `coverImgHtml()` (`js/utils.js:522-530`) is the project's one safe way to emit a cover image: it escapes the `src` and the `data-*` attributes, drops the URL in offline mode (`offlineImageUrl`), adds a `data-cover-url` fallback and — critically — emits `loading="lazy"`. The track row uses it too (`js/utils.js:721`). The four album/playlist `<img>` tags in `search.js` bypass it and are the **only** images in the 5 in-scope modules with no `loading="lazy"` (verified: `grep 'loading="lazy"' search.js` → no match).
- **Cause:** copy-paste of the cover markup instead of reusing `coverImgHtml` (see also F-WN-31-6).
- **Trigger conditions:** switching the search sub-type filter to "Альбомы" or "Плейлисты", or opening an album/playlist detail modal.
- **User impact:** the whole grid's artwork is fetched at once, at full resolution. The iTunes album path rewrites the 100×100 artwork URL to **600×600** (`services/spotify_service.py:71-72`: `raw_artwork.replace("100x100bb", "600x600bb")`), so 20 albums ≈ 20 × 600×600 JPEG/PNG ≈ several MB in one burst, blocking the first paint of the grid and competing with the audio stream. The same four `<img>` tags also lose the delegated error-fallback (`js/utils.js:533-543`) and the offline-mode URL filter.
- **Evidence:**
  ```js
  // search.js:546 (album card) and search.js:769 (playlist card)
  ${cover ? `<img src="${escapeHtml(cover)}" alt="" onerror="this.onerror=null;this.style.display='none'" style="width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:2;">` : ''}
  ```
  ```js
  // js/utils.js:522-530 — the helper that is being bypassed
  export function coverImgHtml({ src, coverUrl, sourceId, source, alt = '', extraAttrs = '' }) {
      const safeSrc = offlineImageUrl((src || '').trim());
      if (!safeSrc) return '';
      let dataAttrs = '';
      if (coverUrl && !window.settings?.network?.offline_mode) dataAttrs += ` data-cover-url="${escapeHtml(coverUrl)}"`;
      ...
      return `<img src="${escapeHtml(safeSrc)}" alt="${escapeHtml(alt)}"${dataAttrs} loading="lazy"${extraAttrs ? ' ' + extraAttrs : ''}>`;
  }
  ```
  Note: the inline `onerror="..."` attribute is also **dead code** — the app's CSP is `script-src 'self'` with no `'unsafe-inline'` (`ui/web_new_v2/index.html:10`), so inline event handlers never run; `js/utils.js:546-548` documents this explicitly. The images still fall back correctly only because of the capture-phase delegated listener in `js/utils.js:533-543`, which these hand-rolled tags do not feed (`data-cover-url` is absent).
- **Reproduction / verification:** search for an artist, switch the sub-type filter to "Альбомы", and open the WebView2 Network panel: all artwork requests start immediately, unlike the track rows, whose requests are deferred until they scroll into view.
- **Suggested fix:** replace the four hand-rolled tags with `coverImgHtml({src, coverUrl, sourceId, source, alt:''})`; this also removes the CSP-invalid inline `onerror`.
- **Fix side effects:** the album/playlist cards rely on the image absolutely positioned over the gradient fallback (`z-index:2`); `coverImgHtml` emits a bare `<img>` — the surrounding wrapper CSS must supply the sizing. `coverImgHtml` also returns `''` for an empty `src`, so the "no cover" gradient stays as it is today.
- **Discovered by:** B

---

#### F-WN-31-4  [P2] — The home feed sections are filled by unversioned events, so a late answer from an earlier `loadHome()` overwrites a newer one

- **File:** `ui/web_new_v2/js/home.js:63-88` (`requestHomeSection`), `ui/web_new_v2/js/home.js:110-213` (`loadHome`), `ui/web_new_v2/js/events.js:163-205` (the event handlers that render into the containers)
- **Confirmed:** yes (the missing guard is confirmed; whether the *user* sees the older data depends on provider latency — see "Trigger conditions")
- **Description:** `requestHomeSection()` calls the bridge method and **discards the return value**; the data arrives later as a bridge event (`popular_results`, `feed_ready`, `releases_ready`, `mixes_ready`, `artists_ready`). `loadHome()` maintains a `homeLoadGeneration` counter, but it is only consulted on the `await`ed calls (`get_home_data`, `get_playlists`, `get_downloaded_tracks`). The event handlers in `js/events.js` render straight into the containers with **no generation check at all**, and the event payloads carry no request id.
- **Cause:** a mixed transport: some home data is request/response (guarded by a generation) and some is push (unguarded). The push half has no staleness token.
- **Trigger conditions:** `loadHome()` is re-entered on (a) **every navigation to the Home tab** (`js/pages.js:166` → `loadHome()` with `isTrackChange=false`, so all four external feeds are re-requested), (b) `nedotify:recommendation_feedback_changed` (`js/home.js:9`), (c) every track change while Home is visible (`js/events.js:229`). Two overlapping loads are therefore routine, not exotic. Whenever the *earlier* load's provider answers after the *later* load's provider, the section settles on the stale generation.
- **User impact:** the "Популярное", "Рекомендуем", "Новинки", "Миксы" or "Исполнители" row silently shows the previous request's data. Because every Home navigation re-requests all four external feeds, the probability of an overlap is high. The `homeLoadGeneration` counter gives a false sense of safety — it protects the parts that were never at risk.
- **Evidence:**
  ```js
  // home.js:63-88 — fire and forget; the result is never used
  function requestHomeSection(containerId, methodName, args = []) {
      const request = () => {
          clearFeedTimeout(containerId);
          renderSkeletons(containerId);
          ...
          try {
              const method = window.pywebview?.api?.[methodName];
              if (typeof method !== 'function') throw new Error('Feed API unavailable');
              Promise.resolve(method(...args)).catch(() => { ... renderRetryButton(containerId, request); });
          } catch (err) { ... }
      };
      request();
  }
  ```
  ```js
  // js/events.js:191-197 — the push side has no generation check
  case 'releases_ready':
      clearFeedTimeout('home-releases');
      if (data) { const tracks = Array.isArray(data) ? data : (data.tracks || []); renderReleases(tracks); }
      break;
  ```
  ```js
  // home.js:114-119 — the guard exists, but only on the awaited calls
  const currentGen = ++homeLoadGeneration;
  const data = await window.pywebview.api.get_home_data() || {};
  if (currentGen !== homeLoadGeneration) return;
  ```
- **Reproduction / verification:** 1) open the Home tab; 2) immediately click "Поиск" and then "Главная" again (or like a track, which fires `nedotify:recommendation_feedback_changed`); 3) in the WebView2 console, log every `feed_ready` / `releases_ready` / `mixes_ready` payload with a timestamp; 4) observe two generations of payloads and note which one is still on screen at the end. A deterministic variant: throttle the network in devtools so the first generation's answers arrive after the second generation's.
- **Suggested fix:** give the home feed its own request token — either (a) return the data from the bridge call instead of discarding it and drop the event path for these sections, or (b) add a `request_id`/generation to the `feed_ready` / `releases_ready` / `mixes_ready` / `popular_results` payloads and drop the stale ones in `js/events.js`.
- **Fix side effects:** (a) changes the bridge contract (WN-09 / WN-06) and would block the bridge thread on the provider call, which is exactly why the event path exists; (b) requires touching five `_emit` call sites in `core/api.py`. Whichever is chosen, the 20 s per-section timeout in `home.js:71-74` must keep working.
- **Discovered by:** B

---

#### F-WN-31-5  [P2] — The particle field is a global, CSS-blurred, always-animating full-window layer that runs on every page

- **File:** `ui/web_new_v2/js/particles.js:31-32`, `ui/web_new_v2/js/particles.js:385`, `ui/web_new_v2/js/particles.js:473-540`, `ui/web_new_v2/js/particles.js:295-306`; `ui/web_new_v2/index.html:76`; `ui/web_new_v2/css/components/base.css:1722-1731`
- **Confirmed:** yes (the CSS/layer facts and the loop's page-independence are confirmed; the CPU figure is derived, not measured — see "Reproduction")
- **Description:** `#particles-bg` is a **body-level** element (`index.html:76`), i.e. it is not inside the Home view. Its canvas is sized to the whole window (`particles.js:309-331`, `window.innerWidth/innerHeight`) and the CSS gives the layer `position: fixed; inset: -25px; filter: blur(8px)`. The rAF loop redraws it 24×/s (`particles.js:31` `targetFps = 24`, `particles.js:483-489`) with up to 80 sprites (`particles.js:385`). Nothing in the module ties the loop to the active page: `syncParticleAnimation` (`particles.js:51-61`) only pauses on `document.hidden` / the native `window-hidden` class / the mini-player / the macOS style / efficiency mode.
- **Cause:** the particle layer is a global decoration rather than a Home-page effect, and the compositor applies an 8 px blur to the full-window layer on every frame.
- **Trigger conditions:** any page of the app while the window is visible and focused. `efficiency.js` only pauses it when the window is *hidden* (default `limit_state='minimize'`, `js/efficiency.js:96/103-105`), so an unfocused-but-visible window keeps animating at the default `limit_state`.
- **User impact:** a constant background cost on a laptop: a full-window canvas `clearRect` + up to 80 sprite blits + an 8 px full-screen blur, 24 times per second, **on the Search, Library, Settings and Player pages too**, where the particles are entirely hidden behind the content. At 1920×1080 with dpr 1.5 the backing store is ≈4.7 M device pixels, i.e. ~112 M pixels/s of clear plus a 24 Hz full-screen blur. This is the classic "background 60 fps canvas" battery defect, reduced (24 fps, bounded count, correct pausing) but not eliminated. The blur is also **redundant**: the particles are already drawn as soft radial-gradient sprites (`particles.js:208-238`).
- **Evidence:**
  ```css
  /* ui/web_new_v2/css/components/base.css:1722-1731 */
  #particles-bg {
      position: fixed;
      inset: -25px;
      pointer-events: none !important;
      z-index: 1;
      overflow: hidden;
      display: block;
      filter: blur(8px);
      -webkit-filter: blur(8px);
  }
  ```
  ```js
  // particles.js:51-61 — the only pause conditions
  function syncParticleAnimation() {
      if (!isParticlesRunning || isWindowHidden() || efficiencyPaused ||
          document.documentElement.dataset.uiStyle === 'macos' ||
          document.body.classList.contains('mini-player-active')) { ...cancel... }
      else if (isParticlesRunning && !animFrameId && animateFn) { ...start... }
  }
  ```
- **Reproduction / verification:** open the **Settings** page (nothing of the particle field is visible), leave the window focused, and sample the WebView2 renderer process CPU (Task Manager → "WebView2" entry) or count `requestAnimationFrame` callbacks per second from the console — it stays at ~24 fps for as long as the window is visible.
- **Suggested fix:** pause the loop when the active view is not the one the layer decorates (`nedotify:page_changed` is already emitted — `js/home.js:1014` consumes it), and/or drop `filter: blur(8px)` in favour of the already-soft sprite.
- **Fix side effects:** the particle layer is a *global* decoration, so pausing it on non-Home pages changes the look of those pages (the particles are currently still faintly visible behind translucent surfaces). Removing the CSS blur changes the visual softness of the dots.
- **Discovered by:** B

---

#### F-WN-31-6  [P2] — Seven hand-written copies of the same `.feed-card` tile; the drift is already visible to the user

- **File:** `ui/web_new_v2/js/home.js:709` (canonical), `ui/web_new_v2/js/home.js:827-836`, `ui/web_new_v2/js/home.js:341-350`, `ui/web_new_v2/js/home.js:372-380`, `ui/web_new_v2/js/home.js:404-412`, `ui/web_new_v2/js/home.js:533-542`, `ui/web_new_v2/js/search.js:543-558`, `ui/web_new_v2/js/search.js:766-781`
- **Confirmed:** yes
- **Description:** the **track row** component is properly shared — `createTrackElement()` (`js/utils.js:688`) is used by `search.js` (3 call sites), `library.js:12/409`, `artist_profile.js:197/593`, `profile.js:42` and `home-shell.js:56`. The **feed tile** is not: seven independent copies of the same markup exist and only one of them (`createFeedCard`) is used as a function.
- **Cause:** the tile was never extracted; each section re-implemented it, and the copies have since diverged.
- **Trigger conditions:** always — this is the current state of the Home and Search pages.
- **User impact:** the drift is already shipped. In `createFeedCard` the artist name is a clickable link that opens the artist profile (`home.js:760` `class="feed-card-sub clickable-artist"` + the handler at `home.js:763-774`); in `renderTopTracks` the very same line has **no** `clickable-artist` class and no handler (`home.js:835`) — so on the Home page the artist is a dead label in "Топ треков" but a live link in "История" and "Рекомендуем". The album and playlist grids in `search.js` are ~85 lines each and are near-identical copies of each other, differing in the ways that matter (no `loading="lazy"`, no `data-cover-url` fallback, see F-WN-31-3). Every future fix (keyboard support, aria labels, offline handling, the `track_id → id` normalisation) has to be applied in seven places, and there is no test that would notice a miss.
- **Evidence:**
  ```js
  // home.js:759-761 — canonical tile: artist is a link
  <div class="feed-card-title">${escapeHtml(track.title || 'Unknown')}</div>
  <div class="feed-card-sub clickable-artist">${escapeHtml(track.artist || '')}</div>
  ```
  ```js
  // home.js:834-835 — copy #1: artist is NOT a link
  <div class="feed-card-title">${escapeHtml(track.title || 'Unknown Title')}</div>
  <div class="feed-card-sub">${escapeHtml(track.artist || 'Unknown')} (${playCount})</div>
  ```
  ```js
  // home.js:348-349 — copy #2 (authentic home): artist is NOT a link
  <div class="feed-card-title">${escapeHtml(item.title || 'Unknown')}</div>
  <div class="feed-card-sub">${escapeHtml(item.artist || '')}</div>
  ```
- **Reproduction / verification:** open Home → "Топ треков": the artist name has no pointer cursor and clicking it does nothing. Open Home → "Ваша история" (or "Рекомендуем"): the same visual element is underlined/cursor-pointer and opens the artist profile. The `clickable-artist` class is present in one file location and absent in the others (`grep -n "clickable-artist" ui/web_new_v2/js/home.js`).
- **Suggested fix:** extract one `createFeedCard(track, trackList, index, {showArtistLink})` component into `js/utils.js` and route `renderTopTracks`, `renderAuthenticHome`, `renderHomePlaylists`, `renderAlbumGrid` and `renderPlaylistGrid` through it; use `coverImgHtml` for the cover.
- **Fix side effects:** the copies differ in deliberate ways today (the `(N)` play-count suffix on Top tracks, the playlist tile's `data-pl-id` hook, the album tile's `onerror` fallback). A single component needs those as options, or the differences become regressions. `home.js:1040-1049` (`enhanceHomeCards`) assumes `.feed-card-play`/`.feed-card-title`/`.clickable-artist` — a shared component must keep those class names.
- **Discovered by:** B

---

#### F-WN-31-7  [P3] — Unescaped provider/DB values interpolated into `innerHTML` in the detail modals and the home stat rows

- **File:** `ui/web_new_v2/js/search.js:686`, `ui/web_new_v2/js/search.js:883`, `ui/web_new_v2/js/home.js:541`, `ui/web_new_v2/js/home.js:835`, `ui/web_new_v2/js/home.js:867`, `ui/web_new_v2/js/home.js:938`
- **Confirmed:** the *sinks* are confirmed; the *exploitability* is a hypothesis — I could not build a working payload (see "Reproduction")
- **Description:** every other interpolation in these same template literals is wrapped in `escapeHtml()`. These six are not. `album.year` and `album.track_count` are third-party/DB values; `pl.track_count`, `playCount`, `playsCount` and `track.plays` are DB aggregates.
- **Cause:** output encoding was applied field-by-field rather than through a single helper, so the numeric fields were missed.
- **Trigger conditions:** opening an album detail modal, a playlist detail modal, or viewing the Home / Wrapped sections.
- **User impact:** today the injected values are integers or a ≤4-character string, so no payload can be delivered. The risk is that this is a **landmine inside the pywebview page**, where — as `index.html:6-9` itself states — "an injected script would be remote code execution". The CSP (`index.html:10`, `script-src 'self'`) blocks inline `<script>` and inline event handlers, so the classic `<img onerror=...>` payload does not fire; that is a mitigation layer, not the control that belongs here, and it still permits same-origin `<script src=...>`.
- **Evidence:**
  ```js
  // search.js:686 — album detail modal, NOT escaped
  <div style="font-size:12px; color:var(--text-sec); opacity:0.8;">${album.year ? album.year + ' г. • ' : ''}${album.track_count ? album.track_count + ' треков' : 'Альбом'}</div>
  ```
  ```js
  // search.js:883 — playlist detail modal, NOT escaped
  <div style="font-size:12px; color:var(--text-sec); opacity:0.8;">${playlist.track_count ? playlist.track_count + ' треков' : 'Плейлист'}</div>
  ```
  ```js
  // search.js:684-685 — the two lines immediately above, escaped: the inconsistency is in the same template
  <div style="font-size:20px; font-weight:800; color:#fff; ...">${escapeHtml(album.title || 'Альбом')}</div>
  <div style="font-size:14px; color:var(--text-sec);">${escapeHtml(album.artist || 'Исполнитель')}</div>
  ```
  Why the values are safe *today*: `album.year` reaches the DOM as a string from `services/spotify_service.py:69` (`year = item.get("releaseDate", "")[:4]` — a 4-character slice) or from `services/youtube_service.py:440`; the local-DB path is integer-coerced twice (`utils/tag_parser.py:76` `int(str(date)[:4])` and `core/api.py:3927` `int(str(raw_year).strip()[:4])`), and the column is `year INTEGER` (`core/database.py:231`); `track_count` is `COUNT(id)` (`core/database.py:1427`) and `plays`/`total_plays` are `SUM(play_count)` (`core/database.py:1411/1712`).
- **Reproduction / verification:** *not reproducible today* — to confirm the sink you would have to inject a malicious iTunes/YouTube album response (or a non-numeric year) and observe the year field rendered as markup in the album modal. The missing evidence is exactly that end-to-end provider test; the *sink* itself is directly visible in the source.
- **Suggested fix:** wrap the six interpolations in `escapeHtml()` (or better, render them as `textContent` on a created node, as `search.js:1023-1027` already does for the correction banner).
- **Fix side effects:** none — the values are numeric today, so escaping changes nothing visually.
- **Discovered by:** B

---

#### F-WN-31-8  [P3] — `loadHome()` fetches the playlist list twice and can issue two `get_playlist_tracks` calls for the same playlist

- **File:** `ui/web_new_v2/js/home.js:124`, `ui/web_new_v2/js/home.js:142-153`; `core/api.py:3307`
- **Confirmed:** yes
- **Description:** `get_home_data()` already returns the playlist list (`core/api.py:3307` → `"playlists": self.get_playlists()`), and `home.js:124` uses `data.playlists`. Nevertheless `loadHome()` calls `get_playlists()` again at `home.js:144` and re-renders the whole quick-access grid at `home.js:149` with the same data.
- **Cause:** the two code paths were written independently; `renderQuickAccess` is called with the same arguments twice.
- **Trigger conditions:** every Home load.
- **User impact:** one extra uncached SQLite query per Home load, one extra full rebuild of the 4-tile quick-access grid, and — because `attachPlaylistCollage` is started for the same playlist twice and the first call has not populated `_plCollageCache` yet when the second one starts (`home.js:470-487`) — a **duplicate `get_playlist_tracks` bridge call** for the same playlist, with the first call's `<img>` collage work later discarded (the container was `replaceChildren()`-ed).
- **Evidence:**
  ```js
  // home.js:124 — first render, already using the playlists from get_home_data()
  renderQuickAccess(data, data.playlists || []);
  ...
  // home.js:142-153 — second, redundant fetch + second render
  if (window.pywebview.api.get_playlists) {
      try {
          const playlists = await window.pywebview.api.get_playlists();
          if (currentGen !== homeLoadGeneration) return;
          if (Array.isArray(playlists)) {
              data.playlists = playlists;
              renderHomePlaylists(playlists);
              renderQuickAccess(data, playlists);   // <-- same content, rebuilt
          }
      } catch (err) { console.warn('Failed to load playlists on home:', err); }
  }
  ```
  ```python
  # core/api.py:3302-3312 — get_home_data already carries the playlists
  return {
      "history": history,
      ...
      "playlists": self.get_playlists(),
      ...
  }
  ```
- **Reproduction / verification:** log every bridge call from the WebView2 console (`window.pywebview.api.get_playlists` / `get_playlist_tracks` are called once per Home load each; the expected count is 1 and 1, the actual count is 2 and 2).
- **Suggested fix:** drop the second `get_playlists()` call and the second `renderQuickAccess()`; use `data.playlists` (already present) and only call `renderHomePlaylists` once.
- **Fix side effects:** `get_playlists()` is also the path that triggers a `playlists_changed`-style refresh; if the intent was to pick up a playlist created between the two calls, that intent is better served by the existing `nedotify:playlists_changed` listener (`js/home.js:444`).
- **Discovered by:** B

---

### 3. Clean areas

- **XSS / output encoding (mostly).** Every third-party *text* value rendered by the 5 modules goes through `escapeHtml()`: track titles/artists/album names in the album grid (`search.js:554-556`), the playlist grid (`search.js:777-779`), the album/playlist modals (`search.js:684-685`, `search.js:881-882`), the authentic-home cards (`home.js:348-349`, `378-379`, `410-411`), the artist cards (`home.js:671`), the top-track card (`home.js:834`), the wrapped-stats rows (`home.js:934-935`), the quick-access tiles (`home.js:246`), the continue-listening strip (`home-shell.js:30`) and the discovery cards (`search-discovery.js:38`). `escapeHtml` (`js/utils.js:17-25`) escapes `& < > " '`, which is sufficient for the attribute and text contexts used here.
- **No `javascript:` URL vector.** The 5 modules build **no** `href` at all (`grep "href\s*=" ui/web_new_v2/js` → only `js/boot.js:33`, a font stylesheet). Artist links are `data-artist` attributes plus a JS handler (`js/utils.js:794-813`), never a URL.
- **CSS `url()` injection is guarded.** `home.js:16-25` (`applyCoverBackground`) parses the URL with `new URL()`, accepts only `https:`/`data:`, and uses `u.href` (already percent-encoded by the URL parser) so the `url("…")` token cannot be broken out of. The project also has a dedicated `safeCssImageUrl()` helper (`js/utils.js:40-50`) that strips `'"()\;`.
- **`coverImgHtml` is a correct shared helper** (`js/utils.js:522-530`): escaped `src` and `data-*`, `offlineImageUrl()` filtering, `loading="lazy"`, and it refuses to emit an empty `src` (which would cause a same-page request).
- **Search staleness is defended twice.** The Python side has a real request-generation guard (`core/api.py:2090-2096`, `self._search_generation` + `is_current()`), so a superseded search never emits; the JS side independently drops chunks whose `data.query` no longer matches (`search.js:332`, `search.js:351`) and additionally guards by source (`search.js:354`) and sub-type (`search.js:355`). The `resultKey` reset logic (`search.js:361-365`) correctly keys on the *requested* source, not the answering provider.
- **The `search_completed` sentinel cannot preempt real results.** `_emit` on a non-main thread calls `evaluate_js` synchronously (`core/api.py:1156-1159`), and the completion sentinel is emitted only after every provider has emitted its chunk (`core/api.py:2123-2129`, `mark_done`). The "Ничего не найдено" state is therefore only reached when there really are no results.
- **Album detail modal cancellation is correct.** `albumModalGeneration` + a single-slot `albumFetchCleanup` (`search.js:595-620`, `search.js:653-658`, `search.js:713`) cancel the in-flight `get_album_details` and ignore a stale reply.
- **`particles.js` lifecycle is correct.** The rAF loop is cancelled on `document.hidden`, on the native minimise (`window-hidden` class), on the mini-player, on the macOS style and on efficiency mode (`particles.js:47-65`, `particles.js:475`); the particle count is bounded (`≤80`, `≤25` on a ≤4-core device — `particles.js:385`); the backing store and every sprite cache are `devicePixelRatio`-aware (`particles.js:77-86`, `js/utils.js:369-469`) and are re-rasterised on a monitor change; `stopParticles()` removes every listener, timer, the canvas and the sprite caches (`particles.js:240-271`). This is covered behaviourally by `tests/test_visual_effects_lifecycle.py:120-196`.
- **No listener or observer leaks.** `initSearchDiscovery` and `initHomeShell` are guarded by an `initialized` flag (`search-discovery.js:94`, `home-shell.js:69`); `initParticles` tears down its own listeners via `stopParticles()` (`particles.js:246-249`, `373-380`); `initSearch` is called exactly once from `main.js:533` inside a one-shot `init()` (`js/main.js:354`, `506`); every other listener in the 5 modules is registered at module scope (evaluated once). The `MutationObserver`s in `search-discovery.js:115` and `home-shell.js:116` observe long-lived static nodes.
- **No `IntersectionObserver`, no `AbortController`, no object URLs** in the 5 modules — therefore nothing to disconnect and no `revokeObjectURL` to call.
- **No scroll listeners** in the 5 modules (the two that exist in the app are in `js/artist_profile.js:674` and `js/library.js:443`, both WN-32, and both `{passive:true}` where applicable).
- **The home feed has no shared loading flag.** Each section owns its own skeleton and its own 20 s timeout + retry button (`home.js:63-88`, `home.js:53-61`), so a slow section cannot switch off another section's spinner. The only shared state is the `home-error` banner, which is only shown on a thrown error (`home.js:208-211`).
- **Home cover images are lazy-loaded.** Every home cover goes through `coverImgHtml` (`home.js:245`, `667`, `754`, `829`) or an explicit `img.loading = 'lazy'` (`home.js:591`), so the Home page does **not** pull 50 full-size covers at once.
- **Test coverage that is genuinely behavioural:** `tests/test_visual_effects_lifecycle.py` runs `particles.js` in a Node `vm` with DOM stubs and asserts listener ownership, pause/resume, the battery FPS limit and full resource release. `tests/test_search_discovery_ui.py` runs `historyToDiscovery()` in a Node `vm` and asserts the real de-duplication/normalisation behaviour. `tests/test_search_query_suggestions.py` is a solid Python test of `utils/search_query.py` (WN-27) — it is not a JS test at all.

---

### 4. Coverage gaps

- **No runtime measurement.** I was not allowed to run the app, so every performance statement above is derived from the code path plus the provider limits (`limit=20` per provider, 4 providers) — not from a profile. The DOM-churn count (200 vs 80 row constructions), the eager image burst and the particle CPU cost are **derived, not measured**. A WebView2 Performance/Network recording would confirm or refute F-1, F-2, F-3 and F-5.
- **F-7 could not be confirmed end-to-end.** The sinks are visible in the source, but the reachable values are integer-coerced upstream (iTunes `releaseDate[:4]`, `int(...)` in `utils/tag_parser.py:76` and `core/api.py:3927`, `year INTEGER` in `core/database.py:231`, SQL `COUNT`/`SUM` for the counts). To *confirm* exploitability I would need a malicious provider response or a non-numeric year written into `tracks.year`; I did not attempt to write to the user's database.
- **The test suite does not cover the 5 in-scope modules behaviourally.** Stating plainly what is and is not covered:
  - `tests/test_search_discovery_ui.py` — **behavioural but narrow**: one pure function (`historyToDiscovery`). Not covered: the DOM rendering of the discovery cards, the `app:artists_avatars_ready` upgrade path, the `refreshSearchHistory` error branch, the `generation` guard, the `MutationObserver` profile mirror.
  - `tests/test_search_query_suggestions.py` — **Python only**; it tests `utils/search_query.py`. The JS side of the correction feature (`search.js:1046-1073` `offerSearchCorrections`, `search.js:1157-1198` `renderSuggestions`) is **not covered by any test**.
  - `tests/test_frontend_js.py` — **static greps**, and only over `js/events.js`, `js/main.js`, `js/artist_profile.js` (plus one sweep of all files for stray `window.onPythonEvent =` assignments). It does not read `search.js`, `home.js`, `home-shell.js`, `particles.js` or `search-discovery.js` for anything else, and its `node --check` list (`test_frontend_js.py:58-61`) does **not** include any of the 5 in-scope files — so a syntax error in `search.js`/`home.js`/`particles.js` is not caught by the suite. Its own docstring says so: "They do NOT prove the UI behaves correctly at runtime."
  - `tests/test_visual_effects_lifecycle.py` — **genuinely behavioural** for `particles.js` (pause on `visibilitychange` / mini-player / native minimise, the battery FPS cap, listener and canvas release across 25 re-inits). Not covered: the particle-count bound, the dpr scaling, `prefers-reduced-motion`, and the fact that the loop keeps running on non-Home pages (F-5).
  - **Nothing at all** covers: the search debounce, the chunked re-render, the search staleness guard, the home feed event race, the quick-access double render, the card-component duplication, or any of the escaping decisions in `search.js`/`home.js`.
- **`js/artist_profile.js` was not read in full** (WN-32 owns it) even though `search.js:315` delegates the whole artist-profile view to it; the artist-profile rendering path is therefore outside this report.
- **`tools/visual_guard/` was not inspected** (WN-35); if it has Home/Search fixtures they may already encode some of the expected card markup, which would sharpen the drift analysis in F-6.
- I did not verify the WebView2 CSP enforcement empirically (no app run); the CSP behaviour is taken from the `meta` tag and from the in-repo comment at `js/utils.js:546-548`.

---

### 5. Architecture improvements (ARCH)

These are **not** defects — no proven failure is attached to them. They are reported separately per the brief.

**ARCH-1 — Extract one feed-tile component (and one cover component) into `js/utils.js`.**
`createTrackElement()` is the project's successful model: one row component, reused by search, library, artist profile, profile and home-shell. The feed tile has no equivalent. Seven copies of the same ~15-line markup exist (`home.js:341`, `372`, `404`, `533`, `709`, `827`; `search.js:543`, `766`). The same drift the shared row component avoided is now present in the tiles (F-6) and in the cover `<img>` (F-3). A `createFeedCard(track, list, index, opts)` next to `createTrackElement` — with `coverImgHtml` as the only cover emitter — would collapse seven copies into one and give the fix target a single home.

**ARCH-2 — Make the search renderer incremental instead of a full-list rebuild.**
`renderResults(allResults)` conflates "the model" and "the view". Splitting it into `renderResults(reset)` + `appendResults(chunk)` would make the per-chunk cost O(chunk) rather than O(total) and would let the batch renderer (`renderSearchResultsBatch`) keep its rAF chunking across chunk boundaries instead of restarting from zero on every provider answer (F-1). The renderer would also stop needing to re-emit the artist-suggest banner and the correction/offline notes on every chunk.

**ARCH-3 — Give the home feed one transport, not two.**
Today the Home page mixes request/response (guarded by `homeLoadGeneration`) with push events (unguarded, no request id) for the same data. Either make the five feed sections request/response with a generation check, or make all of them push with a `request_id` in the payload that `js/events.js` checks. The current mix means the generation counter protects the half that was never at risk and leaves the half that is at risk unprotected (F-4). A single rule — "every home section carries the generation it belongs to" — would also remove the need for the 20 s per-section timeout to guess whether a section will ever be filled.

**ARCH-4 — Introduce a "view owns its animations" contract.**
`particles.js` owns a full-window rAF canvas but has no idea which view is on screen, so it animates behind Settings and Search (F-5). The app already emits `nedotify:page_changed` (`js/pages.js` → consumed at `js/home.js:1014`) and the visualizer already has an `IntersectionObserver` visibility gate (`js/visualizer.js:136-137`). A shared "the effect is only alive while its view is active" helper — used by particles, visualizer and the CSS aura orbs — would remove the need for each effect to re-derive the pause conditions (F-5) and would make the behaviour testable once instead of per effect.

**ARCH-5 — Make output encoding a helper, not a per-field decision.**
`escapeHtml()` exists and is used correctly ~30 times in the 5 modules, but six numeric fields were missed (F-7) because the decision was made at each interpolation site. A `setText(el, value)` / `textOrEmpty(value)` helper (or a `data-*` + delegated-render pattern like the correction banner at `search.js:1023-1027`) would make the safe path the default and remove the whole class of "one field was forgotten" defects.

**ARCH-6 — Give the frontend a lint rule for the two patterns that keep recurring.**
The repo already has `tools/check_lock_nesting.py` and `tools/check_shadow_imports.py` (WN-35) for Python. Two JavaScript rules would have caught most of this area's findings mechanically: (a) "an `innerHTML` template must not contain an unescaped `${`" (F-7), and (b) "an `<img>` emitted outside `js/utils.js` must carry `loading=\"lazy\"`" (F-3). `tests/test_frontend_js.py` is already the natural home for such static checks — and it currently does not read any of the 5 in-scope files.

**ARCH-7 — Close the test-coverage gap on the 5 in-scope modules.**
`js/frontend_js.py`'s `node --check` list omits `search.js`, `home.js`, `home-shell.js`, `particles.js` and `search-discovery.js`, so a syntax error in any of them ships uncaught. The Node `vm` harness that `tests/test_visual_effects_lifecycle.py` already builds (DOM stubs, rAF/timer control, listener counting) is reusable and would let the search debounce, the chunked render, the home-feed generation guard and the card component be tested behaviourally rather than by grep.
