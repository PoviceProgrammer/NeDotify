## AREA WX-09 — Offline mode across playback, library, proxy, downloads — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read |
|---|---|
| `core/offline.py` | 1–77 (whole file) |
| `core/api.py` | 390–549 (`_install_bridge_error_logging`, `_offline_bridge_result`), 1118–1162 (`_emit`), 1160–1280 (`_on_track_changed`), 1398–1520 (`play_track` head), 1519–1768 (`play_track` tail, `_resolve_track`, `play_pause`/`next_track`), 1853–1912 (`get_setting`/`set_setting`), 2016–2075 (`get_next_track`), 2077–2316 (`search`, `get_album_*`, `get_library`, `get_favorites`, `get_downloaded_tracks`, `download_track` head), 2532–2621 (`get_track_info`, `get_playlist_tracks`), 2727–2744 (`get_favorite_tracks`), 2915–2974 (`get_settings`/`save_setting`/`update_setting`), 3192–3321 (`get_lyrics`, `fetch_missing_covers`, `get_home_data`), 3740–3809 (`get_feed`, `get_home_artists/releases/mixes`), 4110–4228 (`get_flow_tracks`, `get_offline_mode`, `set_offline_mode`, `get_offline_library`, `recover_stream`, download bridge methods, smart playlists) |
| `core/settings.py` | 1–200 (defaults, `DEFAULT_SETTINGS["network"]`), 201–510 (`SettingsManager._load_all`, `get`, `set`, `flush`, `_write_batch`) |
| `core/proxy.py` | 1–329 (helpers, `_safe_stream_local_path`), 385–429 (`_safe_urlopen`), 660–779 (`serve_local_file`, `_resolve_stream_local_file`, `do_GET` head), 780–1058 (`do_GET` body: `/api/stream` branch + the `/` branch), 1150–1290 (streaming loop, offline aborts, `LocalProxyManager`), 1300–1334 (`get_proxy_url`) |
| `core/downloader.py` | 1–200 (init, `_offline`, `pause_download`, `resume_download`, `retry_failed_downloads`), 330–509 (`queue_download`, `_process_queue`), 545–711 (`_mark_queue_cancelled`, `_is_cancelled`, `_abort_cancelled`, `_fetch_with_retry`), 713–909 (`_download_worker`, `_execute_download_worker`), 884–909 (`stop`) |
| `core/download_store.py` | 1–71 (whole file) |
| `core/download_transfer.py` | 1–128 (whole file) |
| `core/resolver.py` | 1–60, 160–239 (`resolve`, `get_cached_url`, `refresh`) |
| `core/playback_recovery.py` | 1–183 (whole file) |
| `core/app.py` | 130–289 (offline-guarded startup, `re_resolve_stream_url_async` head), 290–519 (`re_resolve_stream_url_async` body) |
| `core/database.py` | 1166–1289 (`get_track`, `get_all_tracks`, `get_downloaded_tracks`, `mark_track_downloaded`), 2036–2145 (`set_setting`, `set_settings_batch`, `get_all_settings`) |
| `audio/engine.py` | 1–179 (`play_track`, `play_queue`, `next_track`, `_notify_track_changed`, `resolve_stream_url`) |
| `audio/queue.py` | 110–229 (`set_tracks`, `add_track(s)`, `remove_track`, `next_track`), 280–302 (`jump_to`, `clear`) |
| `services/lyrics_lookup.py` | 60–109 (`_read` offline guard) |
| `services/smart_playlists.py` | 145–174 (`available_only` branch) |
| `core/user_errors.py` | 13–14 (offline error category) — grep only |
| `ui/web_new_v2/js/feature-controls.js` | 1–135 (whole file) |
| `ui/web_new_v2/js/player.js` | 95–164 (`normalizeAudioSourceUrl`, `loadAudioSource`), 420–549 (`handleStreamError`, `stopFailedPlayback`), 1420–1499 (prefetch/lookahead), 1630–1739 (`onTrackChanged` source selection) |
| `ui/web_new_v2/js/utils.js` | 600–629 (`offlineImageUrl`, `getCoverUrl`) |
| `ui/web_new_v2/js/main.js` | 385–444 (settings bootstrap) |
| `ui/web_new_v2/js/events.js` | 60–119 (`offline_mode_changed` case) |
| `ui/web_new_v2/js/search.js` | grep only (`offline` hits: 24, 263, 333, 342, 354, 401, 1008–1013, 1078) |
| `ui/web_new_v2/js/library.js` | grep only (18, 27–29, 361–384, 492–519) |
| `ui/web_new_v2/index.html` | 416, 461, 1795–1824 (offline note, offline card, storage rows) |
| `tests/test_offline_mode.py` | 1–110 (whole file) |
| `tests/test_offline_proxy.py` | 1–27 (whole file) |
| `tests/test_proxy_harness.py` | 1–215 (whole file) |
| `tests/conftest.py` | 1–174 |
| `tests/test_download_resume.py` | 1–386 |
| `tests/test_feature_controls_ui.py` | 1–86 |
| `tests/test_playback_recovery.py`, `tests/test_offline_resolve_callbacks.py`, `tests/test_smart_search_bridge.py` | grep only (offline hits) |
| `pytest.ini` | 1–5 |

**Callees traced into other areas**: `audio/engine.py::resolve_stream_url` → `core/resolver.py` (WN-15); `core/proxy.py` → `core/api.py::_is_ssrf_safe_url` (WN-03); `services/lyrics_lookup.py` offline guard (WN-22); `services/smart_playlists.py::available_only` (WN-24); `core/database.py` settings table (WN-12); `core/download_store.py`/`core/download_transfer.py` (WN-13).

**Verification artefacts** (outside the repo tree, nothing in the repo was modified):
`%TEMP%\opencode\wx09\test_wx09_offline.py` (probes A–G) and `%TEMP%\opencode\wx09\test_wx09_table.py` (interception table).
The existing offline suite was run unchanged and passes: `tests/test_offline_mode.py tests/test_offline_proxy.py tests/test_offline_resolve_callbacks.py tests/test_download_resume.py tests/test_feature_controls_ui.py tests/test_playback_recovery.py tests/test_smart_search_bridge.py` → **49 passed**. Every finding below is therefore a *gap in the existing coverage*, not a regression.

---

#### Trace table 1 — the offline key: writer vs reader

| Role | Call site | Category / key | Effective stored key |
|---|---|---|---|
| **Writer (the switch)** | `core/api.py:4135` `self._core.settings.set('network', 'offline_mode', enabled)` | `('network','offline_mode')` | `settings` row `network.offline_mode` (`core/settings.py:456-459` `f"{cat}.{k}"` → `core/database.py:2049-2082` `INSERT OR REPLACE INTO settings (key,…)`) |
| **Reader (canonical)** | `core/offline.py:13` `value = settings.get('network', 'offline_mode', False)` | `('network','offline_mode')` | same row → `core/settings.py:324-325` `self._cache['network']['offline_mode']` |
| Reader (2nd copy) | `core/playback_recovery.py:113` `settings.get("network", "offline_mode", False)` | `('network','offline_mode')` | same row |
| Default | `core/settings.py:54` `"offline_mode": False` under `"network"` | `('network','offline_mode')` | — |

**Verdict: the writer and the reader use the same category and the same key.** The toggle is *not* a no-op at the settings layer. `set_offline_mode` also rejects a non-bool (`ValueError`, `core/api.py:4133-4134`), and `is_offline` accepts `True / 1 / 'true'` (`core/offline.py:14`) while `SettingsManager.get` normalises the strings `"true"/"false"` to bools (`core/settings.py:394-399`). The **real** defect is on the UI side of the switch (F‑WX‑09‑3) and in the state machine that the switch is supposed to trigger (F‑WX‑09‑2, F‑WX‑09‑4).

#### Trace table 2 — what `_offline_bridge_result` intercepts (offline = ON)

`core/api.py:461-512`. Probe over every public `AppApi` method:

| Intercepted (handled=True) | Result returned while offline |
|---|---|
| `get_feed`, `get_popular_tracks`, `get_authentic_home_feed`, `get_home_releases`, `get_home_mixes` | `[]` + the matching `*_ready` event with an empty payload |
| `get_artist_profile` | `{'status':'unavailable',…}` + `artist_profile_error` |
| `get_artists_avatars` / `fetch_missing_covers` | `{}` / `0` |
| `get_album_tracks`, `get_album_details` | the locally available album tracks, or `status='unavailable'` + `album_details_ready` |
| `get_flow_tracks`, `get_recommendations`, `get_yt_playlist_tracks` | `[]` |
| `get_track_wave` | `[]` + `track_wave_ready {offline:True}` |
| `get_playlist_tracks` | `[]` **only** when `source != 'local'`; the local source falls through to the real method (which filters by `available_tracks`, `core/api.py:2563-2564`) |
| `prefetch_track`, `get_lyrics_translation`, `check_zapret_update`, `update_zapret` | `None` |
| `yandex_device_auth` | `{'success':False,'error':'Включён офлайн-режим'}` |
| `download_track`, `download_all_favorites`, `import_external_playlist`, `resume_download`, `retry_failed_downloads` | `{'success':False,'code':'offline',…}` + `operation_error` |

| **NOT intercepted — the real method runs** | Network-capable? |
|---|---|
| `get_settings`, `get_all_settings`, `get_setting`, `save_setting`, `set_setting`, `update_setting` | no (but see F‑4) |
| `get_library`, `get_favorites`, `get_favorite_tracks`, `get_downloaded_tracks`, `get_offline_library`, `get_smart_playlist_tracks` | no — each filters internally with `available_tracks` |
| `play_track`, `play_pause`, `next_track`, `prev_track`, `play_next`, `add_to_queue`, `add_tracks_to_queue`, `remove_from_queue`, `clear_queue`, `reorder_queue`, `get_queue`, `get_next_track` | no — the offline branches live in `play_track` (`core/api.py:1439-1448`) and `_on_track_changed` (`core/api.py:1201-1206`) |
| `recover_stream` | no — it has its own offline branch (`core/api.py:4168-4173`) |
| `search` | **yes, but guarded internally**: `core/api.py:2085-2086` forces `source='local'` → only the local provider runs (`tests/test_offline_mode.py:52-63` asserts `core_ns.youtube.calls == []`) |
| `get_lyrics` | **yes, but guarded internally**: `services/lyrics_lookup.py:73-75` raises `ConnectionError` before the request; the embedded/local cache path still works (`tests/test_offline_mode.py:78-88`) |
| `open_url`, `open_external_url` | yes — opens the OS browser (user-initiated) |
| everything else (window mgmt, playlists, storage, telemetry, tray) | no |

**Verdict:** no method that *must* work offline is blocked (`get_settings`, `get_library`, the queue ops, `play_track` for a local file, `recover_stream` all run). The interception list is **default-ALLOW**: `core/api.py:512` `return False, None` means "not handled → run the real method", so a *new* bridge method is **not** blocked by default (F‑WX‑09‑5).

#### Trace table 3 — state changes caused by the switch

| State being changed | What actually happens | Where | Verdict |
|---|---|---|---|
| In-flight **download** | `set_offline_mode(True)` → `downloader.pause_download()` → the rows in `('pending','downloading')` get `status='paused'`, `resume_on_restart=0`, and their `_track_generations` are bumped. The running worker aborts at its **next checkpoint** (`core/downloader.py:718-728`), `_abort_cancelled` (`core/downloader.py:587-599`) re-marks the row `paused` and **no `download_failed` is emitted**. The partial file stays as `*.part` (`core/download_transfer.py:46-47,109-119`) and is **not** marked complete (`_downloaded_file_defect` rejects `.part`, `core/downloader.py:42-43`). | `core/api.py:4139-4142`, `core/downloader.py:101-113, 587-599, 718-728` | **correct** |
| In-flight **playback** | the open upstream response is aborted before the next 32 KB chunk (`core/proxy.py:1195-1196`, `1229-1230`) → the audio cuts out; the frontend's error handler calls `recover_stream` (`ui/web_new_v2/js/player.js:462-483`) → offline branch (`core/api.py:4168-4173`) returns the **local file**, which `normalizeAudioSourceUrl` (`ui/web_new_v2/js/player.js:97-103`) rewrites into `http://127.0.0.1:<port>/api/stream?url=…` → playback resumes at the saved position. If the track is not downloaded, the UI stops with `code:'offline'` → "Трек недоступен офлайн" (`ui/web_new_v2/js/player.js:477`). | `core/proxy.py:1195,1229`, `core/api.py:4166-4174`, `ui/…/player.js:97-103,462-483` | **correct** (the current track keeps playing because the file is local) |
| **Next** track | the queue was pruned to the available tracks by the switch, so the next track resolves to its local file through the proxy | `core/api.py:4147-4155`, `core/api.py:1201-1206` | correct **unless** the prune empties the queue (F‑WX‑09‑2) |
| **Library** | `get_library` / `get_downloaded_tracks` / `get_favorites` / `get_playlist_tracks(local)` / `get_smart_playlist_tracks` return only tracks whose file really exists on disk | `core/api.py:2269-2280, 2563-2564, 2729-2730, 4216` | correct |
| **Switch OFF** | the flag is cleared; the rows paused by the switch stay `paused` — nothing calls `resume_download` | `core/api.py:4132-4161` | minor gap (F‑WX‑09‑6) |

---

### 2. Findings

#### F-WX-09-1  [P1] — The proxy's generic `/` endpoint still resolves and fetches from the upstream while offline mode is on

- **File:** `core/proxy.py:814-816` (the guard that exists), `core/proxy.py:863-864` (the unguarded branch), `core/proxy.py:891-899` and `core/proxy.py:917-925` (re-resolution), `core/proxy.py:1016` (the upstream fetch), `core/proxy.py:1195-1196`/`1229-1230` (the abort that happens *after* the upstream was already contacted)
- **Confirmed:** yes (probes A and B, both reproduced)
- **Description:** the offline gate exists only inside the `/api/stream` branch of `do_GET`. The sibling branch — the generic `/` endpoint (`KNOWN_PROXY_PATHS[0]`, `core/proxy.py:40`), which is exactly the URL `LocalProxyManager.get_proxy_url()` (`core/proxy.py:1304-1316`) and `engine._notify_track_changed()` (`audio/engine.py:95-99`) hand to the frontend for every source whose stream is not a youtube/soundcloud host — has **no offline check at all**. It calls `engine.resolve_stream_url()` (a full provider/yt-dlp network cascade) and then `urllib.request` against the upstream.
- **Cause:** the guard was added inside one branch of an `if/else` instead of in front of the branch, so the `else:` half of the endpoint has no offline semantics.
- **Trigger conditions:** offline mode is ON **and** the browser issues a request to the `/` proxy URL. That happens when (a) the in-flight remote stream is aborted by `core/proxy.py:1195/1229` and the browser re-requests (seek, retry, gapless pre-load), or (b) the local file was deleted/moved between the availability check and the request — then `core/proxy.py:891-899` explicitly falls back to *"resolving online stream"*; or (c) the track was queued before offline mode was switched on and still carries a remote `stream_url`.
- **User impact:** the app performs a network request the user explicitly disabled, **with the provider credentials attached** (`core/proxy.py:990-1006` injects the YouTube cookie jar and the Yandex OAuth `Authorization` header) and blocks a proxy thread for up to 12 s (`core/proxy.py:1016 timeout=12.0`) plus the whole yt-dlp cascade behind `resolve_stream_url` (`_RESOLVE_TIMEOUT = 12.0`, `core/resolver.py:22`). The user sees the track fail to load instead of a clear "offline" message.
- **Evidence:**
  ```python
  # core/proxy.py:814-816  (guard — only in the /api/stream branch)
              if is_offline(getattr(self.server.app_core, 'settings', None)):
                  self._safe_send_error(503, 'Offline mode: track is not saved locally')
                  return None
  # core/proxy.py:863-864  (the / branch — no guard)
          else:
              target_url = query_params.get('url', [None])[0]
  # core/proxy.py:891-899
                      if (source and source_id) or title:
                          logger.info(f"Local file not found on disk ({local_path[:60]}), resolving online stream for {title or source_id}...")
                          track_info = {...}
                          target_url = self.server.app_core.engine.resolve_stream_url(track_info)
  # core/proxy.py:1016
                      resp = _safe_urlopen(req, timeout=12.0, source=source)
  ```
- **Reproduction / verification:** probe A (offline ON, `GET /?url=https://cdn.example/stream.mp3&source=youtube&source_id=remote`): `upstream_fetches=['https://cdn.example/stream.mp3']` — the fake `_safe_urlopen` was called while offline (status 500 because the fake raised). Probe B (offline ON, `GET /?url=C:\missing\song.mp3&source=youtube&source_id=remote&title=T`): `engine.resolve_stream_url calls=[{'source':'youtube','source_id':'remote',…}, {…}]` — the resolver ran twice while offline. Control: `GET /api/stream?source=youtube&source_id=remote` → **503**, `engine.calls == []` (as `tests/test_offline_proxy.py:6-13` already pins).
- **Suggested fix:** hoist the offline check to the top of `do_GET` (before the `/api/stream` / `/` split) — or duplicate it at the head of the `/` branch — so that no branch can resolve or fetch a remote URL while offline; answer `503` with the same message.
- **Fix side effects:** a `/` request for a track that exists only as a cached *remote* URL will start failing with 503 while offline (intended), but the frontend must surface that as an offline error rather than a generic stream error — the existing `recover_stream` offline branch (`core/api.py:4168-4173`) already returns `code:'offline'`, and `ui/web_new_v2/js/player.js:477` handles it.
- **Discovered by:** A

#### F-WX-09-2  [P1] — Switching offline mode on wipes the whole playback queue even when the current track *is* available offline

- **File:** `core/api.py:4143-4158` (`set_offline_mode` queue pruning), `core/offline.py:35-59` (`available_track`), `core/offline.py:62-73` (`available_tracks`), `core/api.py:1444-1447` (`play_track` queue filtering)
- **Confirmed:** yes (probe C, reproduced)
- **Description:** `available_track` (singular) resolves the local file **through the `tracks` table** (`db.get_track(int(identifier))` → `stored['file_path']`, `core/offline.py:44-52`). `available_tracks` (plural) does **not** consult the `tracks` table at all: it only accepts a `file_path` that is already present in the passed dict, or a `stream_cache` row (`core/offline.py:62-73`). The playback queue holds the *provider* rows the UI sent (search/home results carry no `file_path`), so `available_tracks(db, queue.tracks)` returns `[]` while `available_track(db, queue.current_track)` returns the file. `set_offline_mode` then takes the `else:` branch and calls `queue.clear()`.
- **Cause:** two different notions of "available" coexist in `core/offline.py`; the plural helper is a strict subset of the singular one, and the caller assumes they agree.
- **Trigger conditions:** a track that has a downloaded copy in the library is played from a list (search results, home feed, a playlist fetched from a provider) and offline mode is then switched on. The queue entries are provider dicts → `available_tracks` → `[]`.
- **User impact:** the queue is silently emptied (`queue_updated` is emitted with `{'tracks': [], 'current_index': -1}`); the current track keeps playing in the browser, but "next track" does nothing (`queue.next_track()` → `is_empty` → `_on_queue_end` → `queue_ended`). The event payload claims the opposite: `offline_mode_changed {'enabled': True, 'active_available': True}`. The same asymmetry degrades `play_track`: when `available_tracks` returns `[]`, `track_list` becomes falsy → the `else` branch (`core/api.py:1605-1606`) → `engine.play_track(track)` → the queue is **replaced by the single track**, losing the playlist context.
- **Evidence:**
  ```python
  # core/offline.py:44-52  (singular: DB-aware)
      if identifier is not None:
          try:
              stored = db.get_track(int(identifier))
          except (TypeError, ValueError):
              pass
      if stored:
          path = _local_file(stored.get('file_path'))
  # core/offline.py:69-70  (plural: NOT DB-aware)
          path = _local_file(track.get('file_path')) or _local_file(
              cached.get((track.get('source'), str(track.get('source_id')))), cached=True)
  # core/api.py:4144-4158  (the caller)
              if queue and queue.tracks:
                  current = available_track(self._core.db, queue.current_track)
                  active_available = current is not None
                  tracks = available_tracks(self._core.db, queue.tracks)
                  if current and tracks: ...
                  elif tracks: ...
                  else:
                      queue.clear()
  ```
- **Reproduction / verification:** probe C — a `tracks` row with `file_path` = a real `.mp3`, the queue holding `{'source':'youtube','source_id':'sid','id':<row id>,'title':'Song'}` (no `file_path`): `set_offline_mode -> {'enabled': True, 'active_available': True, 'success': True}` but `queue.count == 0`. Probe D — the same dict: `available_track -> 'C:\\…\\song.mp3'` vs `available_tracks -> []`.
- **Suggested fix:** make `available_tracks` resolve each entry through the same `db.get_track(id)` lookup as `available_track` (or make `available_track` delegate to `available_tracks`), and in `set_offline_mode` fall back to the singular helper for the current track when the plural one yields nothing instead of clearing the queue.
- **Fix side effects:** `available_tracks` is also the offline-library filter (`core/offline.py:76`) and the smart-playlist filter (`services/smart_playlists.py:156-174`) → one extra `db.get_track()` per row; the latter already pre-filters in SQL, so the cost stays bounded.
- **Discovered by:** A

#### F-WX-09-3  [P1] — The offline flag lives in a settings category the bridge never returns: the UI cannot read it and there is no control to switch it on

- **File:** `core/api.py:2929` (the `get_settings` category list), `core/api.py:4129-4130` (`get_offline_mode` — no UI caller), `core/api.py:4135` (the writer), `ui/web_new_v2/js/feature-controls.js:9-24, 52-56, 112` (the only readers), `ui/web_new_v2/js/utils.js:607-608`, `ui/web_new_v2/js/player.js:1440, 1524` (readers of `window.settings.network.offline_mode`), `ui/web_new_v2/index.html:461` (the note that is never shown)
- **Confirmed:** yes (probe E + a repo-wide grep)
- **Description:** the persisted flag is correct and readable by the backend (see trace table 1), but `get_settings()` returns only the 22 categories hard-coded at `core/api.py:2929` and **`'network'` is not among them**. The frontend's only source of settings is `get_settings()` (`ui/web_new_v2/js/main.js:409-418`, plus the `localStorage` copy of the same payload), so `window.settings.network` is always `undefined` in the UI and every `window.settings?.network?.offline_mode` check is permanently false. `get_offline_mode()` exists on the bridge but has **no caller anywhere in `ui/`**.
- **Cause:** the category that holds the flag was never added to the bridge's settings projection, and the UI reads the flag out of that projection instead of calling `get_offline_mode()`.
- **Trigger conditions:** always — from the first paint onwards.
- **User impact:**
  1. **The feature cannot be switched on from the shipped UI.** The only UI call site of `set_offline_mode` is the error-recovery action *"Разрешить сеть"* (`ui/web_new_v2/js/feature-controls.js:54`), which passes `false`. There is no toggle anywhere: a repo-wide grep over `ui/` finds no `set_offline_mode(true)`, `index.html` has no `offline-mode-toggle` element (the id appears only in the test stub `tests/test_feature_controls_ui.py:38`), and `feature-controls.js` never reads such an id. So the offline mode is unreachable for the user — the bridge method and the whole backend half exist but nothing can switch them on.
  2. **After a restart the UI cannot reflect the persisted state**: the `offline-mode` CSS class is not applied and the "Офлайн-режим: доступны локальные файлы…" note (`index.html:461`) stays hidden, because `applyOfflineState({enabled: window.settings?.network?.offline_mode === true})` (`feature-controls.js:112`) always evaluates to `false`.
  3. `offlineImageUrl()` (`ui/web_new_v2/js/utils.js:607-608`) never strips remote cover URLs → the UI keeps issuing remote image requests while the backend is offline; `player.js:1440` (`prefetch_track`) and `player.js:1524` (flow tracks) keep firing (both are intercepted by the bridge, so they degrade to no-ops rather than to network traffic).
- **Evidence:**
  ```python
  # core/api.py:2929
          categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay',
                        'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance',
                        'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services',
                        'session', 'zapret']
  # ui/web_new_v2/js/feature-controls.js:112
      applyOfflineState({ enabled: window.settings?.network?.offline_mode === true });
  # ui/web_new_v2/js/feature-controls.js:54  (the ONLY set_offline_mode call site in the UI)
          const result = await window.pywebview.api.set_offline_mode(false);
  ```
- **Reproduction / verification:** probe E — after `api.set_offline_mode(True)`, `api.get_settings()` contains no `'network'` key (`sorted(settings.keys()) == []` with the stub, i.e. the category is not projected). Static: `Select-String 'offline_mode'` over `ui/web_new_v2/**` returns only the readers listed above; `Select-String 'set_offline_mode'` over the whole desktop tree returns `core/api.py` (definition) and `ui/web_new_v2/js/feature-controls.js:54` (the `false` call).
- **Suggested fix:** project the `'network'` category in `get_settings()` (`core/api.py:2929`) **and** have the UI call `get_offline_mode()` at boot (`ui/web_new_v2/js/feature-controls.js:112`) instead of deriving the state from `window.settings`; add a real toggle (e.g. `offline-mode-toggle` in the settings panel) that calls `set_offline_mode(true|false)`.
- **Fix side effects:** `get_settings` masks secrets per category (`_mask_secrets`); the `network` category holds no secret. The frontend caches the payload in `localStorage` → the cached object gains a `network` key (harmless). Adding the category makes `window.settings.network.offline_mode` meaningful, which also activates `offlineImageUrl()` and the two `player.js` guards — those are the intended behaviours.
- **Discovered by:** A

#### F-WX-09-4  [P2] — The offline flag can be flipped through the generic settings writer, bypassing the whole offline state machine

- **File:** `core/api.py:2940-2953` (`save_setting`), `core/api.py:1871-1900` (`set_setting`), `core/api.py:260-264` (`_bridge_write_error` — only `('general','plugins_enabled')` is refused), `core/api.py:4132-4161` (`set_offline_mode`, the only writer that prunes the queue, pauses the downloader and emits the event)
- **Confirmed:** yes (code path); **no shipped UI call site today** — the impact is API-level / latent
- **Description:** `save_setting('network', 'offline_mode', True)` passes `_bridge_write_error` and writes the flag directly through `settings.set`. `is_offline()` then reports "offline" to every consumer (the proxy refuses, `queue_download` pauses, the search goes local), but **none** of the state-machine side effects of `set_offline_mode` happen: the queue is not pruned, the in-flight downloads are not paused, and no `offline_mode_changed` event is emitted.
- **Cause:** the flag is a plain settings value that can be written through the generic settings API, while the real switch is a separate method with side effects. There is no guard that funnels writes to the flag through `set_offline_mode`.
- **Trigger conditions:** any client writes the flag through `save_setting`/`set_setting`/`update_setting` instead of `set_offline_mode` (the bridge is the app's public API; plugins and future UI code can do this; `tests/` already uses `core_ns.settings.set('network','offline_mode',True)` to force the state).
- **User impact:** a half-offline app — the proxy refuses new remote streams and new downloads are paused, but the queue still holds tracks that cannot be played and the downloads that were already running keep pulling bytes from the provider while the user believes the app is offline.
- **Evidence:**
  ```python
  # core/api.py:2940-2946
      def save_setting(self, key: str, value, category: str = "app"):
          """Save a setting value."""
          if _bridge_write_error(category, key, value):
              return False
          ...
          self._core.settings.set(category, key, value)
  # core/api.py:260-264
  def _bridge_write_error(category: str, key: str, value):
      if (category, key) in _BRIDGE_READONLY_SETTINGS:   # only ("general","plugins_enabled")
          return f"{category}.{key} cannot be changed from the UI"
  ```
- **Reproduction / verification:** `api.save_setting('offline_mode', True, 'network')` → returns `True`, `api.get_offline_mode() == {'enabled': True}`, but `api.get_queue()` still returns the unfiltered queue and no `offline_mode_changed` event is emitted (compare `core/api.py:4159-4160`).
- **Suggested fix:** route writes to `('network','offline_mode')` through `set_offline_mode` inside `save_setting`/`set_setting` (adapting the return shape), or add `('network','offline_mode')` to `_BRIDGE_READONLY_SETTINGS` so only `set_offline_mode` can move the flag.
- **Fix side effects:** `save_setting` returns a bool while `set_offline_mode` returns a dict → the bridge contract would have to be adapted for that key; the `setting_changed` event would need to be re-emitted from `set_offline_mode` for the UI to notice.
- **Discovered by:** A

#### F-WX-09-5  [P2] — The bridge's offline interception is default-ALLOW: a new network-hitting bridge method is not blocked by default

- **File:** `core/api.py:461-463`, `core/api.py:507-512`, `core/api.py:420-427` (the wrapper that consults it)
- **Confirmed:** yes (the interception-table probe over every public `AppApi` method)
- **Description:** `_offline_bridge_result` enumerates 27 method names and ends with `return False, None` — the wrapper then calls the **real** method. The list is therefore an *allow-list of special cases*, not a *deny-list of network calls*: any bridge method that is not explicitly named runs normally while offline. Today the enumeration happens to cover every network-hitting method I could find (the ones that are not named are guarded internally — `search` forces `source='local'` at `core/api.py:2085-2086`, `get_lyrics` raises in `services/lyrics_lookup.py:73-75`), so nothing escapes today; but the safety property the scenario asks about ("is a new bridge method blocked by default?") is **no**.
- **Cause:** the interception was implemented as "handle the methods that need a special offline answer" rather than "deny every method that can reach the network".
- **Trigger conditions:** a new bridge method that reaches a provider (or the proxy) is added without touching `_offline_bridge_result`.
- **User impact:** the new method silently ignores offline mode — it hits the network while the user believes the app is offline. The failure mode is invisible: there is no log line, no error, and the "silent" failure mode this codebase explicitly warns about (`AGENTS.md`).
- **Evidence:**
  ```python
  # core/api.py:461-463
      def _offline_bridge_result(self, method, args, kwargs):
          if not is_offline(getattr(self._core, 'settings', None)):
              return False, None
  # core/api.py:507-512  (the whole deny-list)
          if method in ('download_track', 'download_all_favorites', 'import_external_playlist',
                        'resume_download', 'retry_failed_downloads'):
              data = describe_error('offline', method)
              self._emit('operation_error', dict(data, method=method))
              return True, {'success': False, 'error': data['message'], 'code': 'offline', 'count': 0}
          return False, None          # <-- default ALLOW
  ```
- **Reproduction / verification:** the probe lists 27 intercepted methods and ~120 not intercepted; every not-intercepted method was checked by hand against the network-capable list in trace table 2 — none of them reaches the network while offline *today*.
- **Suggested fix:** invert the policy — keep an explicit allow-list of the methods that must keep working offline (`get_settings`, `get_library`, the queue ops, `play_track` for a local file, `recover_stream`, `search` local, `get_lyrics` local, the download-manager reads) and deny everything else by default, or mark the network-capable methods in a registry that new methods must opt into.
- **Fix side effects:** a full inversion requires every local method to be enumerated (~120 names today) and is easy to get wrong in the other direction (blocking something that must work offline); a registry/decorator is more code but keeps the default safe.
- **Discovered by:** A

#### F-WX-09-6  [P3] — Switching offline mode **off** does not resume the downloads that the switch paused

- **File:** `core/api.py:4132-4161` (the `enabled` branch only), `core/downloader.py:115-128` (`resume_download`), `ui/web_new_v2/js/downloads-view.js:170-171` (the manual "Продолжить все" button)
- **Confirmed:** yes (probe F)
- **Description:** `set_offline_mode(True)` calls `downloader.pause_download()`, which sets the affected rows to `status='paused'` and `resume_on_restart=0` (`core/downloader.py:101-113`). `set_offline_mode(False)` only writes the flag — it never calls `resume_download()`, and `resume_download` is refused while offline (`core/api.py:507-511`) and blocked at the downloader level (`core/downloader.py:116-117`).
- **Cause:** the switch is asymmetric: entering offline mode actively pauses the queue, leaving offline mode does not undo it.
- **Trigger conditions:** switch offline mode on (with downloads queued), then switch it off again.
- **User impact:** the downloads stay on hold until the user presses "Продолжить все" in the downloads view. Low severity — the UI does provide that button, and the rows keep their partial `.part` files, so nothing is lost — but the user has to notice and press it, and the app's own note ("Загрузки остаются на паузе", `index.html:461`) is only about the offline state, not about the fact that the queue stays paused after leaving it.
- **Evidence:**
  ```python
  # core/api.py:4139-4158  (the `if enabled:` branch)
          if enabled:
              downloader = getattr(self._core, 'downloader', None)
              if downloader and hasattr(downloader, 'pause_download'):
                  downloader.pause_download()
              ...
          state = {'enabled': enabled, 'active_available': active_available}
  ```
- **Reproduction / verification:** probe F — a stub downloader recording the calls across `set_offline_mode(True)` → `set_offline_mode(False)`: `downloader calls across the toggle: ['pause']` (no `resume`).
- **Suggested fix:** on the transition online, call `downloader.resume_download()` for the rows that were paused by the offline switch (or leave the rows in a state that the download manager resumes when the flag is cleared).
- **Fix side effects:** an automatic resume would restart transfers the user may have deliberately paused earlier; the rows paused *before* offline mode was entered must be distinguished (a `resume_on_restart`-style marker or a dedicated status would be needed).
- **Discovered by:** A

---

### 3. Clean areas

- **The settings key match is exact.** `set_offline_mode` writes `('network','offline_mode')` (`core/api.py:4135`) and `is_offline` reads `settings.get('network','offline_mode',False)` (`core/offline.py:13`); the value is persisted as the settings row `network.offline_mode` (`core/settings.py:456-459` → `core/database.py:2049-2082`) and reloaded into `self._cache['network']['offline_mode']` (`core/settings.py:315-334`). `is_offline` is the single canonical reader used by the proxy, the downloader, `core/app.py` and `core/api.py`; the one duplicate (`core/playback_recovery.py:113`) uses the same category/key. The toggle is **not** a no-op at the settings layer (probe G: `is_offline` → `True`).
- **The in-flight download is stopped correctly.** The switch pauses the queued rows (`core/downloader.py:101-113`); the running worker aborts at its next checkpoint (`core/downloader.py:718-728`); `_abort_cancelled` (`core/downloader.py:587-599`) re-marks the row `paused` and emits **no** `download_failed`; the partial file stays as `*.part` and is **not** promoted to a finished download — `_downloaded_file_defect` explicitly rejects `.part` and sub-4 KB files (`core/downloader.py:37-52`, `core/downloader.py:801-814`). The partial is reusable for the resume (`core/download_transfer.py:41-125`).
- **The in-flight playback degrades gracefully.** The open upstream response is aborted before the next chunk (`core/proxy.py:1195-1196`, `1229-1230`), the frontend's `handleStreamError` calls `recover_stream`, the offline branch of which returns the **local** file (`core/api.py:4168-4173`), and `normalizeAudioSourceUrl` (`ui/web_new_v2/js/player.js:97-103`) turns that Windows path into `http://127.0.0.1:<port>/api/stream?url=…` — the same form the engine uses — so playback resumes at the saved position. When the track is not downloaded the user gets a clear message ("Трек недоступен офлайн", `core/api.py:4173`; `ui/web_new_v2/js/player.js:477`).
- **The next track falls back to the local file.** The switch prunes the queue to the available tracks, `_on_track_changed` re-checks availability on every change (`core/api.py:1201-1206`) and the engine builds a proxy URL for the local file (`audio/engine.py:106-117`).
- **The library never lists a missing file.** `offline_library` → `available_tracks` → `_local_file` requires `os.path.isfile(path)` and a non-zero size (`core/offline.py:17-25`), so a row whose file was deleted is dropped rather than offered. The same filter guards `get_library`, `get_downloaded_tracks`, `get_favorites`, `get_playlist_tracks(local)` and `get_smart_playlist_tracks` (`core/api.py:2269-2280, 2563-2564, 2729-2730, 4216`).
- **The proxy's `/api/stream` endpoint is properly gated.** `core/proxy.py:814-816` returns 503 before any DNS lookup or resolver call, and local files are still served (`core/proxy.py:780-793, 795-812`); this is pinned by `tests/test_offline_proxy.py`.
- **Search does not touch the network while offline.** `core/api.py:2085-2086` forces `source='local'`, the local results are filtered through `available_tracks` (`core/api.py:2149-2150`) and the `search_results` payload carries `offline: true` (`core/api.py:2116`) so the UI can render its offline note (`ui/web_new_v2/js/search.js:333, 1008-1013`). Pinned by `tests/test_offline_mode.py:52-63`.
- **Lyrics do not touch the network while offline.** `services/lyrics_lookup.py:73-75` raises before the request; the embedded/local cache path still works (`tests/test_offline_mode.py:78-88`).
- **Startup respects the persisted flag.** The yt-dlp self-update, the Zapret auto-update and the Zapret autostart are skipped while offline (`core/app.py:150-155, 240-241`); `DownloadManager.__init__` pauses the pending downloads (`core/downloader.py:87-88`); `re_resolve_stream_url_async` short-circuits to the local file or an error (`core/app.py:296-304`).
- **The blocked-method list does not break anything that must work offline** — `get_settings`, `get_library`, `get_offline_library`, the queue operations, `play_track` for a local file and `recover_stream` all run normally while offline (trace table 2).
- **The existing offline test suite passes unchanged (49 tests)** — the findings above are gaps in that coverage, not regressions.

### 4. Coverage gaps

- The real app was not launched (forbidden by the ground rules). All UI behaviour was derived from the code and from `tests/test_feature_controls_ui.py` (a Node/vm harness), not from clicking the UI; the "no offline toggle in the UI" conclusion is a static-analysis result (repo-wide grep over `ui/`, `core/`, `tests/`, `services/`, `utils/`, `audio/`), not an observed one.
- No real provider was contacted, so the "network request while offline" of F‑1 was proven with a stubbed `_safe_urlopen` (the call is made; the upstream was not actually hit) and with the `RecordingEngine` of `tests/test_proxy_harness.py` for the re-resolution.
- The exact user-visible outcome of F‑1 depends on the browser's retry behaviour (how many times WebView2 re-requests the `/` URL); only the first upstream request was observed.
- `import_external_playlist` is refused wholesale while offline (`core/api.py:507-511`); whether it could be done from a local file offline was not assessed — it is a product decision, not a defect.
- The `get_album_tracks` offline branch resolves the album by **title** (`core/api.py:479-483` → `db.get_album_tracks(title, artist)`); the quality of that title-based match was not assessed (the DB method itself was not read beyond its signature).
- `core/resolver.py` was read only for the offline-relevant paths (`get_cached_url`, `resolve`); the "unavailable" negative cache (`_is_failed`, `_FAIL_TTL`) was not analysed for offline interactions.
- The `services/smart_playlists.py::available_only` path was verified to use a SQL pre-filter plus `available_tracks` on DB rows (so it is unaffected by F‑2), but the SQL pre-filter was not benchmarked.
- `core/tray.py` menu items were not reviewed for offline-specific actions (no `offline` hits).
- The proxy's `do_HEAD` path (`core/proxy.py:636`) was only skimmed; the offline gate was verified for `do_GET` only.
