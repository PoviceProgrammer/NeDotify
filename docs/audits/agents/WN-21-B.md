## AREA WN-21 — Yandex / VK / Spotify / Last.fm / iTunes providers — ROLE B

### 1. Scope reviewed

**Files opened in full (physical 1-based lines):**

| File | Lines read |
|---|---|
| `services/base_service.py` | 1–329 (whole file) |
| `services/yandex_service.py` | 1–288 (whole file) |
| `services/vk_service.py` | 1–98 (whole file) |
| `services/spotify_service.py` | 1–244 (whole file) |
| `services/lastfm_service.py` | 1–614 (whole file) |
| `services/itunes_gateway.py` | 1–93 (whole file) |

**Callees traced into other areas (read only where the callee is the cause of a WN-21 symptom):**

- `core/api.py` — L61 (`PROVIDER_SEARCH_TIMEOUT=6.0`), L67 (`BRIDGE_SYNC_BUDGET=6.0`), L240–253 (`_SECRET_SETTING_KEYS` / `_mask_secrets`), L1216, L1853–1900 (`get_setting`/`set_setting`), L1902–1954 (`yandex_device_auth`), L2077–2232 (`search` fan-out), L2362–2400 (`import_external_playlist`), L2545–2609 (`get_playlist_tracks`)
- `core/app.py` — L91–586 (whole file; provider wiring L129–134, lazy `yandex` L200–211, `re_resolve_stream_url_async` L296–506, `cleanup` L508–586)
- `core/database.py` — L300–324 (`settings` table, `UNIQUE(source, source_id)`), L2036–2100 (`set_setting`/`set_settings_batch`)
- `core/settings.py` — L230–288 (defaults, `auth` category), L395–544 (`get`/`set`/`flush`/`get_category`)
- `core/proxy.py` — L485–520 (log masking), L985–1010 (Yandex `Authorization` injection)
- `core/playback_recovery.py` — L110–150
- `audio/engine.py` — L475–508 (Yandex resolution branch)
- `services/catalog_service.py` — L1–230 (second consumer of `ITunesGateway`)
- `services/recommendation_service.py` — L38–58, L326–365, L566/624/674/866/899
- `services/playlist_import_service.py` — L1–345 (whole file)
- `services/track_resolver.py` — L1–476 (whole file)
- `services/zapret_service.py` — L60–75
- `tools/bench/bench_child.py` — L115–214
- `ui/web_new_v2/index.html` — L379, L1861, L2104, L2235; `ui/web_new_v2/js/search.js` L49, L178; `ui/web_new_v2/js/onboarding.js` L41; `ui/web_new_v2/js/library.js` L158–202
- **Tests read:** `tests/test_itunes_request_queue.py` (1–69), `tests/test_provider_performance.py` (1–102), `tests/test_provider_loading.py` (1–209), `tests/test_lyrics_netease.py` (1–235), `tests/test_proxy_url_validation.py` (95–160)

**Not opened:** `android/**` (out of scope). `services/lyrics_service.py` / `lyrics_lookup.py` (WN-22, not this area).

**Baseline:** `pytest tests/test_itunes_request_queue.py tests/test_provider_performance.py tests/test_provider_loading.py tests/test_lyrics_netease.py tests/test_proxy_url_validation.py -q` → **91 passed** in 4.43 s.

---

### 2. Findings

#### F-WN-21-1  [P1] — The "Spotify" provider is the iTunes Search API; the UI brands it Spotify and advertises a Spotify playlist import the backend does not implement

- **File:** `services/spotify_service.py:31,63,179,221`; `ui/web_new_v2/js/search.js:49,178`; `ui/web_new_v2/index.html:379,1861,2104`; `ui/web_new_v2/js/onboarding.js:41`; `services/playlist_import_service.py:50-58`; `services/zapret_service.py:71`
- **Confirmed:** yes
- **Description:** `SpotifyService` never contacts Spotify. Every outbound URL targets `itunes.apple.com`. The returned objects carry Apple Music identities (`trackId`, `collectionId`, `trackViewUrl` → `https://music.apple.com/...`), yet the UI renders the Spotify logo in Spotify green (`#1DB954`), labels the filter "Источник поиска: Spotify", shows "Поиск в Spotify...", states "Поддерживаются Яндекс Музыка, YouTube и Spotify" and "Ссылка на плейлист (YouTube, Spotify)", and the onboarding accepts `open.spotify.com` as a valid host. The playlist import path, however, only resolves YouTube / SoundCloud / M3U / M3U8 / JSON / text, so a pasted Spotify playlist link fails with a formats list instead of a clear "not supported".
- **Cause:** A provider was renamed/branded without changing the implementation, and the import-service capability matrix was never reconciled with the UI copy.
- **Trigger conditions:** Any search from the "Spotify" chip; any Spotify playlist link pasted into the import modal.
- **User impact:** The user believes they are searching Spotify and sees Spotify branding, but gets Apple Music catalogue data with Apple links; two different recordings of the same song by the same artist are indistinguishable. A Spotify playlist import — explicitly advertised in three places — always fails.
- **Evidence:**
  ```python
  # services/spotify_service.py:31
  url = f"https://itunes.apple.com/search?term={encoded_query}&entity=song&limit={limit}"
  # services/spotify_service.py:43-51
  f"spotify_{item.get('trackId', idx)}", ... "spotify",
  f"ytsearch1: {artist} - {title}",
  item.get("trackViewUrl", f"https://open.spotify.com/search/{encoded_query}")
  ```
  ```python
  # services/playlist_import_service.py:50-58
  if "youtube.com" in target or "youtu.be" in target:  return self._resolve_youtube(target)
  if "soundcloud.com" in target:                       return self._resolve_soundcloud(target)
  raise UnsupportedPlaylistService("Поддерживается импорт плейлистов YouTube, M3U/M3U8, JSON и текстовых списков")
  ```
  The codebase already knows: `services/zapret_service.py:71` — `# SpotifyService actually searches the iTunes metadata catalogue.`
- **Reproduction / verification:**
  ```
  $ & ".venv_win\Scripts\python.exe" -c "import re;t=open('services/spotify_service.py',encoding='utf-8').read();print(sorted(set(re.findall(r'https?://([a-z0-9.\-]+)',t))))"
  ['itunes.apple.com', 'open.spotify.com']
  ```
  `open.spotify.com` occurs only as a *link string* (the `trackViewUrl` fallback); it is never requested. Grep for `requests.get`/`session.get` targets in the file shows only `itunes.apple.com`.
- **Suggested fix:** Rename the provider to `ITunesService` and rebrand the UI (icon, colour, "Источник поиска"), or implement a real Spotify provider behind the Spotify brand; remove the "Spotify" claim from the import modal / onboarding copy, or add Spotify playlist resolution to `PlaylistImportService.resolve`.
- **Fix side effects:** Renaming touches `core/api.py:2100,2217,2573`, `core/app.py:131`, `core/downloader.py:27` (`'spotify'`, `'spotify_album'`), `core/database.py` `source` values (persisted rows!), `core/playback_recovery.py:117`, `core/session.py`, `audio/engine.py`, and the UI. Renaming the DB `source` value needs a migration; keeping `'spotify'` as the stored value while rebranding the UI is the cheaper option.
- **Discovered by:** B

#### F-WN-21-2  [P2] — The iTunes identity is discarded: the library key is a YouTube search string, so the catalogue identity is lossy and can collide

- **File:** `services/spotify_service.py:43,50`; `core/app.py:311-321`; `core/database.py:324`
- **Confirmed:** yes
- **Description:** The iTunes `trackId` is used only as a DOM id (`f"spotify_{item.get('trackId', idx)}"`), and the `source_id` stored in the library is `"ytsearch1: {artist} - {title}"`. The tracks table is keyed `UNIQUE(source, source_id)`, so the identity of a "spotify" track in the library is a free-text YouTube search query. The app can never re-resolve the exact iTunes recording it found, and two different iTunes tracks with the same artist/title collapse into one row.
- **Cause:** The provider produces a "source" that is not a source: it is a cross-catalogue search string in the YouTube provider's format.
- **Trigger conditions:** Saving any track returned by the Spotify/iTunes provider; two Apple tracks with the same artist and title but different releases/recordings.
- **User impact:** The library shows one entry where there should be two; playback re-resolves through YouTube by title, so it can pick a different recording than the one the user saw. The `spotify_<iTunesId>` id is regenerated per search and is not stable.
- **Evidence:**
  ```python
  # services/spotify_service.py:50  source_id = a YouTube search string
  f"ytsearch1: {artist} - {title}",
  # core/app.py:311-321  "spotify" is resolved through the YouTube provider
  if source in ("youtube", "spotify"):
      ... url = sid_str  # "ytsearch1: ..."
      service = self.youtube
  # core/database.py:324
  UNIQUE(source, source_id)
  ```
- **Reproduction / verification:** Search for a title with two Apple releases; both results carry `source_id == "ytsearch1: <artist> - <title>"`; `db.ensure_track_exists` (called from `core/api.py:2393`) collapses them via `UNIQUE(source, source_id)`.
- **Suggested fix:** Keep the real iTunes id (`source_id = str(item['trackId'])`, `source = 'itunes'`) and resolve playback through the iTunes catalogue; keep the `ytsearch1:` string in a separate `yt_hint` field.
- **Fix side effects:** The `source` value is persisted in `tracks`, `stream_cache` and the resolver DB; changing it needs a migration and touches `core/app.py:311`, `core/playback_recovery.py:117`, `core/downloader.py:27`, `audio/engine.py`.
- **Discovered by:** B

#### F-WN-21-3  [P1] — The global iTunes rate limiter (3.5 s slot) is slower than the bridge's 6 s per-provider budget, so a second concurrent catalogue call is silently dropped

- **File:** `services/itunes_gateway.py:21,26,50-63`; `core/api.py:61,2197-2204,2217-2218`; `services/catalog_service.py:91,136,196`
- **Confirmed:** yes
- **Description:** `ITunesGateway` serialises every iTunes request on a global 3.5 s slot with a rolling 18/min cap and an 8 s internal deadline. The bridge allows each provider only `PROVIDER_SEARCH_TIMEOUT = 6.0 s`. Slot wait (3.5 s) + HTTP (up to 3.5–4.0 s) therefore exceeds 6 s, so the second and later concurrent catalogue calls are cut off by the bridge timer and the provider renders as "no results" with no error. `CatalogService` (artist profile, album details) uses the same global gateway, so a catalogue lookup and a search compete for the same slots.
- **Cause:** Two independent budgets (a provider-side global throttle and a bridge-side per-provider deadline) were never reconciled; the gateway's default deadline (8 s) is also longer than the bridge budget (6 s).
- **Trigger conditions:** Two or more distinct iTunes URLs in flight within 3.5 s — e.g. the search tab plus an artist profile, or a track search plus an album lookup, or the album tab (`entity=album`) plus the track tab.
- **User impact:** The Spotify/iTunes section of the search results is silently empty, and the artist/album panel times out. Nothing in the UI distinguishes "no results" from "the provider ran out of time".
- **Evidence:**
  ```python
  # services/itunes_gateway.py:21-22
  INTERVAL = 3.5
  PER_MINUTE = 18
  # services/itunes_gateway.py:26
  deadline = deadline if deadline is not None else time.monotonic() + 8.0
  # core/api.py:61
  PROVIDER_SEARCH_TIMEOUT = 6.0
  # core/api.py:2199-2204
  def _on_timeout(): ... logger.warning("%s search timed out after %.1fs", name, _timeout); _finish([])
  ```
  Measured (5 concurrent distinct URLs, fake session, real gateway):
  ```
  5 concurrent DISTINCT urls -> total 8.02s, per-call: ['0.05', '3.56', '7.09', '8.02', '8.02']
  errors: {2: "CatalogueUnavailable(...)", 3: "CatalogueUnavailable(...)"}
  ```
  The 3rd call needs 7.09 s > 6.0 s → the bridge timer fires first. Worst case = `INTERVAL(3.5) + timeout(3.5) = 7.0 s > 6.0 s`.
- **Reproduction / verification:** `/tmp/opencode/wn21_probe.py` (5 threads → `ITunesGateway.get` with distinct URLs). Deterministic: `ITunesGateway.INTERVAL + 3.5 = 7.0 s > PROVIDER_SEARCH_TIMEOUT = 6.0 s`.
- **Suggested fix:** Give `SpotifyService` a deadline of `min(bridge budget, gateway deadline)` — e.g. pass `deadline=time.monotonic()+5.0` from `SpotifyService.search`; raise the per-provider bridge budget for the iTunes-backed provider; and/or make the gateway's slot interval adaptive to the caller's deadline (skip the wait and fail fast when `deadline - now < INTERVAL`).
- **Fix side effects:** Failing fast turns "slow empty result" into "fast empty result" — the result is the same, but the error becomes visible; a shared-slot scheduler per URL family would reduce the number of waits.
- **Discovered by:** B

#### F-WN-21-4  [P2] — The VK extractor disables TLS certificate verification

- **File:** `services/vk_service.py:59-67` (flag at `:63`)
- **Confirmed:** yes
- **Description:** `VKService.get_stream_url` builds a yt-dlp option set with `'nocheckcertificate': True`, which makes yt-dlp skip certificate-chain and hostname validation for the entire extraction (the VK page *and* the media CDN that serves the audio). No other WN-21 provider does this.
- **Cause:** The flag was added to work around a TLS-interception problem; it was never scoped to a single host.
- **Trigger conditions:** Any successful `VKService.get_stream_url` call. (See F-WN-21-5: today the provider is never invoked, so the exposure is latent, not live.)
- **User impact:** If the provider is ever wired up, any network position that can intercept TLS (rogue Wi-Fi, a transparent proxy, a compromised router) can substitute the audio stream — the app will play or download attacker-supplied bytes as a "track". The same pattern also exists in `services/youtube_service.py:308` and `services/soundcloud_service.py:247,276` (areas WN-19 / WN-20).
- **Evidence:**
  ```python
  # services/vk_service.py:59-67
  ydl_opts = {
      'quiet': True, 'no_warnings': True,
      'format': 'bestaudio/best',
      'nocheckcertificate': True,      # <-- TLS verification off
      'socket_timeout': 10, 'retries': 1,
      'source_address': '0.0.0.0'
  }
  ```
- **Reproduction / verification:**
  ```
  $ rg -n "nocheckcertificate|verify=False|CERT_NONE" --glob '*.py'
  utils/cache_manager.py:352, services/soundcloud_service.py:247,276, services/vk_service.py:63, services/youtube_service.py:308
  ```
  `requests` is never used with `verify=False` anywhere in the repo.
- **Suggested fix:** Remove `nocheckcertificate` and, if a specific host genuinely needs a custom CA, pass it explicitly (`--client-certificate`/`ssl_context`) rather than disabling verification.
- **Fix side effects:** On a network with a TLS-intercepting middlebox the extraction may start failing — which is the correct behaviour, but it needs a user-visible error path (the current `error_callback` string is `f"VK Music ошибка: {str(e)}"`).
- **Discovered by:** B

#### F-WN-21-5  [P2] — `VKService` duplicates provider plumbing instead of extending `BaseMusicService`, and is instantiated at startup but never called

- **File:** `services/vk_service.py:16,23-24,30-48,50-88`; `core/app.py:130`; `core/api.py:2098,1216`; `core/session.py:85`; `core/downloader.py:24-27`
- **Confirmed:** yes
- **Description:** `VKService` is the only WN-21 provider that is not a `BaseMusicService` subclass. As a result it has no shared thread pool (`threading.Thread(..., daemon=True)` per call, unbounded thread creation), no stream/search cache (every `get_stream_url` re-runs a full yt-dlp extraction), no `submit()`/`_join_request()` single-flight (three simultaneous play+queue requests produce three extractions instead of one), and no `auth.proxy_url` support (every other provider honours it). It is also **dead**: `core/app.py:130` `self.vk = VKService(self.settings)` is the only reference to the service anywhere in the tree.
- **Cause:** The provider was written against an earlier interface, was then disabled in the UI (`core/api.py:2098` `DISABLED_UI_PROVIDERS = {"yandex", "vk", "vkontakte", "zeno"}`) and in the downloader (`core/downloader.py:24-27` `_SUPPORTED_SOURCES` excludes `'vk'`), but the eager instantiation and the "vk is a live source" references were left behind.
- **Trigger conditions:** Every app start (the service is constructed eagerly, importing `yt_dlp` at module import). Any attempt to use VK: the UI filter is disabled, `core/api.py:1216` and `core/session.py:85` still treat `'vk'` as a proxy-able/restorable source, and `core/app.py:330-336` answers `"Unsupported source: vk"`.
- **User impact:** Startup cost and memory for a provider that can never answer; a session that contains a `'vk'` track is restored by `core/session.py:85` but can never be resolved or downloaded; a user pasting a VK link gets "Unsupported source" rather than a clear "VK is not supported".
- **Evidence:**
  ```python
  # services/vk_service.py:16        — not a BaseMusicService
  class VKService:
  # services/vk_service.py:48 / :88  — raw thread per call, no pool
  threading.Thread(target=_search, daemon=True).start()
  threading.Thread(target=_extract, daemon=True).start()
  # core/app.py:130
  self.vk = VKService(self.settings)
  ```
  Whole-tree scan for a use of the instance:
  ```
  $ rg -n "self\.vk|core\.vk|\.vk\." --glob '*.py'
  .\core\app.py 130 self.vk = VKService(self.settings)
  ```
  — one hit, the assignment itself.
- **Reproduction / verification:** The scan above. `core/app.py:571-586` (`cleanup`) shuts down the pools of `youtube`, `_soundcloud`, `_yandex`, `spotify` — VK has no pool, confirming it never used the base machinery.
- **Suggested fix:** Either delete `VKService` and the `self.vk` wiring (and drop `'vk'` from `core/api.py:1216` / `core/session.py:85`), or make it a real `BaseMusicService` subclass with a bounded pool, the shared stream cache, `auth.proxy_url` support and single-flight `_join_request`.
- **Fix side effects:** Deleting it removes the "VK is a source" illusion from the session-restore path; users with old `'vk'` rows in `tracks` would need those rows filtered.
- **Discovered by:** B

#### F-WN-21-6  [P2] — Last.fm API keys live in an append-only process-global: a key removed in the UI keeps being used, and the class-attribute/module-global split makes the bench injection a no-op

- **File:** `services/lastfm_service.py:23,103,105-113,207-208,216-225,320-324`; `tools/bench/bench_child.py:144,150,207`
- **Confirmed:** yes
- **Description:** `API_KEYS` is a **module-level global** list. `LastFMService.__init__` only ever *appends* to it (`if key not in API_KEYS: API_KEYS.append(key)`) and never reconciles it with the current settings. Every reader (`available`, `_get_next_api_key`) uses the global. The per-instance `_bad_keys` set is therefore incoherent with the global key list: a key disabled on one instance is still used by another. Because the key list is global but the "bad" set is per instance, the class also has no `API_KEYS` attribute — `tools/bench/bench_child.py:150` sets `LastFMService.API_KEYS = ["bench-dummy-key"]`, which creates a *new class attribute* that the production code never reads.
- **Cause:** A per-instance concern (which keys are configured, which are bad) was modelled as a process-wide mutable list.
- **Trigger conditions:** The user removes or changes `auth.lastfm_api_key` in Settings while the app is running. A second `LastFMService` is constructed later (e.g. by a reset, a test, or the bench).
- **User impact:** **Revoking a Last.fm key does not take effect until the app is restarted** — the old key keeps being transmitted to `ws.audioscrobbler.com` on every request. A key that the provider has rejected (and that was disabled) is still used by other instances.
- **Evidence:**
  ```python
  # services/lastfm_service.py:23
  API_KEYS: List[str] = []
  # services/lastfm_service.py:105-107
  for key in self._resolve_api_keys():
      if key not in API_KEYS:
          API_KEYS.append(key)          # append-only; never reconciled, never cleared
  # services/lastfm_service.py:207-208 / 216-225
  return any(k not in self._bad_keys for k in API_KEYS)      # reads the GLOBAL
  valid_keys = [k for k in API_KEYS if k not in self._bad_keys]
  ```
  Reproduction:
  ```
  after instance 1 (settings key 'KEY-AAA') -> module API_KEYS = ['KEY-AAA']
  after instance 2 (settings key '')       -> module API_KEYS = ['KEY-AAA']
  svc2.available (still uses the old key)  -> True
  svc2._get_next_api_key()                 -> 'KEY-AAA'
  svc1 sees KEY-AAA as bad  -> False
  svc2 sees KEY-AAA as bad  -> True   (global key list, per-instance bad set)
  ```
  And the bench injection is a no-op:
  ```
  has class attr API_KEYS? False
  LastFMService.API_KEYS = ['bench-dummy-key']  -> module global still []
  available? False
  ```
  (`bench_child.py` papers over this by force-replacing the `available` property at `:158-162`.)
- **Reproduction / verification:** `/tmp/opencode/wn21_repro.py` (section 2 and 3) — quoted output above.
- **Suggested fix:** Make the key list an instance attribute (`self._api_keys`), keep `_bad_keys` next to it, and re-resolve it whenever the settings change (or read it per request, as `_resolve_api_keys()` already can). Make the bench patch the instance attribute.
- **Fix side effects:** `services/recommendation_service.py:327` (`_lastfm_enabled`) and `tests/test_recommendation_signals.py:23` / `tests/test_recommendation_service.py:23` monkeypatch `lastfm._resolve_api_keys`, so the per-instance version keeps working with them; `tools/bench/bench_child.py:150` must be updated.
- **Discovered by:** B

#### F-WN-21-7  [P2] — `normalize_proxy_url` writes the proxy credentials (`user:pass@`) into the application log

- **File:** `services/base_service.py:44-62` (log at `:57-61`); log sink `main.py:104-109` → `~/.nedotify/logs/app.log`
- **Confirmed:** yes
- **Description:** When `auth.proxy_url` cannot be parsed as a proxy URL, the raw value is logged with `%r`. A proxy URL normally embeds the credentials (`http://user:pass@host:port`), so the password is written verbatim into a plaintext log file. The `auth` category is already treated as secret-bearing on the bridge side (`core/api.py:240-253` masks `yandex_token` and `oauth_client_secret`), so the intent to keep credentials out of readable places exists — the log path was missed.
- **Cause:** The rejection log was written for developer diagnosis without redacting the userinfo component.
- **Trigger conditions:** A user saves a proxy value that lacks a scheme (`user:pass@host:port`) or a host (`http://user:pass@`). A well-formed `http://user:pass@host:port` is *accepted* and therefore not logged.
- **User impact:** The proxy password lands in `~/.nedotify/logs/app.log`, a file the user (or a log sync, a bug report, a shared support bundle) can read. Rotating the proxy password becomes necessary after any support round-trip.
- **Evidence:**
  ```python
  # services/base_service.py:57-61
  logger.warning(
      "Ignoring unusable auth.proxy_url %r: expected a full URL such as "
      "'http://127.0.0.1:1080'. Falling back to a direct connection.",
      raw,                        # <-- may contain user:pass@
  )
  ```
  Reproduction:
  ```
  WARNING:services.base_service:Ignoring unusable auth.proxy_url 'alice:hunter2@10.0.0.9:1080': expected a full URL such as 'http://127.0.0.1:1080'. Falling back to a direct connection.
  ```
  (`urlsplit("user:pass@host:1080")` yields `scheme='user'`, `hostname=None` → rejected → logged. `urlsplit("http://user:pass@")` yields `scheme='http'`, `hostname=None` → rejected → logged.)
- **Reproduction / verification:** `/tmp/opencode/wn21_repro.py` (section 1) — quoted above. Note `core/proxy.py:489` already masks `k=`/`auth_token=` query parameters, so the codebase has a precedent for redacting.
- **Suggested fix:** Log a redacted form — scheme + host + port, userinfo replaced with `***:***@` — e.g. `raw.split('@')[-1]` or `urllib.parse.urlsplit(raw)._replace(netloc=...).geturl()`.
- **Fix side effects:** None functionally; the log line loses the exact offending value, so the user must be told *which part* was wrong (the message already says "expected a full URL").
- **Discovered by:** B

#### F-WN-21-8  [P2] — `LastFMService` opens a second lock named `_cache_lock`, shadowing the base `RLock` (violates the "join the class's existing lock" contract)

- **File:** `services/lastfm_service.py:116`; `services/base_service.py:125,140-161,186-276`
- **Confirmed:** yes
- **Description:** `BaseMusicService` guards the shared `_search_cache` / `_stream_cache` with the class-level `_cache_lock` (an `RLock`). `LastFMService.__init__` sets `self._cache_lock = threading.Lock()` — a **plain, non-reentrant Lock** bound as an *instance* attribute with the *same name*. Inside `LastFMService` there are therefore two different locks reachable under the same name: `self._cache_lock` (the plain Lock, guarding the Last.fm dict) and `cls._cache_lock` (the base `RLock`, used by every inherited `get_search_cache` / `set_search_cache` / `get_from_cache` / `set_to_cache` call). The AGENTS.md / `WIN_AUDIT_CONTEXT.md` rule #2 explicitly says a new shared field must *join* the class's existing lock rather than open a second one.
- **Cause:** A local convenience lock was introduced for the Last.fm cache without noticing that the base class already owns a lock for the same "provider cache" concern, and without noticing the name shadowing.
- **Trigger conditions:** Any concurrent use of `LastFMService` together with any other provider. Today no code path takes both locks in opposite orders, so there is no deadlock; the hazard is latent.
- **User impact:** None observed today. The concrete risk: the two caches are mutated under two unrelated locks, so there is no ordering relationship between "the Last.fm dict" and "the shared provider cache"; a future edit that calls `self.get_search_cache()` while holding `self._cache_lock` (or the reverse) introduces a lock-order inversion, and because one of them is a plain `Lock` the failure mode would be a hard deadlock rather than the re-entrancy the `RLock` was chosen for.
- **Evidence:**
  ```python
  # services/base_service.py:125
  _cache_lock = threading.RLock()
  # services/lastfm_service.py:116
  self._cache_lock = threading.Lock()
  ```
  Verification:
  ```
  LastFMService._cache_lock class attr is base RLock -> True
  instance _cache_lock type differs from class attr  -> lock vs RLock
  ```
  `LastFMService._cache_lock` (class access) is the base `RLock`; `instance._cache_lock` is a different object.
- **Reproduction / verification:** The snippet above; `& ".venv_win\Scripts\python.exe" -c "..."` as quoted.
- **Suggested fix:** Use `self._cache_lock` (= the inherited `RLock`) for the Last.fm dict as well, or rename the local lock (`self._response_cache_lock`) so the two are not confusable. The inherited `RLock` is reentrant, so it satisfies the "join the existing lock" rule.
- **Fix side effects:** Using the shared `RLock` means the Last.fm dict and the shared search cache are serialised against each other; the critical sections are microseconds, so the cost is negligible (measured worst-case lock acquisition delay during gateway polling: 0.0038 s over 1.59 M probes).
- **Discovered by:** B

#### F-WN-21-9  [P2] — Last.fm and the recommendation service share one 8-worker pool with no host-level circuit breaker, so an unreachable last.fm head-of-line blocks the whole recommendation feed

- **File:** `services/lastfm_service.py:166-178,320-354,389,424,447,485,520,550,583,612`; `services/recommendation_service.py:38,53,566,624,674,866,899`; `services/base_service.py:124,163-172`
- **Confirmed:** yes
- **Description:** `LastFMService` and `RecommendationService` do **not** define their own `_executor`, so both resolve to the single class-level `BaseMusicService._executor` (`_SharedExecutor(max_workers=8)`). Last.fm work is submitted to that pool and can block for the full 5 s HTTP timeout (plus the token-bucket wait). The only resilience mechanism is per-*key* disabling (`_mark_bad_key`), which does nothing when the host itself is unreachable or the key is valid but the service is down. There is no host-level circuit breaker, no failure counter and no backoff.
- **Cause:** The "disable the bad key" mechanism was treated as sufficient resilience; host-level failure was not modelled.
- **Trigger conditions:** last.fm is unreachable, rate-limiting, or returning 5xx while the key is still valid — exactly the conditions under which the recommendation feed is wanted.
- **User impact:** Up to 8 pool workers block for 5 s each on the Last.fm timeout; the recommendation / home-feed tasks (`recommendation_service.py:566,624,674,866,899`) queue behind them, so the home feed stalls for seconds even though the local library is fine. The user sees an empty or very late home feed.
- **Evidence:**
  ```
  RecommendationService defines own _executor? False
  LastFMService defines own _executor?       False
  RecommendationService._executor is BaseMusicService._executor -> True
  LastFMService._executor is BaseMusicService._executor -> True
  shared pool max_workers = 8
  ```
  ```python
  # services/lastfm_service.py:330 — the blocking call
  resp = self._get_session().get(self.BASE_URL, params=req_params, timeout=5.0)
  # services/lastfm_service.py:347-349 — 429/503 rotates the key but never backs off
  if resp.status_code in (429, 503):
      self.logger.warning(f'Last.fm HTTP {resp.status_code}. Rate limit backoff & rotating API key.')
      continue
  ```
  The log message says "backoff" but no backoff is performed — the only delay is the token bucket (2 tokens/s).
- **Reproduction / verification:** The identity checks above plus `services/lastfm_service.py:347-349` (the "backoff" is only a `continue`).
- **Suggested fix:** Give `LastFMService` its own small bounded pool (as YouTube/SoundCloud/Yandex/Spotify each do) and add a host-level circuit breaker (consecutive-failure counter → open for N seconds → serve the stale cache) so a dead last.fm cannot occupy the shared pool.
- **Fix side effects:** A dedicated pool adds up to 2–3 threads; the recommendation feed would keep its own workers free, at the cost of a few more threads. The breaker must be careful not to mask a transient blip — the stale-cache fallback already exists (`_get_stale_cache`) and should be preferred over an error.
- **Discovered by:** B

#### F-WN-21-10  [P2] — The Spotify/iTunes provider snapshots `auth.proxy_url` at construction into a module-global session, so a runtime proxy change never reaches it

- **File:** `services/spotify_service.py:18-24,97-108`; `core/app.py:131`; `core/api.py:1884-1896`
- **Confirmed:** yes
- **Description:** `SpotifyService.__init__` reads `auth.proxy_url` **once** and writes it into the **module-global** `requests.Session` (`_session.proxies`). `AppCore` constructs `SpotifyService` exactly once, at startup (`core/app.py:131`), and nothing recreates it when the setting changes — `set_setting` only writes the setting and emits `setting_changed` to JS (`core/api.py:1884-1896`); there is no Python-side listener. Every other provider re-reads the proxy per request (`services/youtube_service.py:236,359`; `services/soundcloud_service.py:165,256,285`). Because the session is module-global, the *last* constructed `SpotifyService` wins for the entire process.
- **Cause:** The proxy was applied as an instance-time side effect on a shared global object instead of per request.
- **Trigger conditions:** The user sets or changes the proxy in Settings after the app has started (a very common action: the proxy is usually configured *because* the network needs it).
- **User impact:** The iTunes/Spotify provider keeps using the old value — or direct egress — for the rest of the session. On a network where direct egress is blocked, the Spotify tab silently returns nothing while YouTube and SoundCloud work. A proxy that requires authentication is also not applied to iTunes, so those requests may fail or be blocked.
- **Evidence:**
  ```python
  # services/spotify_service.py:107-108
  proxy = normalize_proxy_url(self.settings.get("auth", "proxy_url", "")) if self.settings else ""
  _session.proxies = {"http": proxy, "https": proxy} if proxy else {}
  # services/spotify_service.py:18  — module-level, shared by every instance
  _session = requests.Session()
  ```
  ```python
  # services/youtube_service.py:236 (contrast: re-read per use)
  proxy = normalize_proxy_url(self.settings.get("auth", "proxy_url", ""))
  ```
  `tests/test_proxy_url_validation.py:135-151` pins the "assign, do not conditionally assign" behaviour on the shared session — i.e. the test *documents* the global mutation but nothing covers the runtime-change case.
- **Reproduction / verification:** Construct `AppCore` (or just `SpotifyService(settings)`), then change `settings['auth']['proxy_url']` and observe `services.spotify_service._session.proxies` is unchanged; no code path re-reads it (grep for `proxy_url` shows only `spotify_service.py:107` in that file).
- **Suggested fix:** Resolve the proxy per request (a small helper that sets `session.proxies` from the current settings right before the call), or rebuild the provider/session on `auth.proxy_url` change.
- **Fix side effects:** Re-resolving per request adds one settings read (a dict lookup under a lock) per iTunes call — negligible, and the gateway already batches requests. A settings-change hook must be added on the Python side (there is currently none).
- **Discovered by:** B

#### F-WN-21-11  [P3] — `SpotifyService.available` is always `False`: the base-class availability contract is not implemented

- **File:** `services/base_service.py:315-318`; `services/spotify_service.py` (whole file — no `available` member)
- **Confirmed:** yes
- **Description:** `BaseMusicService.available` is a documented hook ("Override in subclasses to report the availability status") that returns `False` by default. `SpotifyService` does not override it, so `SpotifyService().available` is permanently `False` even though the provider works. `YandexService` (`HAS_YANDEX`), `VKService` (`HAS_YTDLP`) and `LastFMService` (key check) all implement it.
- **Cause:** The provider was added without the availability hook.
- **Trigger conditions:** Any consumer that asks a provider whether it is usable. Today no caller does (the only `.available` read in the tree is inside `LastFMService` itself), so the defect is latent.
- **User impact:** None today. Any future caller, plugin, or UI affordance that consults `available` will treat the Spotify/iTunes provider as permanently unavailable, and a plugin author reading the base class will reasonably assume the hook is implemented.
- **Evidence:**
  ```python
  # services/base_service.py:315-318
  @property
  def available(self) -> bool:
      """Override in subclasses to report the availability status."""
      return False
  ```
  `services/spotify_service.py` contains no `available` definition (verified over the whole 244-line file).
- **Reproduction / verification:** `SpotifyService().available` → `False`; `BaseMusicService.available.fget` is the inherited stub.
- **Suggested fix:** Implement `available` on `SpotifyService` (e.g. `True`, or `True` when the iTunes endpoint is reachable) and on `ITunesGateway` (which also inherits the stub).
- **Fix side effects:** None — nothing currently reads it.
- **Discovered by:** B

#### F-WN-21-12  [P3] — Three independent cache layers over the same data with incoherent TTLs, and a single 300-entry budget shared by every provider

- **File:** `services/base_service.py:132-134,243-276`; `services/itunes_gateway.py:14,16-20,78-81`; `services/spotify_service.py:142,163`; `services/yandex_service.py:150`; `services/recommendation_service.py:338,355`
- **Confirmed:** yes
- **Description:** (a) `ITunesGateway` inherits `BaseMusicService` but uses only its `_cache_lock`; it keeps its **own** `_entries` cache (500 entries, 900 s for non-empty / 60 s for empty) **on top of** the shared `_search_cache` (300 entries, 300 s TTL) that `SpotifyService` also writes to. The effective TTL of a Spotify result is therefore 900 s, not the documented `_SEARCH_CACHE_TTL = 300`. (b) `_search_cache` is a **class attribute on `BaseMusicService`**, so every provider *and* the recommendation service share one 300-entry LRU; a Spotify search writes up to 20 track dicts per query and the recommendation service writes a whole candidate list under `recommendation:candidates:...` into the same budget.
- **Cause:** Each layer was added independently; the class-level (not per-provider) cache dict and the nested cache were never reconciled.
- **Trigger conditions:** Any search. The budget is shared, so a burst of Spotify searches evicts the recommendation candidates and vice versa.
- **User impact:** The effective cache is much smaller than "300 searches"; the recommendation feed is recomputed more often than the TTL suggests; the documented 300 s search TTL does not hold for the Spotify/iTunes provider.
- **Evidence:**
  ```python
  # services/base_service.py:132-134
  _search_cache: Dict[str, Dict[str, Any]] = {}
  _SEARCH_CACHE_TTL = 300
  _SEARCH_CACHE_MAX_SIZE = 300
  # services/itunes_gateway.py:78
  cls._entries[url] = (time.monotonic() + (900 if data['results'] else 60), data)
  ```
  Verified that every provider shares the same dict and the same lock:
  ```
  SpotifyService shares the same _search_cache dict -> True | same _cache_lock -> True
  LastFMService  shares the same _search_cache dict -> True | same _cache_lock -> True
  YandexService  shares the same _search_cache dict -> True | same _cache_lock -> True
  RecommendationService shares the same _search_cache dict -> True | same _cache_lock -> True
  CatalogService shares the same _search_cache dict -> True | same _cache_lock -> True
  ```
- **Reproduction / verification:** The snippet above (class-attribute identity check).
- **Suggested fix:** Make `_search_cache` per-provider (a `dict` on the instance) or namespace it per provider, and pick one authoritative TTL for the iTunes path (either drop `ITunesGateway._entries` in favour of `_search_cache`, or make `_search_cache` the short-lived "rendered result" layer over the gateway's longer-lived raw-response layer and document it).
- **Fix side effects:** Per-provider caches multiply the memory budget by the number of providers; `services/yandex_service.py::reset_client` iterates `self._search_cache` directly (documented in `base_service.py:235-237`) and would need updating.
- **Discovered by:** B

#### F-WN-21-13  [P3] — `auth.lastfm_api_key` is returned to the WebView in plaintext, and a rejected key's prefix is written to the log

- **File:** `core/api.py:240,243-253,2922-2935,2958-2959`; `services/lastfm_service.py:214`
- **Confirmed:** yes
- **Description:** `_SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}` is the allow-list of settings that are masked when the `auth` category is handed to JS. `lastfm_api_key` is written to the same `auth` category but is **not** in the list, so `AppApi.get_settings('auth')` and `get_settings_by_category('auth')` return it verbatim to the WebView. Separately, `_mark_bad_key` logs the first 6 characters of a rejected key.
- **Cause:** The secret allow-list was written for the Yandex/OAuth secrets and never extended when the Last.fm key was added to the same category.
- **Trigger conditions:** The user stores a Last.fm API key in Settings and then opens the auth settings panel (or any code path that reads the whole `auth` category).
- **User impact:** The Last.fm key is readable from the WebView (devtools, any injected script). The project already establishes that auth secrets must not leave the backend as values, so this is an inconsistency in a security control, not a new class of exposure.
- **Evidence:**
  ```python
  # core/api.py:240
  _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}
  # core/api.py:2922-2935
  def get_settings(self, category=None):
      if category: return _mask_secrets(category, self._core.settings.get_category(category))
  # services/lastfm_service.py:214
  self.logger.warning(f'Disabling invalid/blocked Last.fm API key: {api_key[:6]}...')
  ```
- **Reproduction / verification:** `AppApi.get_settings('auth')` with `settings['auth']['lastfm_api_key'] = 'abc123...'` returns the value unchanged, because `_mask_secrets` only rewrites keys present in the tuple.
- **Suggested fix:** Add `"lastfm_api_key"` to `_SECRET_SETTING_KEYS` and return a `has_lastfm_api_key` flag instead; log only a hash/ordinal of the rejected key.
- **Fix side effects:** The UI must not echo the value back into the field (the existing masked-write guard `_is_empty_secret_write` at `core/api.py:267-269` already handles the "blank write must not wipe the stored value" case, so the same pattern applies).
- **Discovered by:** B

#### F-WN-21-14  [P3] — Editing `auth.yandex_token` by hand never reaches the live Yandex client

- **File:** `services/yandex_service.py:38-59,89-101`; `core/api.py:1884-1896,1931-1933`
- **Confirmed:** yes
- **Description:** `YandexService._get_client()` reads `auth.yandex_token` only when it (re)creates the client, and the client is only recreated by `reset_client()`. `reset_client()` is called from exactly one place: the device-auth success path (`core/api.py:1933`). A user who pastes a token into the settings field (the UI explicitly offers that fallback — `core/api.py:1923`: "Введите токен вручную в поле ниже") writes the setting but never invalidates the client, so the app keeps using the anonymous client (or the previous token) until restart.
- **Cause:** The settings-write path has no provider-invalidation hook; only the device-auth path invalidates.
- **Trigger conditions:** Manual token entry, or changing the token from one account to another.
- **User impact:** The app appears to accept the token but keeps behaving as anonymous — no subscription, and (per `services/yandex_service.py:78`) "tracks limited to 30-sec previews" — until the user restarts the app.
- **Evidence:**
  ```python
  # services/yandex_service.py:38-44 — the token is read only at client creation
  def _get_client(self):
      with self._client_lock:
          if not self._client and HAS_YANDEX:
              token = self.settings.get("auth", "yandex_token", "") if self.settings else ""
  # core/api.py:1931-1933 — the only reset_client() call
  self._core.settings.set("auth", "yandex_token", token.access_token)
  self._core.settings.set("auth", "yandex_token_valid", True)
  svc.reset_client()
  ```
  `core/api.py:1884-1896` (`set_setting`) contains no provider invalidation.
- **Reproduction / verification:** Set `settings['auth']['yandex_token']` after startup; `self._core.yandex._client` is unchanged and `YandexService._get_client()` returns the old client.
- **Suggested fix:** In `AppApi.set_setting`, when `(category, key) == ("auth", "yandex_token")`, call `self._core.yandex.reset_client()` (guarded by a hasattr check so the lazy property is not forced).
- **Fix side effects:** `reset_client()` also clears the Yandex stream/search cache entries (`yandex_service.py:93-99`) — correct on a token change, but it means a cache flush on every token write.
- **Discovered by:** B

#### F-WN-21-15  [P3] — Unvalidated identifier interpolated into the iTunes URL, and album/playlist lookups cannot be cancelled

- **File:** `services/spotify_service.py:175-215,217-244`; contrast `services/catalog_service.py:193-196`
- **Confirmed:** yes
- **Description:** `get_album_tracks` and `get_playlist_tracks` interpolate the caller-supplied `collection_id` / `playlist_id` straight into the query string with no validation and no quoting, and call `ITunesGateway.get(...)` **without** an `is_current` callback — so those requests are not cancellable and keep occupying a global rate-limit slot after the user has navigated away. `CatalogService.album_details` does validate the same kind of id (`if not collection.isdigit(): return {'status': 'not_found'}`), so the two paths disagree.
- **Cause:** The two call sites were written independently; the stricter one's validation was not reused.
- **Trigger conditions:** Any album/playlist lookup; the id comes from the UI (`core/api.py:2600` → `srv.get_playlist_tracks(playlist_id, ...)`).
- **User impact:** Low. The host is fixed, so this is query-parameter injection rather than SSRF (`&`/`#` in the id can add or truncate parameters). The non-cancellable requests are the real cost: they consume the shared 3.5 s slot that the search path needs (see F-WN-21-3) and continue after the request is stale.
- **Evidence:**
  ```python
  # services/spotify_service.py:179-180
  url = f"https://itunes.apple.com/lookup?id={collection_id}&entity=song&limit={limit}"
  data = ITunesGateway.get(url, session=_session, timeout=4.0)     # no is_current
  # services/spotify_service.py:221-222 — identical shape for playlist_id
  # services/catalog_service.py:193-194 — the stricter variant
  collection = sid.removeprefix('spotify_album_')
  if not collection.isdigit(): return {'status': 'not_found', 'error': 'Неверный ID альбома'}
  ```
- **Reproduction / verification:** `SpotifyService.get_album_tracks("1&foo=bar")` produces `https://itunes.apple.com/lookup?id=1&foo=bar&entity=song&limit=50` — the injected parameter reaches iTunes.
- **Suggested fix:** Validate the id (`str.isdigit()`) or `urllib.parse.quote()` it, and thread an `is_current` callback (as `SpotifyService.search` already does) into the album/playlist lookups.
- **Fix side effects:** Rejecting non-numeric ids would break a caller that passes an Apple Music URL — currently there is none, but `core/api.py:2600` passes whatever the UI holds.
- **Discovered by:** B

---

### 3. Clean areas

- **No hard-coded credentials.** A regex sweep of all five WN-21 files for `api_key`/`token`/`secret`/`client_id`/`password`/`bearer` literals found **no** hard-coded secret. The Last.fm key is resolved at runtime from `LASTFM_API_KEY` / `auth.lastfm_api_key` (`lastfm_service.py:134-150`); the Yandex token comes from settings (`yandex_service.py:41`); there is no VK or Spotify credential in the codebase at all (there is no Spotify OAuth and no VK OAuth).
- **Outbound hosts are exactly what they should be.** `spotify_service.py` → `itunes.apple.com` only; `lastfm_service.py` → `ws.audioscrobbler.com` only; `yandex_service.py` → the `yandex_music` client; `vk_service.py` → yt-dlp. No unexpected telemetry or third-party endpoints.
- **No `verify=False` / `CERT_NONE` anywhere.** `requests` is never used with certificate verification disabled; the only occurrence of the pattern is the yt-dlp `nocheckcertificate` flag (F-WN-21-4).
- **The Yandex token never reaches the WebView.** `core/api.py:240` masks `yandex_token`; `get_setting` returns `""` for it (`core/api.py:1860-1861`); `get_settings('auth')` returns `""` + `has_yandex_token` (`core/api.py:243-253`); `yandex_device_auth` emits only `{success, message}` (`core/api.py:1934-1937`). The token *is* stored in plaintext in the settings table (by design, `core/settings.py:401-418` → `core/database.py:2036`), and it is read directly by the proxy to inject `Authorization: OAuth …` (`core/proxy.py:1004-1006`) — never echoed to JS. `core/proxy.py:489` already masks `k=`/`auth_token=` query parameters in proxy logs.
- **The search fan-out is resilient: one dead provider does not break the whole search.** `core/api.py:2226-2228` wraps the provider dispatch in `try/except`; `SpotifyService.search` catches every exception and routes it to `error_callback` (`spotify_service.py:167-171`); `core/api.py:2192-2194` turns that into `_finish([])` → `emit_results([], name)` + `mark_done(name)`. `CatalogueUnavailable` is converted to an empty result at `itunes_gateway.py:84-86` and never escapes into the bridge. A timeout is handled the same way (`core/api.py:2199-2204`). **No dead provider can abort the other providers or leave the spinner running.**
- **A missing credential degrades gracefully.** Last.fm: `available` is False with no key and `_api_request` returns the stale cache **without any network call** (`lastfm_service.py:315-318`) — and the "no key configured" message is logged once at init (`lastfm_service.py:109-113`). Yandex: no token → anonymous client, and a Plus-less account logs "No Yandex Plus subscription — tracks limited to 30-sec previews" (`yandex_service.py:78`) and `get_download_info` returns nothing → the user gets "Нет доступных аудиопотоков" instead of a crash. iTunes needs no credential. VK needs none.
- **The iTunes gateway's cancellation and error handling are correct.** A request whose `is_current()` goes false aborts **before** the HTTP call and leaves no cache entry (verified: `Gateway._entries` stayed empty after a stale request); a non-200 is never cached (`itunes_gateway.py:65-76`, pinned by `tests/test_itunes_request_queue.py:46-52`); a 429 `Retry-After` pushes the global next-slot time out instead of being mistaken for "not found" (`:66-72`, pinned by `tests/test_itunes_request_queue.py:62-69`); the `_entries` cache is bounded at 500 with LRU eviction (`:80-81`).
- **The shared cache lock is NOT a contention problem.** `ITunesGateway._condition` is built on `BaseMusicService._cache_lock` (`:15`), which puts the iTunes throttle and every provider cache on the same `RLock`. I measured the worst-case acquisition delay for the shared lock while the gateway was polling: **0.0038 s over 1 591 468 probes**. `Condition.wait()` releases the `RLock` fully, so the HTTP request itself is performed outside the lock (`:64`) and the other providers are not blocked. The concern is therefore *naming/ownership* (F-WN-21-8), not throughput.
- **Provider pools and sessions are shut down.** `core/app.py:571-586` shuts down the shared pool plus the YouTube, SoundCloud, Yandex and Spotify instance pools. `BaseMusicService._SharedExecutor` (`base_service.py:65-118`) is lazy, refuses work after shutdown, and swallows `RuntimeError` during interpreter finalisation.
- **The WN-21 providers are NOT re-instantiated per call.** `services/track_resolver.py` and `services/playlist_import_service.py` do construct providers per call, but only `SoundCloudService` (`track_resolver.py:252`, `playlist_import_service.py:192`) and `YouTubeService` (`track_resolver.py:294`) — both are WN-19 / WN-20 territory. **No WN-21 provider is built per call**: `AppCore` builds `SpotifyService` once (`core/app.py:131`) and `YandexService` once through the lazy `yandex` property (`core/app.py:200-211`); `LastFMService` is built once inside `RecommendationService.__init__` (`recommendation_service.py:53`). The per-call cost for this area is therefore **zero** — no pool, session or client-id scrape is repeated.
- **The Yandex download filename is now sanitised.** `WIN_AUDIT_CONTEXT.md` rule 8 states that `services/yandex_service.py` "still builds `ya_<raw_id>_<ts>.mp3` from an unsanitised id — documented, not enforced". The current code sanitises it: `safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_id)` (`yandex_service.py:271`) before `f"ya_{safe_id}_{int(time.time())}.mp3"` (`:272`). **That documented risk no longer holds** — the brief is stale on this point.
- **Yandex cache-key hygiene is consistent.** `search` uses `ya_search:{query}` (`yandex_service.py:115`) and `reset_client` removes `startswith("ya_")` (`:97`); streams use `yandex:{raw_id}` (`:180,232`) and `reset_client` removes `startswith("yandex:")` (`:94`). No cross-provider key collisions.
- **Test coverage of the area.** `tests/test_itunes_request_queue.py` pins the spacing, the rolling 18/min cap, cache expiry, no-caching-of-failures, stale-request removal and the `Retry-After` back-off — the strongest part of the suite for this area. `tests/test_provider_performance.py:82-102` pins that a failed Spotify search is *not* cached (so a retry after the network recovers works) and that duplicate searches collapse into one task. `tests/test_proxy_url_validation.py:135-160` pins that the shared Spotify session never keeps a stale or unusable proxy.

---

### 4. Coverage gaps

- **The live iTunes/Last.fm/Yandex endpoints were not exercised.** `pytest.ini` deselects the `network` marker and the ground rules forbid running the real app, so every measurement above used a fake session or a monkeypatched `requests`. The 3.5 s slot, the 18/min cap and the 900 s entry TTL are *code* constants and were verified by execution against the real `ITunesGateway.get`; the real-world iTunes response latency and Apple's actual rate-limit response were not measured.
- **The `vk` extractor was not executed at all** (it needs a live VK page and yt-dlp network access), so the practical effect of `nocheckcertificate` on a TLS-intercepting network is asserted from the flag's documented meaning, not from a packet capture.
- **`LastFMService`'s SQLite cache in `~/.nedotify/cache/lastfm_cache.db` was not inspected** (the ground rules forbid touching `~/.nedotify/`). The connect-per-operation cost (`lastfm_service.py:234,296`) and the absence of WAL on that file are read from the code; the contention profile under concurrent recommendation loads was not measured.
- **Multi-instance `LastFMService` behaviour is inferred from code reading plus a synthetic two-instance repro** (`/tmp/opencode/wn21_repro.py`). The shipped app builds only one instance, so the "key list leaks across instances" part of F-WN-21-6 is a design defect rather than a live multi-user symptom; the "revoked key keeps being used" part *is* live (single instance, append-only global).
- **The Yandex `yandex_music` client behaviour** (device-auth handshake, subscription probe, `get_download_info`) was not exercised — the package is imported lazily and no test in the area covers it. The Yandex-specific findings (F-WN-21-14) are based on code reading of the settings/invalidation path, not on a live token change.
- **UI rendering of the Spotify brand** was verified by reading `ui/web_new_v2/js/search.js:49,178` and `index.html:379,1861,2104`; the actual pixels were not rendered (the visual-guard harness is WN-35).
- **`tests/test_lyrics_netease.py` is not WN-21 material.** It exercises `services/lyrics_service.py` (WN-22) only — Netease is a *lyrics* provider and has nothing to do with the Yandex/VK/Spotify/Last.fm/iTunes providers in this area. It was read in full and pinned nothing here. The Spotify-related assertions in `tests/test_provider_loading.py` likewise test the **YouTube** service's handling of a `ytsearch1:` target (`test_spotify_search_target_reaches_extractor`, `:31-41`), i.e. WN-19 behaviour, not the Spotify provider.
- **Not checked (out of area, noted for the owning reviewers):** the bridge methods `core/api.py::search` (WN-06) and `get_playlist_tracks` (WN-07) both block the pywebview bridge thread for up to `BRIDGE_SYNC_BUDGET = 6.0 s`; the Spotify playlist path (`core/api.py:2600-2606`) can exceed that because of the gateway's 3.5 s slot. The blocking bridge method is WN-07's defect; the WN-21 contribution is the 3.5 s serialisation (F-WN-21-3).

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — Give every provider one shape.** WN-21 contains four different provider shapes: `BaseMusicService` subclasses with a class-level pool (`LastFMService`), subclasses with a per-instance pool (`YandexService` 3 workers, `SpotifyService` 5 workers), a subclass that inherits only to steal a lock (`ITunesGateway`), and a non-subclass (`VKService`). A small `Provider` protocol — `search`, `get_stream_url`, `available`, a bounded pool, a session factory, a `close()` — implemented once in `BaseMusicService` would remove the duplicated pool/session/thread logic in `vk_service.py:48,88` and the per-class `_executor` overrides in `yandex_service.py:30` and `spotify_service.py:100`.

**ARCH-2 — Replace the "global mutable list of secrets" with a credential object.** `lastfm_service.py:23` + `:105-107` (a process-global key list), `spotify_service.py:18` (a process-global `requests.Session` mutated from `__init__`) and `yandex_service.py:41` (a token read at client-creation time) are three different credential-lifetime models. One `Credentials` object per provider — resolved on demand, re-readable after a settings change, redacted in logs, never global — would fix F-WN-21-6, F-WN-21-10 and F-WN-21-13 at once.

**ARCH-3 — Split the transport from the provider.** `SpotifyService` is a *transport adapter* over `ITunesGateway` that renames iTunes records to "spotify". Separating "catalogue client" (`ITunesClient`, "I know how to talk to iTunes") from "provider presentation" ("this shows up under the Spotify chip") would make the mislabeling in F-WN-21-1 structurally impossible and would let the same client back the artist/album catalogue that `CatalogService` already uses.

**ARCH-4 — Make the shared cache per-provider and per-layer.** `_search_cache` / `_stream_cache` are class attributes on `BaseMusicService`, so every provider and the recommendation service share one 300-entry LRU, and `ITunesGateway` adds a second, longer-TTL layer on top. A per-provider cache with an explicit "raw response" vs "rendered result" layer (and a documented TTL for each) would make the cache budget predictable and the eviction behaviour explainable.

**ARCH-5 — One scheduler for the iTunes quota, with caller-aware deadlines.** The 3.5 s global slot is correct in spirit (iTunes asks for ~20 req/min) but it is blind to the caller's deadline. A tiny scheduler that takes `(url, deadline, priority)` and either serves immediately, queues, or fails fast with a typed error would remove the silent-empty-result failure of F-WN-21-3 and would let the search path (6 s budget) and the catalogue path (8 s budget) coexist.

**ARCH-6 — Add a host-level circuit breaker to the provider base class.** Today the only resilience primitive is `_mark_bad_key` (key-scoped). A per-provider, per-host breaker (consecutive failures → open → serve the stale cache → half-open probe) plus a dedicated pool for slow providers would decouple a dead last.fm from the recommendation feed (F-WN-21-9) and would be reusable by YouTube/SoundCloud (WN-19/WN-20).

**ARCH-7 — Introduce a provider-invalidation hook on the settings path.** `core/api.py::set_setting` writes a setting and emits an event, but no provider is told that its credentials changed. A small registry (`Provider.on_settings_changed(category, key)`) invoked from `set_setting` would fix F-WN-21-14 (Yandex token) and F-WN-21-10 (proxy) and would give the app a single place to react to credential rotation.
