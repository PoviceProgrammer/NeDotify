## AREA WN-18 — Service base class, track resolver, music matching, artist identity — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `services/base_service.py` — 1–329 (full file)
- `services/track_resolver.py` — 1–476 (full file)
- `services/music_matching.py` — 1–95 (full file)
- `services/artist_identity.py` — 1–63 (full file)
- `tests/test_track_resolver_matching.py` — 1–161 (full)
- `tests/test_provider_loading.py` — 1–209 (full)
- `tests/test_provider_performance.py` — 1–102 (full)
- `tests/test_resolve_fallback_budget.py` — 1–98 (full)
- `tests/test_resolver_state.py` — 1–249 (full)
- `tests/test_lazy_service_deadlock.py` — 1–102 (full)
- `tests/test_proxy_url_validation.py` — 1–172 (full)

**Callers / callees traced (read, for attribution only)**

- `core/api.py` — 90–159 (SSRF guard), 2077–2249 (`search` fan-out, provider dispatch), 2915–2957 (settings masking), 2955–2979
- `core/app.py` — 180–299 (lazy service properties), 490–586 (`cleanup`, pool shutdown)
- `core/playback_recovery.py` — 60–119 (reaches into `BaseMusicService._stream_cache`)
- `core/downloader.py` — 495–554 (per-download `TrackResolver` creation)
- `core/database.py` — 2110–2139 (`get_all_settings`)
- `core/settings.py` — 180–359 (defaults; `auth` block)
- `services/youtube_service.py` — 180–389, 386–525, 540–659, 900–969
- `services/soundcloud_service.py` — 248–307, 520–589
- `services/spotify_service.py` — 90–199
- `services/yandex_service.py` — 60–139
- `services/lastfm_service.py` — 1–60, 210–309
- `services/itunes_gateway.py` — 1–80
- `services/catalog_service.py` — 1–80, 120–169
- `services/recommendation_service.py` — 50–89, 330–399, 415–529
- `services/artist_service.py` — 320–379
- `services/lyrics_service.py` — 285–314 (`_title_match_score`)
- `services/lyrics_lookup.py` — 18–19, 42–46, 127, 155, 243–257 (hot callers of `similarity`/`artist_matches`)
- `ui/web_new_v2/index.html` — 1745–1762 (proxy field label); `ui/web_new_v2/js/settings.js` — 385–414 (proxy save handler)

**Runtime probes** (read-only scripts under `%TEMP%`, no repo file touched):
`wn18_probe.py`, `wn18_probe2.py`, `wn18_probe3.py`, `wn18_probe5.py` — all run with `& ".venv_win\Scripts\python.exe"`.

---

### 2. Findings

#### F-WN-18-1  [P1] — The provider artist field is compared as one raw string, so any track with a comma-joined artist list is rejected

- **File:** `services/track_resolver.py:239-246` (threshold at `services/track_resolver.py:80`)
- **Confirmed:** yes
- **Description:** `_is_plausible_match` compares the requested artist against the provider's `artist` field with a whole-string `SequenceMatcher` ratio. YouTube, SoundCloud and Yandex all build that field as a **comma-joined list** (`youtube_service.py:414` `", ".join(...)`, `youtube_service.py:468`, `yandex_service.py:138`). A request for `Adele` therefore scores 0.5556 against the provider's `"Adele, Someone"` and is rejected — even though the track really is by Adele.
- **Cause:** the resolver borrows `LyricsService._title_match_score` (`lyrics_service.py:296-298`), a *title* comparator that is applied here to an *artist* field. The codebase already contains the correct artist comparator — `services/music_matching.py:48-52 artist_matches()` splits the string into credits and compares canonical sets — but `track_resolver` does not use it.
- **Trigger conditions:** any provider hit whose artist string carries a second credit. Very common on YouTube ("Artist, Featured") and on SoundCloud ("Artist & Other").
- **User impact:** the SoundCloud/YouTube fallback silently gives up and returns `TrackResolver._unresolved()` (`track_resolver.py:143-153`, `source='unknown'`). In `core/downloader.py:524-538` that means the Spotify download falls out of the TrackResolver path into the direct YouTube search path; in `services/recommendation_service.py:588/738/885` the candidate is dropped from the feed.
- **Evidence:**
  ```python
  # services/track_resolver.py:238-246
  @staticmethod
  def _is_plausible_match(title: str, artist: str, top: Dict[str, Any]) -> bool:
      from services.lyrics_service import LyricsService
      if title and LyricsService._title_match_score(title, top.get('title') or '') < TRACK_MATCH_MIN_SCORE:
          return False
      if artist and LyricsService._title_match_score(artist, top.get('artist') or '') < TRACK_MATCH_MIN_SCORE:
          return False
      return True
  ```
  Probe output (threshold `TRACK_MATCH_MIN_SCORE = 0.6`):
  ```
  artist want='Adele'        got='Adele, Someone'   score=0.5556 accepted=False
  artist want='Drake'        got='Drake, Future'    score=0.5882 accepted=False
  artist want='Adele'        got='Adele'            score=1.0000 accepted=True
  music_matching.artist_matches('Adele', ['Adele','Someone']) = True   <-- the correct answer
  ```
- **Reproduction / verification:** run `wn18_probe.py` section A; or in a REPL: `LyricsService._title_match_score('Adele', 'Adele, Someone')` → `0.5555…` < `services.track_resolver.TRACK_MATCH_MIN_SCORE` (0.6) → `TrackResolver._is_plausible_match('X','Adele', {'title':'X','artist':'Adele, Someone'})` → `False`.
- **Suggested fix:** use `services.music_matching.artist_matches(requested, offered_credits, settings)` for the artist dimension (it already handles comma lists, `&`, `feat.` and the user's artist aliases); keep `similarity` for the title dimension only.
- **Fix side effects:** `artist_matches` is alias-aware, so it is *looser* than the raw comparison — a request for artist "A" would now also accept a provider row crediting "A" among several others. The title check must stay mandatory to compensate.
- **Discovered by:** B

---

#### F-WN-18-2  [P1] — Version markers are stripped from both sides, so a request for one version matches a different version

- **File:** `services/music_matching.py:80-93` (`base_title` construction), consumed at `services/track_resolver.py:242`
- **Confirmed:** yes
- **Description:** `title_metadata()` removes `(Live)`, `(Remix)`, `(Sped Up)`, `(Official Video)`, … from the title. Because the *same* function is applied to the requested title and to the provider's title, the version token is erased on **both** sides and the comparison degenerates to the bare song name. A request for `"Song (Live)"` therefore matches a provider hit titled `"Song (Remix)"` with similarity 1.0.
- **Cause:** `base_title` is designed for *lyrics* lookup (WN-22), where "Song" vs "Song (Live)" is an acceptable match. Track **resolution** has a different contract: it names one concrete playable file that is subsequently streamed and downloaded.
- **Trigger conditions:** any provider result that carries a version qualifier, or any request that does. Common for remixes, live cuts, sped-up versions and "Official Video" uploads.
- **User impact:** the resolver returns a different recording than the one asked for. `core/downloader.py:524-538` then downloads *that* file into `~/.nedotify/downloads/` and `core/proxy.py` streams it — the user gets the wrong version in their library, and the mistake is persistent (a file on disk).
- **Evidence:**
  ```python
  # services/music_matching.py:88-92
  def remove_variant(match):
      return '' if any(re.search(p, match.group(1), re.I) for p in VERSION_PATTERNS.values()) else match.group(0)
  base = re.sub(r'[\[(]([^\])]+)[\])]', remove_variant, clean)
  ```
  Probe output:
  ```
  want='Song (Live)'->base 'Song' | got='Song (Remix)'->base 'Song' score=1.0000 accepted=True
  want='Song (Live)'->base 'Song' | got='Song'->base 'Song'          score=1.0000 accepted=True
  ```
  `_is_plausible_match('Song (Live)', 'Adele', {'title':'Song (Remix)','artist':'Adele'})` → `True`.
- **Reproduction / verification:** `wn18_probe.py` section B and `wn18_probe3.py` section 6a.
- **Suggested fix:** resolve tracks against the *full* normalised title (version token retained), or require the detected `version` (`music_matching.py:86`) to agree when both sides declare one.
- **Fix side effects:** the resolver would start rejecting legitimate pairs where the provider labels the version differently ("Remix" vs "Remix (Official Video)"); a normalisation of the version vocabulary is needed before tightening.
- **Discovered by:** B

---

#### F-WN-18-3  [P2] — An empty requested title disables the title check entirely: any track by that artist is accepted

- **File:** `services/track_resolver.py:239-246`
- **Confirmed:** yes
- **Description:** both checks are guarded by a truthiness test on the *requested* value: `if title and …` / `if artist and …`. With an empty title the title dimension is skipped completely, so the only remaining condition is "some artist similarity ≥ 0.6".
- **Cause:** the guard was meant to make the artist check optional, but it makes the **title** check optional too — and the title is the dimension that identifies the song.
- **Trigger conditions:** `services/recommendation_service.py:885` calls `self.resolver.resolve_track(item.get('name',''), item.get('artist',''))` — a candidate with an empty `name` resolves to *any* track by that artist. `core/downloader.py:524` calls `resolve_track(title or query_hint, artist or '')` — with both empty, `_resolve_uncached` queries `artist` alone.
- **User impact:** a wrong song is resolved and then downloaded/played. The blast radius is the same as F-WN-18-2 (a concrete file lands in the user's library).
- **Evidence:**
  ```python
  # services/track_resolver.py:241-246
  if title and LyricsService._title_match_score(title, top.get('title') or '') < TRACK_MATCH_MIN_SCORE:
      return False
  if artist and LyricsService._title_match_score(artist, top.get('artist') or '') < TRACK_MATCH_MIN_SCORE:
      return False
  ```
  Probe output:
  ```
  title=''  artist='Adele'  top={'title': 'Totally Different Song', 'artist': 'Adele'} -> plausible=True
  ```
- **Reproduction / verification:** `wn18_probe3.py` section 6a, first non-trivial case.
- **Suggested fix:** treat an empty requested title as "no match" (return `None`) instead of "skip the check", or fall back to `base_title` comparison against a non-empty requested value.
- **Fix side effects:** artist-only lookup (used by `recommendation_service.py:885`) would stop resolving; that caller should pass a concrete song name instead.
- **Discovered by:** B

---

#### F-WN-18-4  [P2] — The TrackResolver fallback chain has no budget (local → SoundCloud 5 s → YouTube 5 s), and a batch timeout hides the overrun instead of bounding it

- **File:** `services/track_resolver.py:269-270` and `:311-312` (two sequential 5 s waits), `:342-360` (the chain), `:362-433` (`resolve_tracks`)
- **Confirmed:** yes
- **Description:** `_resolve_uncached` runs three providers **strictly sequentially**: local DB → SoundCloud (blocking `done_event.wait(timeout=5.0)`) → YouTube (another 5 s). The worst case per track is therefore ~10 s of wall clock plus the provider's own socket timeouts. `resolve_tracks` caps the *batch* at `BATCH_TIMEOUT = 10.0` (`track_resolver.py:92`) — but that is a wall-clock ceiling on the *wait*, not on the work: the submitted futures are **never cancelled** when they miss the deadline (`track_resolver.py:414-420` only writes an "unresolved" memo entry).
- **Cause:** the batch deadline is enforced by `concurrent.futures.wait(..., timeout=…)` and the `not_done` set is used only to fill in a fallback value; `future.cancel()` is never called for it. (Contrast `services/recommendation_service.py:389-391`, which *does* cancel its pending futures.)
- **Trigger conditions:** any track that is not in the local library and whose provider is slow or unreachable — exactly the "no VPN / DPI block" scenario the app already has a budget for elsewhere.
- **User impact:** after a batch timeout the 8-worker resolver pool stays saturated with orphaned resolutions; a subsequent `resolve_track_async` (`track_resolver.py:443`) or `prefetch` (`track_resolver.py:435`) queues behind them. The recommendation feed then resolves to "unknown" rows for up to `MISS_TTL` (15 s).
- **Evidence:**
  ```python
  # services/track_resolver.py:405-420
  _done, not_done = concurrent.futures.wait(list(pending.keys()), timeout=wait_timeout)
  for future, indices in pending.items():
      ...
      if future in not_done:
          logger.debug(f"Batch resolve timed out for '{artist} - {title}'")
          unresolved = self._unresolved(title, artist)
          self._memo_put(key, unresolved)
          ...
          continue
  ```
  Probe output (12 pairs, `timeout=1.0`):
  ```
  resolve_tracks(12 pairs, timeout=1.0) returned in 1.00s; results=12
  provider 'search' calls still in flight after the batch returned: 8
  TrackResolver pool threads still alive: 8
  ```
  (8 of 12 tasks were still running and had consumed every worker; the other 4 had not even started.)
  Secondary race: the timeout path writes the "unresolved" memo entry while the orphaned worker later writes the *real* result into the same key (`track_resolver.py:338-339`) — last writer wins, so a valid answer can be clobbered by an "unknown" row for 15 s.
- **Reproduction / verification:** `wn18_probe2.py` section PROBE 4.
- **Suggested fix:** (a) call `future.cancel()` for every future in `not_done`; (b) give the whole chain a single deadline and pass the *remaining* budget into the second provider instead of a fresh 5 s; (c) keep the memo write in the worker only.
- **Fix side effects:** cancelling a future that has already started does not interrupt the running provider call — the worker still occupies the pool until the provider answers. A per-provider socket timeout is still needed to bound the pool occupancy.
- **Discovered by:** B

---

#### F-WN-18-5  [P2] — The TrackResolver pool is never shut down before interpreter exit: queued resolutions *run* during shutdown instead of being cancelled

- **File:** `services/track_resolver.py:76` (`atexit.register(_resolver_pool.shutdown, wait=False, cancel_futures=True)`), `services/track_resolver.py:110-113` (`shutdown_executor`, no caller)
- **Confirmed:** yes (measured)
- **Description:** the pool is only stopped from an `atexit` hook. CPython runs `threading._register_atexit` callbacks (which is how `concurrent.futures.thread` joins the pool workers) **before** the `atexit` module callbacks, so by the time `_resolver_pool.shutdown(cancel_futures=True)` runs, the queued futures have already been executed.
- **Cause:** `core/app.py:571` explicitly shuts down `BaseMusicService` and `core/app.py:572-586` explicitly shuts down the per-provider pools — but `TrackResolver.shutdown_executor()` is never called, so the resolver pool relies solely on the (ineffective) `atexit` hook.
- **Trigger conditions:** closing the app while a recommendation/prefetch batch is queued or running.
- **User impact:** the app hangs at exit for as long as the orphaned queue takes — up to ~10 s per queued wave, because each queued task is a full local→SoundCloud→YouTube chain (`track_resolver.py:342-360`).
- **Evidence:**
  ```python
  # services/track_resolver.py:75-76
  _resolver_pool = _TrackResolverExecutor(max_workers=8, thread_name_prefix="TrackResolver")
  atexit.register(_resolver_pool.shutdown, wait=False, cancel_futures=True)
  ```
  ```
  # core/app.py:562-571
  def _shutdown_shared_pool():
      from services.base_service import BaseMusicService
      shutdown = getattr(BaseMusicService, "shutdown_executor", None)
      ...
  _step("base_service pool", _shutdown_shared_pool)
  ```
  Probe output (4 queued tasks on a 1-worker pool, `atexit`-registered `shutdown(cancel_futures=True)`):
  ```
    0.001s  task 0 START
    0.101s  main: 4 tasks submitted, 1 worker
    0.102s  threading._register_atexit (pool worker join starts)
    0.801s  task 0 END
    0.802s  task 1 START
    1.603s  task 1 END
    1.604s  task 2 START
    2.405s  task 2 END
    2.405s  task 3 START
    3.206s  task 3 END
    3.208s  atexit module callback        <-- the cancel_futures=True hook runs LAST
  === wall clock: 3.36 s ===
  ```
  All four queued tasks ran; the atexit cancellation arrived after the join had already drained the queue.
- **Reproduction / verification:** `wn18_probe5.py` (writes `probe7_order.txt`).
- **Suggested fix:** call `TrackResolver.shutdown_executor()` from `core/app.py::cleanup()` next to the other pool shutdowns; keep the `atexit` hook only as a backstop. Consider the same for `services/lyrics_service.py:193`.
- **Fix side effects:** cancelling the pool at cleanup means in-flight resolutions are dropped at shutdown — acceptable, the app is exiting.
- **Discovered by:** B

---

#### F-WN-18-6  [P2] — The proxy is installed on only 3 of 7 providers, although the UI promises a proxy "for bypassing YouTube and third-party services"

- **File:** `services/base_service.py:25-62` (the only proxy helper in the codebase); applied at `services/youtube_service.py:210`, `:236`, `:359`; `services/soundcloud_service.py:165`, `:256`, `:285`; `services/spotify_service.py:107`. **Not** applied in `services/itunes_gateway.py:64` (`session.get(url, …)`), `services/lastfm_service.py` (plain `requests`), `services/vk_service.py`, `services/yandex_service.py`.
- **Confirmed:** yes
- **Description:** `normalize_proxy_url` is a free function in the base module; every provider re-implements "read `auth.proxy_url` → normalise → assign `session.proxies`" on its own. The four providers that do not do this silently bypass the proxy.
- **Cause:** `BaseMusicService` has **no transport layer** — it owns caches, a thread pool and a pending-request table, but no HTTP session factory. There is therefore no single place where the proxy is (or must be) installed, and the duplication is exactly what let four providers miss it.
- **Trigger conditions:** any user who sets `auth.proxy_url` (the field exists precisely for blocked networks).
- **User impact:** iTunes catalogue lookups, Last.fm requests, VK and Yandex calls still leave the machine directly. The user's real IP is exposed to those services and the block they wanted to bypass is not bypassed there — contrary to the label in `ui/web_new_v2/index.html:1752-1753` ("Для обхода блокировок YouTube и сторонних сервисов").
- **Evidence:**
  ```
  ui/web_new_v2/index.html:1752-1753
     <div class="setting-label">HTTP/HTTPS Прокси</div>
     <div class="setting-sublabel">Для обхода блокировок YouTube и сторонних сервисов
                                   (например, http://127.0.0.1:1080)</div>
  ```
  Grep for `normalize_proxy_url` across `services/` returns hits **only** in `youtube_service.py`, `soundcloud_service.py`, `spotify_service.py` and `base_service.py` itself.
- **Reproduction / verification:** `grep -n "normalize_proxy_url" services/*.py`; then set a proxy, run a Last.fm/iTunes-backed feature and observe a direct egress.
- **Suggested fix:** give the base class a proxy-aware session factory (`def make_session(self, **kw)` that installs `session.proxies` from `normalize_proxy_url(self.settings.get('auth','proxy_url',''))`) and route every provider through it; the iTunes gateway and Last.fm client should use it too.
- **Fix side effects:** routing iTunes/Last.fm through the proxy increases latency for those calls and may hit proxy-side rate limits; the iTunes rate limiter (`services/itunes_gateway.py:21-22`) is time-based, not proxy-aware.
- **Discovered by:** B

---

#### F-WN-18-7  [P2] — A proxy change is stored but never applied to the live transports: the setting only takes effect after an app restart

- **File:** `services/spotify_service.py:107-108` (module-level `_session.proxies` assigned in `__init__`), `services/soundcloud_service.py:165-167` (session proxies in `__init__`), `services/youtube_service.py:210-212` (YTMusic session in `__init__`)
- **Confirmed:** yes
- **Description:** each provider reads `auth.proxy_url` **once**, at construction, and installs it on a long-lived session object. `core/api.py::save_setting` (`:2940-2953`) writes the value, syncs autostart and emits `setting_changed` — it does not reconfigure any provider transport. The only re-reading hook, `services/youtube_service.py:227 reset_ydl()`, has **no caller** in the repo (grep: `reset_ydl` matches only its definition).
- **Cause:** the proxy is applied at construction instead of being a property of a transport that can be rebuilt; there is no settings-change hook in the provider layer.
- **Trigger conditions:** the user edits the proxy in Settings while the app is running.
- **User impact:** the UI reports the value as saved, but traffic keeps using the old proxy (or direct egress) until the app is restarted. For a user whose proxy just died, this looks like the setting does nothing.
- **Evidence:**
  ```python
  # services/spotify_service.py:102-108
  # `_session` is module-level and shared by every instance, so this has to
  # ASSIGN rather than only overwrite when set: ...
  proxy = normalize_proxy_url(self.settings.get("auth", "proxy_url", "")) if self.settings else ""
  _session.proxies = {"http": proxy, "https": proxy} if proxy else {}
  ```
  ```python
  # core/api.py:2940-2953 (save_setting) — no service reconfiguration
  def save_setting(self, key: str, value, category: str = "app"):
      ...
      self._emit("setting_changed", {"category": category, "key": key, "value": value})
      return True
  ```
- **Reproduction / verification:** change the proxy in Settings, then trigger a Spotify/SoundCloud request and watch the egress (the module-level `_session.proxies` still holds the old value); restart the app and observe the change.
- **Suggested fix:** expose a `reconfigure()`/`reset_transport()` on the base class, call it from the settings-change path when `auth.proxy_url` changes, and let the Spotify module-level session be rebuilt rather than mutated.
- **Fix side effects:** rebuilding the YouTube YTMusic session drops its connection pool and in-flight requests on the shared `requests.Session`; the provider would need to re-warm its client id.
- **Discovered by:** B

---

#### F-WN-18-8  [P2] — `auth.proxy_url` is credential-bearing free text, stored in plaintext and returned verbatim by the bridge, while the neighbouring auth secrets are masked

- **File:** `core/api.py:240` (`_SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}`), `core/api.py:243-253` (`_mask_secrets`), `core/api.py:2922-2938` (`get_settings`); storage: `core/database.py:2117-2132` (`get_all_settings` reads the raw `settings` table, no decryption layer anywhere in `core/database.py`)
- **Confirmed:** yes
- **Description:** `auth.proxy_url` is a free-text field that routinely carries credentials (`http://user:pass@host:8080`). It is validated only for *shape* (`services/base_service.py:49-56`: scheme ∈ {http,https,socks4,socks4a,socks5,socks5h} and a non-empty hostname) — the userinfo is neither validated nor stripped. It is stored verbatim in the `settings` table and returned verbatim by `AppApi.get_settings()` / `get_all_settings()`, because it is not in `_SECRET_SETTING_KEYS`. `yandex_token` and `oauth_client_secret` *are* masked, so the handling of secrets in the same category is inconsistent.
- **Cause:** the masking list was curated per secret type and `proxy_url` was never classified as a secret, even though it can contain a password.
- **Trigger conditions:** a user who configures an authenticated proxy (common for commercial proxies).
- **User impact:** the proxy password sits in plaintext in `~/.nedotify/nedotify_storage.db` and crosses the bridge to the WebView unmasked. The threat model is local (any process running as the user, any backup/sync of `~/.nedotify/`), so this is not remote exposure — but it is materially weaker than the Yandex token's treatment in the same table.
- **Evidence:**
  ```python
  # core/api.py:239-253
  # Secrets never travel back to JS: the bridge answers with "" and a has_* flag.
  _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}
  ...
  masked[f"has_{key}"] = bool(masked[key])
  masked[key] = ""
  ```
  Probe output (validator accepts credential-bearing and LAN/loopback targets unchanged):
  ```
  'http://user:pass@proxy.example:8080'  -> 'http://user:pass@proxy.example:8080'
  'http://127.0.0.1:1080'                -> 'http://127.0.0.1:1080'
  'http://192.168.1.10:8080'             -> 'http://192.168.1.10:8080'
  'http://metadata.google.internal'      -> 'http://metadata.google.internal'
  'ftp://1.2.3.4:21'                     -> ''      (rejected: bad scheme)
  '127.0.0.1:1080'                       -> ''      (rejected: no scheme)
  ```
  Note: `normalize_proxy_url` accepting `http://127.0.0.1:<port>` and LAN addresses is **by design** — the UI placeholder is literally `http://127.0.0.1:1080` (`ui/web_new_v2/index.html:1755`) and a local VPN/proxy is the documented use case. The finding is about the *credentials* and the *unvalidated host*, not about loopback acceptance.
- **Reproduction / verification:** set `auth.proxy_url = "http://user:pass@127.0.0.1:1080"` in the DB, then call `AppApi.get_settings()` — the value comes back with the password intact, while `auth.yandex_token` comes back as `""` + `has_yandex_token: True`.
- **Suggested fix:** treat the proxy URL as a secret-bearing field: split it into "display value" (host:port) and "credential" parts, mask the credential at the bridge the way `yandex_token` is masked, and keep the credential encrypted at rest if the DB ever grows one.
- **Fix side effects:** masking the credential breaks the settings input's round-trip (`ui/web_new_v2/js/settings.js:394-399` writes the raw field value back) unless the UI is changed in step; `_is_empty_secret_write` (`core/api.py:267-269`) already handles the "blank must not wipe" case for the masked keys and would need to cover this one.
- **Discovered by:** B

---

#### F-WN-18-9  [P2] — The base class declares a provider contract that Spotify violates; the bridge compensates with a name check and a `TypeError` probe

- **File:** `services/base_service.py:320-329` (the declared contract), `services/spotify_service.py:110` (the violation), `core/api.py:2217-2225` (the compensation)
- **Confirmed:** yes
- **Description:** `BaseMusicService.search` is declared as `search(self, query, max_results=20, callback=None, error_callback=None)` and `get_stream_url(self, url, callback=None, error_callback=None, **kwargs)`, but both bodies are `raise NotImplementedError` — nothing enforces them. `SpotifyService.search` is `search(self, query, callback=None, error_callback=None, limit=20, result_type=None, is_current=None)`: the second positional parameter is `callback`, not `max_results`, and the count is called `limit` rather than `max_results`. `SpotifyService` is also the only provider that accepts `is_current`.
- **Cause:** the base class is a *bag of helpers*, not a contract: no `abc.ABC`/`abstractmethod`, no `typing.Protocol`, and the two "interface" methods are inert stubs.
- **Trigger conditions:** any caller that follows the declared contract positionally, e.g. `svc.search(query, 20)`.
- **User impact:** on Spotify that call passes `20` as the *callback*; the results are never delivered and the callback path raises `TypeError: 'int' object is not callable` inside the worker (logged, not surfaced). No current caller does this — all use keywords — so the defect is latent, but the contract the base class publishes is wrong.
- **Evidence:**
  ```
  BaseMusicService.search  (self, query: str, max_results: int = 20, callback=None, error_callback=None)
  YouTubeService.search     (self, query, max_results=20, result_type=None, callback=None, error_callback=None, prefetch=False)
  SoundCloudService.search  (self, query, max_results=20, callback=None, error_callback=None)
  SpotifyService.search     (self, query, callback=None, error_callback=None, limit=20, result_type=None, is_current=None)   <-- 2nd positional = callback
  YandexService.search      (self, query, max_results=20, callback=None, error_callback=None)
  ```
  ```python
  # core/api.py:2217-2225 — the bridge works around the missing contract
  if name == "spotify":
      srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error, is_current=is_current)
  elif result_type:
      try:
          srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error)
      except TypeError:
          srv.search(query, callback=_on_success, error_callback=_on_error)
  ```
- **Reproduction / verification:** `wn18_probe3.py` section 6b; or `inspect.signature(SpotifyService.search)` vs `inspect.signature(BaseMusicService.search)`.
- **Suggested fix:** define the provider surface as a `typing.Protocol` (or an ABC with `search`/`get_stream_url` as abstract methods) using **keyword-only** parameters, make every provider conform (`SpotifyService.search` → `max_results`), and delete the `if name == "spotify"` / `except TypeError` workarounds in `core/api.py`.
- **Fix side effects:** touching `SpotifyService.search`'s parameter order is a public-signature change for its direct callers (`core/api.py:2218`, `services/spotify_service.py` internals, tests) — they must be updated in the same change.
- **Discovered by:** B

---

#### F-WN-18-10  [P2] — The stream and search caches are class-level and shared: one provider's traffic evicts another provider's entries out of a single global budget

- **File:** `services/base_service.py:126-134`
- **Confirmed:** yes
- **Description:** `_stream_cache` (2000 entries) and `_search_cache` (300 entries) are **class attributes** of `BaseMusicService`, so every provider and every instance writes into the same two dicts, guarded by the same lock and bounded by the same LRU budget. Keys are namespaced by prefix (`yt_search:`, `yt_related:`, `sc_search:`, `sc_playlist:`, `sc_rel:`, `soundcloud:`, `ya_search:`, `spotify_search:`), so there is **no key collision** — I verified this. The *budget* is nevertheless global.
- **Cause:** the caches were introduced on the base class for convenience rather than as per-provider namespaces; `_cache_recent` (`base_service.py:223-241`) evicts the globally oldest entry regardless of which provider owns it.
- **Trigger conditions:** a burst of searches on one provider (e.g. the user typing in the SoundCloud filter, or the recommendation feed filling the 300-entry search cache with `recommendation:feed:*` keys).
- **User impact:** one provider's cache is silently evicted by another's traffic → repeated provider requests → more traffic through the user's proxy, more provider rate-limit pressure, and a slower first result for the evicted provider.
- **Evidence:**
  ```python
  # services/base_service.py:126-134
  _stream_cache: Dict[str, Any] = {}
  _MAX_CACHE_SIZE = 2000
  _SEARCH_CACHE_TTL = 300
  _search_cache: Dict[str, Dict[str, Any]] = {}
  _SEARCH_CACHE_MAX_SIZE = 300
  ```
  Probe output:
  ```
  _search_cache keys: ['yt_search:q:None:20', 'sc_search:q:20']
  -> one class-level dict holds every provider's search results (namespaced by prefix)
  _MAX_CACHE_SIZE (stream) = 2000  _SEARCH_CACHE_MAX_SIZE = 300
  -> a single provider can evict another provider's entries (shared budget)
  ```
  `services/recommendation_service.py:478` and `:467` store the *entire recommendation feed* (up to `max_results` track dicts) in this same 300-entry search cache under the key `recommendation:feed:<sha>`.
- **Reproduction / verification:** `wn18_probe2.py` section PROBE 5; then fill the search cache with 300 `sc_search:*` entries and observe the `yt_search:*` entries disappear.
- **Suggested fix:** give each provider its own cache namespace object (a small `TTLCache` instance per provider) instead of class-level dicts; keep a shared pool only if a global budget is genuinely wanted, and make it per-provider.
- **Fix side effects:** `core/playback_recovery.py:87-92` and `services/yandex_service.py:93-99` reach directly into `BaseMusicService._stream_cache` / `_search_cache` and pop keys by prefix; splitting the caches breaks those two call sites (they must move to a public `invalidate(prefix)` API on the base class).
- **Discovered by:** B

---

#### F-WN-18-11  [P2] — The shared 8-worker pool serves the artist-profile, Last.fm and recommendation subsystems, and one task can hold a worker for minutes

- **File:** `services/base_service.py:124` (`_executor = _SharedExecutor(max_workers=8)`), used by `services/artist_service.py:338` and `:386`, `services/lastfm_service.py:389/424/447/485/520/550/583/612`, `services/recommendation_service.py:491/566/624/674/866/899`
- **Confirmed:** yes
- **Description:** only YouTube, SoundCloud, Spotify and Yandex override `_executor` with their own pool (`youtube_service.py:195`, `soundcloud_service.py:132`, `spotify_service.py:100`, `yandex_service.py:30`). Everything else inherits the single class-level 8-worker pool: `ArtistService`, `LastFMService`, `RecommendationService`, `ITunesGateway`, `CatalogService`. One submitted task can occupy a worker for a very long time — `ArtistService.get_avatars` (`artist_service.py:329-339`) resolves **up to 30 artist names sequentially** in one task, and each `CatalogService.resolve_artist` carries an 8-second deadline (`catalog_service.py:103-104`), i.e. up to ~240 s in a single pool worker.
- **Cause:** the shared pool is sized as if all tasks were short provider calls; the artist/recommendation tasks are long fan-outs, and the pool has no per-subsystem quota or priority.
- **Trigger conditions:** the UI requests avatars for a list of artists (e.g. an artist page with many names) while a recommendation feed is being generated.
- **User impact:** the artist profile and the recommendation feed starve each other. `ArtistService.get_profile` is submitted to the same pool (`artist_service.py:386`) and simply queues behind the long-running fan-outs — the profile panel stays empty and the recommendation request times out.
- **Evidence:**
  ```python
  # services/base_service.py:124
  _executor = _SharedExecutor(max_workers=8)
  ```
  ```python
  # services/artist_service.py:329-339
  def get_avatars(self, names, callback=None):
      def task():
          mapping = {}
          for name in list(dict.fromkeys(n.strip() for n in names or [] if isinstance(n, str) and n.strip()))[:30]:
              resolved = self.catalog.resolve_artist(name)      # 8 s deadline each
              ...
      if self.submit(task) is None and callback:
          callback({})
  ```
  ```python
  # services/catalog_service.py:103-104
  def resolve_artist(self, name, artist_ref=None, is_current=lambda: True, _deadline=None):
      deadline = _deadline if _deadline is not None else time.monotonic() + 8
  ```
- **Reproduction / verification:** submit `ArtistService.get_avatars` with 30 names against a stubbed catalogue that sleeps 8 s, then submit `get_profile`; the profile callback never arrives while the avatars task is running. The pool size is visible at `services/base_service.py:124`.
- **Suggested fix:** give `ArtistService` and `RecommendationService` their own bounded pools (the pattern already used for `_candidate_executor`, `recommendation_service.py:57`), or split `get_avatars` into one task per name so the pool can interleave.
- **Fix side effects:** more threads; the recommendation fan-out already bounds itself with a 12 s deadline (`recommendation_service.py:349`), so the starvation is mostly one-sided.
- **Discovered by:** B

---

#### F-WN-18-12  [P2] — `BaseMusicService` is a helper bag: a YouTube-specific parser sits in the generic base class, and the base class's own cache/executor primitives are bypassed by four subclasses

- **File:** `services/base_service.py:278-313` (`_parse_yt_entry`), `services/base_service.py:65-118` (`_SharedExecutor`), shadowed at `services/youtube_service.py:195`, `services/soundcloud_service.py:132`, `services/spotify_service.py:100`, `services/yandex_service.py:30`
- **Confirmed:** yes
- **Description:** two symptoms of the same root cause. (a) `_parse_yt_entry` is a yt-dlp entry parser that hardcodes YouTube semantics (`'source': 'youtube'`, `'Unknown Artist'`, the `img.youtube.com` cover fallback) and has **no callers** anywhere in the repository (grep: the only match is its own definition). (b) The base class carefully wraps its executor in `_SharedExecutor` so that `submit()` returns `None` instead of raising `RuntimeError: cannot schedule new futures after interpreter shutdown` — but four subclasses replace `_executor` with a raw `ThreadPoolExecutor`, which restores exactly the failure mode the wrapper was written to prevent.
- **Cause:** `BaseMusicService` mixes four unrelated responsibilities — a shared thread pool, two shared caches, a pending-request coalescer and a yt-dlp entry parser — and offers no transport layer, no contract and no protected way to extend it, so subclasses reach around it.
- **Trigger conditions:** (a) is dead code today; (b) fires during interpreter teardown, when a provider's `search()`/`get_stream_url()` is entered after the pool has been shut down — `youtube_service.py:512`, `:700`, `:769`, `:1069`, `soundcloud_service.py:402/491/846`, `spotify_service.py:173/214/244` and `yandex_service.py:158/252` all call `self._executor.submit(...)` with no `RuntimeError` guard.
- **User impact:** (b) surfaces as a "search could not start" / silent empty result at teardown (`core/api.py:2226-2228` catches it and emits an empty result set) rather than a clean shutdown; a provider call that races the shutdown silently returns nothing.
- **Evidence:**
  ```python
  # services/base_service.py:278-313 (dead code in the generic base class)
  @staticmethod
  def _parse_yt_entry(entry: dict) -> Optional[dict]:
      """Convert a yt-dlp entry dict into a standardized track dictionary."""
      ...
      return {
          'title': entry.get('title', 'Unknown Title'),
          ...
          'source': 'youtube',
          ...
      }
  ```
  ```python
  # services/base_service.py:65-73 — the protection the subclasses bypass
  class _SharedExecutor:
      """Lazy, shutdown-safe stand-in for the shared ThreadPoolExecutor.
      ... `submit()` returns None instead of raising once the pool has been shut down
      or the interpreter is finalizing, which is what used to produce
      `RuntimeError: cannot schedule new futures after interpreter shutdown` ...
      """
  ```
  ```python
  # services/youtube_service.py:195 — shadows the class attribute with a raw pool
  self._executor = ThreadPoolExecutor(max_workers=10)
  ```
- **Reproduction / verification:** `grep -rn "_parse_yt_entry" .` → only `services/base_service.py:279`. For (b): shut a provider's pool down and call `provider.search("x")` → `RuntimeError` from `ThreadPoolExecutor.submit`.
- **Suggested fix:** delete `_parse_yt_entry` (or move it to `services/youtube_service.py`); make `_executor` a read-only class attribute and give each provider its own `_SharedExecutor` instance instead of shadowing the shared one; make `search`/`get_stream_url` abstract so the contract is enforced.
- **Fix side effects:** removing the instance-level pools changes the per-provider worker counts (10/10/5/3 today) and the `_SharedExecutor` laziness — the per-provider pools would then also be created on first submit rather than in `__init__`, which shifts a little construction cost out of the startup path.
- **Discovered by:** B

---

#### F-WN-18-13  [P3] — `artist_aliases()` is rebuilt on every comparison, inside candidate loops

- **File:** `services/artist_identity.py:13-32`; hot callers `services/music_matching.py:48-52` (`artist_matches`), `services/catalog_service.py:143`, `services/lyrics_lookup.py:46`
- **Confirmed:** yes (measured)
- **Description:** `artist_matches(wanted, offered, settings)` calls `artist_aliases(settings)` on **every** invocation. `artist_aliases` copies `DEFAULT_ALIASES`, re-reads two settings keys and recomputes a SHA-256 digest for every artist binding (`artist_identity.py:29-31`). `services/catalog_service.py:143` calls `artist_matches` once per candidate.
- **Cause:** the alias map is a pure function of the settings, but it is recomputed at the innermost level instead of being hoisted or cached per settings revision.
- **Trigger conditions:** an artist lookup with many candidates, on a user who has configured artist aliases/bindings (the `personalization` settings category).
- **User impact:** the artist-profile path pays a measurable latency penalty. It is not user-visible on its own, but it sits on the artist-page critical path and inside the catalogue single-flight critical section.
- **Evidence:**
  ```python
  # services/artist_identity.py:27-31
  source = next((s for s in ('youtube', 'itunes') if refs.get(s)), None)
  if source:
      digest = hashlib.sha256(str(refs[source]).encode()).hexdigest()
      lookup = ('@context:' + hashlib.sha256(key.encode()).hexdigest()) if binding.get('context') else name_key(key)
      aliases[lookup] = '@catalog:' + source + ':' + digest
  ```
  Measured (`wn18_probe2.py` PROBE 2):
  ```
  bindings=  0   artist_aliases() = 0.001 ms/call
  bindings= 50   artist_aliases() = 0.082 ms/call
  bindings=200   artist_aliases() = 0.351 ms/call
  ```
  With 200 candidates and 200 bindings that is ~70 ms of pure SHA-256 per artist lookup.
- **Reproduction / verification:** `wn18_probe2.py` PROBE 2.
- **Suggested fix:** build the alias map once per request (or memoise it on the settings revision) and pass it into `artist_matches`/`canonical_artist`; `canonical_artist(value, aliases)` already accepts a pre-built map.
- **Fix side effects:** a cached alias map must be invalidated when the user edits `personalization.artist_aliases` / `artist_bindings`; the settings revision counter or a `settings.get` version would provide that.
- **Discovered by:** B

---

#### F-WN-18-14  [P3] — `similarity()` re-normalises both arguments on every call, and callers sort by it

- **File:** `services/music_matching.py:21-35`; sort-key callers `services/lyrics_lookup.py:127` and `:155`
- **Confirmed:** yes (measured); **impact is small**
- **Description:** `similarity(want, got)` calls `normalize()` on both arguments on every invocation. The callers in `lyrics_lookup.py` use it as a `sorted()` key, so the *same constant* left-hand string is normalised `O(n log n)` times per sort.
- **Cause:** the module exposes only the two-argument form; there is no "normalise once" variant.
- **Trigger conditions:** sorting a candidate list of songs by similarity (lyrics lookup), and the per-candidate `similarity` calls in `services/catalog_service.py:144`/`:201`/`:236`.
- **User impact:** measured below the noise floor — a 50-candidate sort costs 0.91 ms, of which normalisation is ~8 %. I am reporting it because the brief asks whether the strings are pre-normalised once; the answer is "no", but the practical consequence is minor.
- **Evidence:**
  ```python
  # services/music_matching.py:27-35
  def similarity(want, got):
      a, b = normalize(want), normalize(got)
      if not a or not b:
          return 0.0
      if a == b:
          return 1.0
      if min(len(a.replace(' ', '')), len(b.replace(' ', ''))) <= 4:
          return 0.0
      return SequenceMatcher(None, a, b, autojunk=False).ratio()
  ```
  ```python
  # services/lyrics_lookup.py:127
  for song in sorted(candidates, key=lambda s: (similarity(form['metadata']['base_title'], s.get('name')),
  ```
  Measured (`wn18_probe2.py` PROBE 3):
  ```
  similarity() = 28.0 us/call (2x normalize + SequenceMatcher)
  normalize()  =  2.3 us/call  -> ~8% of similarity() is normalisation
  sorted(50 candidates, key=similarity) = 0.91 ms  (~282 similarity calls)
  ```
- **Reproduction / verification:** `wn18_probe2.py` PROBE 3.
- **Suggested fix:** add `normalize_once(value) -> str` plus `similarity_normalized(a, b)`, and use them for sort keys.
- **Fix side effects:** two normalisation paths can drift apart; keep `similarity` as a thin wrapper over the new pair so there is one implementation.
- **Discovered by:** B

---

#### F-WN-18-15  [P3] — The single class-level `_cache_lock` is the mutex for five unrelated subsystems

- **File:** `services/base_service.py:125`; reused at `services/catalog_service.py:45` and `:62` (WN-24), `services/itunes_gateway.py:15` (WN-21), `services/lastfm_service.py:228/243/262/287` (WN-21), `services/recommendation_service.py:65/341/362/508/523/528` (WN-23), `services/yandex_service.py:93` (WN-21)
- **Confirmed:** yes — and the *hypothesis* the brief asked me to test ("the shared lock is held across network I/O, serialising every provider request globally") is **FALSE**
- **Description:** `BaseMusicService._cache_lock` is an `RLock` created once on the class. Because subclasses inherit it, five subsystems that have nothing to do with the stream/search caches use it as their own mutex — including the iTunes rate limiter, which uses it as the lock of a `threading.Condition`. `services/catalog_service.py:62-69` even holds it across `copy.deepcopy` of a catalogue result.
- **Cause:** the base class is the only thing every subsystem inherits, so it became the default place to get "a lock".
- **Trigger conditions:** any concurrent catalogue / lyrics / recommendation / provider activity.
- **User impact:** short critical sections, so no measurable stall today; the risk is structural — a future change that holds the lock across I/O in any one subsystem would serialise the entire app's provider traffic behind one global mutex.
- **Evidence (the hypothesis is refuted):**
  ```python
  # services/base_service.py:125
  _cache_lock = threading.RLock()
  ```
  ```python
  # services/itunes_gateway.py:15 — a rate limiter built on the global cache lock
  class ITunesGateway(BaseMusicService):
      _condition = threading.Condition(BaseMusicService._cache_lock)
  ```
  Probe (PROBE 1) — the lock is **free** while a provider performs its network call:
  ```
  lock was FREE during the provider network call: True
  -> the shared _cache_lock is NOT held across network I/O
  ```
  I read every `with self._cache_lock` / `with cls._cache_lock` site in `services/` (21 sites) plus `core/playback_recovery.py:87`: in all of them the network call is **outside** the critical section (e.g. `youtube_service.py:403` `self._ytmusic.search(...)` runs after `get_search_cache` released the lock; `lastfm_service.py:233-250` and `:268-274` do their SQLite work outside the lock).
- **Reproduction / verification:** `wn18_probe2.py` PROBE 1.
- **Suggested fix:** give each subsystem its own lock (`self._lock = threading.RLock()` in `CatalogService`, `LastFMService`, `RecommendationService`, `ITunesGateway`) and reserve `BaseMusicService._cache_lock` for the two shared caches only; then the rule in `AGENTS.md` ("a new shared field joins its class's existing lock") stays true per class.
- **Fix side effects:** `services/itunes_gateway.py:15` would need its own `Condition`; `core/playback_recovery.py:87-92` (WN-15) reaches into `BaseMusicService._stream_cache` and would need a public invalidation API instead.
- **Discovered by:** B

---

### 3. Clean areas

- **`normalize_proxy_url` shape validation** (`services/base_service.py:25-62`): correctly rejects the failure mode that caused a real outage (a bare token such as `"AuraQA46638"` that `requests`/yt-dlp would silently prepend `http://` to) — `ftp://…`, `"127.0.0.1:1080"` and `""` all return `""`, and the rejection is logged with the offending value (`base_service.py:57-61`). Pinned by `tests/test_proxy_url_validation.py:25-59`. Accepting `http://127.0.0.1:<port>` and LAN addresses is **correct** — it is the documented use case (`ui/web_new_v2/index.html:1755`).
- **No TLS verification is disabled inside `BaseMusicService`** — the base class performs no HTTP at all. (For completeness: `verify=False` / `CERT_NONE` appear nowhere in the repo; yt-dlp's own `"nocheckcertificate": True` does appear in `services/youtube_service.py:308` and `services/soundcloud_service.py:276` — **WN-19 / WN-20 own that**, and it applies to the requests that carry the user's `cookiefile`/`cookiesfrombrowser`, so it deserves a finding in those areas.)
- **The `_cache_lock` is never held across provider network I/O** — the brief's main concurrency hypothesis is refuted (PROBE 1). Every critical section is a short dict operation.
- **Cache key namespacing is sound** — every provider prefixes its keys (`yt_search:`, `yt_related:`, `sc_search:`, `sc_playlist:`, `sc_rel:`, `soundcloud:`, `ya_search:`, `spotify_search:`), so the shared class-level caches cannot serve one provider's results for another's query (verified in PROBE 5).
- **LRU eviction is genuinely LRU, not FIFO** — `services/base_service.py:223-241` drops and re-inserts the key around every access, preserving the original timestamp so a read does not extend the TTL. Pinned by `tests/test_cache_lru.py:39-113`; the raw-value tolerance in `get_from_cache`/`get_search_cache` (`:194-214`, `:251-263`) is also pinned (`tests/test_cache_lru.py:144-168`).
- **`get_from_cache` respects the 6 h stream TTL and `stream_url_expired()`** — `services/base_service.py:201-204` with `utils/stream_urls.py:7-26`; a dead googlevideo URL is dropped instead of being served into the proxy self-heal path.
- **The shared executor's shutdown path is sound in itself** — `services/base_service.py:82-118` returns `None` instead of raising when the pool is gone or the interpreter is finalising, and `core/app.py:562-586` shuts down the base pool **and** every per-provider pool. (The gap is `TrackResolver` — F-WN-18-5.)
- **No provider API key is hardcoded** — `services/lastfm_service.py:19-23` resolves keys at runtime from `LASTFM_API_KEY` or the settings, and `DEFAULT_ALIASES` (`artist_identity.py:6`) contains no secret.
- **`services/artist_identity.py` alias resolution is loop-safe** — `canonical_artist` (`:48-54`) keeps a `visited` set, so a cyclic alias chain terminates instead of hanging.
- **`services/music_matching.py` `similarity()` short-string guard** — `music_matching.py:33-34` returns `0.0` for titles of ≤ 4 non-space characters unless they are exactly equal, which prevents a 4-character title from fuzzy-matching an unrelated one. Verified: `similarity('Love','Lovers') == 0.0`.

### 4. Coverage gaps

- **I did not execute the pytest suite.** The findings above are backed by targeted runtime probes and by reading the code; I did not confirm that the existing suite is green, nor that any of my findings currently fails a test. A test that pins the *current* behaviour of a defective path would need to be updated together with the fix.
- **`tests/test_resolve_fallback_budget.py` does not cover `services/track_resolver.py` at all.** It asserts on `core.app._SC_FALLBACK_BUDGET_S` (a constant in WN-02) and then re-implements the guard inside the test itself (`test_resolve_fallback_budget.py:45-67` defines its own `FakeApp._on_err_impl`, `:90-97` its own `while` loop). **It tests a copy of the logic, not the shipped cascade** — so the "budget" it appears to guarantee is not enforced by the code it names. The TrackResolver chain (F-WN-18-4) is untested.
- **No test pins the shared-lock-across-network-call property.** Nothing asserts that `_cache_lock` is free during provider I/O; I established it empirically (PROBE 1) but there is no regression guard. A test that swaps `_cache_lock` for a wrapper recording hold-time and asserts the maximum hold is sub-millisecond would lock the property in.
- **No test covers the provider-artist-list case** (F-WN-18-1): `tests/test_track_resolver_matching.py` exercises only the **local DB** path (`_search_local`), where the artist comes from a DB column; the provider path (`_search_soundcloud` / `_search_youtube`) is covered by exactly one test (`test_rejected_local_row_falls_through_to_matching_provider`, `:121-136`) with a single-artist provider row.
- **No test covers the version-stripping behaviour** (F-WN-18-2) or the empty-title behaviour (F-WN-18-3) at the resolver level. `tests/test_catalog_verification.py:139-142` covers `music_matching` directly but not the resolver's use of it.
- **`tests/test_resolver_state.py` is about `core/resolver.py::StreamResolver` (WN-15), not WN-18**, and `tests/test_lazy_service_deadlock.py` is about `core/app.py::_service_lock` (WN-02) — neither exercises any WN-18 code. `tests/test_provider_loading.py` and `tests/test_provider_performance.py` do exercise the base-class machinery (pending-request coalescing, cache key with `max_results`, shared extraction) but only with the *happy* path.
- **I did not measure end-to-end app latency** (no run of the real app, per the ground rules). The performance figures quoted here are micro-measurements of the functions in question.
- **The `yt-dlp` `"nocheckcertificate": True` flag** (`youtube_service.py:308`, `soundcloud_service.py:276`) disables certificate verification on the requests that carry the user's browser cookies. I have **not** confirmed whether it is reachable in a hostile-network scenario in practice, and whether the packaged build overrides it — that belongs to WN-19/WN-20. I flag it here only because the brief asked whether TLS verification is disabled anywhere in the provider layer.
- **Whether the `auth.proxy_url` value is ever surfaced outside the settings UI** (logs, crash reports) was not exhaustively checked; `core/api.py:2952` emits `setting_changed` with the raw value to the WebView event bus, and `logger.warning` in `base_service.py:57-61` logs the raw value on rejection.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — Make `BaseMusicService` a real contract, not a helper bag.** Today it owns (i) a shared thread pool, (ii) two shared caches, (iii) a pending-request coalescer, (iv) a dead YouTube entry parser, and (v) two `raise NotImplementedError` stubs. It owns **no** transport, no HTTP session, no retry policy and no timeout policy — every provider therefore re-implements all of those (three copies of the proxy installation, four different session constructions, four different socket timeouts). A `Provider` protocol (`search`, `get_stream_url`, `available`, keyword-only arguments) plus a `Transport` helper (session factory with the proxy installed, a shared timeout budget, a retry policy) would remove the duplication and make F-WN-18-6/F-WN-18-7/F-WN-18-9 structural rather than accidental.

**ARCH-2 — One shared lock is not a contract.** `AGENTS.md` states "a new shared field joins its class's existing lock". In practice, inheriting `BaseMusicService` *is* how five unrelated subsystems ended up sharing one mutex (`catalog_service.py:45/62`, `itunes_gateway.py:15`, `lastfm_service.py:228…`, `recommendation_service.py:65…`, `yandex_service.py:93`). The rule needs a companion rule: a subsystem that inherits a base class for helpers must **not** inherit its lock — it must declare its own.

**ARCH-3 — Cache ownership should follow the provider.** The two class-level caches make the cache *address space* global while the cache *budget* is also global, so providers evict each other (F-WN-18-10). A per-provider `TTLCache` object would give each provider its own budget and make invalidation a method call rather than a prefix scan — which is exactly what `core/playback_recovery.py:87-92` (WN-15) and `services/yandex_service.py:93-99` (WN-21) currently do by reaching into `BaseMusicService._stream_cache` / `_search_cache` and matching prefixes. That reach-in is the clearest symptom of the missing API.

**ARCH-4 — The matching policy is spread over three modules with three different thresholds.** `services/track_resolver.py` uses `TRACK_MATCH_MIN_SCORE = 0.6` on a *raw string*; `services/lyrics_service.py` uses `_TITLE_MATCH_MIN = .85`; `services/catalog_service.py` uses `.75` for artists and `.85` for titles. `services/music_matching.py` already owns the correct primitives (`normalize`, `credits`, `artist_matches`, `title_metadata`), but `track_resolver` bypasses them by importing `LyricsService._title_match_score` (`track_resolver.py:241-244`) — a *lyrics* service reaching into a *matching* service, inverting the dependency direction. A single `music_matching` entry point (`match_track(requested, offered, settings) -> MatchResult`) with one documented threshold policy would fix F-WN-18-1/F-WN-18-2/F-WN-18-3 at once and remove the lyrics→resolver coupling.

**ARCH-5 — Version identity should be part of the match key, not a decoration.** `music_matching.title_metadata` already extracts a `version` field (`music_matching.py:79-87`) — and then throws it away for matching purposes by stripping it from `base_title` (`:88-92`). Matching on `(base_title, version)` instead of `base_title` alone is strictly more precise and costs nothing; the version vocabulary just needs normalising (`"Remix"` vs `"rmx"` vs `"bootleg"` are already folded by `VERSION_PATTERNS`).

**ARCH-6 — The base class's session/transport policy should be re-read on demand, not captured at construction.** Proxy and cookie settings are read once in `__init__` (`youtube_service.py:210`, `soundcloud_service.py:165`, `spotify_service.py:107`) and then live in a long-lived session. A settings-change hook that invalidates the transport would make `auth.proxy_url` and `auth.cookies_file_path` live settings instead of restart-required ones (F-WN-18-7).

**ARCH-7 — A resolution needs a deadline object, not a chain of fixed waits.** `TrackResolver` uses two hard-coded 5 s waits (`track_resolver.py:270`, `:312`) and a separate 10 s batch timeout (`:92`), while `core/app.py` has a completely separate `_SC_FALLBACK_BUDGET_S` budget for a different cascade. A single `Deadline` value threaded through the chain (local → SC → YT) — the pattern `services/catalog_service.py:34-42` already uses — would make the total cost of a miss explicit and give the caller one number to reason about.

**ARCH-8 — `TrackResolver` should be a singleton-ish service, not constructed per operation.** `core/downloader.py:515-522` builds a fresh `TrackResolver` for every download, so the 300 s resolution memo (`track_resolver.py:88`) is always cold; `services/recommendation_service.py:56` keeps one long-lived instance and therefore benefits. The same track resolved by the downloader and by the feed is resolved twice. Constructing the resolver once in `AppCore` (WN-02) and passing it to the downloader would make the memo effective — the downloader is the caller, so the fix belongs there, but the memo only pays off if the resolver is shared.

**ARCH-9 — `artist_aliases` should be a value, not a computation.** `artist_identity.py:13-32` is a pure function of the settings but is recomputed at the innermost comparison (F-WN-18-13). `canonical_artist` and `artist_matches` already take a pre-built alias map; the base class could own a cached, revision-invalidated instance of it and hand it out.

**ARCH-10 — The provider dispatch in the bridge is name-based and special-cased.** `core/api.py:2164-2230` resolves a provider with `getattr(self._core, name, None)` where `name` comes from the caller-supplied `source` argument, and then special-cases Spotify by name and probes the signature with `except TypeError`. That is the symptom of the missing provider contract (F-WN-18-9). An explicit registry (`{"youtube": YouTubeService, "soundcloud": SoundCloudService, …}`) plus a validated `source` argument would remove both the special case and the unvalidated `getattr`.
