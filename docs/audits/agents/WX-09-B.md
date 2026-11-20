## WX-09 — Offline mode across playback, library, proxy, downloads — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (whole) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (whole) |
| `core/offline.py` | 1–77 (whole) |
| `core/settings.py` | 1–589 (whole) |
| `core/api.py` | 23, 392–444, 446–560, 1105–1164, 1180–1259, 1420–1539, 1540–1659, 1608–1660, 2078–2207, 2255–2334, 2530–2619, 2720–2759, 2915–2984, 3192–3341, 3537–3636, 3620–3679, 3740–3799, 4120–4228 |
| `core/proxy.py` | 21, 28–47, 660–779, 780–879, 863–1042, 1040–1154, 1150–1279, 1295–1334 |
| `core/resolver.py` | 1–271 (whole) |
| `core/app.py` | 140–209, 230–349, 380–429 |
| `core/downloader.py` | 60–219, 255–314, 333–419, 700–789 |
| `core/playback_recovery.py` | 1–183 (whole) |
| `core/user_errors.py` | 1–24 (whole) |
| `core/services/discord_rpc.py` | 1–183 (whole) |
| `audio/engine.py` | 75–124, 195–254 |
| `services/lyrics_lookup.py` | 55–184, 295–344 |
| `services/lyrics_service.py` | 225–284 |
| `services/soundcloud_service.py` | 1010–1055 |
| `services/smart_playlists.py` | 135–177 |
| `services/itunes_gateway.py` | 40–93 |
| `core/database.py` | 305–334, 1184–1243, 2149–2188 |
| `ui/web_new_v2/js/feature-controls.js` | 1–135 (whole) |
| `ui/web_new_v2/js/utils.js` | 505–564, 600–659 |
| `ui/web_new_v2/js/player.js` | 1722–1751, 2241–2291 |
| `ui/web_new_v2/js/main.js` | 390–434, 434–478 |
| `ui/web_new_v2/js/search.js` | 255–284 |
| `ui/web_new_v2/js/settings.js` | 920–979 |
| `ui/web_new_v2/index.html` | 450–479 (grep over the whole file for `offline`) |
| `tests/test_offline_mode.py` | 1–110 (whole) |
| `tests/test_offline_proxy.py` | 1–27 (whole) |
| `tests/test_offline_resolve_callbacks.py` | 1–117 (whole) |
| `tests/test_feature_controls_ui.py` | 1–86 (whole) |
| `tests/test_proxy_harness.py` | 1–215 (whole) |
| `tests/conftest.py` | 1–129 |

**Callees traced into other areas**
- `core/api.py::_offline_bridge_result` → `core/offline.py::available_tracks/offline_library` → `core/database.py::get_all_tracks/get_cached_stream` (WN-12).
- `core/api.py::play_track` → `audio/engine.py::resolve_stream_url` → `core/resolver.py::StreamResolver.resolve` → provider services (WN-15, WN-17, WN-19…21).
- `core/proxy.py::do_GET` → `core/proxy.py::_safe_urlopen`, `audio/engine.py::resolve_stream_url`, `core/app.py::re_resolve_stream_url_async` (WN-11, WN-15).
- `core/api.py::get_waveform` → `services/soundcloud_service.py::get_waveform_data_sync` → `requests.Session.get` (WN-21).
- `core/api.py::get_lyrics` → `services/lyrics_service.py` → `services/lyrics_lookup.py` (WN-22).
- `core/api.py::get_settings` → `core/settings.py::SettingsManager.get_category` (WN-14).
- `core/api.py::set_offline_mode` → `core/downloader.py::pause_download`, `audio/queue.py::set_tracks` (WN-13, WN-17).

---

### 2. Findings

#### F-WX-09-1  [P1] — The proxy's `/?url=` branch performs an outbound request while offline mode is ON

- **File:** `core/proxy.py:863-1016` (the `else` branch of `do_GET`), contrast `core/proxy.py:814` (the gate that exists only in the `/api/stream` branch); `core/proxy.py:1195` and `core/proxy.py:1229` (chunk-loop check, runs *after* the request is sent); `core/proxy.py:40` (`KNOWN_PROXY_PATHS`); `audio/engine.py:97` and `core/proxy.py:1316` (producers of the `/?url=` form).
- **Confirmed:** yes — reproduced at runtime (script below).
- **Description:** `do_GET` has two branches. The `/api/stream` branch checks the offline policy at `core/proxy.py:814` **before** resolving or connecting. The `/` (`?url=…`) branch has **no** offline check at all: it goes straight to `engine.resolve_stream_url()` (`core/proxy.py:899`, `:925`) and then to `resp = _safe_urlopen(req, timeout=12.0, source=source)` at `core/proxy.py:1016`. The only offline checks in that branch are inside the body-copy loop (`core/proxy.py:1195`, `:1229`), i.e. **after** the TCP/TLS connection is open and the HTTP request (plus provider cookies / Yandex OAuth header) has been sent upstream. The response *body* is aborted; the *request* is not.
- **Cause:** the policy is implemented as a per-branch guard rather than at the single point where the proxy leaves the machine. The branch that lacks it is the one the app actually uses: `audio/engine.py:97` and `core/proxy.py:1316` emit `http://127.0.0.1:<port>/?url=…` for every cloud stream whose host is not `youtube.com` / `youtu.be` / `soundcloud.com` — which includes googlevideo CDN URLs, SoundCloud CDN URLs and Yandex CDN URLs, i.e. the normal production path.
- **Trigger conditions:** offline mode is ON and the browser issues a request for `/?url=<remote>` against the loopback proxy. This happens (a) when the user flips offline mode on while a cloud track is playing — the `<audio>` element keeps its `/?url=…` src, and `feature-controls.js:99-103` does not reload or stop it unless `active_available === false`; (b) on any subsequent seek/rebuffer of that track.
- **User impact:** the user's IP address and request path are disclosed to the provider CDN despite an explicit "no network" instruction, and provider credentials (yt-dlp cookies for `youtube`/`soundcloud`, `Authorization: OAuth <yandex_token>` for `yandex`, `core/proxy.py:990-1006`) are attached to the outbound request. The audio body itself is cut off, so playback silently stalls instead of failing loudly.
- **Evidence:**
  ```python
  # core/proxy.py:814  — the ONLY offline gate, inside the /api/stream branch
              if is_offline(getattr(self.server.app_core, 'settings', None)):
                  self._safe_send_error(503, 'Offline mode: track is not saved locally')
                  return None
  # core/proxy.py:863  — the '?' branch starts here; no gate follows
          else:
              target_url = query_params.get('url', [None])[0]
  ...
  # core/proxy.py:1016 — unconditional outbound request
                  resp = _safe_urlopen(req, timeout=12.0, source=source)
  # core/proxy.py:1195 — gate, but only inside the body loop (request already sent)
                          if is_offline(getattr(self.server.app_core, 'settings', None)):
                              raise ConnectionAbortedError('Offline mode enabled')
  ```
  ```python
  # audio/engine.py:97 — the URL the frontend actually plays
                              proxy_url = (f"http://127.0.0.1:{self.proxy.port}/?url={quoted_url}&source={src}"
  ```
- **Reproduction / verification:** a hermetic script (kept outside the repo, `%TEMP%\opencode\verify_wx09_proxy.py`) started the real `StreamProxyHandler` with `network.offline_mode = True`, replaced `core.proxy._safe_urlopen` with a recorder and `core.proxy._is_ssrf_safe_url` with `lambda url: True`, then issued two requests:
  ```
  OFFLINE MODE ON: network.offline_mode = True
  A) GET /api/stream?source=youtube&source_id=remote-id
     status=503  outbound_attempts=[]  engine.resolve_stream_url calls=[]
  B) GET /?url=https://cdn.example.com/track.mp3&source=yandex&source_id=yid-1
     status=500  outbound_attempts=['https://cdn.example.com/track.mp3']
  ```
  Branch A is correctly refused with 503 and no outbound attempt; branch B reaches `_safe_urlopen`. (The 500 is the recorder raising; the point is that the request was attempted.)
- **Suggested fix:** add the offline gate at the top of `do_GET` for the `/?url=` branch (before `engine.resolve_stream_url()` and before `_safe_urlopen`), or — better — hoist a single `if is_offline(...): return 503` into a shared helper used by every branch that can leave the machine, and keep the in-loop check only as a mid-transfer abort.
- **Fix side effects:** a stream that was already playing when the switch flipped will start returning 503; the frontend must treat that as "track not available offline" and fall back to the local file, otherwise the player shows a hard error instead of the buffered audio finishing. The proxy cannot know whether the client already had bytes buffered.
- **Discovered by:** B

---

#### F-WX-09-2  [P2] — `get_waveform` is absent from the offline interception list and performs an outbound request while offline

- **File:** `core/api.py:3583-3593` (`get_waveform`), `core/api.py:461-512` (`_offline_bridge_result` — the interception list), `services/soundcloud_service.py:1018-1055` (`get_waveform_data_sync` → `self._session.get(json_url, timeout=10.0)`), `ui/web_new_v2/js/player.js:1734` and `ui/web_new_v2/js/player.js:2274` (the caller).
- **Confirmed:** yes.
- **Description:** `_offline_bridge_result` is a **method-name allowlist whose default is ALLOW**: any bridge method that is not named in the list falls through to `return False, None` (`core/api.py:512`) and its real body executes. `get_waveform` is not in the list and has no internal offline check; it calls `self._core.soundcloud.get_waveform_data_sync(waveform_url)`, which performs an HTTPS GET against the SoundCloud waveform JSON endpoint.
- **Cause:** the policy is enforced by *naming* the methods to block rather than by tagging the methods that reach the network. A new (or forgotten) network-capable bridge method is allowed by default.
- **Trigger conditions:** offline mode is ON and any track carrying a `waveform_url` is played. `player.js:1734` calls `fetchAndRenderWaveform(track)` on **every** track change; `player.js:2274` calls `window.pywebview.api.get_waveform(track)` with no offline guard. `waveform_url` is attached to SoundCloud search results (`services/soundcloud_service.py:338`, `:996`) and is preserved by the offline rewrites: `core/offline.py:29` (`dict(track, file_path=path, offline_available=True)`) and `core/api.py:4147` (queue pruning keeps every other key), so a track found while online still carries the URL after the switch.
- **User impact:** one outbound HTTPS request to the SoundCloud CDN per track change while the user asked for no network; the user's IP and the track's provider identity are disclosed.
- **Evidence:**
  ```python
  # core/api.py:3583
      def get_waveform(self, track_data: dict):
          """Get sound wave peak amplitude points (0.0..1.0) for waveform scrubber."""
          if not track_data or not isinstance(track_data, dict):
              return []
          waveform_url = track_data.get("waveform_url") or ""
          if waveform_url and hasattr(self._core, "soundcloud"):
              try:
                  return self._core.soundcloud.get_waveform_data_sync(waveform_url)
  ```
  ```python
  # core/api.py:502-512 — the allowlist; 'get_waveform' is absent, default = ALLOW
              if method in ('prefetch_track', 'get_lyrics_translation', 'check_zapret_update', 'update_zapret'):
                  return True, None
              ...
              return False, None
  ```
- **Reproduction / verification:** `core/api.py:461` `_offline_bridge_result('get_waveform', (track,), {})` returns `(False, None)` for an offline settings object → the wrapper at `core/api.py:424-427` calls the real method. Grep of the whole bridge surface (`core/api.py`, `def ` list) against the allowlist shows exactly one network-capable method that is neither in the list nor internally gated: `get_waveform`.
- **Suggested fix:** add `'get_waveform'` to the interception list in `_offline_bridge_result` (return `[]`, the same shape the method already returns on failure), and add an `is_offline` guard inside `get_waveform` so the method is safe when called outside the bridge wrapper.
- **Fix side effects:** none visible — `player.js:2277` already falls back to `generatePseudoWaveform(track)` when the returned array is empty, so the scrubber keeps working offline with a synthetic waveform.
- **Discovered by:** B

---

#### F-WX-09-3  [P2] — The UI reads a different source of truth than the backend: `network` is missing from `get_settings()`, so a persisted offline mode is invisible to the UI at startup

- **File:** `core/api.py:2929` (the hard-coded category list of `get_settings`), `core/api.py:4129-4130` (`get_offline_mode` — never called by the UI), `ui/web_new_v2/js/feature-controls.js:112` and `:133`, `ui/web_new_v2/js/main.js:409-418`, `ui/web_new_v2/js/utils.js:526` and `:607-613`, `ui/web_new_v2/js/player.js:1440` and `:1524`.
- **Confirmed:** yes.
- **Description:** the backend exposes the offline flag as `settings['network']['offline_mode']` (`core/settings.py:52-55`). The frontend reads it from `window.settings?.network?.offline_mode`, and `window.settings` is populated exclusively from `AppApi.get_settings()` (`ui/web_new_v2/js/main.js:409`, `onboarding.js:65/183`) or from the localStorage copy of the same payload. `get_settings()` assembles the tree from a **hard-coded category list that does not contain `'network'`**, so `window.settings.network` is `undefined` for the whole session until something calls `applyOfflineState` with an explicit state.
- **Cause:** the settings tree is assembled from a duplicated literal list rather than from `DEFAULT_SETTINGS`, so a category added to the schema (`network`) is silently invisible to the UI. `get_offline_mode()` — the one bridge method that would give the UI the truth — has no caller in `ui/web_new_v2` (verified by grep over every `*.js` and `index.html`).
- **Trigger conditions:** the app is restarted while `network.offline_mode` is persisted as `True` in the database (the flag is persisted by `core/api.py:4135` → `core/settings.py:401-418` → batched SQLite write). Also: the UI never shows an offline toggle at all (`index.html` contains only `offline-mode-note` at line 461 and no `offline-mode-toggle`), so offline mode can only be entered through the bridge API.
- **User impact:**
  1. **Visible defect:** the backend is offline, the UI is not — no `offline-mode` class on `<html>`, the "Офлайн-режим…" note stays hidden (`feature-controls.js:15-17`), and the user has no indication that the app is in offline mode.
  2. **Frontend-side network leak:** `utils.js:607-613 offlineImageUrl()` returns remote URLs unchanged when the flag is falsy, so the WebView loads cover art directly from `img.youtube.com`, `yandex.net` and SoundCloud CDNs while the backend is offline. This traffic never touches the Python layer and bypasses every backend gate.
  3. `player.js:1440` (prefetch) and `player.js:1524` (flow) gates are open at startup; they are only stopped by the backend allowlist (`core/api.py:492`, `:502`), not by the UI's own knowledge of the state.
- **Evidence:**
  ```python
  # core/api.py:2929 — 'network' is not in this list
          categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay', 'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance', 'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services', 'session', 'zapret']
  ```
  ```js
  // ui/web_new_v2/js/feature-controls.js:112 — reads a value that is never delivered
      applyOfflineState({ enabled: window.settings?.network?.offline_mode === true });
  // ui/web_new_v2/js/utils.js:607
  export function offlineImageUrl(url) {
      if (!url || !window.settings?.network?.offline_mode || !/^https?:/i.test(url)) return url;
  ```
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" -c "…re.search(r'categories = \[(.*?)\]', src)…"` prints `has network: False` and the literal list above. Cross-check with a grep of `ui/web_new_v2` for `get_offline_mode` → no hits. The same session also proves the persisted flag survives a restart (`core/api.py:4135` writes it to SQLite; `core/settings.py:315-342` reloads it in `_load_all`).
- **Suggested fix:** (a) add `'network'` to the `get_settings()` category list (or better, derive the list from `core.settings.DEFAULT_SETTINGS`); and (b) have `feature-controls.js` call `window.pywebview.api.get_offline_mode()` at boot and reconcile it with `window.settings.network.offline_mode`, so the UI's truth is the backend's truth.
- **Fix side effects:** adding `network` to the settings tree exposes one more category to the frontend; `settings.js`'s `applySettingsFromBackend` iterates known categories only, so it is inert. `get_settings()` is also the payload cached in `localStorage` — the cache will start carrying the flag, which is what the UI needs anyway.
- **Discovered by:** B

---

#### F-WX-09-4  [P2] — The policy is not enforced at the network choke point: `core/resolver.py` and `audio/engine.py::resolve_stream_url` never consult the offline flag

- **File:** `core/resolver.py:165-230` (`StreamResolver.resolve` — "mem → DB → network cascade, single-flight"), `audio/engine.py:121-151` (`AudioEngine.resolve_stream_url`), `core/resolver.py` (whole file — zero occurrences of `is_offline`).
- **Confirmed:** yes.
- **Description:** `StreamResolver` is described in its own docstring as the "cache layer in front of the network resolution cascade" — every provider stream resolution in the app funnels through `resolver.resolve(source, source_id, _network)` (`audio/engine.py:149`). Neither `core/resolver.py` nor `audio/engine.py::resolve_stream_url` nor `_resolve_via_network` consults the offline policy. The policy is instead re-implemented by each *caller*.
- **Cause:** the offline switch was treated as a UI/bridge-level feature rather than as a network-boundary invariant. Because the resolver owns the single point where "do we talk to a provider?" is decided, the gate belongs there (and in the proxy), not in 40+ call sites.
- **Trigger conditions:** any new code path that calls `resolver.resolve(...)` / `engine.resolve_stream_url(...)` without remembering to check the flag. Two such paths exist today: the proxy's `/?url=` branch (`core/proxy.py:899`, `:925`) and `AppApi.prefetch_track` (`core/api.py:3661`) — the latter is only stopped because its *name* appears in the bridge allowlist.
- **User impact:** the guarantee "offline ⇒ no outbound request" is not structurally enforced. It holds today only because of a hand-maintained allowlist plus per-caller `if is_offline(...)` statements, and it has already failed in two places (F-WX-09-1, F-WX-09-2).
- **Evidence:**
  ```python
  # core/resolver.py:165-176 — the cascade entry point; no policy consultation
      def resolve(self, source: str, source_id, resolver_fn: Callable[[], Tuple[Optional[str], Optional[str]]]) -> Optional[str]:
          """Return a stream URL for (source, source_id).
          resolver_fn runs the network cascade and returns (url, error).
          """
          key = self._key(source, source_id)
          cached = self.get_cached_url(source, source_id)
  ```
  ```python
  # audio/engine.py:143-149
              def _network():
                  try:
                      return self._resolve_via_network(track), None
                  except Exception as e:
                      return None, str(e)
              return resolver.resolve(source, source_id, _network)
  ```
  The full Python-side inventory of offline checks is **41 call sites in 6 files** (`core/api.py` 13, `core/app.py` 7, `core/downloader.py` 5, `core/playback_recovery.py` 5, `core/proxy.py` 3, `services/lyrics_lookup.py` 4) — plus **4** in the frontend (`utils.js` 2, `player.js` 2). None of them sits in `core/resolver.py` or `audio/engine.py`.
- **Reproduction / verification:** grep of `core/resolver.py` and `audio/engine.py` for `is_offline|offline_mode` returns zero matches; grep of the whole Python tree returns the 41 sites listed above.
- **Suggested fix:** make the resolver the policy boundary — give `StreamResolver` a `settings` reference and refuse `resolve()` (returning `None` plus a distinguishable "offline" reason) when the policy is on; keep the per-caller checks for *presentation* (local-file fallback, user-facing message) but stop relying on them for *prevention*.
- **Fix side effects:** the resolver is also used by the proxy's self-healing re-resolution path (`core/proxy.py:1051`); refusing it offline is exactly the desired behaviour, but the proxy's 403/410 recovery path must then answer 503 instead of 404 (`core/proxy.py:1080-1082`).
- **Discovered by:** B

---

#### F-WX-09-5  [P3] — `available_tracks()` re-scans the whole `stream_cache` table on every call, and smart playlists scan it once per 500-row batch

- **File:** `core/offline.py:62-73`, `core/offline.py:76-77`, `core/api.py:2267-2292`, `core/api.py:4147`, `core/api.py:2564`, `services/smart_playlists.py:165-166`, `core/database.py:311-325` (no index on `cached_file_path`).
- **Confirmed:** yes.
- **Description:** `available_tracks()` builds a fresh index of every cached stream on every invocation:
  ```python
  cached = {(row['source'], str(row['source_id'])): row['cached_file_path']
            for row in db.conn.execute('SELECT source, source_id, cached_file_path FROM stream_cache WHERE cached_file_path IS NOT NULL')}
  ```
  `stream_cache` has only `UNIQUE(source, source_id)`; there is no index on `cached_file_path`, so this is a full table scan of a table that grows by one row per (source, source_id) ever resolved. The function then performs an `os.path.isfile` + `os.path.getsize` per candidate track (`core/offline.py:23`). It is called from 9 sites, including the two library loaders (`core/api.py:2270`, `:2280` → `offline_library` → `db.get_all_tracks()` with **no LIMIT**, `core/database.py:1184-1209`) and the offline queue rewrite (`core/api.py:4147`). `services/smart_playlists.py:165-166` calls it *inside* a `fetchmany(500)` loop, so a 5 000-track smart playlist triggers **10** full `stream_cache` scans.
- **Cause:** the availability filter is implemented as "load the whole cache index, then stat every file" instead of as a per-track lookup; the helper has no memoisation and its callers have no idea it is O(cache rows).
- **Trigger conditions:** every library page load while offline, every smart-playlist page while offline, and every offline queue rewrite.
- **User impact:** noticeable UI latency with a large library (library load = full `tracks` read + full `stream_cache` scan + one filesystem stat per track); the smart-playlist path multiplies the scan by the number of batches.
- **Evidence:** see the quoted snippet above; `core/offline.py:23`:
  ```python
          return path if os.path.isfile(path) and os.path.getsize(path) >= (4096 if cached else 1) else None
  ```
- **Reproduction / verification:** `services/smart_playlists.py:15` (`MAX_TRACKS = 500`) with the loop at `:165`; `core/database.py:324` shows `UNIQUE(source, source_id)` as the only index on `stream_cache`. The overhead is directly measurable with `EXPLAIN QUERY PLAN SELECT … FROM stream_cache WHERE cached_file_path IS NOT NULL` → `SCAN stream_cache`.
- **Suggested fix:** index `stream_cache(cached_file_path)` and query it per requested `(source, source_id)` instead of loading the whole table, or memoise the index for the duration of one request; for the smart-playlist loop, build the index once before the `fetchmany` loop and pass it in.
- **Fix side effects:** adding an index changes the `stream_cache` write path slightly (one more index to maintain on every `cache_stream`/`set_cached_file`), and requires a migration for existing databases.
- **Discovered by:** B

---

#### F-WX-09-6  [P3] — Turning offline mode back off does not resume the downloads it paused, and the paused rows are marked non-resumable across a restart

- **File:** `core/api.py:4132-4161` (`set_offline_mode` — only the `if enabled:` branch acts), `core/downloader.py:101-113` (`pause_download` → `resume_on_restart=0`), `core/downloader.py:333-354` (`_resume_pending_downloads`).
- **Confirmed:** yes.
- **Description:** `set_offline_mode(True)` calls `downloader.pause_download()` (`core/api.py:4141-4142`). `pause_download` marks every pending/downloading row `status='paused', resume_on_restart=0` and drops them from the in-memory queue. `set_offline_mode(False)` has **no** corresponding branch — it only flips the setting and emits the event. The paused downloads therefore stay paused until the user clicks "Возобновить всё" in the download manager (`ui/web_new_v2/js/downloads-view.js:143`, `:171`).
- **Cause:** the switch handler implements only the "enter offline" half of the transition; the "leave offline" half was never written.
- **Trigger conditions:** any offline→online transition with queued downloads.
- **User impact:** downloads silently stall after the user re-enables the network; the user must find the download manager and press resume. Because `resume_on_restart` was cleared to `0`, an app restart in between does not auto-resume them either (`core/downloader.py:333-352` only picks up `resume_on_restart` rows — see `tests/test_download_resume.py:160`).
- **Evidence:**
  ```python
  # core/api.py:4132-4161
      def set_offline_mode(self, enabled):
          ...
          self._core.settings.set('network', 'offline_mode', enabled)
          ...
          if enabled:
              downloader = getattr(self._core, 'downloader', None)
              if downloader and hasattr(downloader, 'pause_download'):
                  downloader.pause_download()
              ...
          state = {'enabled': enabled, 'active_available': active_available}
          self._emit('offline_mode_changed', state)
          return dict(state, success=True)
      # <- no else: branch that resumes the paused downloads
  ```
- **Reproduction / verification:** `core/api.py:4141` is the only call site of `pause_download` outside the downloader's own internals; grep for `resume_download` in `core/api.py` shows only the bridge passthrough at `:4186-4187`. The UI affordance exists (`downloads-view.js:171` renders a `resume-all` button), so the state is at least visible.
- **Suggested fix:** add the symmetric branch — on `enabled=False`, re-queue the rows that were paused by the offline switch (the downloader already exposes `resume_download()`), and only for rows this switch paused, so an unrelated user pause is not undone.
- **Fix side effects:** resuming automatically starts network traffic the moment the user re-enables online mode; if the user paused a download *before* going offline it must stay paused, so the paused set needs to be recorded by the switch, not re-derived from the store.
- **Discovered by:** B

---

#### F-WX-09-7  [P3] — Discord Rich Presence keeps publishing the now-playing track while offline mode is ON

- **File:** `core/app.py:147` (`self.discord_rpc.start()` — unconditional), `core/api.py:1229-1236` (`update_presence` on every track change, no offline check), `core/services/discord_rpc.py:87-161` (no `is_offline` anywhere in the service).
- **Confirmed:** yes (the absence of any offline check is confirmed; the *transport* is a local IPC socket, so the app itself makes no outbound request).
- **Description:** `DiscordRPCService` never consults the offline policy. `AppCore` starts it unconditionally at boot (`core/app.py:147`), and `AppApi._on_track_changed` pushes the track title and artist into the presence payload on every track change (`core/api.py:1229-1236`) even when `is_offline()` is true.
- **Cause:** the offline policy was defined as "no outbound network from the app"; the Discord integration was considered out of scope, but it is still a metadata channel that leaves the machine.
- **Trigger conditions:** offline mode ON + the Discord client running.
- **User impact:** the title/artist of what the user is listening to is published to Discord (and from there to Discord's servers) while the user has explicitly asked the app for no network. The app-side socket is local (`pypresence` → local Discord IPC), so the leak is second-hand — hence P3 rather than P2.
- **Evidence:**
  ```python
  # core/app.py:146-147 — started with no policy consultation
          self.discord_rpc = DiscordRPCService(self.settings)
          self.discord_rpc.start()
  # core/api.py:1229-1236
          if hasattr(self._core, "discord_rpc") and self._core.discord_rpc:
              self._core.discord_rpc.update_presence(
                  track_title=track_copy.get("title", ""),
  ```
- **Reproduction / verification:** grep of `core/services/discord_rpc.py` for `is_offline|offline_mode` → no matches; `core/app.py:147` has no `is_offline` guard (contrast `core/app.py:150` and `:154`, where the yt-dlp updater and the Zapret auto-updater *are* guarded).
- **Suggested fix:** either clear/skip the presence while offline (`DiscordRPCService.update_presence` should no-op when the policy is on, and `set_offline_mode` should call `clear_presence()`), or document explicitly that Discord Rich Presence is out of scope for the offline promise and surface it in the UI.
- **Fix side effects:** clearing the presence on the switch removes the "now playing" badge from Discord for offline listening; if the user wants it, the fix must be opt-in rather than a hard block.
- **Discovered by:** B

---

### 3. Clean areas

- **The offline flag is cached in memory and invalidated correctly.** `core/settings.py` loads the whole tree into `self._cache` at construction (`_load_all`, `:315-342`) and `get()` reads only that dict under an `RLock` (`:351-399`) — **no SQLite read per check**. `set()` updates the cache synchronously before scheduling the batched write (`:413-418`), so `set_offline_mode` (`core/api.py:4135`) is visible to every consumer on the very next read; the 0.5 s write-behind delay only affects crash durability, not visibility. **No performance defect on this path.**
- **The `SettingsManager.get()` cost on hot paths is negligible.** `is_offline()` → `settings.get('network','offline_mode',False)` is a lock acquire + two dict lookups. Even on the proxy's 32 KB chunk loop (`core/proxy.py:1195`, `:1229`) this is noise compared to the socket read.
- **Cooperative cancellation of in-flight downloads is correct.** `DownloadManager._download_worker`'s `checkpoint()` (`core/downloader.py:718-728`) raises `DownloadInterrupted` when the track was paused or the offline flag flipped, so an in-flight transfer is aborted rather than left to time out; `set_offline_mode(True)` also calls `pause_download()` (`core/api.py:4141`).
- **Startup with offline mode ON does not start any download.** `DownloadManager.__init__` resumes pending rows first (`core/downloader.py:86`) and pauses them immediately after (`:87-88`), and the processor thread is only started at `:89-90` — after the pause. Pinned by `tests/test_download_resume.py:160`.
- **Late network results are discarded correctly when the switch flips mid-resolution.** `AppCore.re_resolve_stream_url_async` re-checks the flag at the start of the worker (`core/app.py:306`), in the `offline_result()` helper (`:338-346`) and again on the provider callback (`:364`, `:380`, `:447`, `:471`, `:500`), so a resolution that lands after the switch is replaced by the local file or reported as offline. Pinned by `tests/test_offline_resolve_callbacks.py` (5 tests, all pass).
- **Stale search results are dropped.** `set_offline_mode` bumps `self._search_generation` (`core/api.py:4136-4137`) and `search` checks `is_current()` before emitting (`core/api.py:2094-2096`, `:2109`), so in-flight provider searches cannot repopulate the UI with online results.
- **`core/playback_recovery.py` is the best-gated module in the codebase.** It checks the flag five times (`:113`, `:131`, `:137`, `:149`, `:166`) — before the first provider call, after each provider callback, and before returning the proxy URL.
- **The lyrics cascade has a proper network choke point.** `services/lyrics_lookup.py::_read` (`:73-81`) refuses to open a URL while offline, and every HTTP lyrics provider (LRCLIB, Netease, QQ Music, Genius — `:86-184`) goes through it. `services/lyrics_lookup.py:307`/`:327`/`:377` additionally suppress the network cascade when the flag is set, and the embedded-lyrics path stays local. Pinned by `tests/test_offline_mode.py:78`.
- **The `/api/stream` proxy branch is correctly gated.** `core/proxy.py:814` refuses with 503 *before* the resolver or any DNS lookup; `tests/test_offline_proxy.py:6-13` pins that no resolver call and no SSRF/DNS lookup happens. Local files are still served (`:16-27`).
- **The library/library-offline views filter correctly.** `get_library` (`core/api.py:2269`), `get_downloaded_tracks` (`:2279`), `get_favorite_tracks` (`:2729`), `get_playlist_tracks` (`:2563`) and `get_smart_playlist_tracks` (`:4216`) all restrict to locally available audio while offline.
- **`play_track` / `_resolve_track` handle the offline case.** `core/api.py:1439-1448` replaces the track with its local file and rewrites the queue; `core/api.py:1201-1206` rejects a track with no local file.
- **User-facing error mapping for the offline state is coherent.** `core/user_errors.py:13-14` maps any offline error to `{code:'offline', action:'online'}`, and `ui/web_new_v2/js/feature-controls.js:52-56` turns that action into `set_offline_mode(false)` — the one path that reliably switches offline mode back off.
- **The bridge-level interception covers the majority of network-capable methods.** Of the ~40 network-capable bridge methods, all but `get_waveform` are either named in `_offline_bridge_result` (`core/api.py:461-512`) or carry their own internal check (`search` `:2085`, `get_lyrics` via `lyrics_lookup`, `recover_stream` `:4168`, `get_smart_playlist_tracks` `:4216`).

---

### 4. Coverage gaps

- **The `/?url=` proxy branch was not covered by any offline test.** `tests/test_offline_proxy.py` exercises `/api/stream` only (both tests use `client.url('/api/stream', …)`); `tests/test_proxy_paths.py` covers the `'/'` path for the *empty-query* 400 case only. The leak in F-WX-09-1 therefore passed CI silently.
- **No test asserts that the offline flag reaches the UI.** `tests/test_feature_controls_ui.py:30-54` drives `applyOfflineState()` directly with a synthetic `window.settings`; nothing tests that `get_settings()` (or any other call) delivers `network.offline_mode` to the frontend. F-WX-09-3 was invisible to the suite.
- **No test enumerates the blocked-method list.** Nothing asserts that every network-capable bridge method is either in `_offline_bridge_result` or internally gated — which is exactly how `get_waveform` slipped through.
- **No test covers the switch *during* an in-flight download.** `tests/test_offline_mode.py:33-49` uses a `SimpleNamespace(pause_download=…)` stub, so the cooperative `checkpoint()` abort path (`core/downloader.py:726-728`) is not exercised end-to-end; `tests/test_download_resume.py:160` covers the startup case only.
- **No test covers offline→online transition semantics.** Nothing asserts whether the downloads paused by the switch should be resumed (F-WX-09-6); the only assertion is `api.set_offline_mode(False)['success']` (`tests/test_offline_mode.py:47`).
- **No test covers the offline→online transition of an *already playing* remote stream**, i.e. the case in which the `<audio>` element keeps its `/?url=…` src (F-WX-09-1). Reproducing it needs a live WebView.
- **I could not verify the live WebView behaviour** (whether the WebView2 process re-requests the proxy URL after the switch, and whether `<audio>` keeps buffering). The finding rests on the server-side evidence that the request is issued and on the frontend code path (`feature-controls.js:99-103`) that does not reload or stop the element.
- **I did not run the real app** (per the audit rules), so the "persisted offline flag is invisible in the UI" claim (F-WX-09-3) is verified from the settings-assembly code and the `get_settings()` category list rather than from a screenshot.
- **The `network` category's absence from `get_settings()` was not checked against other areas' expectations** — e.g. whether WN-08 (settings bridge) considers this list canonical. If another area owns `get_settings()`'s category list, F-WX-09-3 should be re-attributed to that area.

---

### 5. Architecture improvements (ARCH)

No proven defect; listed separately from the findings above.

1. **Make the offline switch a single policy object consulted at the network boundary, not a boolean re-read 41 times.** Today the flag is a `bool` in the settings tree, and every subsystem re-implements "should I touch the network?" (`core/api.py` 13×, `core/app.py` 7×, `core/downloader.py` 5×, `core/playback_recovery.py` 5×, `core/proxy.py` 3×, `services/lyrics_lookup.py` 4×, plus 4 in JS). A `NetworkPolicy` object exposing `allow_remote(host, purpose) -> bool` and `offline_local_only()` would make the decision auditable in one file and would let the proxy, the resolver, the downloader and the lyrics cascade share it. (This is the fix direction of F-WX-09-1 and F-WX-09-4.)

2. **Invert the bridge interception from an allowlist to a capability declaration.** `_offline_bridge_result` (`core/api.py:461-512`) is a list of *blocked* method names with a default of ALLOW; every new network-capable bridge method must be added by hand, and `get_waveform` proves the failure mode. Declaring the capability on the method itself (`@bridge(requires_network=True)`) and letting the wrapper read the attribute makes the default SAFE (deny) and removes the duplication between "the method needs the network" and "the method is named in a list somewhere else".

3. **Put the offline gate at the two places that actually leave the machine: the proxy's request builder and `StreamResolver.resolve`.** Both already exist and both own a choke point; today the proxy has a gate in one of its two branches and the resolver has none. A single `if not policy.allow_remote(): return 503` in the proxy, plus a `policy` reference in `StreamResolver`, would make the "offline ⇒ no outbound request" guarantee structural rather than incidental.

4. **Give the frontend one authoritative offline state.** Today the UI has three readings: `window.settings.network.offline_mode` (broken at startup, F-WX-09-3), the `offline` flag on `search_results` events (`core/api.py:2116`, correct) and the `offline_mode_changed` event (correct, but only after a toggle). A single `get_offline_mode()` call at boot — or shipping `network` in the settings tree — collapses them into one and lets the UI-side gates (`utils.js:608`, `player.js:1440/1524`) be trusted instead of merely decorative.

5. **Model the offline transition as a state machine with an explicit "leave offline" edge.** `set_offline_mode` currently performs a set of side effects on the *enter* edge only (pause downloads, prune the queue, rewrite the current track) and none on the *leave* edge (F-WX-09-6). A symmetric transition — with the paused-by-offline set recorded so an unrelated user pause is not undone — would make the behaviour predictable and testable.

6. **Move the offline availability filter out of "load everything and filter" into a query.** `core/offline.py::available_tracks` loads the whole `stream_cache` index and stats every candidate file (F-WX-09-5); the natural shape is a SQL join (`tracks LEFT JOIN stream_cache`) plus an index on `stream_cache(cached_file_path)`, which would also remove the per-batch re-scan in `services/smart_playlists.py:165`.

7. **Keep the offline state inside the settings schema rather than beside it.** `network.offline_mode` is the only settings key that changes the *behaviour of other subsystems*, and it is the only category that the UI cannot see. Treating "policy" keys separately from "preference" keys in `core/settings.py` (a small `POLICY_CATEGORIES` set) would let `get_settings()` expose them deliberately and would document, in one place, which flags are cross-cutting.
