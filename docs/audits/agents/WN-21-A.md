## AREA WN-21 — Yandex / VK / Spotify / Last.fm / iTunes providers — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read |
|---|---|
| `services/yandex_service.py` | 1–288 (whole file) |
| `services/vk_service.py` | 1–98 (whole file) |
| `services/spotify_service.py` | 1–244 (whole file) |
| `services/lastfm_service.py` | 1–614 (whole file) |
| `services/itunes_gateway.py` | 1–93 (whole file) |
| `services/base_service.py` | 1–329 (whole file — the shared cache/`_join_request` contract) |
| `core/api.py` | 230–259, 1208–1237, 1902–1954, 2000–2079, **2077–2256 (`AppApi.search`)**, 2545–2614, 3192–3251 |
| `core/app.py` | 110–229, 296–418, 480–524 |
| `core/downloader.py` | 100–169, 700–759 |
| `core/resolver.py` | 225–271 (`refresh` / `invalidate`) |
| `core/proxy.py` | 975–1119 (credential injection + 403/410 self-heal) |
| `core/playback_recovery.py` | 70–109 |
| `core/settings.py` | 236–275, 300–379 |
| `core/database.py` | 2036–2060 (`set_setting`) |
| `audio/engine.py` | 470–508 (yandex resolve branch) |
| `services/catalog_service.py` | 168–247 (iTunes/spotify album path) |
| `services/recommendation_service.py` | 326–328, 382–387, 498–516, 552–572, 659–661, 756–881 (grep-level + read of the Last.fm call sites) |
| `utils/stream_urls.py` | 1–26 (whole file) |
| `ui/web_new_v2/js/events.js` | 426–445 |
| `ui/web_new_v2/js/search.js` | 80–149, 815–874 |
| `ui/web_new_v2/js/settings.js` | 949–1008 (grep-level) |
| `ui/web_new_v2/js/utils.js` | 3, 641 (grep-level) |
| `ui/web_new_v2/js/lyrics.js` | 760–874 |
| `services/yandex_service.py` deps | installed `yandex_music` **3.0.0** (`Client`, `DeviceAuth`, `OAuthToken`, `DownloadInfo`, `Track`) inspected via `inspect.getsource` |

**Callees traced into other areas** (defects in those belong to the owning area):

- `core/api.py::AppApi.search` (WN-06) — the `_search_generation` counter and the `is_current` predicate; `PROVIDER_SEARCH_TIMEOUT = 6.0`; `DISABLED_UI_PROVIDERS`.
- `core/api.py::yandex_device_auth` (WN-05) — the OAuth device flow; token persistence.
- `core/app.py::AppCore` (WN-02) — eager `self.vk` / `self.spotify`, lazy `self.yandex` / `self.recommendations`.
- `core/resolver.py` (WN-15) — `refresh` / `invalidate`.
- `core/proxy.py` (WN-11) — 403/410 self-heal.
- `core/playback_recovery.py` (WN-15) — the only place that clears the service-level `_stream_cache`.
- `services/base_service.py` (WN-18) — `_search_cache` / `_stream_cache` / `_join_request`.
- `services/catalog_service.py` (WN-24) — the other consumer of `ITunesGateway`.
- `core/downloader.py` (WN-13) — `download_audio_sync` dispatch, `_SUPPORTED_SOURCES`.
- `ui/web_new_v2/js/*` (WN-31/32) — search dispatch, `HIDDEN_SOURCES`, the `yandex_auth_error` event that the backend never emits.

**Verification harnesses** (scratch files under `%TEMP%\opencode\audit_reports\`, no repo file touched):

- `_scratch_wn21.py` — iTunes gateway throttle / deadline behaviour.
- `_scratch_wn21b.py` … `_scratch_wn21f.py` — real `SpotifyService` + real `ITunesGateway` leader/joiner races.
- `_scratch_wn21g.py` — Last.fm key resolution and rotation.

---

### 2. Findings

#### F-WN-21-1  [P1] — A superseded search generation's cancellation error is delivered to the *current* generation, silently wiping the Spotify results of the search the user is looking at

- **File:** `services/spotify_service.py:110-119` (join key + `is_current` hand-off), `services/base_service.py:140-161` (`_join_request` fan-out), `services/itunes_gateway.py:55-56` (the `is_current()` cancellation), `core/api.py:2090-2096` (the generation counter)
- **Confirmed:** yes
- **Description:** `SpotifyService.search` joins concurrent identical requests under the cache key `f'spotify_search:{query}:{result_type}:{limit}'` — a key that carries **no generation**. The `is_current` predicate that is threaded into the gateway is **per-generation** (`core/api.py:2094-2096`: `generation == self._search_generation`). When the leader of a joined group is superseded, the gateway aborts the leader's queued request with `CatalogueUnavailable('Запрос устарел или истёк срок ожидания каталога')`; `SpotifyService._search_thread` turns that into `error_callback(...)`, and `BaseMusicService._join_request.finish(error=...)` notifies **every listener of the group — including the listener of the current, still-valid generation.** The current generation never issued a request of its own and loses all Spotify results.
- **Cause:** a *generation-scoped* cancellation predicate is combined with a *generation-agnostic* pending-request key. The joiner inherits the leader's cancellation.
- **Trigger conditions:** two searches with the **same query text** within the leader's flight window — e.g. typing a query (the search box debounces 200 ms, `ui/web_new_v2/js/search.js:109-113`) and then pressing Enter (`search.js:87`), or `ui/web_new_v2/js/artist_profile.js:118` re-searching the artist name that is already in flight. The leader must be parked in the iTunes throttle queue when it is superseded (which is the normal case, see F-WN-21-2), otherwise the leader has already completed and the join is harmless.
- **User impact:** the user searches, presses Enter, and the Spotify section of the results comes back **empty** even though iTunes is reachable and the catalogue was never queried. The reason is only `logger.info("%s search failed: %s", ...)` in `core/api.py:2193`; nothing reaches the UI.
- **Evidence:**
  ```python
  # services/spotify_service.py:110-119
  def search(self, query, callback=None, error_callback=None, limit=20, result_type=None, is_current=None):
      key = f'spotify_search:{query}:{result_type}:{limit}'      # <- no generation
      cached = self.get_search_cache(key)
      ...
      leader, callback, error_callback = self._join_request(key, callback, error_callback)
      if not leader:
          return None                                            # <- joins, makes no request
  ```
  ```python
  # services/itunes_gateway.py:55-56  (inside the owner's throttle wait)
  if now >= deadline or not is_current():
      raise CatalogueUnavailable('Запрос устарел или истёк срок ожидания каталога')
  ```
  ```python
  # services/base_service.py:149-161
  def finish(data=None, error=None):
      with self._cache_lock:
          listeners = self._pending_requests.pop(key, [])
      for on_success, on_error in listeners:      # <- BOTH generations
          if error is not None:
              if on_error: on_error(error)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_reports\_scratch_wn21f.py` drives the real `SpotifyService` + real `ITunesGateway` with a fake iTunes session, parks the leader in the throttle queue (`ITunesGateway._next_at = now + 1.2`), then starts a second generation on the **same query**:
  ```
  0.000s gen1 search 'song'  -> parks in the 3.5s throttle queue
  0.101s gen2 search 'song'  (SAME query -> same cache key -> joins gen1)
  4.101s outcomes: {'gen1': ('error', 'Запрос устарел или истёк срок ожидания каталога'),
                    'gen2': ('error', 'Запрос устарел или истёк срок ожидания каталога')}
         iTunes HTTP calls: 0
  ```
  Zero HTTP calls were made — the current generation produced an *error* purely because the stale leader was cancelled.
- **Suggested fix:** make the pending-request key generation-aware (include the `is_current` generation), or make the fan-out per-listener: a listener whose own `is_current()` is still true must not be failed by another generation's cancellation; it should issue its own request.
- **Fix side effects:** including the generation in the join key removes the de-duplication benefit for identical repeated queries (a second identical search would issue a second iTunes request) — acceptable given the 3.5 s throttle, but it increases iTunes traffic against `PER_MINUTE = 18`.
- **Discovered by:** A

---

#### F-WN-21-2  [P1] — The iTunes gateway's global 3.5 s single-slot throttle plus its 8 s deadline is tighter than the bridge's 6 s provider timeout, so the Spotify tab returns zero results whenever the iTunes round-trip is slower than ~2.5 s

- **File:** `services/itunes_gateway.py:21-22, 26, 51-64`; `services/spotify_service.py:32, 64`; `core/api.py:61, 2197-2208`
- **Confirmed:** yes
- **Description:** `ITunesGateway` serialises **every** iTunes call in the process (Spotify search, Spotify album/playlist lookups, and the catalog service's artist/album resolution all share it) behind one slot, spaced `INTERVAL = 3.5` s apart, with `PER_MINUTE = 18` and a default per-call deadline of `now + 8.0` s. The bridge, however, arms `threading.Timer(PROVIDER_SEARCH_TIMEOUT = 6.0)` around the provider call and emits an **empty** Spotify result set when it fires. A request that has to wait for a free slot therefore consumes most of the 6 s budget before a single byte is fetched; anything slower than ~2.5 s of actual iTunes latency pushes the total past 6 s and the user sees "no Spotify results" — while the request itself keeps running in the background and quietly populates the search cache, so the *second* attempt works.
- **Cause:** the gateway's own deadline (8 s) is longer than the caller's timeout (6 s), and the throttle queue is not visible to the caller, so the caller's timeout always fires before the queue can report "still waiting".
- **Trigger conditions:** every Spotify search after the first one in a session (the first request consumes the slot and pushes `_next_at` 3.5 s into the future); a burst of keystrokes; a slow or geo-restricted iTunes endpoint.
- **User impact:** the Spotify section of the search results is silently empty on most queries; the user has to retype the query to see the results (they then hit the 300 s search cache). The same throttle also delays `AppApi.get_playlist_tracks(source="spotify")`, whose synchronous bridge budget is `BRIDGE_SYNC_BUDGET = 6.0` (`core/api.py:67, 2605-2606`) — the user sees "Таймаут получения треков плейлиста" while the request later succeeds.
- **Evidence:**
  ```python
  # services/itunes_gateway.py:21-22, 26
  INTERVAL = 3.5
  PER_MINUTE = 18
  ...
  deadline = deadline if deadline is not None else time.monotonic() + 8.0
  ```
  ```python
  # services/itunes_gateway.py:57-61
  if not cls._active and now >= cls._next_at and len(cls._recent) < cls.PER_MINUTE:
      cls._active = True; acquired = True
      cls._recent.append(now)
      cls._next_at = now + cls.INTERVAL          # <- global 3.5s spacing
  ```
  ```python
  # core/api.py:61 / 2197-2208
  PROVIDER_SEARCH_TIMEOUT = 6.0
  _timeout = 8.0 if name == "soundcloud" else PROVIDER_SEARCH_TIMEOUT
  timer = threading.Timer(_timeout, _on_timeout); timer.daemon = True; timer.start()
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_reports\_scratch_wn21.py`
  * EXPERIMENT 1 — two sequential iTunes calls, 0.4 s latency each:
    ```
    request#1 'a'  completed after 0.40s
    request#2 'ab' completed after 3.22s (started 0.70s after #1)
    ```
    The second call spends 3.2 s purely in the throttle queue.
  * EXPERIMENT 2 — 8 concurrent iTunes requests, 0.1 s latency each:
    ```
    ok     : [(0, 0.10), (4, 3.65), (1, 7.21)]
    failed : [(6, 8.00, 'Запрос устарел или истёк срок ожидания каталога'), (7, 8.00, ...),
              (2, 8.01, ...), (3, 8.01, ...), (5, 8.01, ...)]
    ```
    5 of 8 requests die at the 8 s gateway deadline. In the app the bridge kills them at 6 s and shows nothing.
- **Suggested fix:** make the gateway deadline shorter than the caller's budget (or make the gateway deadline a parameter derived from it), and/or let the provider surface "queued" as a distinct outcome so the bridge does not report an empty result set for a request that is merely waiting. Increasing the throughput (per-URL coalescing is already there; a real pool instead of one global slot) would also help.
- **Fix side effects:** a shorter gateway deadline turns slow-but-successful iTunes responses into hard failures instead of late results; raising `INTERVAL`/slot count risks Apple rate-limiting (HTTP 403, see F-WN-21-3). The 6 s bridge timeout itself belongs to WN-06.
- **Discovered by:** A

---

#### F-WN-21-3  [P2] — An iTunes HTTP 403 (geo-block / rate-limit) is converted into `CatalogueUnavailable` and swallowed as "no results", so the whole Spotify surface dies without a reason

- **File:** `services/itunes_gateway.py:65-73`; `services/spotify_service.py:53-55, 167-171`; `core/api.py:2192-2194`
- **Confirmed:** yes
- **Description:** the iTunes Search API answers **403** for a geo-restricted region and for throttled clients. `ITunesGateway.get` raises `CatalogueUnavailable(f'iTunes HTTP {response.status_code}')` for every non-200. `SpotifyService._search_thread` catches it in a blanket `except Exception` and calls `error_callback(str(e))`; `core/api.py::_on_error` logs it at `INFO` and calls `_finish([])` → the bridge emits `search_results` with an **empty** track list for the Spotify provider. The 429 branch does apply a `Retry-After` backoff to `_next_at`, but the request that got the 429 is still failed rather than retried.
- **Cause:** transport-level failures (403 geo-block, 429 throttling, malformed body) are mapped onto the same "provider produced nothing" channel as a genuinely empty result set.
- **Trigger conditions:** the app runs in a region where Apple blocks the iTunes Search API, or Apple throttles the shared egress IP, or the endpoint returns a non-JSON body.
- **User impact:** the Spotify tab is permanently empty; the user sees an empty provider section, not an error. The `CatalogueUnavailable` class exists precisely to signal "the catalogue is not available", but nothing in the bridge maps it onto a user-visible message.
- **Evidence:**
  ```python
  # services/itunes_gateway.py:65-73
  if response.status_code != 200:
      if response.status_code == 429:
          ... cls._next_at = max(cls._next_at, time.monotonic() + retry)
      raise CatalogueUnavailable(f'iTunes HTTP {response.status_code}')
  ```
  ```python
  # services/spotify_service.py:167-171
  except Exception as e:
      self.logger.error(f"Spotify search error: {e}")
      if error_callback: error_callback(str(e))
      return []
  ```
  ```python
  # core/api.py:2192-2194
  def _on_error(err):
      logger.info("%s search failed: %s", name, err)
      _finish([])
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_reports\_scratch_wn21d.py` EXPERIMENT (b) drives the real `SpotifyService` with a fake session returning HTTP 403:
  ```
  iTunes HTTP calls: 1
  outcomes: {'gen1': ('error', 'iTunes HTTP 403'), 'gen2': ('error', 'iTunes HTTP 403')}
  ```
  Note: on this host the real endpoint is unreachable (`SSLError: [SSL: UNEXPECTED_EOF_WHILE_READING]` for `https://itunes.apple.com/search?...`), which produces the same "empty Spotify results" symptom via the same `CatalogueUnavailable` path — so the failure mode is not hypothetical in this environment.
- **Suggested fix:** distinguish `CatalogueUnavailable` from an empty result in `SpotifyService`, and surface it (e.g. a `search_provider_error` event or a provider-status line) instead of emitting an empty track list; honour `Retry-After` by retrying once instead of failing the request.
- **Fix side effects:** a visible error banner for a transient Apple outage is noisier than silence; the `CatalogueUnavailable` type is shared with `catalog_service.py` (WN-24), so the mapping must not break that consumer.
- **Discovered by:** A

---

#### F-WN-21-4  [P2] — Yandex: a rejected or expired token silently falls through to an anonymous client, and the auth/subscription hooks that were meant to tell the user are never wired

- **File:** `services/yandex_service.py:38-67` (the fall-through), `services/yandex_service.py:27-29, 69-87` (the dead hooks), `ui/web_new_v2/js/events.js:434`, `ui/web_new_v2/js/settings.js:996-1008`
- **Confirmed:** yes
- **Description:** in `_get_client`, the `try` around `Client(token).init()` catches every exception, sets `self.auth_error = True`, and then **falls through** to the anonymous branch `self._client = Client().init()`. The service therefore keeps working in a degraded, unauthenticated mode with no indication to the user. `self.auth_error` is written but **never read anywhere in the repo**; `self.on_auth_error` and `self.on_subscription_status` are initialised to `None` and **never assigned** by anybody, so the "token rejected" and "no Yandex Plus — tracks limited to 30-second previews" conditions are never surfaced. The frontend even has the event wired for it — `js/events.js:434` handles `case 'yandex_auth_error':` — but the backend never emits it, and `js/settings.js:996-1008` documents that gap in a comment ("the backend never emits a `yandex_auth_error` event"). `_check_subscription()` is only called on the *token-success* path, so the anonymous client is never subscription-checked.
- **Cause:** the exception handler does not `return` after recording the failure; the anonymous fallback is not distinguished from a deliberate anonymous session.
- **Trigger conditions:** the stored Yandex OAuth token expires, is revoked, or the user pastes a wrong token into Settings.
- **User impact:** search still returns Yandex tracks (the anonymous client can search), but every track fails to play with "Трек недоступен (нет прав или требуется подписка Яндекс Музыки)" or "Ошибка авторизации Яндекс Музыки. Добавьте токен в Настройки → Авторизация" — and the app never tells the user *why* the token stopped working or prompts a re-auth. The user is stuck in a loop of re-entering a token with no feedback that the previous one was rejected.
- **Evidence:**
  ```python
  # services/yandex_service.py:38-67
  def _get_client(self):
      with self._client_lock:
          if not self._client and HAS_YANDEX:
              token = self.settings.get("auth", "yandex_token", "") if self.settings else ""
              if token and len(token.strip()) > 5:
                  try:
                      self._client = Client(token).init()
                      ...
                      return self._client
                  except Exception as e:
                      self.logger.error(f"Failed to initialize Yandex Music client with token: {e}")
                      self.auth_error = True
                      if self.on_auth_error:
                          self.on_auth_error(True)
              else:
                  ...
              try:
                  self._client = Client().init()      # <- falls through after a FAILED token
                  self.logger.info("Yandex Music client initialized (anonymous).")
              except Exception as e:
                  self.logger.error(f"Failed to initialize Yandex Music client (anonymous): {e}")
          return self._client
  ```
  Repo-wide grep for `on_auth_error|on_subscription_status|auth_error` returns hits **only** inside `services/yandex_service.py`; `ui/web_new_v2/js/events.js:434` listens for a `yandex_auth_error` event that no Python code emits.
- **Reproduction / verification:** static — the `except` block has no `return`, and `self.on_auth_error`/`self.on_subscription_status` have no writer outside `__init__`. A runtime check: set `auth.yandex_token` to a bogus value, restart, and observe `logs/app.log` containing both *"Failed to initialize Yandex Music client with token"* and *"Yandex Music client initialized (anonymous)"*, with no UI feedback.
- **Suggested fix:** after a token failure, keep the client unset (or mark the session as unauthenticated) and expose the state — e.g. wire `on_auth_error` to the bridge's `yandex_auth_error` event, and make `auth_error` readable by `AppApi` so the UI can show the banner that already exists in `index.html`.
- **Fix side effects:** refusing the anonymous fallback removes the "browse without a token" capability that some users may rely on; the fix should keep anonymous mode but only when no token was configured.
- **Discovered by:** A

---

#### F-WN-21-5  [P2] — Yandex: the OAuth refresh token is thrown away, so an expired access token can only be fixed by a full device re-authorisation

- **File:** `core/api.py:1930-1932` (token persistence), `services/yandex_service.py:38-50` (the only consumer of the token)
- **Confirmed:** yes (the token-storage half is owned by WN-05; the "no refresh anywhere" half is WN-21's)
- **Description:** `yandex_music` 3.0.0's device flow returns an `OAuthToken` carrying `access_token`, `refresh_token` and `expires_in`. `AppApi.yandex_device_auth` persists **only** `token.access_token` (plus a `yandex_token_valid` flag that is written and never read). Repo-wide grep for `refresh_token` / `expires_in` outside the library returns **zero** hits: nothing refreshes the access token, nothing notices its expiry, and `Client` has no refresh entry point of its own (the installed 3.0.0 exposes only `device_auth`, `poll_device_token`, `request_device_code`). `YandexService._get_client` therefore keeps reusing a dead token until the user re-runs the device flow by hand.
- **Cause:** the refresh half of the OAuth grant is discarded at persistence time and there is no expiry bookkeeping anywhere in the provider.
- **Trigger conditions:** the Yandex access token expires (typically hours after the device authorisation) or is invalidated server-side.
- **User impact:** Yandex playback stops working mid-session and the user must manually re-authorise; combined with F-WN-21-4 the failure is silent (no banner, no re-auth prompt).
- **Evidence:**
  ```python
  # core/api.py:1930-1932
  if token and getattr(token, "access_token", ""):
      self._core.settings.set("auth", "yandex_token", token.access_token)
      self._core.settings.set("auth", "yandex_token_valid", True)   # never read anywhere
      svc.reset_client()
  ```
  ```python
  # services/yandex_service.py:41-42 — the only place the token is consumed
  token = self.settings.get("auth", "yandex_token", "") if self.settings else ""
  if token and len(token.strip()) > 5:
  ```
  Installed library (`yandex_music.OAuthToken`): `access_token: str; refresh_token: Optional[str]; expires_in: Optional[int]`.
- **Reproduction / verification:** grep the repo for `refresh_token` → only the vendored library; grep `yandex_token_valid` → only `core/api.py:1932`. Set a short-lived token and observe that no code path re-reads or renews it.
- **Suggested fix:** persist `refresh_token` alongside `access_token` (and its expiry), and refresh/re-authorise proactively in `YandexService._get_client` when the stored token is past its expiry or when the API answers 401.
- **Fix side effects:** storing a refresh token widens the secret surface (the settings table stores values in clear text — `core/database.py:2036-2047`), and `core/api.py:240` `_SECRET_SETTING_KEYS` would have to mask the new key as well.
- **Discovered by:** A

---

#### F-WN-21-6  [P2] — Yandex: the direct link is cached in the service-level `_stream_cache` for 6 hours and nothing invalidates it when the link dies, so a dead link is re-served on every attempt

- **File:** `services/yandex_service.py:180-184, 232`; `services/base_service.py:131, 187-214`; `utils/stream_urls.py:7-26`; `core/proxy.py:1024-1051`; `core/playback_recovery.py:77-92`
- **Confirmed:** the invalidation gap is confirmed; Yandex's actual link lifetime is a hypothesis (not observable from this host)
- **Description:** `YandexService.get_stream_url` serves `self.get_from_cache(f"yandex:{raw_id}")` before touching the network, and `get_from_cache` only expires an entry when `stream_url_expired(url)` is true. `stream_url_expired` recognises **only** the `expire` / `Expires` query parameters — Yandex's `get-mp3` links carry their expiry as a Unix timestamp embedded in the **path** (`https://storage.mds.yandex.net/get-mp3/<md5>/<ts><path>`), so the helper always returns `False` for them and the entry survives the full `_STREAM_CACHE_TTL = 6 * 3600` seconds. The proxy's 403/410 self-heal (`core/proxy.py:1024-1051`) calls `resolver.invalidate(source, source_id)`, which clears the **resolver's** memory and DB cache but **not** the provider's `_stream_cache`; the re-resolution therefore asks `YandexService.get_stream_url` again and receives the same dead URL. The only code that clears the service-level entry is `core/playback_recovery.py::_invalidate` (WN-15).
- **Cause:** the shared stream cache has one expiry rule (YouTube-style query parameters) and one TTL, applied unchanged to a provider whose link format and lifetime are different; the provider does not expose an invalidation hook.
- **Trigger conditions:** a Yandex link expires while the app is running and the same track is played again.
- **User impact:** Yandex playback fails repeatedly instead of recovering on the second attempt; recovery depends on `playback_recovery` (WN-15) running first, which is not guaranteed on every path.
- **Evidence:**
  ```python
  # services/yandex_service.py:180-184, 232
  info = self.get_from_cache(f"yandex:{raw_id}")
  if info:
      if callback: callback(info.get("stream_url"), info)
      return
  ...
  self.set_to_cache(f"yandex:{raw_id}", metadata)
  ```
  ```python
  # utils/stream_urls.py:18-23 — only query parameters are understood
  query = parse_qs(urlsplit(url).query)
  for name in ("expire", "Expires"):
      for value in query.get(name, ()):
          if value.isdigit() and len(value) >= 6 and int(value) <= deadline:
              return True
  ```
  ```python
  # core/proxy.py:1026-1030 — invalidates the resolver only
  resolver = getattr(self.server.app_core, 'resolver', None)
  if resolver is not None:
      resolver.invalidate(source, source_id)
  ```
- **Reproduction / verification:** put a Yandex-shaped URL (`.../get-mp3/<md5>/1700000000/path`) into `BaseMusicService._stream_cache` and confirm `stream_url_expired(url)` is `False`; then confirm `resolver.invalidate('yandex', '123')` leaves `BaseMusicService._stream_cache['yandex:123']` in place (it only touches `resolver._mem` and the DB row, `core/resolver.py:238-254`).
- **Suggested fix:** give `YandexService` its own expiry rule for its own link format (or a much shorter TTL for `yandex:` entries) and drop the entry when the proxy reports 403/410 for that source.
- **Fix side effects:** a shorter Yandex TTL means more `download-info` round trips per track; Yandex may rate-limit anonymous clients, so the token path must remain the fast one.
- **Discovered by:** A

---

#### F-WN-21-7  [P2] — Last.fm: the API-key list is a module global populated only at construction, so a key added after startup is silently ignored

- **File:** `services/lastfm_service.py:23, 105-113, 204-225, 309-318`; `services/recommendation_service.py:326-328, 53`
- **Confirmed:** yes
- **Description:** `API_KEYS` is a **module-level list** that `LastFMService.__init__` appends to. `available` and `_get_next_api_key` read that global, so they reflect the key set as it was **when the service was constructed**. The service is constructed exactly once, lazily, by `RecommendationService.__init__` (`services/recommendation_service.py:53`), and `RecommendationService` itself is cached by the `AppCore.recommendations` lazy property (`core/app.py:213-234`) — it is never rebuilt. Meanwhile `RecommendationService._lastfm_enabled()` calls `self.lastfm._resolve_api_keys()`, which re-reads the environment and the settings **on every call**. The two disagree: the recommendation service believes Last.fm is enabled while `LastFMService.available` is still `False`, and `_api_request` then short-circuits (`if not self.available: … return self._get_stale_cache(...)`) and never touches the network.
- **Cause:** the key set is captured once into process-global state while the "is it enabled?" question is answered from live settings.
- **Trigger conditions:** the user configures `auth.lastfm_api_key` (or `LASTFM_API_KEY`) after the app has already created the recommendation service.
- **User impact:** Last.fm-derived recommendations silently stay empty until the app is restarted, with no indication that the key was picked up but not used. There is currently no Last.fm field in `ui/web_new_v2/` (no `lastfm` match in the UI sources), so the setting can only be written through the generic bridge API — which makes the "it looks configured but does nothing" trap easy to hit.
- **Evidence:**
  ```python
  # services/lastfm_service.py:23, 105-113
  API_KEYS: List[str] = []
  ...
  for key in self._resolve_api_keys():
      if key not in API_KEYS:
          API_KEYS.append(key)
  if not API_KEYS:
      self.logger.info('Last.fm API key not configured — ... Last.fm features are disabled.')
  ```
  ```python
  # services/lastfm_service.py:204-208 / 315-318
  @property
  def available(self) -> bool:
      with self._key_lock:
          return any(k not in self._bad_keys for k in API_KEYS)
  ...
  if not self.available:
      self.logger.debug(f'Skipping Last.fm {method}: no usable API key configured')
      return self._get_stale_cache(cache_key)
  ```
  ```python
  # services/recommendation_service.py:326-328
  def _lastfm_enabled(self):
      configured = getattr(self.lastfm, '_resolve_api_keys', None)
      return bool(configured()) if callable(configured) else bool(self.lastfm)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_reports\_scratch_wn21g.py` (a):
  ```
  after construction: available=False  API_KEYS=[]
  after user sets a key in settings:
    recommendation_service._lastfm_enabled() -> True
    LastFMService.available                  -> False
    API_KEYS (module global)                 -> []
  ```
- **Suggested fix:** resolve the keys on demand (inside `available` / `_get_next_api_key`) instead of caching them in a module global at construction, or rebuild the `LastFMService` when the setting changes.
- **Fix side effects:** resolving on every call adds a settings read per request (cheap, it is an in-memory dict) and makes the module global unnecessary — which also removes the `LastFMService.API_KEYS` vs `services.lastfm_service.API_KEYS` confusion described in F-WN-21-8.
- **Discovered by:** A

---

#### F-WN-21-8  [P3] — Last.fm: `self._cache_lock` shadows the base class's re-entrant lock with a non-reentrant one, and the module global `API_KEYS` is not reachable as `LastFMService.API_KEYS`

- **File:** `services/lastfm_service.py:23, 116`; `services/base_service.py:125, 140-147`
- **Confirmed:** yes
- **Description:** two related sharp edges in the same class.
  1. `LastFMService.__init__` sets `self._cache_lock = threading.Lock()` — an **instance** attribute that shadows `BaseMusicService._cache_lock` (an `RLock`, `services/base_service.py:125`). `BaseMusicService._join_request` guards shared state with `self._cache_lock` (`services/base_service.py:142`), i.e. with `cls._cache_lock` everywhere else but with the *non-reentrant* instance lock on a `LastFMService`. Today `LastFMService` never calls `_join_request`, so nothing breaks; the moment it does (or any base-class method that takes `self._cache_lock` is added), the plain `Lock` is not re-entrant and the lock discipline of the codebase (`AGENTS.md`: "A new shared field joins its class's existing lock rather than opening a second one") is broken.
  2. `API_KEYS` is a module global, so `LastFMService.API_KEYS` does **not** exist — `getattr(LastFMService, "API_KEYS", None)` is `None`. `tools/bench/bench_child.py:144-150` does exactly that (`orig_keys = list(getattr(LastFMService, "API_KEYS", []))` / `LastFMService.API_KEYS = ["bench-dummy-key"]`), so the benchmark's Last.fm key isolation is a **no-op**: it creates a new class attribute that the service never reads. (The benchmark file itself belongs to WN-35; the root cause — a module global masquerading as class state — is here.)
  Also in the same class: `_init_sqlite_cache_db` uses `with sqlite3.connect(self._db_path) as conn:` — the sqlite3 context manager commits a transaction, it does **not** close the connection, so one file handle to `~/.nedotify/cache/lastfm_cache.db` is leaked per service construction (on Windows this keeps the file open against the user's library directory).
- **Cause:** instance state and module state chosen where class state was expected.
- **Trigger conditions:** (1) any future use of `_join_request` on a `LastFMService`; (2) running the Last.fm benchmark, which then performs **real** Last.fm requests with the developer's real key; (3) every service construction leaks one sqlite handle.
- **User impact:** (2) is a developer/benchmark hygiene problem — it silently issues real API calls during a "fake-key" benchmark and can rate-limit the developer's key; (3) is a small handle leak on Windows.
- **Evidence:**
  ```python
  # services/lastfm_service.py:115-116
  self._cache = {}
  self._cache_lock = threading.Lock()          # shadows BaseMusicService._cache_lock (RLock)
  ```
  ```python
  # services/lastfm_service.py:190-191
  with sqlite3.connect(self._db_path) as conn:   # commits, does NOT close
  ```
  ```python
  # services/base_service.py:140-147
  def _join_request(self, key, callback, error_callback):
      with self._cache_lock:                    # <- instance lock on LastFMService
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_reports\_scratch_wn21g.py` (c):
  ```
  'API_KEYS' in LastFMService.__dict__      -> False
  getattr(LastFMService, 'API_KEYS', None)   -> None
  module global lf.API_KEYS                  -> ['key-one']
  ```
- **Suggested fix:** rename the instance lock (e.g. `_lastfm_cache_lock`) so it cannot shadow the base attribute, or drop it and reuse `cls._cache_lock`; move `API_KEYS` to a class attribute (`API_KEYS: List[str] = []` on `LastFMService`) so that `LastFMService.API_KEYS` is the same object; close the sqlite connection explicitly.
- **Fix side effects:** making `API_KEYS` a class attribute changes the module-global access pattern used by `services/lastfm_service.py` itself and by the bench harness (which would then start working as intended — and start needing a valid fake network stub).
- **Discovered by:** A

---

#### F-WN-21-9  [P3] — VK: there is no VK integration at all — no API host, no access token, no version parameter; the whole service is unreachable dead code

- **File:** `services/vk_service.py` (whole file), `core/app.py:130`, `core/api.py:2098`, `core/downloader.py:24-27`, `ui/web_new_v2/js/utils.js:3`, `core/settings.py:254`
- **Confirmed:** yes
- **Description:** the audit brief's premise — a VK access token, `api.vk.com/method/...` calls, a pinned `v` version parameter — **does not apply to this codebase**. `VKService` never contacts `api.vk.com`; it has no token handling, no version parameter and no credential storage. Concretely:
  * `search()` (L30-48) spawns a thread that unconditionally calls `callback([])` — it can never return a result. It also spawns a raw `threading.Thread` instead of using the shared executor.
  * `get_stream_url()` (L50-88) is the only real function, and it delegates entirely to `yt-dlp`'s generic extractor.
  * `play_direct_url()` (L90-98) has **no caller anywhere in the repo** (repo-wide grep for `play_direct_url` returns only its own definition).
  * `AppCore` instantiates `self.vk = VKService(self.settings)` (`core/app.py:130`) and then **never uses it** — repo-wide grep for `self.vk` / `.vk.` finds only that assignment.
  * The UI hides the source (`ui/web_new_v2/js/utils.js:3` `HIDDEN_SOURCES = new Set(['yandex','vk','vkontakte','zeno'])`) and the bridge refuses it (`core/api.py:2098` `DISABLED_UI_PROVIDERS`).
  * `'vk'` is not in `core/downloader.py:27` `_SUPPORTED_SOURCES`, so downloading a VK track fails with "No download provider for source 'vk'." (asserted by `tests/test_downloader_cancel.py:356-370`).
  * `core/settings.py:254` ships `"vk_enabled": True` — a setting that is **never read** (repo-wide grep: one hit, the default itself). Toggling it would do nothing even if the UI exposed it.
- **Cause:** the provider was reduced to a stub but the surrounding wiring (the `AppCore` field, the settings key, the hidden-source list) was left in place.
- **Trigger conditions:** none — the code paths simply cannot be reached.
- **User impact:** none directly; the risk is a false impression that VK is supported. A user who finds `vk_enabled` in the settings export has no way to tell that it is inert.
- **Evidence:**
  ```python
  # services/vk_service.py:40-48
  def _search():
      try:
          if callback:
              callback([])          # <- always empty
      except Exception as e:
          if error_callback: error_callback(str(e))
  threading.Thread(target=_search, daemon=True).start()
  ```
  ```python
  # services/vk_service.py:59-67  (the whole "integration")
  ydl_opts = {'quiet': True, 'no_warnings': True, 'format': 'bestaudio/best',
              'nocheckcertificate': True, 'socket_timeout': 10, 'retries': 1,
              'source_address': '0.0.0.0'}
  ```
- **Reproduction / verification:** repo-wide greps for `api.vk.com`, `access_token`/`token` in `services/vk_service.py`, `play_direct_url`, and `self.vk` — the first two return nothing, the latter two return only the definitions.
- **Suggested fix:** either implement a real VK client (token + `api.vk.com/method/...` with a pinned `v`) or delete the stub and the inert `vk_enabled` setting so the codebase stops advertising a provider it does not have.
- **Fix side effects:** removing `self.vk` from `AppCore` changes `core/app.py` (WN-02) and the `services.vk_enabled` default would disappear from the persisted settings schema (unknown keys are preserved by `core/settings.py:336-342`, so user files stay loadable).
- **Discovered by:** A

---

#### F-WN-21-10  [P2] — VK: TLS certificate verification is disabled for the one extractor that is actually reachable

- **File:** `services/vk_service.py:63`
- **Confirmed:** yes
- **Description:** `ydl_opts` sets `'nocheckcertificate': True`. yt-dlp then accepts **any** server certificate for the media host it connects to, so the audio stream can be served by an intercepting proxy without detection. The same option is set unconditionally — there is no setting to turn it off and no warning.
- **Cause:** a debugging/anti-TLS-interception flag left enabled in production code.
- **Trigger conditions:** any call to `VKService.get_stream_url`.
- **User impact:** the fetched media (and any headers/cookies yt-dlp sends) can be tampered with in transit. This is primarily a security finding (Role B may own the framing); it is recorded here because the flag is a *defect in the WN-21 file*, not in the caller.
- **Evidence:**
  ```python
  # services/vk_service.py:59-67
  ydl_opts = {
      'quiet': True,
      'no_warnings': True,
      'format': 'bestaudio/best',
      'nocheckcertificate': True,        # <- TLS verification off
      'socket_timeout': 10,
      'retries': 1,
      'source_address': '0.0.0.0'
  }
  ```
- **Reproduction / verification:** static — the option is unconditional; no settings key toggles it (grep for `nocheckcertificate` finds this one occurrence in `services/`).
- **Suggested fix:** remove `nocheckcertificate` (or make it an explicit, off-by-default opt-in).
- **Fix side effects:** users behind a TLS-inspecting corporate proxy or with a broken CA store would lose playback until the CA is installed properly — which is the intended trade-off.
- **Discovered by:** A

---

#### F-WN-21-11  [P3] — Track-shape drift across the five providers: durations are consistently seconds (no ms/s bug), but several dicts do not match the app's track contract

- **File:** `services/yandex_service.py:139-147`; `services/vk_service.py:90-98`; `services/spotify_service.py:42-52, 77-87, 150-161, 195-206`; `services/lastfm_service.py:377-383`; `core/api.py:2044-2054`
- **Confirmed:** yes
- **Description:** the app's canonical track shape is `{id, title, artist, album, duration, cover_url, source, source_id, stream_url}` with `duration` in **seconds** (`core/api.py:2044-2054`; the DB column `tracks.duration REAL`, `core/database.py:218`). Checking every duration producer in this area:
  * Yandex: `t.duration_ms / 1000.0` → seconds ✓ (`services/yandex_service.py:142, 224`)
  * Spotify: `int(item.get("trackTimeMillis", 180000) / 1000)` → seconds ✓ (`services/spotify_service.py:38, 191`); `float(item.get("trackTimeMillis", 0)) / 1000.0` ✓ (`:232`)
  * VK: `info.get('duration', 0)` (yt-dlp) → seconds ✓ (`services/vk_service.py:77`)
  * Last.fm: `int(t.get('duration', 0))` — the Last.fm `track.getsimilar` payload has **no** `duration` field, so this is always `0`; the unit is irrelevant, but the value is always empty (`services/lastfm_service.py:471`).

  **No seconds/milliseconds mix-up exists in this area.** (The frontend compensates with a heuristic at `ui/web_new_v2/js/lyrics.js:786` — `track.duration > 10000 ? track.duration : track.duration * 1000` — which is a WN-32 concern, not WN-21's.) The shape problems that *do* exist:
  * **Yandex search** emits `{title, artist, duration, source, source_id, source_url, cover_url}` — **no `album` and no `id`**. `album` renders as "Unknown Album" and the row has no stable identifier.
  * **Spotify** emits `source: "spotify"` but `source_url` is the **iTunes** `trackViewUrl` (an Apple Music link) — `services/spotify_service.py:51`; and the album variant emits `source_id = collection_id` (an iTunes collection id) while `id = "spotify_album_<collection_id>"` (`:78-86`).
  * **VK `play_direct_url`** emits `{title, artist, source, source_url, file_path}` — no `duration`, no `cover_url`, and `file_path` holds an **http URL**, which the rest of the app treats as a local path (`core/api.py:2058-2060` `os.path.exists(str(track["file_path"]))`). The function has no caller (F-WN-21-9), so the impact is latent.
  * **Last.fm** returns an entirely different shape (`name`, `artist`, `match`, `playcount`, `image`, `url`) — correct for the recommendation engine, which is its only consumer, but it is not a track dict.
- **Cause:** each provider was written against its own idea of the contract; the shared shape lives only in `core/api.py`'s consumers.
- **Trigger conditions:** rendering a Yandex result row (missing album), clicking a "Spotify" row (the source link goes to Apple Music), using a VK direct URL as a track.
- **User impact:** cosmetic/metadata inconsistencies rather than crashes.
- **Evidence:** see the file:line list above; the app contract is
  ```python
  # core/api.py:2044-2054
  track = {"id": ..., "title": ..., "artist": ..., "album": ..., "duration": float(...),
           "cover_url": ..., "source": ..., "source_id": ..., "stream_url": ...}
  ```
- **Suggested fix:** give the providers a single normalisation helper (the repo has none — `WIN_AUDIT_CONTEXT.md` rule 8) and make the Yandex dict include `album`/`id`.
- **Fix side effects:** changing the Spotify `source_url` to an Apple Music link would change what the UI's "open in Spotify" affordance does today.
- **Discovered by:** A

---

#### F-WN-21-12  [P3] — Spotify: the album-track fetcher is dead code and the playlist fetcher bypasses both the cancellation predicate and the request fan-out

- **File:** `services/spotify_service.py:175-215` (`get_album_tracks`), `services/spotify_service.py:217-244` (`get_playlist_tracks`), `core/api.py:2600-2606`
- **Confirmed:** yes
- **Description:** `SpotifyService.get_album_tracks` has **no caller** — the album path in the app goes through `AppApi.get_album_details` → `CatalogService.album_details` (`core/api.py:2244-2248`, `services/catalog_service.py:192-211`), which performs its own iTunes lookup. `get_playlist_tracks` *is* reachable (`core/api.py:2573, 2600`). Both call `ITunesGateway.get(url, session=_session, timeout=4.0)` **without `is_current` and without a deadline**, so the gateway substitutes `is_current = lambda: True` and the default 8 s deadline: the request can never be cancelled when the user navigates away, and it occupies the single global throttle slot that Spotify *search* needs. Neither method uses `_join_request`, so two identical calls are not de-duplicated. `get_playlist_tracks` also omits `source_url` and produces `id = f"spotify_{item.get('trackId')}"` → the literal string `"spotify_None"` when the payload has no `trackId`.
- **Cause:** the service kept a second, parallel implementation of the iTunes album/playlist lookup that the app no longer uses, with weaker cancellation and caching than the code that replaced it.
- **Trigger conditions:** opening a Spotify playlist while a Spotify search is in flight.
- **User impact:** the playlist fetch competes with search for the single iTunes slot (see F-WN-21-2) and can push the search past the 6 s bridge budget; the bridge then answers "Таймаут получения треков плейлиста" although the request eventually completes.
- **Evidence:**
  ```python
  # services/spotify_service.py:179-180 / 221-222
  url = f"https://itunes.apple.com/lookup?id={collection_id}&entity=song&limit={limit}"
  data = ITunesGateway.get(url, session=_session, timeout=4.0)      # no is_current, no deadline
  ```
  ```python
  # core/api.py:2600-2606
  srv.get_playlist_tracks(playlist_id, limit=limit, callback=_on_success, error_callback=_on_error)
  ...
  if not done.wait(timeout=BRIDGE_SYNC_BUDGET):      # 6.0 s
      return {"success": False, "error": "Таймаут получения треков плейлиста"}
  ```
- **Reproduction / verification:** repo-wide grep for `get_album_tracks` callers shows only `core/api.py:2244` (→ `CatalogService`) and `core/database.py`; `SpotifyService.get_album_tracks` is never invoked.
- **Suggested fix:** delete the unused `get_album_tracks`; give `get_playlist_tracks` an `is_current`/deadline and route it through the same join/cache path as `search`.
- **Fix side effects:** removing a public method could break third-party plugins that call it (`core/plugins.py` loads user plugins) — a grep of `plugins/` shows none, but the contract is public.
- **Discovered by:** A

---

#### F-WN-21-13  [P3] — Yandex download filename: the id *is* sanitised (the brief's rule #8 is stale), but the branch is unreachable in production and the URL→ID extraction is missing

- **File:** `services/yandex_service.py:263-287`; `core/downloader.py:140-150, 730-733`; `core/download_transfer.py:16-20`
- **Confirmed:** yes
- **Description:** `WIN_AUDIT_CONTEXT.md` rule 8 states that "`services/yandex_service.py` still builds `ya_<raw_id>_<ts>.mp3` from an unsanitised id". Reading the current file, that is **no longer true**: `safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_id)` reduces the id to `[A-Za-z0-9_-]`, so the constructed name cannot contain any character Windows rejects (`< > : " / \ | ? *`) and cannot escape the output directory. Two further facts:
  * The branch is **dead in production**: `core/downloader.py:730-733` always installs a `DownloadContext` and `core/downloader.py:140-150` passes it to the provider, so `download_audio_sync` takes the `download_context` path and writes `download_context.stem + '.mp3'` — and `core/download_transfer.py:19-20` sanitises the track id itself (`re.sub(r'[^a-zA-Z0-9_-]', '_', str(track_id))`).
  * `download_audio_sync` does **not** perform the URL→track-id extraction that `get_stream_url` does (`services/yandex_service.py:167-176`): it does `str(source_id).split(":")[0]`, so a URL source id becomes the literal `"https"` and `client.tracks(["https"])` fails. The failure happens before the filename is built, so it is an inconsistency rather than a corruption, but the two entry points disagree about what a `source_id` may be.
  * Also note `raw_id.split(":")[0]` truncates at the first colon — the same truncation the stream path applies, so a `provider:id` style source id silently loses its id part.
- **Cause:** the sanitisation rule was applied but the surrounding code was not unified; the brief's documentation is stale.
- **Trigger conditions:** a URL-shaped `source_id` reaching `download_audio_sync` (not produced by the current search flow, which stores the numeric id).
- **User impact:** an error message ("Трек не найден в Яндекс Музыке" from the Yandex API) instead of a download, in a path the current UI cannot reach.
- **Evidence:**
  ```python
  # services/yandex_service.py:263-282
  raw_id = str(source_id).split(":")[0].strip()
  ...
  safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_id)     # <- sanitised
  file_name = f"ya_{safe_id}_{int(time.time())}.mp3"
  ...
  output_path = os.path.join(output_dir, download_context.stem + '.mp3')   # <- production path
  return download_context.download_http(variant.get_direct_link(), output_path)
  ...
  output_path = os.path.join(output_dir, file_name)      # <- unreachable in production
  track.download(output_path, codec="mp3", bitrate_in_kbps=320)
  ```
  ```python
  # core/download_transfer.py:18-20
  digest = hashlib.sha256(f'{source}:{source_id}'.encode('utf-8')).hexdigest()[:16]
  safe_track_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(track_id))
  self.stem = f'download_{safe_track_id}_{digest}'
  ```
- **Reproduction / verification:** `re.sub(r'[^a-zA-Z0-9_-]', '_', 'https://music.yandex.ru/track/1')` → `https___music_yandex_ru_track_1` (no illegal character); `core/downloader.py:140-150` shows `download_context` is always supplied.
- **Suggested fix:** extract the URL→id handling into one helper used by both `get_stream_url` and `download_audio_sync`; update `WIN_AUDIT_CONTEXT.md` rule 8 (or `CODING_STANDARDS.md`) so the documented contract matches the code.
- **Fix side effects:** none material.
- **Discovered by:** A

---

### 3. Clean areas

Checked and found correct:

* **Duration units (the classic ms/s trap) — no mix-up in this area.** Yandex divides `duration_ms` by 1000 (`:142`, `:224`), Spotify divides `trackTimeMillis` by 1000 (`:38`, `:191`, `:232`), VK uses yt-dlp's seconds (`:77`). The app's canonical unit is seconds (`core/api.py:2049`, `tracks.duration REAL`). The only oddity is Last.fm's `duration`, which is always `0` because the Last.fm payload has no such field.
* **`is_current` is thread-safe and correctly scoped.** `core/api.py:2090-2096` increments `_search_generation` and reads it under `self._search_lock`; the predicate is a pure function of the generation. It is *not* a cache-invalidation counter (the cache is keyed by query and is not invalidated by it) — it is a "has this request been superseded" predicate, and `ITunesGateway` uses it correctly to abandon a queued request. The defect is the *combination* with the generation-agnostic join key (F-WN-21-1), not the counter itself.
* **Cache TTLs are applied.** The provider search cache uses `BaseMusicService._SEARCH_CACHE_TTL = 300 s` with LRU eviction (`services/base_service.py:243-270`); the iTunes response cache uses 900 s for a non-empty result and 60 s for an empty one (`services/itunes_gateway.py:78`); the Last.fm caches use `RECOMMENDATION_TTL = 604800` / `CHART_TTL = 86400` plus a SQLite-backed copy.
* **Spotify key handling and the "Spotify" API.** There is **no** Spotify Web API, no client-credentials token and no expiry-aware refresh — `SpotifyService` is a thin wrapper over the **iTunes** Search/Lookup API (`services/spotify_service.py:31, 63, 179, 221`). The brief's "client-credentials token fetched and cached" question therefore does not apply to this codebase. The module-level `requests.Session` is correctly shared, and the proxy assignment is correctly unconditional (`services/spotify_service.py:102-108`) — the previous `if proxy:` bug is fixed, and `tests/test_proxy_url_validation.py:143-157` pins it.
* **Yandex OAuth device flow mechanics.** `Client.device_auth(on_code=..., timeout=300)` matches the installed `yandex_music` 3.0.0 signature; the returned `OAuthToken.access_token` is persisted and `svc.reset_client()` is called so the next `_get_client()` re-reads it (`core/api.py:1926-1933`). `Client(token).init()` correctly populates `client.me`, which `_check_subscription()` reads.
* **Yandex download-info handling.** `track.get_download_info(get_direct_links=True)` does populate `DownloadInfo.direct_link` (verified against the installed library: `DownloadInfo.de_list(..., get_direct_links=True)` calls `info.get_direct_link()` for every entry), so `best_info.direct_link` in `get_stream_url` is valid. The best-mp3 selection loop (`services/yandex_service.py:207-210`) is correct.
* **Yandex cache invalidation on re-auth.** `reset_client()` clears exactly the `yandex:` stream entries and the `ya_` search entries, and re-initialises the client off the calling thread (`services/yandex_service.py:89-101`).
* **Last.fm key rotation.** `_get_next_api_key` round-robins over the non-bad keys and `_mark_bad_key` retires a key on error codes 10/26 and on HTTP 401/403. Verified: with keys `k1,k2` the sequence is `k1,k2,k1,k2,k1`; after `_mark_bad_key('k1')` it is `k2,k2,k2,k2`. `_split_keys` handles `,`/`;`, whitespace, `None`, lists and tuples correctly. A `set` yields a non-deterministic order (P3, not reported separately).
* **Last.fm handler classes are wired up.** `LastFmArtistHandler` / `LastFmTrackHandler` / `LastFmChartHandler` / `LastFmUserHandler` (`services/lastfm_service.py:40-89`) are instantiated in `__init__` and used by `RecommendationService` (`services/recommendation_service.py:385, 387, 516, 572, 659-661, 756-881`). They are thin, correct delegations.
* **Last.fm error handling.** `_api_request` degrades gracefully: a bad key is retired, a stale cache is served as a fallback, and an exception breaks out of the rotation loop rather than looping forever. The per-thread `requests.Session` (`services/lastfm_service.py:152-164`) correctly avoids the non-thread-safe shared-session problem.
* **iTunes gateway concurrency.** The single-flight map, the `_entries` LRU, the `Retry-After` back-off on 429 and the `finally` block that always releases `_active` and wakes the waiters are all correct. The `CatalogueUnavailable` type is raised and caught consistently at every call site in this area (`services/spotify_service.py:53, 88, 209, 240`).
* **No credentials configured → the app does not break.** No Yandex token ⇒ the service falls back to an anonymous client and every failure is reported through `error_callback`; no Last.fm key ⇒ `_api_request` returns the stale cache (or `None`) without touching the network; Spotify/VK/iTunes need no credentials at all. `AppApi.search` (`core/api.py:2098`) disables the Yandex/VK providers outright and the UI hides them (`ui/web_new_v2/js/utils.js:3`).
* **The Spotify search cache key is complete for its purpose** (`query`, `result_type`, `limit`) and the empty-result case is deliberately not cached (`services/spotify_service.py:141, 162`).

---

### 4. Coverage gaps

* **No live provider calls were made.** This host cannot reach `https://itunes.apple.com` (`SSLError: [SSL: UNEXPECTED_EOF_WHILE_READING]`), so the real behaviour of the iTunes Search API (403 geo-block frequency, real latency, real payload shape) could not be observed; all iTunes behaviour was verified against a fake session. The Yandex, VK and Last.fm endpoints were not called at all.
* **Yandex link lifetime is not observable from here.** The 6-hour `_STREAM_CACHE_TTL` vs. Yandex's real `get-mp3` link lifetime (F-WN-21-6) could not be measured; only the *invalidation gap* is confirmed.
* **`yandex_music` behaviour was read from the installed 3.0.0 wheel**, not from a live account: the anonymous-client capability (does `Client().search()` really succeed?), the exact exception class raised for an expired token (`UnauthorizedError`), and whether `Client().init()` raises for an anonymous session were not executed against the API.
* **The `is_current` → generation coupling in `core/api.py` (WN-06) was read but not modified**; the cross-generation join in `BaseMusicService._join_request` (WN-18) is shared by other providers — I only traced the Spotify consumer. Whether YouTube/SoundCloud suffer the same cross-generation fan-out was **not** verified (out of area).
* **`core/app.py`'s lazy `recommendations` property and `RecommendationService` (WN-23)** were only read at the Last.fm call sites; the full recommendation pipeline was not audited.
* **`tools/bench/*` (WN-35)** was inspected only for the `LastFMService.API_KEYS` interaction described in F-WN-21-8; the benchmark itself was not run.
* **`ui/web_new_v2/js/*` (WN-28…32)** was read only where it is the direct caller of a WN-21 service (search dispatch, the `yandex_auth_error` event, the lyrics duration heuristic). The UI-side rendering of a Spotify/VK/Yandex result was not audited.
* **The `plugins/` folder** was not searched for third-party callers of `SpotifyService.get_album_tracks` or `VKService.play_direct_url`.
