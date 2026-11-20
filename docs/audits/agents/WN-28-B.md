## AREA WN-28 — UI document, bootstrap, event bus, shared utilities — ROLE B

### 1. Scope reviewed

**Files opened and read in full** (physical line counts; the area map quotes non-empty
line counts, hence the deltas):

| File | Physical lines | Notes |
|---|---|---|
| `ui/web_new_v2/index.html` | 2314 | 209,048 bytes, ~1,939 open tags, 836 `<div>`, 279 `<button>`, 59 `<input>`, 464 inline `style=""`, 212 `data-lucide` icons |
| `ui/web_new_v2/js/utils.js` | **1690** | area map says 1533 = non-empty lines |
| `ui/web_new_v2/js/boot.js` | 72 | |
| `ui/web_new_v2/js/main.js` | 718 | area map says 665 = non-empty lines |
| `ui/web_new_v2/js/events.js` | 464 | area map says 406 = non-empty lines |
| `ui/web_new_v2/js/pages.js` | 198 | area map says 163 = non-empty lines |
| `ui/web_new_v2/js/debug.js` | 44 | |
| `ui/web_new_v2/js/contextmenu.js` | 46 | |
| `ui/web_new_v2/js/efficiency.js` | 192 | area map says 166 = non-empty lines |

**Supporting reads (not full review):** `js/lucide.min.js` (createIcons impl),
`js/appearance-assets.js`, `js/window-resize.js`, `core/api.py` (bridge surface + `open_url`),
`core/settings.py` (`DEFAULT_SETTINGS['efficiency'/'optimization']`), `core/downloader.py:830-845`
(`download_complete` emission), `main.py:60-90` (Bottle `Cache-Control` hook) and `main.py:330-381`
(`create_window`), `webview/http.py` (pywebview Bottle server),
`tests/test_frontend_js.py`, `tests/test_frontend_css_wiring.py`, `tests/test_visual_guard_diff.py`,
`tools/visual_guard/{capture,run_guard}.py`.

**Callees traced into other areas (read for contract only, not re-reviewed):**

- `core/api.py::AppApi` — **174 public methods** reachable as `window.pywebview.api.*` (WN-03…WN-10).
- `core/downloader.py:839` — `self._emit('download_complete', {'track_id': track_id})` (WN-13).
- `core/settings.py:98-118` — `DEFAULT_SETTINGS['efficiency']['unfocus_enabled'] = False`,
  `['optimization']['limit_state'] = 'minimize'` (WN-14).
- `core/proxy.py` — the loopback cover/stream URLs `utils.js::getCoverUrl` builds (WN-11).
- `main.py:71` — `Cache-Control: no-cache, no-store, must-revalidate` on every asset (WN-01).
- `js/player.js`, `js/library.js`, `js/home.js`, `js/search.js`, `js/lyrics.js`,
  `js/artist_profile.js`, `js/settings.js`, `js/queue.js` — cross-referenced only (WN-29…WN-32).
- `tools/visual_guard/**`, `tests/**` (WN-34, WN-35).

### 2. Findings

#### F-WN-28-1  [P1] — `window.NeDotify` is re-assigned with an object literal, silently deleting the floating-menu dismissal guard (dead fix)

- **File:** `ui/web_new_v2/js/main.js:82` ; `ui/web_new_v2/js/utils.js:1079-1081`, `:1214` ;
  `ui/web_new_v2/js/player.js:1234` ; `ui/web_new_v2/js/library.js:847`
- **Confirmed:** yes
- **Description:** `utils.js` registers two helpers on the global namespace **at module-evaluation
  time**:
  `window.NeDotify = window.NeDotify || {}; window.NeDotify._armFloatingMenuGuard = _arm;
  window.NeDotify.closeAllFloatingMenus = closeAllFloatingMenus;`
  ES-module semantics guarantee that every dependency module body runs *before* the importing
  module's body, so `utils.js` (a dependency of `main.js` through `profile.js`) has already
  populated `window.NeDotify` by the time `main.js:82` runs
  `window.NeDotify = { openPlaylistMenu: ..., toggleMiniPlayerMode: ... }` — an object **literal**,
  not a merge. The replacement object does not contain `_armFloatingMenuGuard` or
  `closeAllFloatingMenus`, so both properties are destroyed. The same clobbering silently drops
  `window.NeDotify.toggleMiniLyrics` registered at module scope in `js/lyrics.js:1261-1262`.
  Every consumer therefore evaluates `window.NeDotify?._armFloatingMenuGuard?.()` to `undefined`
  and the optional call is a **silent no-op**.
- **Cause:** two different conventions for the same global namespace — `||` (merge) in
  `utils.js:1079` / `lyrics.js:1261` / `player.js:1196` versus full replacement in `main.js:82` —
  combined with a load-order dependency that nothing documents or tests.
- **Trigger conditions:** always, on every launch. The guard is *never* armed.
- **User impact:** the fixed-position floating menus are never dismissed on window resize,
  scroll or page change. `utils.js:1042-1045` states this was the bug the guard was written to
  fix ("a menu opened in a small window stayed stranded (misplaced) after the window was
  maximised"), and `player.js:1232` repeats it ("Fixed-position menu: dismiss it when the
  window resizes or the page changes"). Concretely: the rich track context menu
  (`utils.js:1105-1397`) and the player-bar `#track-options-menu` (`player.js:1221-1235`) stay
  open at their old viewport coordinates when the window is resized or the user switches page,
  and float over an unrelated view. `utils.js::closeAllFloatingMenus` is exported and advertised
  on the namespace but is unreachable.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/utils.js:1060-1082 (module scope)
  if (typeof window !== 'undefined') {
      let _floatMenuTeardown = null;
      const _dismiss = () => { closeAllFloatingMenus(); ... };
      const _arm = () => { ... window.addEventListener('resize', _dismiss); ... };
      window.NeDotify = window.NeDotify || {};
      window.NeDotify._armFloatingMenuGuard = _arm;      // <-- set at module eval
      window.NeDotify.closeAllFloatingMenus = closeAllFloatingMenus;
  }
  ```
  ```js
  // ui/web_new_v2/js/main.js:82 (main.js module body - runs LAST)
  window.NeDotify = {
      openPlaylistMenu: openPlaylistMenu,
      ...
      toggleMiniPlayerMode: toggleMiniPlayerMode
  };                                                     // <-- replaces the object
  ```
  ```js
  // ui/web_new_v2/js/utils.js:1213-1214
      activeRichMenu = menu;
      window.NeDotify?._armFloatingMenuGuard?.();       // <-- always undefined
  ```
  ```js
  // ui/web_new_v2/js/player.js:1232-1235
      // Fixed-position menu: dismiss it when the window resizes or the page changes.
      if (optMenu.classList.contains('visible')) {
          window.NeDotify?._armFloatingMenuGuard?.();   // <-- always undefined
      }
  ```
- **Reproduction / verification:** reproduce the ES-module ordering with node (this exact script
  was executed and prints `undefined`):
  ```powershell
  # a.mjs
  globalThis.window = {};
  window.NeDotify = window.NeDotify || {};
  window.NeDotify._armFloatingMenuGuard = () => 'armed';
  # b.mjs
  import './a.mjs';
  window.NeDotify = { bar: 1 };
  console.log('after main.js body, _armFloatingMenuGuard =', typeof window.NeDotify._armFloatingMenuGuard);
  # -> after main.js body, _armFloatingMenuGuard = undefined
  ```
  In the app: open the player bar, click the three-dot button (`#pb-btn-options`), resize the
  window → the menu stays at the old pixel offset instead of closing.
- **Suggested fix:** make the namespace a single owner. Either (a) have `main.js:82` merge into
  the existing object (`window.NeDotify = Object.assign(window.NeDotify || {}, {...})`) and move
  the module-scope registrations in `utils.js`/`lyrics.js` into an explicit `init*()` call, or
  (b) delete the global entirely and import the helpers directly (`utils.js` already exports
  `closeAllFloatingMenus`; `_arm` should be exported as a named function).
- **Fix side effects:** option (a) keeps the `window.NeDotify?.…` lookups working but leaves the
  namespace mutable from anywhere; option (b) requires touching `player.js`, `library.js`,
  `home.js`, `library-view.js`, `search.js`, `queue.js` (WN-29/31/32) and could break any
  consumer that still reads `window.NeDotify.*` after the change. Whichever is chosen, add a test
  that asserts the namespace is never *replaced* after module evaluation.
- **Discovered by:** B

#### F-WN-28-2  [P1] — `download_complete` refreshes the library twice per track and bypasses the 300 ms burst debounce its sibling case uses

- **File:** `ui/web_new_v2/js/events.js:258-264` ; `ui/web_new_v2/js/library.js:548-550`, `:379-391` ;
  `core/downloader.py:839`
- **Confirmed:** yes
- **Description:** the `download_complete` handler calls `loadDownloaded()`, `loadPlaylists()`
  **and** `window.refreshActiveLibraryView()`. `loadDownloaded()` is nothing but
  `refreshActiveLibraryView()` (`library.js:548-550`), so the active library view is rebuilt
  **twice** for every completed download. Unlike the `library_updated` case
  (`events.js:211-231`), this case is **not** debounced and is **not** guarded by
  `isPageVisible('library')`.
  Cost per event: `refreshActiveLibraryView()` → `loadLibrarySummary()` → 2 bridge calls
  (`get_favorites`, and `get_downloaded_tracks`, which ships the *entire* downloaded-tracks
  table) plus `selectSection()` → another bridge call + a full list re-render; then
  `loadPlaylists()` → `get_playlists()` + a full sidebar re-render; then the whole first block
  a second time. That is **6 bridge round-trips and 2 list rebuilds per finished track**.
- **Cause:** the handler was written by copy-adapting the `library_updated` branch without
  noticing that `loadDownloaded()` already performs the refresh, and without inheriting the
  debounce that the sibling branch installs (`events.js:216-217`).
- **Trigger conditions:** every `download_complete` event. `core/downloader.py:839` emits one
  per finished task, so a batch download of N tracks produces N of these.
- **User impact:** a batch download of 100 tracks causes ~600 bridge round-trips, 100 full
  `get_downloaded_tracks` payloads, 200 library-list re-renders and 100 playlist-sidebar
  re-renders while the download is running — the UI stutters and the library list visibly
  re-sorts under the user's cursor.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/events.js:258-264
              case 'download_complete':
              case 'track_downloaded':
                  loadDownloaded();
                  loadPlaylists();
                  if (window.refreshActiveLibraryView) window.refreshActiveLibraryView();
                  document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
                  break;
  ```
  ```js
  // ui/web_new_v2/js/library.js:548-550  (loadDownloaded == refreshActiveLibraryView)
  export async function loadDownloaded() {
      refreshActiveLibraryView();
  }
  ```
  ```js
  // ui/web_new_v2/js/events.js:215-217  (the debounce the sibling case DOES use)
                  // O-5: debounce burst events — a single refresh 300ms after the last one
                  if (libraryRefreshTimer) clearTimeout(libraryRefreshTimer);
                  libraryRefreshTimer = setTimeout(() => {
  ```
  ```python
  # core/downloader.py:839
                  self._emit('download_complete', {'track_id': track_id})
  ```
- **Reproduction / verification:** start a batch download of ≥30 tracks from the Library view and
  count bridge calls / list re-renders (DevTools console: wrap
  `window.pywebview.api.get_downloaded_tracks` with a counter, or read `~/.nedotify/logs/app.log`).
  Expected: ≥6 `get_downloaded_tracks`-class calls per finished track; the correct number is 2.
- **Suggested fix:** drop the redundant `window.refreshActiveLibraryView()` call and route the
  case through the same 300 ms debounce used by `library_updated` (reuse `libraryRefreshTimer`),
  plus the same `isPageVisible('library')` guard.
- **Fix side effects:** the download spinner on a track row is cleared by the
  `nedotify:track_downloaded` CustomEvent (`utils.js:1008-1017`), which is dispatched
  synchronously — keep that dispatch outside the debounce or the spinner will linger.
- **Discovered by:** B

#### F-WN-28-3  [P2] — `awaitBridge()` starts one unbounded 100 ms polling timer per call site, and none of them ever stop if the bridge never initialises

- **File:** `ui/web_new_v2/js/main.js:44-73`
- **Confirmed:** yes
- **Description:** `awaitBridge()` registers a `pywebviewready` listener **and** starts a
  self-rescheduling `setTimeout(check, 100)` poll. The poll only terminates when `complete()`
  runs, and `complete()` requires either the `pywebviewready` event or `isBridgeReady()` to
  become true — i.e. it requires the bridge. `awaitBridge()` has **16 call sites**
  (`main.js:122`, `main.js:354`, `smart-playlists.js:72`, `library.js:502`, `library.js:563`,
  `settings.js:434`, `library-view.js:138`, `search-discovery.js:71`, `queue.js:78`,
  `profile.js:12`, `onboarding.js:61`, `home.js:111/451/468/616/896`). Each call made while
  the bridge is down creates its **own independent** poll chain — there is no shared promise
  and no shared timer.
- **Cause:** the readiness gate is implemented as a per-caller polling loop instead of a single
  cached, shared "bridge ready" promise.
- **Trigger conditions:** (a) the documented cold-start window — `main.js:29-31` says a cold
  WebView2 start can take ~16 s to inject the bridge, so every module that calls `awaitBridge()`
  during that window adds its own 10 Hz loop; (b) permanently, if the bridge never initialises
  (exactly the scenario the 45 s bridge-dead overlay at `main.js:377-388` exists for).
- **User impact:** during a cold start the UI runs up to 16 concurrent 10 Hz timers; in the
  bridge-dead case it burns CPU forever with no visible feedback until the third reload
  (see F-WN-28-7). On a laptop this is measurable battery drain on an app that is supposed to be
  idle-friendly.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/main.js:44-72
      return new Promise((resolve) => {
          let resolved = false;
          const complete = () => { ... resolve(); };
          window.addEventListener('pywebviewready', complete, { once: true });
          const check = () => {
              if (isBridgeReady()) { complete(); return; }
              if (!resolved) {
                  setTimeout(check, 100);          // <-- never cancelled
              }
          };
          check();
      });
  ```
  Note also that `main.js:354` writes
  `window.awaitBridge().then(() => init()).catch(() => init());` — `awaitBridge` never rejects,
  so the `.catch` arm is unreachable dead code; the only thing that ever calls `init()` on a
  dead bridge is the 4 s fallback timer at `main.js:367-372`.
- **Reproduction / verification:** open DevTools on the running app, block the bridge (or start
  the app with the backend wedged), and count timers: `setInterval(()=>console.log('tick'),100)`
  in the console shows the same rate as the number of pending `awaitBridge()` polls.
- **Suggested fix:** build one module-level cached promise (`let bridgeReadyPromise`) in
  `main.js`, return it from every `awaitBridge()` call, and give it a bounded deadline plus a
  single `pywebviewready` listener.
- **Fix side effects:** a shared promise must be reset if the bridge is torn down and re-created
  (e.g. a WebView2 process crash reloads the page, which resets module state anyway); a deadline
  changes the "wait forever" semantics that some callers may rely on (e.g. `library.js:563`
  `loadPlaylists()` currently blocks until the bridge appears).
- **Discovered by:** B

#### F-WN-28-4  [P2] — `initBlurObserver` observes the entire `document.body` because the `#views-container` element it scopes to does not exist

- **File:** `ui/web_new_v2/js/efficiency.js:48-51`, `:68-69` ; `ui/web_new_v2/index.html` (absent)
- **Confirmed:** yes
- **Description:** the blur-out IntersectionObserver is meant to be scoped to the views
  container. The code does `document.getElementById('views-container') || document.body`, and
  **no element with id `views-container` exists anywhere in the UI** — the only two occurrences
  of the string in the whole `ui/` tree are the two `getElementById` calls in `efficiency.js`
  itself. The `MutationObserver` is therefore registered on `document.body` with
  `{ childList: true, subtree: true }`, i.e. on the entire document.
- **Cause:** the container id was renamed/removed in the markup and the fallback silently
  widened the observation scope by an order of magnitude. The fallback is not observable
  because nothing logs which branch was taken.
- **Trigger conditions:** always (`initBlurObserver()` is called unconditionally from
  `main.js:433`).
- **User impact:** every DOM mutation anywhere in the app now wakes the observer. The callback
  iterates the mutation list and, for **each added element node**, runs
  `root.querySelectorAll('.card, .glass-panel, .player-glass-card, .settings-modal-card')` over
  that node's subtree; for each removed node it runs the mirror `querySelectorAll` to unobserve.
  This is the hottest path in the app: `renderIcons()` (`utils.js:943-958`) calls
  `window.lucide.createIcons({ root: document.body })`, and `lucide.min.js:150-151` does
  `root.querySelectorAll('[data-lucide]')` then **replaces every matched `<i>` with a new
  `<svg>`** — i.e. one full-document icon sweep produces N separate DOM mutations, and the
  observer then does N subtree queries. On a library page with 200 rows that is hundreds of
  extra `querySelectorAll` calls per re-render.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/efficiency.js:48-51 and 68-69
      const scan = () => {
          const container = document.getElementById('views-container') || document.body;
          scanElement(container);
      };
  ...
      const targetContainer = document.getElementById('views-container') || document.body;
      observer.observe(targetContainer, { childList: true, subtree: true });
  ```
  ```js
  // ui/web_new_v2/js/lucide.min.js:146-152
      function createIcons(options) {
          options = options || {};
          const nameAttr = options.nameAttr || 'data-lucide';
          const root = options.root || document;
          const elements = root.querySelectorAll(`[${nameAttr}]`);
          elements.forEach(el => renderElement(el, nameAttr));
      }
  ```
  ```powershell
  Select-String -Path ui\web_new_v2\index.html -Pattern 'views-container'   # -> 0 matches
  ```
- **Reproduction / verification:** open DevTools → Performance → record while switching to the
  Library view with 200 tracks; the MutationObserver callback appears as a significant share
  of scripting time, scaling with the number of icons replaced.
- **Suggested fix:** either add a real `#views-container` element around the view stack in
  `index.html`, or scope the observer to the actual view roots
  (`#view-home, #view-search, #view-library, #view-player, #view-profile`) and coalesce the
  added-node scans into one `requestAnimationFrame` batch instead of one
  `querySelectorAll` per added node.
- **Fix side effects:** narrowing the observer means cards created outside the views container
  would no longer get the `blur-out` class and would keep their `backdrop-filter` — the exact
  regression the observer was added to avoid (C-5).
- **Discovered by:** B

#### F-WN-28-5  [P2] — seven inline `onerror=` handlers are permanently dead under the document's own CSP

- **File:** `ui/web_new_v2/index.html:10` (CSP) ; `ui/web_new_v2/js/utils.js:721`, `:1128`
  (cross-ref WN-31/WN-32: `js/artist_profile.js:480`, `js/search.js:546`, `:682`, `:769`, `:879`)
- **Confirmed:** yes
- **Description:** the document ships a strict CSP with `script-src 'self'` and no
  `'unsafe-inline'`. Inline **event-handler attributes** (`onerror="…"`) are governed by
  `script-src`'s `unsafe-inline` flag, so all seven of them are blocked by the app's own
  policy and never execute. The rest of the codebase already knows this — `utils.js:545-548`
  explicitly documents that it replaced inline `onload`/`onerror` attributes with a
  capture-phase delegated listener because `script-src 'self'` "silently blocks" them — but
  two of the replacements were left behind in `utils.js` itself.
- **Cause:** the migration to delegated listeners was applied to `index.html` and to
  `utils.js`'s own delegated handlers, but the string templates that still emit
  `onerror="…"` were never updated.
- **Trigger conditions:** every image that fails to load (a dead cover URL, a 404 from the
  loopback proxy, an offline-mode blank).
- **User impact:** (a) the rich track context menu's cover never falls back to the default
  placeholder — `utils.js:1128` intends `this.src='<default svg>'`, but the delegated handler
  at `utils.js:533-543` instead sets `display:none`, so the menu's cover tile is simply blank;
  (b) each failed cover load emits a CSP violation into the console, and because the console
  is the only diagnostics channel in this app (there is no user-facing error surface for image
  failures) the noise is indistinguishable from a real script failure. The `escapeHtml`d
  attributes themselves are safe; the problem is purely that the handlers are unreachable.
- **Evidence:**
  ```html
  <!-- ui/web_new_v2/index.html:6-10 -->
  <!-- The pywebview bridge exposes the whole backend API to this document, so an
       injected script would be remote code execution. ... script-src stays locked to
       same-origin files, so no inline or remote script can execute. -->
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; ...">
  ```
  ```js
  // ui/web_new_v2/js/utils.js:1127-1128
              ${coverBgUrl ? `<div class="rich-menu-header-bg" style="background-image: url('${escapeHtml(coverBgUrl)}')"></div>` : ''}
              <img class="rich-menu-cover" src="${escapeHtml(coverUrl || DEFAULT_COVER_DATA_URI)}" onerror="this.onerror=null;this.src='${DEFAULT_COVER_DATA_URI}';">
  ```
  ```js
  // ui/web_new_v2/js/utils.js:719-721
              ${coverSrc ? `<img src="${escapeHtml(coverSrc)}" alt="" onerror="this.onerror=null;this.style.display='none';" loading="lazy">` : ''}
  ```
  ```js
  // ui/web_new_v2/js/utils.js:545-553 (the correct pattern, already used elsewhere)
  // 'load' also does not bubble, so it needs the same capture-phase delegation.
  // It replaces inline onload/onerror attributes, which `script-src 'self'`
  // (no 'unsafe-inline') silently blocks: #mp-cover ships with display:none and
  // an inline onload that could never run.
  document.addEventListener('load', (e) => { ... }, true);
  ```
- **Reproduction / verification:** open the app with DevTools enabled, right-click a track to
  open the rich menu, and break the cover request (DevTools → Network → block). The console
  shows `Refused to execute inline event handler` and the menu cover is blank instead of
  showing the default placeholder.
- **Suggested fix:** delete the `onerror="…"` attributes from the two `utils.js` templates (and
  the five cross-referenced ones in WN-31/WN-32) and extend the existing delegated
  `error`/`load` listeners in `utils.js:533-553` to cover the cases they replace (e.g. a
  `data-fallback-src` attribute for the default cover).
- **Fix side effects:** the delegated `error` handler currently hides any `<img>` that has no
  `data-cover-url`; the rich-menu cover needs a *fallback src*, not a hide, so the delegated
  handler has to learn that case or the placeholder must be supplied up front.
- **Discovered by:** B

#### F-WN-28-6  [P3] — `hls.min.js` (375 KB) is fetched and parsed on every launch although only HLS streams need it

- **File:** `ui/web_new_v2/index.html:19` ; `ui/web_new_v2/js/player.js:122-139` ;
  `main.py:71`
- **Confirmed:** yes
- **Description:** `<script src="js/hls.min.js" defer></script>` sits unconditionally in
  `<head>`. The file is 375.2 KB. The only consumer is `player.js:122-139`, which uses
  `window.Hls` **only** when the resolved media URL matches `.m3u8`, `/playlist` or
  `format=m3u8` — a minority of providers (YouTube/SoundCloud use direct or proxied streams).
  Because `main.py:71` forces `Cache-Control: no-cache, no-store, must-revalidate, max-age=0`
  on every asset, the 375 KB is re-read from disk and re-transferred on **every** app start.
- **Cause:** the library is loaded statically instead of being injected on demand the first
  time an HLS URL is seen.
- **Trigger conditions:** every launch.
- **User impact:** 375 KB of download + parse and ~1 MB of resident script on every cold start,
  for a code path most sessions never take; `defer` means it does not block the parser, but it
  still executes before the deferred module graph (`main.js` is a module, deferred classic
  scripts and modules share one ordered execution list, and `hls.min.js` is earlier in the
  document), so it sits in front of `main.js` on the critical path to `init()`.
- **Evidence:**
  ```html
  <!-- ui/web_new_v2/index.html:18-19 -->
      <script src="js/lucide.min.js"></script>
      <script src="js/hls.min.js" defer></script>
  ```
  ```js
  // ui/web_new_v2/js/player.js:122-123
          const isHls = typeof mediaUrl === 'string' && (mediaUrl.includes('.m3u8') || mediaUrl.includes('/playlist') || mediaUrl.includes('format=m3u8'));
          if (isHls && window.Hls && window.Hls.isSupported()) {
  ```
  ```powershell
  Get-ChildItem ui\web_new_v2\js\hls.min.js | Select Name,@{N='KB';E={[math]::Round($_.Length/1KB,1)}}
  # Name        KB
  # hls.min.js  375.2
  ```
- **Reproduction / verification:** DevTools → Network on a cold start: `js/hls.min.js` is
  fetched (375 KB, `Cache-Control: no-store`); the same entry appears on every subsequent
  launch.
- **Suggested fix:** load `hls.min.js` lazily — `player.js` can create the `<script>` element
  on the first HLS URL it sees and await its `load` event before `new Hls(...)`; or bundle a
  trimmed build. Note that the current `player.js` path degrades silently to a direct `src` if
  `window.Hls` is missing, so a lazy load must be awaited, not fire-and-forget.
- **Fix side effects:** the first HLS track would start ~1 RTT later; `player.js` currently
  falls back to `audioEl.src = src` when `window.Hls` is absent, so a naive lazy injection
  would silently break HLS playback for that first track.
- **Discovered by:** B

#### F-WN-28-7  [P3] — a dead bridge produces no user-visible error for 45 s, and the error overlay needs three failed launches to appear

- **File:** `ui/web_new_v2/js/main.js:377-388`, `:366-372`
- **Confirmed:** yes
- **Description:** the "bridge-dead" overlay is gated on two conditions: the bridge must still
  be missing after **45 s**, and `sessionStorage['nedotify_bridge_strikes']` must be **≥ 3**.
  The strike counter is incremented once per page load in which the bridge is missing, so the
  overlay can only appear on the *third* consecutive bridge-less load. On the first two
  failures the user gets a fully interactive-looking UI whose every bridge call silently
  fails.
- **Cause:** the counter was designed around the backend watchdog silently reloading the page
  twice, but it cannot distinguish "the watchdog is reloading" from "the user is using the
  app", so the common single-failure case never surfaces an error.
- **Trigger conditions:** the WebView2 bridge failing to initialise (a real scenario — the
  code comments it twice: `main.js:30` "~16s to inject the bridge", `main.js:374-376` "the
  backend watchdog silently reloads twice").
- **User impact:** the app looks alive but nothing works; the user must reload twice, wait
  45 s each time, before any explanation appears. In practice the user restarts the process.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/main.js:374-388
  // Bridge-dead last resort: count page loads that happened without a bridge
  // (the backend watchdog silently reloads twice), and only then show the error
  // overlay — after 45s of bridge absence on the 3rd load (initial + 2 reloads).
  if (!isBridgeReady()) {
      const strikes = parseInt(sessionStorage.getItem('nedotify_bridge_strikes') || '0', 10) + 1;
      sessionStorage.setItem('nedotify_bridge_strikes', String(strikes));
  }
  setTimeout(() => {
      if (isBridgeReady()) return;
      const strikes = parseInt(sessionStorage.getItem('nedotify_bridge_strikes') || '0', 10);
      if (strikes >= 3) {
          sessionStorage.removeItem('nedotify_bridge_strikes');
          showBridgeError();
      }
  }, 45000);
  ```
- **Reproduction / verification:** start the app with the backend bridge disabled (or block
  `window.pywebview` injection) — the splash disappears after the 4 s fallback
  (`main.js:366-372`), the UI renders, but no button works and no message appears until the
  45 s timer fires *and* the strike count is already ≥ 3.
- **Suggested fix:** show a non-blocking "connecting to the application…" state as soon as the
  bridge is known to be missing at, say, 10 s, and lower the overlay threshold to 1 when the
  bridge is still missing at 45 s (the strike counter can remain as a guard against a
  transient watchdog reload).
- **Fix side effects:** a 10 s "connecting" banner would also appear on a genuinely slow cold
  start (the code itself documents ~16 s), so the threshold must be above the observed worst
  case or the banner must be quiet.
- **Discovered by:** B

#### F-WN-28-8  [P3] — `init()` latches `_nedotifyInitialized` before doing the work, so a mid-init exception leaves a permanently half-initialised app with no retry

- **File:** `ui/web_new_v2/js/main.js:390-392`, `:637-648`
- **Confirmed:** yes
- **Description:** `init()` sets `window._nedotifyInitialized = true` on its second line, before
  any of the ~15 module initialisations. The body is wrapped in one big `try/catch`; the catch
  paints a "Critical Init Error" toast and removes the splash — but the latch is already set,
  so no later call can retry. `initWindowResize()` (`main.js:445`) is the only initialiser
  **not** wrapped in the `safeInit` helper, so a throw there aborts everything after it
  (player, search, library, settings, particles, visualizer, lyrics, equalizer, queue).
- **Cause:** the idempotence guard was placed on entry rather than on completion.
- **Trigger conditions:** any exception thrown by an initialiser that is not individually
  wrapped (`initWindowResize`, `initProfileComparison`, the `document.getElementById(...)`
  window-control wiring, `setupProfileAndGreeting`).
- **User impact:** the app shows a red toast and a permanently dead UI (no player, no library,
  no search) with no way to recover except restarting the process.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/main.js:390-392
  async function init() {
      if (window._nedotifyInitialized) return;
      window._nedotifyInitialized = true;
  ```
  ```js
  // ui/web_new_v2/js/main.js:443-445  (initWindowResize is NOT inside safeInit)
          // Window controls (frameless) - Initialize first to ensure app can always be closed
          initWindowResize();
  ```
  ```js
  // ui/web_new_v2/js/main.js:637-648
      } catch (e) {
          console.error("Init Error:", e);
          ...
          const tc = document.getElementById('toast-container');
          if (tc) tc.innerHTML = `<div style="background:red;padding:10px;color:white;z-index:9999;">Critical Init Error: ${escapeHtml(e.message)}</div>`;
      }
  ```
- **Reproduction / verification:** inject a throw into `initWindowResize` (or any unwrapped
  initialiser) and reload — the "Critical Init Error" toast appears and the nav items do
  nothing; reloading the page reproduces the same half-dead state because the latch is set
  before the throw.
- **Suggested fix:** set the latch at the *end* of `init()` (or use a separate
  `_nedotifyInitInFlight` flag), and wrap `initWindowResize()` in `safeInit` like its
  neighbours.
- **Fix side effects:** moving the latch to the end opens a small window in which two
  concurrent `init()` calls could both run; guard with an in-flight promise instead of a
  boolean.
- **Discovered by:** B

#### F-WN-28-9  [P3] — `debug.js` grows an unbounded DOM log and its console wrapper can throw on non-serialisable values

- **File:** `ui/web_new_v2/js/debug.js:22-39`, `:41-43` ; `ui/web_new_v2/js/main.js:436-442`
- **Confirmed:** yes
- **Description:** `debug.js` monkey-patches `console.log/error/warn` and appends a `<div>` to a
  fixed panel for **every** call. There is no cap and no trimming, so the panel grows without
  bound for the lifetime of the page. `js/events.js:74` logs every Python event
  (`console.log('Python Event:', eventName, data)`), and `position_changed` fires roughly
  once per second — so the debug console adds ~3,600 nodes per hour. Separately, the wrapper
  does `JSON.stringify(arg)` for any object argument, which **throws** on cyclic structures
  and on DOM elements; the throw happens inside the `console.log` replacement, so the
  application code that logged the value gets the exception instead of a log line.
- **Cause:** the debug console was written as a fire-and-forget overlay with no retention
  policy and a naive serialiser.
- **Trigger conditions:** the app must be launched with `?debug=1` (`main.js:437`), which is
  opt-in — so the blast radius is limited to a developer session.
- **User impact:** in a debug session the panel degrades over time (DOM growth, layout cost on
  every append) and a `console.log(someElement)` can crash the calling code path.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/debug.js:22-31
      function log(type, args) {
          const msg = Array.from(args).map(arg => typeof arg === 'object' ? JSON.stringify(arg) : arg).join(' ');
          const line = document.createElement('div');
          ...
          debugDiv.appendChild(line);
          debugDiv.scrollTop = debugDiv.scrollHeight;
      }
  ```
  ```js
  // ui/web_new_v2/js/main.js:436-441
              if (new URLSearchParams(location.search).has('debug')) {
                  const dbgScript = document.createElement('script');
                  dbgScript.src = 'js/debug.js';
                  document.head.appendChild(dbgScript);
              }
  ```
- **Reproduction / verification:** launch with `?debug=1`, play a track for a minute, and count
  the `div` children of `#debug-console` (it grows with every `position_changed`); then
  `console.log(document.body)` in the app console and observe the thrown `TypeError`.
- **Suggested fix:** cap the panel at N lines (drop the oldest), and wrap the serialiser in
  `try/catch` with a `[unserialisable]` fallback.
- **Fix side effects:** none — the panel is opt-in and developer-facing.
- **Discovered by:** B

#### F-WN-28-10  [P3] — the entire `AppApi` (174 public methods) is reachable from any script running in the document; the CSP is the only barrier

- **File:** `main.py:348-351` (`js_api=api`) ; `core/api.py` (174 public methods on `AppApi`) ;
  `ui/web_new_v2/index.html:10` (CSP)
- **Confirmed:** yes (blast radius) / the exploitability precondition is a **hypothesis** — no
  XSS was found in the WN-28-owned code
- **Description:** `webview.create_window(..., js_api=api)` exposes the whole `AppApi` object to
  the page as `window.pywebview.api`. pywebview publishes **every public method** of the
  object — there is no allow-list, no per-window restriction and no capability model. The
  surface therefore includes destructive and privileged operations, e.g.
  `open_external_url`/`open_url` (`core/api.py:1109-1116`, guarded only by
  `_is_ssrf_safe_url`), `delete_playlist` (`core/api.py:2504`), `clear_storage`
  (`core/api.py:3105`), `choose_cover_image` (`core/api.py:4002`), `update_track_tags`,
  `import_playlist`, `save_setting`, `play_track`, `play_next`, `add_to_queue`.
  The document's CSP (`script-src 'self'`) is the **only** thing standing between remote
  content (cover art, lyric text, artist bios, search results) and that API.
- **Cause:** the standard pywebview integration. The frontend compensates with a strict CSP and
  a disciplined `escapeHtml`/`textContent` convention, but the two are not coupled by any
  mechanism — nothing fails loudly if the CSP is weakened or an unescaped sink is added.
- **Trigger conditions:** any script execution in the document (an XSS, a CSP regression, a
  same-origin file planted by an installer/update path) immediately yields full backend control.
- **User impact:** with script execution the attacker can delete playlists and downloaded
  files, wipe the cache, rewrite track metadata, open arbitrary URLs in the default browser,
  and drive the player — i.e. remote code execution in the app's trust context.
- **Evidence:**
  ```python
  # main.py:348-351
      window = webview.create_window(
          "NeDotify",
          url=html_path,
          js_api=api,
  ```
  ```powershell
  (Get-Content core\api.py | Select-String -Pattern '^\s{4}def [a-zA-Z_]+\(').Count
  # -> 174
  ```
  ```html
  <!-- ui/web_new_v2/index.html:6-10 -->
  <!-- The pywebview bridge exposes the whole backend API to this document, so an
       injected script would be remote code execution. ... -->
  ```
- **Reproduction / verification:** in DevTools, `Object.keys(window.pywebview.api).length`
  enumerates the whole surface; `await window.pywebview.api.clear_storage('cache')` succeeds
  from the console with no additional authorisation.
  **Missing evidence for a confirmed exploit:** an actual unescaped injection sink. The
  WN-28-owned sinks were audited (`utils.js`, `main.js`, `events.js`, `pages.js`, `boot.js`,
  `contextmenu.js`, `efficiency.js`) and all of them either use `escapeHtml` or `textContent`;
  see §3. The WN-32-owned high-risk sinks (`js/lyrics.js`, `js/artist_profile.js`) were spot
  checked and also use `textContent` for lyric lines and bios. **No XSS was confirmed.**
- **Suggested fix:** (a) keep the CSP strict and add a regression test that asserts the
  `Content-Security-Policy` meta tag is present and that `script-src` contains no
  `'unsafe-inline'`/`'unsafe-eval'`; (b) add a static test that fails on any
  `innerHTML =` / `insertAdjacentHTML` interpolation that is not `escapeHtml`-wrapped; (c) on
  the Python side (WN-03), consider exposing a narrow facade object to `js_api` instead of
  the full `AppApi`, or at minimum deny-list the destructive methods from the JS-facing surface.
- **Fix side effects:** (c) is a breaking change to the bridge contract and touches WN-03…WN-10;
  a facade would need careful forwarding and would break the `window.pywebview.api.<method>`
  convention the frontend uses in ~200 call sites.
- **Discovered by:** B

### 3. Clean areas

- **XSS discipline in the WN-28-owned sinks.** `js/utils.js:17-25` defines `escapeHtml` and it
  is applied at every HTML sink I could reach: `createTrackElement`
  (`utils.js:718-748` — title, artist, cover URL, source badge), `showTrackContextMenu`
  (`utils.js:1125-1202` — title, artist, cover URL), `formatArtistNames`
  (`utils.js:650-657`), `coverImgHtml` (`utils.js:522-530`), `renderPlaylistCoverCollage`
  (`utils.js:587-605`), `artistAvatarHtml` (`utils.js:574-579`),
  `js/events.js:158` (`escapeHtml(data.error)`), `js/main.js:647`
  (`escapeHtml(e.message)`). Text-only payloads use `textContent`
  (`utils.js:159` toast, `boot.js:64` toast, `pages.js:116/162/188` title).
  **No unescaped user-controlled interpolation was found in this area.**
- **CSS-context URL handling.** `utils.js:40-50` `safeCssImageUrl()` correctly recognises that
  `escapeHtml` cannot make a value safe inside `url('…')` and restricts the scheme to
  `https:`/`data:` while stripping `' " ( ) \ ;`. It is used for the one CSS background URL in
  the area (`utils.js:1127`). `getCoverUrl()` (`utils.js:615-648`) returns a raw URL and every
  HTML consumer of it escapes it (verified across all 12 call sites in
  `player.js`, `queue.js`, `home.js`, `home-shell.js`, `library-view.js`, `profile.js`,
  `search-discovery.js`, `artist_profile.js`).
- **Import graph: no cycles.** I mapped the static import graph of all 34 modules under
  `ui/web_new_v2/js/`. There is **no cycle**: the deepest chain is
  `main.js → events.js → search.js → search-discovery.js → home-shell.js → library.js →
  library-view.js → smart-playlists.js → utils.js`, and `utils.js` imports nothing. Because
  there is no cycle, no module observes a partially-initialised binding from another module at
  module-evaluation time.
- **Hub analysis.** `utils.js` is the only real hub — imported by 24 of the 31 hand-written
  modules. `player.js` (12 importers), `library.js` (6) and `home-shell.js` (4) are the next
  tier. The hub is a leaf (imports nothing), which is what keeps the graph acyclic; the
  god-module aspect is covered in §5.
- **`pywebviewready` is handled exactly once per consumer.** `main.js:61` uses
  `{ once: true }` plus an explicit `removeEventListener` in `complete`; `main.js:363` uses
  `{ once: true }`; `main.js:484` (`scheduleSnapButton`) is idempotent because it cancels the
  previous `requestAnimationFrame` before scheduling a new one (`main.js:479-482`).
  `window.onPythonEvent` is bound to a single stable dispatcher at module scope and re-bound
  identically by `initEvents()` (`events.js:69`, `events.js:72`) — no late-clobber window.
- **`init()` is idempotent at the call level.** `window._nedotifyInitialized` (`main.js:391`)
  prevents double initialisation; `initPages`, `initContextMenu`, `initHotkeys`,
  `initEfficiency`, `initBlurObserver`, `initBatchActionBar`, `initWindowResize`
  (`window-resize.js:4-5`) are all individually guarded, so the module-scope
  `document.addEventListener` calls in `utils.js:533/549/561/971/1008/1019` and
  `pages.js:105` / `contextmenu.js:2` / `utils.js:1684` are registered exactly once.
- **Event-name and payload contract (audit rules #6/#7).** `js/events.js` handles
  `download_complete` and `download_failed` and does **not** read a `file_path` from
  `download_complete` (rule #7 respected). There is no `EventSource`/`WebSocket`/SSE usage
  anywhere in the area (rule #6 respected): the only Python→JS channel is
  `window.onPythonEvent`.
- **First-paint DOM size.** ~1,939 elements / 836 `<div>` / 279 `<button>` in `index.html`
  is not a first-paint problem for a desktop WebView2 app; the skeleton splash
  (`index.html:55-62`) covers the module-graph fetch and the bridge wait, and `main.js:607-616`
  removes it once the UI is interactive.
- **CSS is fully wired.** `tests/test_frontend_css_wiring.py` asserts that every `.css` under
  `ui/web_new_v2/css` is linked from `index.html` (only `css/styles.css` is allow-listed as an
  intentional duplicate-import reference), that `visual-polish.css` is linked last among the
  shared sheets, and that `--ring` is defined in a linked sheet. I verified the 26 `<link>`
  tags in `index.html:17-50` match that expectation.

### 4. Coverage gaps

- **No browser-level or DOM-level test exists.** `tests/test_frontend_js.py` states this
  explicitly in its own docstring: "The Windows frontend is Vanilla-JS ES modules running
  inside pywebview/WebView2 and has **no runtime test harness** in this repository.
  Everything below is therefore a *static* assertion on the shipped source text (plus a real
  `node --check` parse when a Node binary is available)."
  I confirmed there is no `playwright`/`selenium` reference anywhere in `tests/`.
  Consequently F-WN-28-1 (namespace clobbering), F-WN-28-4 (observer scope) and F-WN-28-5
  (CSP-blocked handlers) are all invisible to the current suite — every one of them is
  detectable with a 20-line DOM test or a static grep, and none is checked.
- **The visual guard covers nothing in this area right now.**
  `tools/visual_guard/goldens/` exists but is **empty** (0 files), so the pixel half of
  `run_guard.py` has no baseline to compare against and cannot detect a visual regression.
  `tools/visual_guard/reports/` contains two historical JSON reports only. The tool is a
  CLI (`python tools/visual_guard/run_guard.py --capture|--compare|--all`), not a pytest
  target, and `tests/test_visual_guard_diff.py` only exercises the *arithmetic* of
  `compare_png`/`compare_sets` on synthetic images — it never captures the real UI. So
  `index.html` layout and `js/utils.js` rendering have **no** visual regression coverage.
- **`tests/test_visual_guard_css_decls.py`** guards the *values* of
  transition/animation/backdrop-filter/filter/will-change/contain declarations and the custom
  properties feeding them, by (file, property, value). As `tests/test_frontend_css_wiring.py`
  itself documents, it "scans every `.css` file under `ui/` whether or not the document links
  it", so it is structurally unable to notice a change in *which* stylesheets are applied — and
  it says nothing about the JS/DOM layer at all.
- **`tests/test_frontend_js.py` covers 7 files** for `node --check`
  (`events.js`, `main.js`, `artist_profile.js`, `utils.js`, `boot.js`, `player.js`,
  `lyrics.js`) — `pages.js`, `debug.js`, `contextmenu.js` and `efficiency.js` are **not**
  parse-checked, and `node` is optional (`pytest.skip` when absent; it is present on this
  machine, so the check does run). The file's substantive assertions are all about the
  `api_error` handler and the `addPythonEventHandler` registry; it has **no** assertion about
  the global namespace, the CSP, or inline event handlers.
- **I did not run the app.** Per the audit ground rules the real app must not be launched
  (it would disturb `~/.nedotify/`), so all runtime claims about F-WN-28-1, F-WN-28-4,
  F-WN-28-5 and F-WN-28-7 are derived from source plus an executable node reproduction of the
  module-ordering semantics, not from an observed session.
- **Bridge surface details were read, not audited.** `core/api.py` (174 methods) was read only
  for the method inventory and for `open_url`/`_is_ssrf_safe_url`; the SSRF guard, the
  `_emit` thread-safety and the per-method permission model belong to WN-03…WN-10 and were
  not re-reviewed here.
- **`js/efficiency.js`'s effectiveness could not be measured.** There is no profiler run
  against the webview in the repository (the `tools/bench` harness is Python-side), so the
  cost claims in F-WN-28-4 are analytic (mutation counts × query cost), not measured.

### 5. Architecture improvements (ARCH)

These are improvements **without** a proven defect; they are reported separately from §2.

- **ARCH-1 — `js/utils.js` is a 1,690-line god-module mixing four unrelated concerns.**
  It holds (a) DOM/HTML builders (`createTrackElement`, `coverImgHtml`,
  `renderPlaylistCoverCollage`, `artistAvatarHtml`), (b) formatters (`formatTime`,
  `formatListeningTime`, `formatArtistNames`), (c) the modal focus-trap manager
  (`openModalFocusTrap`/`closeModalFocusTrap`/`isFocusInsideModalTrap`, ~140 lines),
  (d) canvas/DPR plumbing (`sizeCanvasForDpr`, `registerCanvasDprListener`), (e) storage
  helpers (`checkLocalStorageQuota`, `compressBackgroundImage`), (f) the multi-select engine
  (`selectedTracksMap`, `handleTrackMultiSelectClick`), (g) the track context menu
  (`showTrackContextMenu`, ~290 lines), (h) the tag-edit modal (`openEditTagsModal`), and
  (i) the recommendation-feedback bridge wrapper. It is also **not a pure module**: it installs
  six `document`-level listeners at module-evaluation time (`utils.js:533`, `:549`, `:561`,
  `:971`, `:1008`, `:1019`) plus a toast bridge (`:166-172`) and a toast-container bootstrap
  (`:133-146`). Direction: split into `dom/`, `format/`, `modal/`, `canvas/`, `storage/`,
  `selection/` and `bridge/` modules and keep `utils.js` as a thin re-export barrel. Risk:
  24 importers must be updated; the module-scope side effects must be moved into an explicit
  `initUtils()`.
- **ARCH-2 — the global `window.NeDotify` namespace is an unowned, half-mergeable registry.**
  Three modules write to it (`utils.js:1079`, `lyrics.js:190/1261`, `player.js:1196`),
  `main.js:82` replaces it, and 20+ modules read from it through optional chaining — which is
  exactly how F-WN-28-1 became invisible. Direction: delete the global in favour of direct
  ES-module imports (the code is already ES modules; the global is a leftover of the
  pre-module era). A short-term mitigation is a single `defineNeDotify()` merge helper.
- **ARCH-3 — the frontend talks to the backend through ~50 distinct `window.pywebview.api.*`
  calls with no typed façade.** There is no wrapper module that owns the bridge contract:
  each call site does its own optional-chaining and its own error handling, and the event
  bus in `events.js` is the only place that knows the event names. Direction: introduce
  `js/bridge.js` exporting a typed façade (`bridge.getSettings()`, `bridge.playTrack(…)`, …)
  and a single event-name constant table, so the bridge contract has one owner and can be
  validated against `core/api.py` by a test.
- **ARCH-4 — two independent "current page" notions coexist.**
  `js/pages.js:13` keeps `currentBasePage`; `js/events.js:13-14` keeps `currentPageId` — which
  is written on `nedotify:page_changed` and **never read** (the actual visibility test is
  `isPageVisible()` at `events.js:16-19`, which re-queries the DOM). Direction: delete
  `currentPageId` and make `pages.js` the single owner of navigation state, exposed through
  an event or a getter.
- **ARCH-5 — `js/events.js` is a 400-line switch that mixes routing, rendering and
  side-effects.** `case 'download_complete'` alone calls three unrelated subsystems. Direction:
  split the dispatcher into per-domain handlers registered through the existing
  `addPythonEventHandler` registry (which already exists and is tested), so each event name
  has exactly one owner and can be unit-tested in isolation.
- **ARCH-6 — 26 render-blocking stylesheets and 25 separate module requests, all with
  `Cache-Control: no-store`.** `main.py:71` forces revalidation on every asset, so each
  launch re-reads ~380 KB of CSS and ~500 KB of JS from disk over the loopback Bottle server
  (26 + 25 HTTP requests), plus 375 KB of `hls.min.js`. The no-store policy is a deliberate
  freshness guarantee (the code comments say so) but it also removes the browser cache as a
  lever. Direction: consider a build-time content hash in the asset name with a short
  `max-age` for immutable hashed files, and keep `no-store` only for `index.html`.
- **ARCH-7 — the frontend has no runtime test layer at all.** The entire verification story
  is static greps plus `node --check`. A minimal DOM harness (jsdom, or a
  `data:`-URL page driven by the existing CDP tooling in `tools/bench`) would have caught
  F-WN-28-1, F-WN-28-4 and F-WN-28-5 automatically. This is the single highest-leverage
  structural improvement available to this area.
- **ARCH-8 — `js/debug.js` is loaded by URL query at runtime.**
  `main.js:437` injects `js/debug.js` when `?debug=1` is present. The URL is served by the
  local pywebview server, so the parameter is not attacker-controllable today, but it does
  mean a debug surface (console monkey-patching, an always-on overlay) can be switched on in
  a shipping build. Direction: gate it on a build/debug flag in the Python side rather than a
  URL parameter, or keep it but make the overlay removable.
