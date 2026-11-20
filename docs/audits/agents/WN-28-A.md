## AREA WN-28 — UI document, bootstrap, event bus, shared utilities — ROLE A

### 1. Scope reviewed

**Files opened (path : line ranges actually read)**

- `ui/web_new_v2/index.html` — 1–2314 (whole document: head/CSP/script tags, body DOM, modals, onboarding, footer script tags)
- `ui/web_new_v2/js/boot.js` — 1–72 (whole file)
- `ui/web_new_v2/js/main.js` — 1–718 (whole file)
- `ui/web_new_v2/js/events.js` — 1–464 (whole file)
- `ui/web_new_v2/js/pages.js` — 1–198 (whole file)
- `ui/web_new_v2/js/debug.js` — 1–44 (whole file)
- `ui/web_new_v2/js/contextmenu.js` — 1–46 (whole file)
- `ui/web_new_v2/js/efficiency.js` — 1–192 (whole file)
- `ui/web_new_v2/js/utils.js` — 1–1690 (whole file)

**Callees traced into other areas (read for the bridge contract, not audited as WN-28 code)**

- `core/api.py` — L395–524 (`_install_bridge_error_logging`, `_offline_bridge_result`), L1090–1269 (`_emit`, `_on_track_changed`, `_on_queue_end`, `_on_audio_error`), L1360–1449 (`report_state`, `report_position`, `_notify_queue_updated`), L1770–1794 (`get_queue`), L2085–2154 (`search`/`search_results`), L2300–2379 (`download_track`), L2320–2360 (`download_failed` call sites), L2753/3038/3092/3207/3264/3327–3385/3490–3528/3567/3715–3793/3994/4091/4160/4201–4211 (`_emit` call sites)
- `core/downloader.py` — L95–234, L780–890 (`_emit`, `download_complete`, `download_failed`, `download_queue_updated`)
- `core/user_errors.py` — 1–24 (`describe_error` payload shape)
- `core/proxy.py` — `proxy_status` emit sites (L1020, L1108, L1118)
- `services/watchdog_service.py` — L129 (`library_updated`)
- `services/base_service.py` — L285–313 (provider track shape: `source_id`, **no** `id`)
- `main.py` — L290–429 (`on_loaded()` → `track_changed` / `session_autoplay` emit)
- `.venv_win/Lib/site-packages/webview/util.py` L150–259, `event.py` L30–93, `js/finish.js` L1–12, `platforms/edgechromium.py` L110–130, L296–314 (pywebview 5.4 event ordering)
- `ui/web_new_v2/js/player.js` — L915–1034, L1190–1289 (consumer of `track_changed` / re-sync check)
- `ui/web_new_v2/js/library.js` — L545–623; `ui/web_new_v2/js/queue.js` — L55–94; `ui/web_new_v2/js/ui-style.js` — L1–40, L180–294; `ui/web_new_v2/js/home-shell.js` — L65–89; `ui/web_new_v2/js/profile-comparison.js` — 1–56; `ui/web_new_v2/js/lyrics.js` — L185–198, L1256–1262 (cross-module consumers of the areas above)
- `ui/web_new_v2/css/components/base.css` L869–880, L3045–3095; `css/components/settings-refresh.css` L1–5 (view/overlay CSS, to judge the "two active views" question)
- `tests/test_frontend_js.py` — 1–318 (what the existing static suite pins)

**Verification commands run**

- `Test-Path` on every `<script src>` target → all 12 referenced files exist
- Python script extracting every `_emit("…")` / `emit_event("…")` from `core/api.py`, `core/downloader.py`, `core/proxy.py`, `services/watchdog_service.py`, `main.py` and every `case '…':` in `events.js` → diff table in §2
- Python script over `index.html`: 524 `id=` attributes, **0 duplicates**; 3 `<form>` elements (all have submit handlers); 1 `<img>` without `alt`; 1 `<button>` with no accessible name (filled at runtime by `feature-controls.js`); 0 `<a href>`
- `pytest tests/test_frontend_js.py -q` → **41 passed** (none of the findings below are covered by it)

---

### 2. Findings

#### F-WN-28-1  [P1] — Bridge events that arrive before `initEvents()` installs the core handler are silently dropped: the restored session track and the session-autoplay request never reach the UI

- **File:** `ui/web_new_v2/js/events.js:46-73` (also `ui/web_new_v2/js/main.js:352-372, 516-528`; trigger in `main.py:389-400`)
- **Confirmed:** yes (the drop mechanism is deterministic; see "Reproduction" for the pywebview 5.4 ordering that makes it hit on every start)
- **Description:** `events.js` installs a *stable dispatcher* on `window.onPythonEvent` at module-evaluation time (good), but the **core switch that actually interprets the events** lives in `coreEventHandler`, which is `null` until `initEvents()` runs. `initEvents()` is called exactly once, from `main.js:528`, i.e. *after* `init()` has awaited the bridge (`awaitBridge()` → `pywebviewready`) **and** after `await safeInit('Icons', …)` which is gated on `requestIdleCallback(…, {timeout: 300})`. Any event that arrives in that window reaches `dispatchPythonEvent`, finds `coreEventHandler === null`, and is **dropped with no trace** — no queue, no replay, no log line.
  The two events that matter most are emitted by `main.py::on_loaded()`, which pywebview fires *immediately* after injecting the bridge, i.e. before `init()` has even started:
  - `track_changed` — the session-restored track (`main.py:391-392` → `core/api.py:1240`)
  - `session_autoplay` — the "resume where you left off" request (`main.py:396-400`)
- **Cause:** The registry design fixed the *subscriber* half of the problem (the subscriber loop runs unconditionally) but not the *core handler* half. The comment at `events.js:46-47` ("null before that so the registry stays usable even if `initEvents()` throws or is never reached") treats the null handler as a feature, but in practice it means "every event before `initEvents()` is lost", and `initEvents()` is deliberately scheduled late (behind an idle callback) rather than early.
- **Trigger conditions:** Any app start with a saved session (`~/.nedotify/` session file present) — i.e. every normal restart. The window is: from `pywebviewready` to the `requestIdleCallback`/`setTimeout(50)` callback in `safeInit('Icons')` (50–300 ms), during which the Python `on_loaded()` thread emits `track_changed` + `session_autoplay`.
- **User impact:** After a restart the player bar shows "Не играет" / "Трек не выбран" and the full-player page shows no track, although the backend has the track queued; and the "continue playback where you left off" autoplay silently never happens (the user must press play themselves). Nothing is logged on the JS side beyond `console.log('Python Event:', …)` — the event *is* seen in the console by the dispatcher, which makes the failure look like a backend problem.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/events.js:46-53
  let coreEventHandler = null;

  function dispatchPythonEvent(eventName, data) {
      if (coreEventHandler) {                 // <-- null until initEvents()
          try { coreEventHandler(eventName, data); } catch (err) { ... }
      }
      for (const fn of pythonEventHandlers.slice()) { ... }
  }
  ```
  ```js
  // ui/web_new_v2/js/events.js:71-73
  export function initEvents() {
      window.onPythonEvent = dispatchPythonEvent;
      coreEventHandler = function(eventName, data) { switch (eventName) { ... } };
  }
  ```
  ```js
  // ui/web_new_v2/js/main.js:516-528
  await safeInit('Icons', () => new Promise((resolve) => {
      const runIcons = () => { try { renderIcons(); } catch (err) {...} resolve(); };
      if (window.requestIdleCallback) { window.requestIdleCallback(runIcons, { timeout: 300 }); }
      else { setTimeout(runIcons, 50); }
  }));
  await safeInit('Events', () => initEvents());   // <-- core handler installed HERE, ~50-300ms late
  ```
  ```python
  # main.py:389-400
  def on_loaded():
      logging.info(f"[startup] window loaded ...")
      if app_core.engine.queue.current_track:
          app_core.engine._on_track_changed(app_core.engine.queue.current_track)   # -> _emit("track_changed")
      try:
          if app_core.session.should_autoplay and app_core.engine.queue.current_track:
              api.emit_event("session_autoplay", {...})
  ```
  pywebview 5.4 ordering that makes the window real:
  ```python
  # .venv_win/.../webview/util.py:210-225  (generate_js_object, a background thread)
  def generate_js_object():
      window.run_js(js_code)                 # injects api.js
      window.events._pywebviewready.set()
      try:
          with window._expose_lock:
              func_list = generate_func()
              window.run_js(finish_script % {...})   # -> dispatchEvent('pywebviewready')
              window.events.loaded.set()              # <-- on_loaded() runs from here
  ```
  ```python
  # .venv_win/.../webview/event.py:55-60
  if len(self._items):
      if self._should_lock: execute()
      else:
          t = threading.Thread(target=execute)   # 'loaded' handlers run on a SEPARATE thread
          t.start()
  ```
  ```js
  // .venv_win/.../webview/js/finish.js:9
  window.dispatchEvent(new CustomEvent('pywebviewready'));
  ```
  ```python
  # .venv_win/.../webview/platforms/edgechromium.py:126
  self.webview.Invoke(Func[Object](lambda: self.webview.ExecuteScriptAsync(script).ContinueWith(...)))
  ```
  `ExecuteScriptAsync` means the script is *queued*; `Invoke` returns as soon as the delegate has run. The WebView UI thread therefore executes: `api.js` → `finish.js` (fires `pywebviewready` → `init()` starts and suspends at the `requestIdleCallback` await) → **`onPythonEvent` script for `track_changed`** → *later* the idle callback → `initEvents()`. The `track_changed` script runs with `coreEventHandler === null`.
- **Reproduction / verification:**
  1. Start the app once so a session is saved (`core/session.py`), then close and restart it.
  2. Open the WebView2 devtools console (`Ctrl+Shift+I` works in the EdgeChromium backend).
  3. Observe `Python Event: track_changed {…}` in the console **and** an empty player bar ("Не играет") — the event was received but no case ran.
  4. Static confirmation: `grep -n "coreEventHandler" ui/web_new_v2/js/events.js` shows the only assignment is inside `initEvents()`; `grep -n "initEvents()" ui/web_new_v2/js/*.js` shows a single call site (`main.js:528`), which sits behind the `requestIdleCallback` await.
  5. Deterministic variant: temporarily move `await safeInit('Events', () => initEvents());` above the Icons await and re-test — the restored track appears.
- **Suggested fix:** Install the core handler at module-evaluation time (same place the dispatcher is bound), not inside `initEvents()`; or, if the handler genuinely needs a live DOM, buffer incoming events in `dispatchPythonEvent` while `coreEventHandler === null` and replay them immediately after `initEvents()` returns.
- **Fix side effects:** Replaying `track_changed` into a half-initialised DOM can make `onTrackChanged()` touch elements that do not exist yet (`player.js` runs before `initPlayer()` has wired the controls). A replay buffer keyed on "init complete" (e.g. flush after `initEvents()` **and** after `initPlayer()`), or a core handler that only touches elements it can find, is safer than a bare move.
- **Discovered by:** A

---

#### F-WN-28-2  [P2] — `download_complete` carries only the numeric DB `track_id`, so the download spinner on provider-sourced rows is never cleared after a successful download

- **File:** `ui/web_new_v2/js/utils.js:688-791, 977-1017` (also `core/downloader.py:835-840`, `core/api.py:2319-2335`, `services/base_service.py:305-313`)
- **Confirmed:** yes
- **Description:** `download_complete` is emitted with `{"track_id": <int>}` and nothing else — no `source_id`, no `file_path` (this matches the documented contract, `WIN_AUDIT_CONTEXT.md` rule 7). The JS success path re-matches that id against the rendered row with `matchDownloadTarget()`, which compares it against `el.dataset.trackSourceId` and `el._trackData.id / .source_id`. For a row that came from a provider (search results, album details, playlist details) the DOM is keyed by the **provider** id (a YouTube videoId), while the payload carries the **database** id that was minted by `db.add_track()` at download time. The two can never be equal, so `clearDownloadSpinner()` never runs and the button keeps spinning forever.
  The failure path already contains the compensating fallback; the success path does not — a clear asymmetry that shows the mismatch was known on one side only.
- **Cause:** The DOM row is identified by `source_id`; the event payload is identified by the DB primary key; no translation between the two exists on the success path.
- **Trigger conditions:** Download any track from the **Search** page, from an album-detail modal, or from a playlist-detail modal (any track that is not already a row in the local DB). The library page is unaffected because those rows carry the DB `id` in `_trackData`.
- **User impact:** The download icon on that row spins indefinitely even though the file was downloaded successfully into `~/.nedotify/downloads/`. The user can click it again (the `downloading` guard class was never cleared, but the button state is wrong), which enqueues a duplicate download request that the backend then rejects as a duplicate.
- **Evidence:**
  ```python
  # core/downloader.py:838-839
  self._emit('download_queue_updated', {'track_id': track_id, 'status': 'completed'})
  self._emit('download_complete', {'track_id': track_id})     # <- DB id only
  ```
  ```python
  # core/api.py:2319-2327  (a provider track not yet in the DB gets a NEW numeric id)
  if not track_id:
      try:
          track_id = self._core.db.add_track(
              title=track_data.get("title", "Unknown"), artist=..., source=source,
              source_id=source_id, duration=track_data.get("duration", 0))
  ```
  ```python
  # services/base_service.py:305-313  (provider results carry source_id and NO id)
  return {'title': ..., 'artist': ..., 'duration': ..., 'source': 'youtube',
          'source_id': source_id, 'source_url': ..., 'cover_url': cover_url}
  ```
  ```js
  // ui/web_new_v2/js/utils.js:694
  item.dataset.trackSourceId = String(track.source_id || track.id || '');
  // ui/web_new_v2/js/utils.js:977-992
  function matchDownloadTarget(el, data) {
      const tid = (data.track_id !== undefined && data.track_id !== null) ? String(data.track_id) : '';
      const sid = (data.source_id !== undefined && data.source_id !== null) ? String(data.source_id) : '';
      if (!tid && !sid) return false;
      const ds = el.dataset && el.dataset.trackSourceId ? String(el.dataset.trackSourceId) : '';
      if (ds && ((tid && ds === tid) || (sid && ds === sid))) return true;
      const trk = el._trackData;
      if (trk) {
          const ids = [trk.id, trk.source_id].map(v => (v !== undefined && v !== null) ? String(v) : '');
          if (ids.some(v => v && ((tid && v === tid) || (sid && v === sid)))) return true;
      }
      return false;                       // <- provider row: "dQw4w9WgXcQ" != "42"  =>  no match
  }
  ```
  ```js
  // ui/web_new_v2/js/utils.js:1008-1017  (success path — no fallback)
  document.addEventListener('nedotify:track_downloaded', (e) => {
      const data = e.detail;
      if (!data) return;
      document.querySelectorAll('.track-item').forEach(el => {
          if (matchDownloadTarget(el, data)) { clearDownloadSpinner(el, true); }
      });
      renderIcons();
  });
  // ui/web_new_v2/js/utils.js:1029-1036  (failure path — HAS a fallback)
  if (!matched) {
      document.querySelectorAll('.download-btn.downloading').forEach(btn => {
          btn.classList.remove('downloading');
          btn.innerHTML = '<i data-lucide="download" ...></i>';
      });
  }
  ```
- **Reproduction / verification:**
  1. Start the app, go to Search, search for something (e.g. "daft punk"), and click the download icon on a provider row that is not in the local library.
  2. Wait for the file to land in `~/.nedotify/downloads/` and for the "downloaded" toast / Library refresh.
  3. The button on the **search row** is still the spinning `loader-2` icon; the Library page shows the track as downloaded. The same row in the Library *does* flip to the check mark (that row carries the DB `id`).
  4. Static confirmation: `grep -n "dataset.trackSourceId" ui/web_new_v2/js/utils.js` and `grep -n "_emit('download_complete'" core/downloader.py`.
- **Suggested fix:** Carry the provider id in the event (`download_complete` → `{"track_id": …, "source_id": …, "source": …}`) and match on `source_id` as well, or add the same "no rendered row matched" fallback to the success path that the failure path already has.
- **Fix side effects:** Extending the payload changes the bridge contract for `download_complete`; the contract is documented in `WIN_AUDIT_CONTEXT.md` rule 7 and is asserted by tests, so the payload extension and the doc/test must change together. A fallback that clears *all* spinners on success would be wrong (it would clear spinners of still-running downloads) — see F-WN-28-4.
- **Discovered by:** A

---

#### F-WN-28-3  [P2] — `main.js` replaces `window.NeDotify` wholesale and destroys the floating-menu guard that `utils.js` installs at module scope

- **File:** `ui/web_new_v2/js/main.js:82-173` (also `ui/web_new_v2/js/utils.js:1060-1082, 1214`; `ui/web_new_v2/js/library.js:847`; `ui/web_new_v2/js/player.js:1234`; `ui/web_new_v2/js/lyrics.js:1260-1262`)
- **Confirmed:** yes
- **Description:** `utils.js` publishes `window.NeDotify._armFloatingMenuGuard` and `window.NeDotify.closeAllFloatingMenus` while its module body runs. `main.js` then assigns a brand-new object literal to `window.NeDotify` in its module body. ES module evaluation order guarantees that every dependency's body (including `utils.js`) runs **before** the importing module's body, so `main.js`'s assignment unconditionally discards the two properties `utils.js` just installed. Every call site (`utils.js:1214`, `library.js:847`, `player.js:1234`) is written as `window.NeDotify?._armFloatingMenuGuard?.()` — an optional call on a now-`undefined` property, i.e. a silent no-op.
- **Cause:** Two modules publish into the same global namespace with incompatible semantics: `utils.js` *merges* (`window.NeDotify = window.NeDotify || {}`), `main.js` *replaces*.
- **Trigger conditions:** Every start. The guard is armed lazily on the first floating menu, so the symptom is: a track/playlist context menu opened in a small window stays stranded (mis-positioned) after the window is maximised — exactly the bug the code comment at `utils.js:1042-1046` says it fixed.
- **User impact:** The context menu stays at its old screen coordinates after a resize/maximise and can end up off-screen or over the wrong control; the user has to press Escape / click elsewhere to dismiss it. `window.NeDotify.closeAllFloatingMenus` is also gone (no external caller today), and `window.NeDotify.toggleMiniLyrics` (`lyrics.js:1262`, also module scope) is lost with it.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/utils.js:1079-1081  (runs during utils.js module evaluation)
  window.NeDotify = window.NeDotify || {};
  window.NeDotify._armFloatingMenuGuard = _arm;
  window.NeDotify.closeAllFloatingMenus = closeAllFloatingMenus;
  ```
  ```js
  // ui/web_new_v2/js/main.js:81-93  (runs during main.js module evaluation -> AFTER utils.js)
  let trackWaveRequestSequence = 0;
  window.NeDotify = {
      openPlaylistMenu: openPlaylistMenu,
      createPlaylist: createPlaylist,
      loadHome: loadHome,
      ...
  };
  ```
  ```js
  // ui/web_new_v2/js/utils.js:1042-1046 (the comment describing the behaviour that is lost)
  /* Fixed-position popups keep viewport-absolute coordinates. Resizing or
     scrolling the window invalidates them, so a menu opened in a small window
     stayed stranded (misplaced) after the window was maximised. ... */
  ```
  ```js
  // ui/web_new_v2/js/utils.js:1214
  window.NeDotify?._armFloatingMenuGuard?.();     // <- undefined -> no-op
  ```
- **Reproduction / verification:**
  1. `node --input-type=module -e "…"` is overkill; the static proof is enough: `grep -n "window.NeDotify *=" ui/web_new_v2/js/*.js` → `utils.js:1079` (merge), `main.js:82` (replace), `lyrics.js:190/1261`, `player.js:1196` (merge, but inside `initLyrics()`/`initPlayer()` → runtime → safe).
  2. In the running app: open a track context menu, then maximise the window → the menu does not follow/dismiss (compare with the intended behaviour in the comment).
  3. In the devtools console: `typeof window.NeDotify._armFloatingMenuGuard` → `"undefined"`; `typeof window.NeDotify.closeAllFloatingMenus` → `"undefined"`.
- **Suggested fix:** Make `main.js` merge instead of replace (`window.NeDotify = Object.assign(window.NeDotify || {}, {...})`), or publish `main.js`'s API onto the existing object rather than replacing it.
- **Fix side effects:** Merging means `main.js`'s `loadHome`/`loadLibrary`/… overwrite the same-named properties set earlier by `lyrics.js:190-196` — those are set inside `initLyrics()` at runtime (after `main.js`), so they are unaffected today, but the merge order becomes load-bearing and should be documented. Fixing this also **activates** the listener leak described in F-WN-28-10, which is currently masked because the guard never arms.
- **Discovered by:** A

---

#### F-WN-28-4  [P2] — `download_failed` clears the spinner of *every* downloading button, not only the failed track's

- **File:** `ui/web_new_v2/js/events.js:266-281`
- **Confirmed:** yes
- **Description:** The `download_failed` case begins with a global sweep that removes the `downloading` class and rewrites the icon of **all** `.download-btn.downloading` elements in the document, not just the one belonging to the failed track. The track-specific clearing happens afterwards, in `utils.js`, via the `nedotify:track_download_failed` event.
- **Cause:** The handler needed a "the failed row may not be rendered" fallback and implemented it as a global reset instead of a scoped one. The `download_failed` payload *does* carry `track_id`, so the scope could have been determined.
- **Trigger conditions:** Two or more downloads running concurrently (batch download, or two separate clicks) and one of them fails.
- **User impact:** The still-running downloads lose their spinner and show an idle "download" arrow, so the user believes they finished (or that nothing is happening) and clicks again → a duplicate download request that the backend rejects as a duplicate. When the second download eventually completes, its `download_complete` event arrives with the DB id, which for a provider row does not match (F-WN-28-2), so the row can be left showing an idle download arrow even though the file exists.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/events.js:266-275
  case 'download_failed': {
      // Drop the spinner on every download button (global fallback;
      // utils.js also clears the exact track button by strict id match).
      document.querySelectorAll('.download-btn.downloading').forEach(btn => {
          btn.classList.remove('downloading');
          if (!btn.classList.contains('downloaded')) {
              btn.innerHTML = '<i data-lucide="download" style="width:14px;height:14px"></i>';
          }
      });
      renderIcons();
  ```
  ```js
  // ui/web_new_v2/js/utils.js:767-790  (the guard that is defeated by the global reset)
  if (downloadBtn.classList.contains('downloaded') || downloadBtn.classList.contains('downloading')) {
      return;                       // <- 'downloading' was just removed by events.js
  }
  ```
- **Reproduction / verification:**
  1. Start two downloads (e.g. download two different tracks from Search, or use the batch action bar on 2+ tracks).
  2. Force one of them to fail (e.g. pick a track whose provider refuses the download, or revoke network access for one provider only).
  3. Observe that the *other*, still-running track's button immediately switches from the spinner back to the plain download arrow.
  4. Static confirmation: `grep -n "download-btn.downloading" ui/web_new_v2/js/events.js ui/web_new_v2/js/utils.js` → both places sweep the whole document.
- **Suggested fix:** Scope the reset to the failed track (match on `data.track_id` / `source_id` as in `utils.js::matchDownloadTarget`) and only fall back to a global sweep when no row matched **and** no other download is still in flight.
- **Fix side effects:** Narrowing the sweep means a download that fails *without* a rendered row can leave a spinner behind — the current global sweep is a safety net for that case. The correct fix is to keep a live registry of in-flight downloads (track id → button) rather than relying on a document-wide DOM sweep.
- **Discovered by:** A

---

#### F-WN-28-5  [P2] — Fire-and-forget bridge calls produce unhandled promise rejections and can leave the UI stuck

- **File:** `ui/web_new_v2/js/main.js:104-109` (also `ui/web_new_v2/js/utils.js:767-790, 1271-1277, 1286-1289, 1647-1678`)
- **Confirmed:** yes
- **Description:** Several call sites invoke `window.pywebview.api.*` without awaiting, returning or catching the promise. `core/api.py::_install_bridge_error_logging` re-raises after emitting `api_error`, so the JS promise **rejects** — which becomes an unhandled rejection (nothing in the app installs a `window.onunhandledrejection` handler; the WebView2 console is the only place it shows).
  The most consequential case is the download path: `main.js::NeDotify.downloadTrack` is the *primary* branch in `utils.js::createTrackElement`, and the `else` branch that contains the `try/catch` that resets the spinner is **dead code** because `window.NeDotify.downloadTrack` always exists.
- **Cause:** The bridge call sites were written as fire-and-forget, while the error contract they rely on (`api_error` / `download_failed` events) is only a *partial* backstop — a rejection can also occur before/without those events (e.g. the method is missing, or the wrapper itself fails).
- **Trigger conditions:** Any bridge call that raises — a provider error, an offline-mode refusal, a `describe_error` path, or a method that does not exist on the API object.
- **User impact:** (a) The download button of the affected row can keep the spinning "downloading" state forever, because the only code that resets it on error lives in the unreachable `else` branch of `utils.js:780-789`; (b) the batch-action bar reports success even when `add_tracks_to_queue` rejected (`utils.js:1657-1660` shows the success toast *after* an un-awaited `await` that is not inside a `try`); (c) the "share" action always reports "Ссылка скопирована в буфер!" even when `navigator.clipboard.writeText` rejected (`utils.js:1286-1289`).
- **Evidence:**
  ```js
  // ui/web_new_v2/js/main.js:104-109
  downloadTrack: (track) => {
      if (!track) return;
      if (window.pywebview?.api?.download_track) {
          window.pywebview.api.download_track(track);     // <- no await, no .catch(), promise dropped
      }
  },
  ```
  ```js
  // ui/web_new_v2/js/utils.js:778-789
  if (window.NeDotify?.downloadTrack) {
      window.NeDotify.downloadTrack(track);               // <- PRIMARY branch: no error handling
  } else if (window.pywebview?.api?.download_track) {
      try {
          await window.pywebview.api.download_track(track);
      } catch(err) {
          downloadBtn.classList.remove('downloading');      // <- unreachable: NeDotify always exists
          downloadBtn.innerHTML = '<i data-lucide="download" ...></i>';
          renderIcons(item);
          showToast('Ошибка скачивания', 'error');
      }
  }
  ```
  ```python
  # core/api.py:428-441  (the wrapper re-raises, so the JS promise rejects)
  except Exception as exc:
      logger.error("bridge call %s() failed: %s: %s", method_name, type(exc).__name__, exc, exc_info=True)
      try:
          inner_self._emit("api_error", {"method": method_name, "error": f"{type(exc).__name__}: {exc}",
                                         **describe_error(exc, method_name)})
      except Exception:
          logger.debug("api_error emit failed", exc_info=True)
      raise
  ```
  ```js
  // ui/web_new_v2/js/utils.js:1647-1661  (batch "add to queue")
  document.getElementById('batch-btn-queue')?.addEventListener('click', async () => {
      ...
      if (window.pywebview?.api?.add_tracks_to_queue) {
          await window.pywebview.api.add_tracks_to_queue(tracks);   // <- no try/catch
      } else if (window.pywebview?.api?.add_to_queue) { ... }
      window.dispatchEvent(new CustomEvent('nedotify:toast',
          { detail: { msg: `✅ Добавлено в очередь: ${tracks.length} треков`, type: 'success' } }));
  ```
  ```js
  // ui/web_new_v2/js/utils.js:1284-1290  (share)
  case 'share':
      const shareStr = `${track.title || ''} - ${track.artist || ''}`;
      if (navigator.clipboard) { navigator.clipboard.writeText(shareStr); }   // <- rejected promise ignored
      showToast('Ссылка скопирована в буфер!', 'success');
  ```
- **Reproduction / verification:**
  1. Devtools console: `window.addEventListener('unhandledrejection', e => console.log('REJ', e.reason))`.
  2. Trigger any failing bridge call (e.g. download a track from a provider that refuses, or temporarily break `window.pywebview.api.get_playlists` in the console and press the batch "add to queue" button) → the rejection handler fires and no toast is shown.
  3. Static confirmation: `grep -n "pywebview.api\." ui/web_new_v2/js/utils.js ui/web_new_v2/js/main.js` and look for calls that are neither awaited inside a `try` nor `.catch()`-ed.
- **Suggested fix:** Centralise bridge access in one helper that always returns a settled promise (e.g. `callBridge(method, ...args)` returning `{ok, value, error}`), and use it everywhere; make `NeDotify.downloadTrack` return the promise so `createTrackElement` can `await` it and reset the spinner on failure.
- **Fix side effects:** A shared helper changes the shape of every call site (large diff across modules owned by other areas — WN-29/WN-30/WN-32). A minimal, local fix is to add `.catch()` to the four call sites named above and to make `NeDotify.downloadTrack` return its promise.
- **Discovered by:** A

---

#### F-WN-28-6  [P3] — `debug.js` replaces `console.error` with a function that throws on circular objects, masking the errors it is meant to display

- **File:** `ui/web_new_v2/js/debug.js:22-39` (loaded only via `?debug=1`, `ui/web_new_v2/js/main.js:436-442`)
- **Confirmed:** yes
- **Description:** The debug console's `log()` helper serialises every object argument with `JSON.stringify(arg)` and does not guard it. `JSON.stringify` throws `TypeError: Converting circular structure to JSON` for cyclic objects and for DOM nodes (a DOM element has a circular `parentNode`/`children` chain). Because the override calls `log('error', arguments)` **after** the original `console.error`, the throw happens inside `console.error` itself and propagates into the caller.
- **Cause:** Unguarded serialisation in a console interceptor.
- **Trigger conditions:** The app is opened with `?debug=1` **and** any code logs an object with a circular reference (a DOM element, a pywebview return-value object, a track object with a parent pointer).
- **User impact:** In a debug session the diagnostic tool breaks the application: the original error message is swallowed and the code path that logged it aborts, so the very error the developer is chasing becomes invisible.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/debug.js:22-31
  function log(type, args) {
      const msg = Array.from(args).map(arg => typeof arg === 'object' ? JSON.stringify(arg) : arg).join(' ');
      ...
  }
  // ui/web_new_v2/js/debug.js:37-39
  console.log = function() { _log.apply(console, arguments); log('log', arguments); };
  console.error = function() { _error.apply(console, arguments); log('error', arguments); };
  console.warn = function() { _warn.apply(console, arguments); log('warn', arguments); };
  ```
  ```js
  // ui/web_new_v2/js/main.js:436-442
  if (new URLSearchParams(location.search).has('debug')) {
      const dbgScript = document.createElement('script');
      dbgScript.src = 'js/debug.js';
      document.head.appendChild(dbgScript);
  }
  ```
- **Reproduction / verification:**
  1. Open the app with `?debug=1`.
  2. In the console run `console.error({a: document.body})` → the call throws `TypeError: Converting circular structure to JSON` (the DOM element is cyclic); the debug panel shows the error line only if the throw happens after `_error.apply`.
  3. Static confirmation: `grep -n "JSON.stringify(arg)" ui/web_new_v2/js/debug.js`.
- **Suggested fix:** Wrap the serialisation in `try/catch` (fall back to `String(arg)` or `[object Object]`) and truncate the resulting line; also cap the number of retained lines so the panel does not grow without bound.
- **Fix side effects:** None; the debug panel is opt-in via a query flag and is not loaded in the normal UI.
- **Discovered by:** A

---

#### F-WN-28-7  [P3] — Inline `onerror` handlers emitted by `utils.js` are blocked by the page CSP (and one of them is not even valid JS), so the context-menu cover never falls back

- **File:** `ui/web_new_v2/js/utils.js:721, 1128` (CSP at `ui/web_new_v2/index.html:10`)
- **Confirmed:** yes
- **Description:** `createTrackElement()` and `showTrackContextMenu()` emit `onerror="…"` attributes into generated HTML. The document's CSP is `script-src 'self'` with no `'unsafe-inline'`, so inline event handlers are blocked by Chromium and never run. The codebase is aware of this — `utils.js:546-548` explicitly documents that inline `onload`/`onerror` attributes "silently block" and replaced them with delegated listeners — but the two call sites above were not updated. The `showTrackContextMenu` handler is additionally a JavaScript syntax error: the substituted `DEFAULT_COVER_DATA_URI` contains single quotes (`xmlns='http://www.w3.org/2000/svg'`) inside a single-quoted JS string literal, so the literal terminates early.
- **Cause:** Two generators were written before the strict CSP was introduced and were not migrated to the delegated pattern.
- **Trigger conditions:** Every rendered track row (the `onerror` is simply inert) and every rich context menu whose cover URL 404s.
- **User impact:** The track-row cover is still hidden on error, because the delegated capture-phase handler at `utils.js:533-543` covers it — so the visible impact is limited to the **rich context-menu cover**, which is hidden (`display:none`) instead of showing the built-in note placeholder. A blank square appears in the context-menu header for tracks whose cover cannot be loaded.
- **Evidence:**
  ```html
  <!-- ui/web_new_v2/index.html:10 -->
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; ...">
  ```
  ```js
  // ui/web_new_v2/js/utils.js:721
  ${coverSrc ? `<img src="${escapeHtml(coverSrc)}" alt="" onerror="this.onerror=null;this.style.display='none';" loading="lazy">` : ''}
  // ui/web_new_v2/js/utils.js:1128
  <img class="rich-menu-cover" src="${escapeHtml(coverUrl || DEFAULT_COVER_DATA_URI)}" onerror="this.onerror=null;this.src='${DEFAULT_COVER_DATA_URI}';">
  // ui/web_new_v2/js/utils.js:27
  export const DEFAULT_COVER_DATA_URI = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' ...";
  ```
  ```js
  // ui/web_new_v2/js/utils.js:533-543  (the delegated handler that actually runs)
  document.addEventListener('error', (e) => {
      const target = e.target;
      if (!target || target.tagName !== 'IMG') return;
      if (!target.dataset.coverUrl) { target.style.display = 'none'; return; }
      handleImageError(target, target.dataset.coverUrl, ...);
  }, true);
  ```
- **Reproduction / verification:**
  1. Devtools console: `document.querySelector('.rich-menu-cover')?.getAttribute('onerror')` → the attribute string is present.
  2. Devtools console: `document.querySelector('.rich-menu-cover').onerror` → `null` (the CSP blocked the compilation of the inline handler), and the CSP violation appears in the console as "Refused to execute inline event handler".
  3. Static confirmation: `grep -n "script-src" ui/web_new_v2/index.html` (no `unsafe-inline`) vs `grep -n "onerror=" ui/web_new_v2/js/utils.js`.
- **Suggested fix:** Delete both inline attributes and route the context-menu cover through the same delegated capture-phase handler (adding a `data-fallback-src` attribute for the default cover, and honouring it in `utils.js:533-543`).
- **Fix side effects:** The delegated handler currently *hides* images without `data-cover-url`; adding a fallback attribute changes that behaviour for every other `<img>` without a cover URL (e.g. `lib-collage-cell` images) — those would start showing the default cover instead of disappearing. That change should be opt-in per element.
- **Discovered by:** A

---

#### F-WN-28-8  [P3] — `main.js` touches `sessionStorage` at module top level without a guard; a throw aborts the module body and the 45-second bridge-error overlay is never scheduled

- **File:** `ui/web_new_v2/js/main.js:374-388`
- **Confirmed:** yes (the code path); the trigger (`sessionStorage` throwing) is environment-dependent
- **Description:** The "bridge-dead last resort" block reads and writes `sessionStorage` at module top level, outside any `try/catch`. `localStorage` accesses elsewhere in the same file are guarded (`main.js:210` wraps the whole `restorePreferences` IIFE in `try/catch`; `pages.js:48-50, 67-69` guard their accesses), so the unguarded `sessionStorage` access is inconsistent with the file's own convention. `Storage` access throws `SecurityError` when the document is denied storage access (privacy settings, a `file://` origin with storage disabled, a corrupted profile).
- **Cause:** Inconsistent guarding of a Web Storage access that can throw.
- **Trigger conditions:** Web Storage access denied for the WebView2 profile.
- **User impact:** The exception aborts the rest of `main.js`'s module body, so the `setTimeout(…, 45000)` that shows the "bridge not initialised" overlay is **never registered**: the user is left staring at the splash screen forever with no error message and no reload button, instead of the intended recovery dialog. (The `init()` trigger itself is registered earlier at `main.js:360-372`, so the app still comes alive if the bridge appears.)
- **Evidence:**
  ```js
  // ui/web_new_v2/js/main.js:374-388
  if (!isBridgeReady()) {
      const strikes = parseInt(sessionStorage.getItem('nedotify_bridge_strikes') || '0', 10) + 1;   // <- unguarded
      sessionStorage.setItem('nedotify_bridge_strikes', String(strikes));
  }
  setTimeout(() => {
      if (isBridgeReady()) return;
      const strikes = parseInt(sessionStorage.getItem('nedotify_bridge_strikes') || '0', 10);          // <- unguarded
      if (strikes >= 3) {
          sessionStorage.removeItem('nedotify_bridge_strikes');
          showBridgeError();
      }
  }, 45000);
  ```
  ```js
  // ui/web_new_v2/js/pages.js:48-50  (the convention used elsewhere)
  try { localStorage.setItem(SIDEBAR_COLLAPSED_KEY, JSON.stringify(next)); }
  catch (e) { /* private mode / quota - the rail still works for this session */ }
  ```
- **Reproduction / verification:**
  1. Devtools console: `Object.defineProperty(window, 'sessionStorage', { get() { throw new DOMException('denied','SecurityError'); } })` before the module runs (e.g. via a devtools "local override" on `index.html`).
  2. Reload → the module body throws at the `sessionStorage.getItem` line; the console shows the uncaught `SecurityError` and the bridge-error overlay never appears.
  3. Static confirmation: `grep -n "sessionStorage" ui/web_new_v2/js/main.js` → 3 unguarded uses.
- **Suggested fix:** Wrap the strike counter in `try/catch` (degrade to "no strike tracking") and schedule the 45 s overlay *before* touching storage.
- **Fix side effects:** None — the strike counter is a best-effort heuristic for the backend watchdog's silent reloads.
- **Discovered by:** A

---

#### F-WN-28-9  [P3] — `showPage('settings')` leaves the previous base view `.active`, so `events.js::isPageVisible()` still reports it visible and re-renders the hidden page behind the settings overlay

- **File:** `ui/web_new_v2/js/pages.js:114-141` (also `ui/web_new_v2/js/events.js:12-19, 211-231`)
- **Confirmed:** yes
- **Description:** `showPage()` has two branches. The non-settings branch loops over every `.view-page` and toggles `.active` so exactly one base view is active. The settings branch returns **before** that loop: it only adds `.active` to `#view-settings` and leaves the previous base view (e.g. `#view-home`) with `.active` as well. `events.js::isPageVisible()` decides whether to re-render a page purely from the `.active` class, so while the settings overlay is open the app still believes the home/library page is visible and re-renders it on every `library_updated` / `favorites_updated` / `playlists_updated` burst.
- **Cause:** The "current page" state is derived from a CSS class that the settings branch does not maintain; the CSS papers over the visual overlap with `visibility: hidden` but the JS state model still sees two active views.
- **Trigger conditions:** Any library/favourite/playlist mutation while the settings overlay is open (e.g. the auto-download-favourites toggle, or a download completing in the background).
- **User impact:** The hidden page behind the overlay is re-fetched and re-rendered (a full `get_feed`/`get_library` round-trip plus a DOM rebuild) for a page the user cannot see. No visible corruption, but wasted work on every mutation and a second source of truth that does not match what is on screen.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/pages.js:114-153
  export function showPage(pageId) {
      if (pageId === 'settings') {
          ...
          settingsView.classList.add('active');     // <- base view is NOT deactivated
          ...
          return;                                     // <- returns before the base-view loop
      }
      closeSettings();
      currentBasePage = pageId;
      document.querySelectorAll('.view-page').forEach(p => {
          if (p.id !== 'view-settings') {
              p.classList.toggle('active', p.id === 'view-' + pageId);
          }
      });
  ```
  ```js
  // ui/web_new_v2/js/events.js:16-19
  function isPageVisible(pageId) {
      const el = document.getElementById('view-' + pageId);
      return !!(el && el.classList.contains('active'));   // <- true for the base page while Settings is open
  }
  ```
  ```css
  /* ui/web_new_v2/css/components/settings-refresh.css:2 */
  #main-content:has(#view-settings.active) .view-page:not(#view-settings) { visibility: hidden; }
  ```
- **Reproduction / verification:**
  1. Open the app, go to Home, then open Settings (the Home view keeps `class="active"` — check in the Elements panel).
  2. Trigger a `library_updated` (e.g. complete a download in the background) and watch the Network/devtools log for a `get_feed`/`loadHome` call while the settings overlay is open.
- **Suggested fix:** Make `isPageVisible()` consult a single source of truth (e.g. the `currentBasePage`/`nedotify:page_changed` state) instead of the CSS class, or deactivate the base view in the settings branch.
- **Fix side effects:** `nedotify:page_changed` is not dispatched for the settings branch (`pages.js:175` is only reached in the non-settings branch), so subscribers currently keep the last base page — changing the semantics of that event affects WN-29/WN-30/WN-32 subscribers.
- **Discovered by:** A

---

#### F-WN-28-10  [P3] — `showTrackContextMenu` leaks `document` click/keydown listeners when a second menu replaces an open one, and the 50 ms deferred attach lets the first click through

- **File:** `ui/web_new_v2/js/utils.js:1105-1114, 1372-1397`
- **Confirmed:** yes (currently masked — see "Trigger conditions")
- **Description:** `showTrackContextMenu()` registers `onDocumentClick` and `onKeyDown` on `document` from a `setTimeout(…, 50)`. When a second menu is opened while the first is still open, the old menu element is removed (`activeRichMenu.remove()`) **without** removing its document listeners; the new menu installs a second pair. Every such replacement therefore leaks one click listener and one keydown listener for the lifetime of the page. In addition, the 50 ms delay means a click in that window is not caught by `onDocumentClick`, so the menu does not close.
- **Cause:** The listener teardown lives in `closeMenu()`, which is only reachable from the menu's own click handler, the Escape handler, or `closeAllFloatingMenus()`. The "replace an open menu" path bypasses all three.
- **Trigger conditions:** Two context menus opened in quick succession. Today this is masked because the floating-menu guard that would call `closeAllFloatingMenus()` never arms (F-WN-28-3) — **fixing F-WN-28-3 without also fixing this finding makes the leak live.**
- **User impact:** A slow leak of document listeners (one pair per rapid menu replacement) and a 50 ms window in which the menu ignores outside clicks. Once the guard is fixed, the stale `onDocumentClick` also closes the *new* menu on the first outside click (because it reads the module-level `activeRichMenu`), which is a visible mis-dismiss.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/utils.js:1111-1114  (replacing an open menu - no teardown)
  if (activeRichMenu) {
      activeRichMenu.remove();
      activeRichMenu = null;
  }
  // ui/web_new_v2/js/utils.js:1372-1379  (teardown only here)
  function closeMenu() {
      if (activeRichMenu) { activeRichMenu.remove(); activeRichMenu = null; }
      document.removeEventListener('click', onDocumentClick);
      document.removeEventListener('keydown', onKeyDown);
  }
  // ui/web_new_v2/js/utils.js:1393-1396  (deferred attach)
  setTimeout(() => {
      document.addEventListener('click', onDocumentClick);
      document.addEventListener('keydown', onKeyDown);
  }, 50);
  ```
- **Reproduction / verification:**
  1. Static: `grep -n "activeRichMenu" ui/web_new_v2/js/utils.js` → the removal path at 1111-1114 has no `removeEventListener`.
  2. Runtime: open a track context menu, then open another one from a different track without closing the first; count `document` click listeners in the devtools "Event Listeners" panel — the number of `onDocumentClick` entries grows by one per replacement.
- **Suggested fix:** Keep a single module-level pair of document handlers (registered once, lazily) instead of one pair per menu, and register them synchronously rather than after a 50 ms timeout.
- **Fix side effects:** The 50 ms delay exists so that the click that opened the menu does not immediately close it. A synchronous registration needs an explicit "ignore the opening click" flag instead of a timer.
- **Discovered by:** A

---

### 2.1 Event-name diff — Python `_emit` / `emit_event` → `events.js` handler

Producers scanned: `core/api.py`, `core/downloader.py`, `core/proxy.py`, `services/watchdog_service.py`, `main.py`.
Consumers scanned: `ui/web_new_v2/js/events.js` (core switch) **and** `ui/web_new_v2/js/main.js` (subscriber path, live for every event because the subscriber loop in `dispatchPythonEvent` runs unconditionally).

**Python → JS: 51 emitted names, 51 handled, 0 missing.**

| Python event (producer:line) | JS handler (events.js:line) | Verdict |
|---|---|---|
| `album_details_ready` (api.py:490, 2263) | `case 'album_details_ready'` (348) | ✅ |
| `api_error` (api.py:434) | `case 'api_error'` (335) | ✅ payload `{method,error,code,title,message,action}` read correctly |
| `artist_candidates_ready` (api.py:3507) | `case 'artist_candidates_ready'` (352) | ✅ |
| `artist_profile_error` (api.py:475, 3490) | `case 'artist_profile_error'` (361) | ✅ |
| `artist_profile_ready` (api.py:3502) | `case 'artist_profile_ready'` (356) | ✅ |
| `artists_avatars_ready` (api.py:3528) | `case 'artists_avatars_ready'` (187) | ✅ |
| `artists_ready` (api.py:3762) | `case 'artists_ready'` (179) | ✅ |
| `audio_error` (api.py:1259) | `case 'audio_error'` (378) | ✅ |
| `authentic_home_ready` (api.py:3370, 3375, 3382, 3385) | `case 'authentic_home_ready'` (139) | ✅ |
| `batch_download_cancelled` (downloader.py:283) | `case 'batch_download_cancelled'` (254) | ✅ |
| `batch_download_finished` (downloader.py:211, 235) | `case 'batch_download_finished'` (250) | ✅ |
| `batch_download_progress` (downloader.py:228) | `case 'batch_download_progress'` (246) | ✅ |
| `batch_download_started` (api.py:3715) | `case 'batch_download_started'` (242) | ✅ |
| `download_complete` (downloader.py:839) | `case 'download_complete'` (258) | ⚠️ payload `{track_id}` only — id-domain mismatch → **F-WN-28-2** |
| `download_failed` (api.py:2331, 2340, 2351; downloader.py:858, 879) | `case 'download_failed'` (266) | ⚠️ payload OK, but global spinner sweep → **F-WN-28-4** |
| `download_progress` (downloader.py:169) | `case 'download_progress'` (79) | ✅ (intentional no-op) |
| `download_queue_updated` (downloader.py:112,127,137,284,382,409,787,838,860,881) | `case 'download_queue_updated'` (78) | ✅ (intentional no-op) |
| `error` (api.py:1260) | `case 'error'` (323) | ✅ |
| `favorites_updated` (api.py:2627, 2724) | `case 'favorites_updated'` (212) | ✅ (debounced 300 ms) |
| `feed_ready` (api.py:3746, 3747, 3751) | `case 'feed_ready'` (171) | ✅ |
| `library_updated` (api.py:3264,3454,3898,3904,3993; downloader.py:835; watchdog_service.py:129) | `case 'library_updated'` (211) | ✅ (debounced 300 ms) |
| `lyrics_ready` (api.py:3207) | `case 'lyrics_ready'` (344) | ✅ |
| `mixes_ready` (api.py:3788, 3789, 3793) | `case 'mixes_ready'` (199) | ✅ |
| `mute_changed` (api.py:1990) | `case 'mute_changed'` (392) | ✅ |
| `offline_mode_changed` (api.py:4160) | `case 'offline_mode_changed'` (77) | ✅ (intentional no-op) |
| `operation_error` (api.py:510) | `case 'operation_error'` (86) | ✅ |
| `playlist_changed` (api.py:2529) | `case 'playlist_changed'` (214) | ✅ (debounced 300 ms) |
| `playlists_updated` (api.py:2398, 2501, 2508, 3433) | `case 'playlists_updated'` (213) | ✅ (debounced 300 ms) |
| `popular_results` (api.py:3327, 3330, 3334) | `case 'popular_results'` (163) | ✅ |
| `position_changed` (api.py:1423) | `case 'position_changed'` (110) | ✅ payload `{pos,duration,position_ms,duration_ms}` read correctly |
| `proxy_status` (proxy.py:1020, 1108, 1118) | `case 'proxy_status'` (432) → `logFutureEvent`; **real handler** in `main.js:572-586` via `addPythonEventHandler` | ✅ (works through the subscriber path) |
| `queue_ended` (api.py:1253) | `case 'queue_ended'` (396) | ✅ |
| `queue_updated` (api.py:1433, 1639, 1785, 1791, 1801, 1813, 1832, 1847) | `case 'queue_updated'` (283) | ✅ payload `{tracks,current_index,…}` matches `queue.js:63-68` |
| `releases_ready` (api.py:3774, 3775, 3779) | `case 'releases_ready'` (191) | ✅ |
| `repeat_changed` (api.py:2013) | `case 'repeat_changed'` (297) | ✅ |
| `search_completed` (api.py:2129, 2134) | `case 'search_completed'` (134) | ✅ |
| `search_results` (api.py:2111) | `case 'search_results'` (130) | ✅ |
| `session_autoplay` (main.py:397) | `case 'session_autoplay'` (418) | ⚠️ **dropped at startup** → **F-WN-28-1** |
| `setting_changed` (api.py:1887, 1896, 2952) | `case 'setting_changed'` (313) | ✅ (intentional no-op) |
| `shuffle_changed` (api.py:2007) | `case 'shuffle_changed'` (288) | ✅ |
| `smart_playlists_updated` (api.py:4201, 4206, 4211) | `case 'smart_playlists_updated'` (82) | ✅ |
| `state_changed` (api.py:1373) | `case 'state_changed'` (103) | ✅ payload `{state,elapsed_ms}` read correctly |
| `storage_info` (api.py:3038, 3092, 3102) | `case 'storage_info'` (317) | ✅ |
| `storage_updated` (api.py:4091, 4103) | `case 'storage_updated'` (319) | ✅ |
| `theme_changed` (api.py:2753) | `case 'theme_changed'` (388) | ✅ |
| `track_changed` (api.py:1240) | `case 'track_changed'` (97) | ⚠️ **dropped at startup** → **F-WN-28-1** |
| `track_updated` (api.py:3994) | `case 'track_updated'` (405) | ✅ |
| `track_wave_ready` (api.py:496, 3567) | `case 'track_wave_ready'` (366) | ✅ |
| `window_visibility` (api.py:600, 603) | `case 'window_visibility'` (89) | ✅ |
| `yandex_device_auth_code` (api.py:1912) | `case 'yandex_device_auth_code'` (370) | ✅ |
| `yandex_device_auth_result` (api.py:505, 1921, 1934, 1939, 1945) | `case 'yandex_device_auth_result'` (374) | ✅ |

**JS → Python: 9 JS cases the backend never emits (dead branches, no missing functionality).**

| JS case (events.js:line) | Note |
|---|---|
| `yt_playlist_ready` (145) | no producer |
| `authentic_home_error` (155) | no producer (the error path is `artist_profile_error`) |
| `recommendations_ready` (172) | no producer — recommendations arrive as `feed_ready` |
| `mood_playlists_ready` (207) | no producer |
| `mini_player_toggled` (233) | **no producer** — `core/api.py:773 toggle_mini_player()` does not emit it; the `mini-player-active` body class is only set by `main.js::toggleMiniPlayerMode` |
| `track_downloaded` (259) | alias of `download_complete` (same case label) |
| `storage_info_updated` (318) | alias of `storage_info` / `storage_updated` |
| `smart_home_ready` (433) | explicitly deprecated (`logFutureEvent`) |
| `yandex_auth_error` (434) | explicitly deprecated (`logFutureEvent`) |
| *(subscriber only)* `network_status` (main.js:558) | no producer — handled in `_handleNetworkEvent` only |

**Observation for Role B (not a correctness defect):** `download_complete` is **not** debounced, unlike the `library_updated` / `favorites_updated` / `playlists_updated` burst (events.js:215-231, 300 ms). Each completed download therefore triggers `loadDownloaded()` + `loadPlaylists()` (a `get_playlists()` bridge round-trip) + `refreshActiveLibraryView()` immediately, so a 50-track batch download produces 50 back-to-back playlist fetches and library re-renders.

---

### 3. Clean areas

- **Script load order (`index.html`)** — every `<script>` target exists on disk (verified with `Test-Path`): `js/appearance-assets.js`, `js/ui-style.js`, `js/lucide.min.js`, `js/hls.min.js`, `js/boot.js`, `js/main.js`. No duplicate script tags, no 404 candidates, no inline `<script>` block anywhere in the document (the CSP `script-src 'self'` is therefore satisfiable). Order is correct: the two head classic scripts (`appearance-assets.js`, `ui-style.js`) publish `window.NeDotifyAssets` / `window.NeDotifyAppearance` before `main.js`'s module body uses them; `lucide.min.js` is parser-blocking so `window.lucide` exists for `boot.js`'s `DOMContentLoaded` handler; `hls.min.js` is `defer` and therefore executes in the deferred list ahead of the `type="module"` entry, so `window.Hls` exists before `player.js` runs (and `player.js:123` guards it anyway); `boot.js` (classic, parser-blocking, line 2307) runs before the deferred module graph, so the toast bridge is armed before any module can dispatch `nedotify:toast`; `main.js` (module, line 2308) is deferred and therefore runs after the whole document is parsed, so `#profile-edit-dialog` (line 2309) exists when `initProfile()` binds its form.
- **Event-name diff** — **every** event name emitted by the Python side has a matching `case` in `events.js` (51 Python names, 60 JS cases, zero missing). The full table is in §2 below. No renamed/lost event. The reverse direction has nine JS cases that the backend never emits (`yt_playlist_ready`, `authentic_home_error`, `recommendations_ready`, `mood_playlists_ready`, `mini_player_toggled`, `track_downloaded`, `storage_info_updated`, plus the two explicitly-deprecated `smart_home_ready` / `yandex_auth_error`); all are harmless dead branches, but `mini_player_toggled` (events.js:233) is worth a note — `core/api.py:773 toggle_mini_player()` does **not** emit it, so the `mini-player-active` body class is only ever set by `main.js::toggleMiniPlayerMode`'s optimistic swap.
- **Payload shapes** — the payloads that matter all line up:
  - `download_complete` → `{"track_id": <int>}` (downloader.py:839); the JS reads only `track_id` ✓ — the defect is the id *domain*, not the shape (F-WN-28-2).
  - `download_failed` → `{"track_id", "error", "code", "title", "message", "action", "method"}` (downloader.py:174-175 adds `describe_error(...)`); the JS reads `data.error || data.message` and `data.title` — all present ✓.
  - `api_error` → `{"method", "error", "code", "title", "message", "action"}` (api.py:434-438); the JS reads `data.method`, `data.error`, `data.title` ✓.
  - `state_changed` → `{"state", "elapsed_ms"}` (api.py:1373); the JS normalises `data.state` ✓.
  - `position_changed` → `{"pos", "duration", "position_ms", "duration_ms"}` (api.py:1423-1428); the JS reads exactly those four ✓.
  - `queue_updated` → `get_queue()` = `{tracks, current_index, current_track, shuffle, repeat}` (api.py:1772-1780); `queue.js:63-68` reads `q.tracks` / `q.current_index` ✓.
  - `track_changed` → the whole track dict ✓; `track_updated` → the track dict, matched against `cur.id ?? cur.source_id` ✓.
- **`utils.js` shared helpers** — `escapeHtml` exists and is applied consistently to every interpolated value in the generated HTML (`createTrackElement`, `formatArtistNames`, `coverImgHtml`, `artistAvatarHtml`, `renderPlaylistCoverCollage`, `showTrackContextMenu`); `safeCssImageUrl` correctly refuses anything that is not `https:`/`data:` and strips the CSS metacharacters `)'"\\;` before the value is interpolated into `url('…')`, which is the correct way to escape for the CSS grammar. The modal focus trap (`openModalFocusTrap` / `closeModalFocusTrap` / `isFocusInsideModalTrap`) is a well-behaved, idempotent, self-healing implementation with a `Map`-based registry — no listener leak, correct return-focus handling, and a capture-phase `keydown` listener that a modal cannot starve. `formatTime`, `formatListeningTime`, `formatListeningTimeShort` all return `'0:00'` / `'0 ч'` / `'0 мин'` for `0`, `null`, `undefined` and `NaN`. `checkLocalStorageQuota` and every `localStorage` read in `utils.js`/`pages.js` are wrapped in `try/catch`, so a quota error or private-mode `SecurityError` degrades instead of throwing. The delegated capture-phase `error`/`load` listeners at `utils.js:533-569` are the correct CSP-safe replacement for inline `onerror`/`onload` (the two stragglers are F-WN-28-7).
- **`contextmenu.js`** — correct: it only calls `preventDefault()` when the target is a track row or a playlist card, so the native context menu (copy/paste) is preserved on every text input, search field and settings field. It resolves the track from `_trackData` first and falls back to parsing `dataset.track`; the playlist branch has a sensible `dataset` fallback. `initContextMenu()` is called exactly once (`main.js:430`) and is wrapped in `try/catch`.
- **`efficiency.js`** — `initBlurObserver()` and `initEfficiency()` are both idempotent (`blurObserverInitialized` / `efficiencyInitialized` guards), so re-entry does not stack observers or listeners. The `IntersectionObserver` correctly unobserves removed nodes (`releaseElement`) and skips elements that are not connected. `initBlurObserver()` correctly refuses to arm when `perf-low` is set — and `main.js`'s `restorePreferences()` IIFE (which adds `perf-low`) runs at module-evaluation time, i.e. before `init()` calls `initBlurObserver()`, so the ordering is right. `evaluateEfficiencyState()` handles `undefined` settings and falls back to `localStorage` for every key, and `limit_state === 'off'` is honoured (the `|| 'minimize'` fallback only applies to a falsy value, and `'off'` is truthy).
- **`pages.js`** — the "current page" state is singular for the base views (`showPage` toggles `.active` over all `.view-page` except `#view-settings`), `currentBasePage` is remembered so that closing the settings overlay restores the previous nav item and title, the settings panels are switched by id and their `display` is kept in sync, `Escape` closes the settings overlay, and the sidebar collapse state is persisted to `localStorage` behind a `try/catch` and restored before the first paint. Keyboard parity is provided for the `role="button"` logo. There is no hash/URL routing in this app at all, so there is no URL state to keep in sync (a deliberate simplification, not a defect).
- **`index.html` structure** — 524 `id` attributes, **zero duplicates**; all three `<form>` elements (`macos-search-form`, `home-search-form`, `profile-edit-form`) have submit handlers that call `preventDefault()` (so the CSP `form-action 'none'` is never violated); no `<a href="#">`; no `onclick=`/`onchange=`/`onsubmit=` inline attributes; the only `<img>` without an `alt` is the decorative title-bar logo (`index.html:84`), and the only `<button>` without an accessible name is `#operation-error [data-error-action]`, whose label is filled in at runtime by `feature-controls.js:82`. The CSP itself is coherent: `script-src 'self'` (no inline script), `style-src 'self' 'unsafe-inline'` (the UI uses inline `style` attributes throughout), `form-action 'none'`, `object-src 'none'`, `base-uri 'none'`.
- **`boot.js`** — the CSP-safe replacement for the old inline bootstrap: it publishes the lazy Google-Fonts loader only on demand (so a cold start and an offline install issue no remote request), and it arms the global `nedotify:toast` bridge early (before any module can dispatch one). The `__nedotifyToastBridgeArmed` flag makes the bridge idempotent between `boot.js` and `utils.js:166` — exactly one of the two implementations wins, and the two implementations are behaviourally equivalent (same class name, same 4-toast cap, same 4 s auto-remove).
- **Existing static test suite** — `pytest tests/test_frontend_js.py -q` → 41 passed. It pins the `window.onPythonEvent` registry design (`tests/test_frontend_js.py:120-221`), the `api_error` handler, the block-scoped case bodies, and a `node --check` ES-module parse of the seven reviewed files. None of the findings above are covered by it.

### 4. Coverage gaps

- **No runtime harness.** The repository has no JS test runner and no WebView2 integration test; every finding above was established by reading the real source and by tracing pywebview 5.4's own source in `.venv_win/Lib/site-packages/webview/`. The F-WN-28-1 timing argument depends on `ExecuteScriptAsync` queuing semantics and on `Event.set()` spawning a thread (both confirmed in the installed package source) but was **not** observed in a live run, because the ground rules forbid launching the real app (it would disturb the user's `~/.nedotify/` profile). Confirming it needs a single instrumented run: log `performance.now()` at `events.js:69`, at `initEvents()` and inside `dispatchPythonEvent`, then restart the app with a saved session and check the ordering.
- **Other areas' modules were read but not audited.** `player.js`, `queue.js`, `library.js`, `settings.js`, `search.js`, `home.js`, `lyrics.js`, `ui-style.js`, `home-shell.js`, `profile-comparison.js` were read only where WN-28 code calls into them. Defects inside them (e.g. `library.js::loadPlaylists()`'s `try` block, `queue.js`'s drawer logic, `player.js`'s `onTrackChanged`) belong to WN-29/WN-30/WN-31/WN-32 and were deliberately not reported here.
- **The `download_complete` payload contract** was checked only against the producers in `core/downloader.py` and `core/api.py`. If a third producer exists outside the repo's Python tree (plugins under `plugins/`), its payload was not verified.
- **`utils.js` line 1586-1690 (multi-select engine)** was read but not exhaustively modelled: the Shift-range selection indexes `tracksArray` and the DOM sibling list with the same index, which assumes the rendered list and the array are 1:1 and in the same order. I could not confirm a scenario where that assumption breaks (it holds for the current `createTrackElement` call sites) and therefore did not report it.
- **CSS-layer behaviour** (blur observer effectiveness, `visibility: hidden` cost, the `perf-low` thresholds) was checked only where it changes a JS state decision; the CSS itself is WN-33's scope.
- **`ui/MACos_ui/`** was not opened (out of scope for WN-28, and it is only a legacy CSS pack referenced from `index.html:47-50`).
- **`core/proxy.py`'s `proxy_status` payload** was verified only for the fact that it is emitted and that `main.js:572-586` consumes it through the *subscriber* path (which is live for every event, independent of `coreEventHandler`); the proxy's own retry semantics are WN-11's scope.
