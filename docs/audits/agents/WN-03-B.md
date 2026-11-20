## AREA WN-03 — Bridge core: init, `_emit`, SSRF guard, error logging, offline interception — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py` **L1–520** (full in-scope range: module header/imports/constants, SSRF helpers
  L93–195, `_extract_first_url` L198–220, `_as_float` L223–230, `_mask_secrets` L239–253,
  `_bridge_write_error` L256–264, `_is_empty_secret_write` L267–269,
  `_normalize_cache_quota` L272–327, `_missing_local_file_message` L330–339,
  `class AppApi` L342–512: `__init__` L345–392, `_UNWRAPPED` L397–399,
  `_install_bridge_error_logging` L401–444, `cleanup` L446–459, `_offline_bridge_result` L461–512).
- `core/api.py` out-of-scope ranges read **only to trace the contract stated in L239–253**:
  L1109–1160 (`open_url`, `open_external_url`, `_emit`), L1830–1919 (`get_setting`, `set_setting`),
  L2340–2419 (`import_external_playlist`), L2900–2989 (`get_settings`, `save_setting`,
  `get_settings_by_category`), L3185–3224 (`_lyrics_lock` / `_lyrics_cascade_count`).
- `core/proxy.py` L20–45, L355–444 (`SafeRedirectHandler`, `_safe_urlopen`), L480–539 (token auth),
  L625–664 (HEAD gate), L820–1089 (the three `_is_ssrf_safe_url` gates + `_safe_urlopen` call).
- `utils/url_safety.py` L1–37 (the *second* SSRF guard).
- `utils/cache_manager.py` L390–449 (`save_cover_from_url` + its own redirect handler).
- `core/settings.py` L1–589 (schema, `SettingsManager.get/set/get_category`).
- `core/offline.py` L1–77 (`is_offline`, `available_track(s)`).
- `core/user_errors.py` L1–24 (`describe_error`).
- `core/app.py` L500–586 (`AppCore.cleanup`).
- `main.py` L150–269 (the `socket.getaddrinfo` DoH patch), L378–427 (`on_loaded`).
- `core/plugins.py` L8–49 (how `general.plugins_enabled` is read).
- `services/base_service.py` L20–79 (`normalize_proxy_url` — proves `auth.proxy_url` may carry credentials).
- `ui/web_new_v2/js/settings.js` L368–398, L713–752, L1035–1053; `js/feature-controls.js` L1–135;
  `js/main.js` L385–434; `js/events.js` L305–334; `js/artist_profile.js` L135–153;
  `js/search.js` L600–615; `js/main.js` L124–165 (bridge call signatures).
- `tests/test_api_audit_b.py` L1–719, `tests/test_emit_thread_safety.py` L1–168,
  `tests/test_media_guard_f3.py` (guard expectations), `tests/test_frontend_js.py` L82–113.

**Callees traced into other areas** (defect attributed to the owner, not duplicated here)

- `core/proxy.py` → `SafeRedirectHandler` / `_safe_urlopen` — owner **WN-11** (redirect re-validation is
  implemented correctly; see Clean areas).
- `core/proxy.py::_authorized` / `_authenticate` — owner **WN-11** (token gate, fail-closed).
- `core/settings.py::SettingsManager` — owner **WN-14**.
- `core/user_errors.py::describe_error` — owner **WN-16**.
- `core/offline.py::is_offline` — owner **WN-15**.
- `core/plugins.py` — owner **WN-02**.
- `ui/web_new_v2/js/settings.js` / `js/feature-controls.js` — owner **WN-30**.
- `core/download_transfer.py` / `core/downloader.py` — owner **WN-13** (they use the *stricter*
  `utils/url_safety.is_safe_media_url`, so they are not affected by the api.py guard defects).

**Verification harnesses run** (read-only, written under `%TEMP%`, never into the repo):
`verify_ssrf.py`, `verify_toctou.py`, `verify_readonly.py`, `verify_perf.py` — all run with
`& ".venv_win\Scripts\python.exe"`.

---

### 2. Findings

#### F-WN-03-1  [P2] — The SSRF guard fails **open** when DNS resolution raises, and the "safe" verdict is then cached for 120 s

- **File:** `core/api.py:133-158` (also `core/api.py:124-130` for the cache write)
- **Confirmed:** yes
- **Description:** `_dns_resolves_to_public_ip` initialises `verdict = True` and only ever turns it
  `False` inside the `try` block. When `socket.getaddrinfo()` raises, the `except` branch falls back to
  a *string prefix* test that covers only `169.254.`, `10.`, `192.168.` and `127.`. Every other
  unresolvable host — and every host in `172.16.0.0/12` or the CGNAT range `100.64.0.0/10` — is
  reported as **public / safe**. That verdict is then written into the 120-second memo
  (`_ssrf_cache_put`), so a single transient resolver failure poisons the cache and the guard stops
  re-resolving that host for two minutes.
- **Cause:** the function treats "could not determine" as "safe" instead of "unsafe". The two failure
  modes (unresolvable ⇒ `True`, and private ⇒ `False`) are conflated into one boolean that starts at
  the permissive value.
- **Trigger conditions:** any `socket.gaierror` from the guard's resolution. This is a *normal*
  condition in this app: `main.py:180-225` patches `socket.getaddrinfo` with a DoH fallback that
  raises `socket.gaierror("All DoH endpoints failed for host")` after 3 × 2 s when the network (or the
  ISP's DNS) is blocked — exactly the scenario the fallback exists for. `utils/url_safety.py:26-27`
  resolves the identical input the opposite way (`return False` = fail closed).
- **User impact:** for up to two minutes the SSRF guard is a no-op for that host: the loopback proxy
  (`core/proxy.py:954`) and `import_external_playlist` (`core/api.py:2365`) fetch an unvetted host,
  including `172.16.0.0/12` (RFC1918) and `100.64.0.0/10` addresses that the guard is documented to
  reject.
- **Evidence:**
  ```python
  # core/api.py:143-157
  verdict = True
  try:
      addr_info = socket.getaddrinfo(hostname, None)
      ...
  except Exception:
      # If DNS resolution fails, fallback string check
      if hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("192.168.") or hostname.startswith("127."):
          verdict = False
  _ssrf_cache_put(hostname, verdict)
  ```
  ```python
  # utils/url_safety.py:25-27  (the stricter sibling, used by the download/engine sinks)
  except (OSError, UnicodeError, ValueError):
      return False
  ```
- **Reproduction / verification:** `verify_ssrf.py` monkeypatches `socket.getaddrinfo` to raise and
  prints both guards:
  ```
  https://totally-unresolvable-host.example/x   api=True    url_safety=False
  http://172.16.0.5/x                           api=False   url_safety=False   <- blocked only by the literal pre-check? no: prefix list misses 172.
  http://100.64.0.1/x                           api=True    url_safety=False
  ```
  (measured values: `api=True` for the unresolvable host and for `100.64.0.1`; `url_safety=False` for
  both). `verify_ssrf.py` part 2 shows the poisoning:
  ```
  first call : True
  cache entry: {'cached-host.example': (199165.87..., True)}
  second call: True
  dns calls during 2nd call: []   (0 == served from the poisoned cache)
  ```
  Note also `verify_ssrf.py` part 3: `http://0x7f000001/x` (hex-encoded `127.0.0.1`) → `True`
  (allowed), because `ipaddress.ip_address('0x7f000001')` raises, is swallowed at `core/api.py:189-190`,
  and the host is then "unresolvable" on Windows so the fail-open path applies.
- **Suggested fix:** fail closed — an unresolvable host, an empty `getaddrinfo` result, or an
  unparsable address must return "unsafe"; extend the literal/prefix pre-check to `172.16.0.0/12`
  and `100.64.0.0/10` (or use `ipaddress.ip_address(...).is_global`); cache the *negative* verdict
  with a much shorter TTL than the positive one.
- **Fix side effects:** a resolver hiccup would start blocking legitimate streams; mitigate with a
  short negative TTL plus one retry, and make sure `main.py`'s DoH fallback is treated as a
  *resolution* failure, not as "public".
- **Discovered by:** B

---

#### F-WN-03-2  [P2] — The guard resolves DNS but never pins the address: TOCTOU / DNS-rebinding

- **File:** `core/api.py:133-158`; consumers `core/api.py:2365-2376` (`import_external_playlist` →
  `importer.resolve(url)` → yt-dlp), `core/proxy.py:954` + `core/proxy.py:1016` (`_safe_urlopen`),
  `utils/cache_manager.py:408-423`.
- **Confirmed:** yes
- **Description:** the guard resolves the hostname, inspects the addresses and then **throws the
  addresses away**. The subsequent HTTP request performs its own, later `getaddrinfo`. Nothing binds
  the request to the address that was vetted, so a hostname whose DNS answer changes between the two
  resolutions passes the guard with a public answer and is fetched with a private one.
- **Cause:** classic check-then-use separation: validation and use are two different name lookups.
- **Trigger conditions:** an attacker-controlled hostname with a short TTL that alternates between a
  public and a private address (the standard DNS-rebinding setup). The 120 s verdict cache
  (`core/api.py:99`) makes it worse: after the first public verdict the guard does not re-resolve at
  all for two minutes.
- **User impact:** the app fetches `http://127.0.0.1:…/` or `http://169.254.169.254/latest/meta-data/`
  (cloud instance metadata / IMDS) on the user's machine and returns the body to the caller — a
  working SSRF against the loopback proxy and against the playlist importer.
- **Evidence:**
  ```python
  # core/api.py:144-151  (addresses resolved, then discarded)
  addr_info = socket.getaddrinfo(hostname, None)
  for family, socktype, proto, canonname, sockaddr in addr_info:
      ip_str = sockaddr[0]
      ip = ipaddress.ip_address(ip_str)
      ...
  ```
  ```python
  # core/proxy.py:390-393  (the request resolves the name a second time)
  def _safe_urlopen(req, timeout=12.0, source=''):
      opener = urllib.request.build_opener(SafeRedirectHandler(max_redirects=5, source=source))
      return opener.open(req, timeout=timeout)
  ```
- **Reproduction / verification:** `verify_toctou.py` installs an alternating resolver
  (`93.184.216.34` then `127.0.0.1`) and shows the guard and the request disagree:
  ```
  step 1  guard resolves rebind.test  -> True
          dns resolutions so far     = 1
  step 2  guard called again (cache)  -> True
          dns resolutions so far     = 1   <- guard did NOT re-resolve
  step 3  address the REAL request uses: 127.0.0.1
          -> request goes to 127.0.0.1 while the guard said 'safe'
  ```
- **Suggested fix:** pin the vetted address — resolve once, then connect to that address with the
  original `Host:` header / TLS SNI, or re-validate the address at connect time (e.g. a custom
  `HTTPSHandler`/`http.client` connection hook that re-checks `getpeername()`); shorten the verdict
  TTL and do not memoise a host whose answer set changed between resolutions.
- **Fix side effects:** pinning breaks TLS SNI / `Host` matching unless done carefully, and breaks
  CDNs that rotate addresses — the fix must keep the original hostname for the HTTP layer.
- **Discovered by:** B

---

#### F-WN-03-3  [P2] — Two divergent SSRF guards exist in the tree; the bridge and the proxy use the permissive one

- **File:** `core/api.py:161-195` vs `utils/url_safety.py:13-37`; the dependency edge
  `core/proxy.py:23` (`from core.api import _is_ssrf_safe_url`).
- **Confirmed:** yes
- **Description:** the codebase contains **two** SSRF guards with **opposite** failure semantics:

  | case | `core/api.py::_is_ssrf_safe_url` | `utils/url_safety.py::is_safe_media_url` |
  |---|---|---|
  | DNS failure | **True = safe** (fail open) | **False = unsafe** (fail closed) |
  | IPv6 zone id (`fe80::1%25eth0`) | zone id not stripped → parse error → fail open | stripped (`.split('%',1)[0]`) → correctly blocked |
  | numeric/decimal literal | explicit handling | relies on `getaddrinfo` |
  | memoisation | 120 s cache | none |

  `is_safe_media_url` is used by the media sinks (`audio/engine.py:176,440`,
  `core/downloader.py:639,650`, `core/download_transfer.py:67`); `_is_ssrf_safe_url` is used by the
  bridge and the proxy (`core/api.py:1111,2365`, `core/proxy.py:379,841,954,1054`,
  `utils/cache_manager.py:408,419`). The guard that protects the *fetching* surface is the weaker
  one; the stricter implementation sits next to it, unused for that purpose.
- **Cause:** the security primitive was re-implemented inside the JS-bridge module instead of being
  reused, and the two copies drifted. The dependency direction is also inverted: the HTTP proxy
  imports the 4228-line bridge module (and therefore `webview`) to obtain one boolean function.
- **Trigger conditions:** always — the two guards simply disagree on any host that fails to resolve.
- **User impact:** a fix applied to one copy leaves the other open; today the proxy and the bridge
  inherit the fail-open behaviour while the downloader does not. It also makes the security property
  untestable in one place: `tests/test_media_guard_f3.py` pins the *strict* guard, and
  `tests/test_api_audit_b.py` L246–339 pins the *lax* one (its L327 test even asserts
  `_is_ssrf_safe_url("http://ftp://example.com/x") is False`, i.e. it only covers the cheap
  pre-DNS rejections).
- **Evidence:**
  ```python
  # core/proxy.py:23-24
  from core.api import _is_ssrf_safe_url  # mirrors core/api.py:_is_ssrf_safe_url; imported (not copied) ...
  _is_safe_url = _is_ssrf_safe_url
  ```
  ```python
  # utils/url_safety.py:16-17 (docstring states the intent)
  """True only for http(s) URLs whose host resolves exclusively to public addresses.
  DNS failures and unparsable hosts fail closed (return False)."""
  ```
- **Reproduction / verification:** the side-by-side table printed by `verify_ssrf.py` (part 1) and the
  `is_safe_media_url` call sites listed above.
- **Suggested fix:** one implementation in a dedicated module (`core/net_safety.py` or
  `utils/url_safety.py`) that is *cached* **and** *fail-closed*, imported by `core/api.py`,
  `core/proxy.py` and `utils/cache_manager.py`; delete the duplicate.
- **Fix side effects:** the proxy would inherit the stricter semantics — exotic-but-legitimate hosts
  could start being blocked; `main.py`'s DoH fallback must be reconciled with "unresolvable ⇒ unsafe"
  so that a DNS outage does not kill playback.
- **Discovered by:** B

---

#### F-WN-03-4  [P2] — The "secrets never travel back to JS" contract is enforced only on the settings **read** path; the **write** path echoes the secret, and `auth.proxy_url` (which may embed a proxy password) is never masked

- **File:** `core/api.py:239-253` (contract + `_mask_secrets` + `_SECRET_SETTING_KEYS`),
  `core/api.py:240`; the emitting write paths `core/api.py:1887`, `core/api.py:1896`,
  `core/api.py:2952`; the caller `ui/web_new_v2/js/settings.js:379` and `js/settings.js:1040`.
- **Confirmed:** yes
- **Description:** the contract is stated explicitly at `core/api.py:239`:
  *"Secrets never travel back to JS: the bridge answers with `""` and a `has_*` flag."* It is honoured
  on the read path (`get_settings`, `get_settings_by_category`, `get_setting`) but **not** on the write
  path: every successful `set_setting` / `save_setting` emits
  `setting_changed` with the **raw value** in the payload. When the user types their Yandex OAuth
  token into the settings UI, the backend stores it *and broadcasts it back to the WebView*. In
  addition, the secret key list is incomplete: `auth.proxy_url` — a free-text proxy URL that
  `services/base_service.py:25-56` accepts with embedded credentials (`http://user:pass@host:port`) —
  and `auth.cookies_file_path` (a path under the user's home directory) are **not** masked and are
  returned verbatim by `get_settings()`.
- **Cause:** masking is applied at one call site (`_mask_secrets`) instead of at the boundary; the
  secret inventory (`_SECRET_SETTING_KEYS`) is a hand-maintained per-category allowlist that is not
  derived from the settings schema and is not covered by a test that enumerates `DEFAULT_SETTINGS`.
- **Trigger conditions:** every token save (the UI does it on `change`, `js/settings.js:377-380`);
  `get_settings()` / `get_settings_by_category('auth')` whenever a proxy URL with credentials or a
  cookie-file path is configured.
- **User impact:** the Yandex token and any proxy password leave the backend and land in the
  WebView's JavaScript heap; the UI additionally mirrors them into `localStorage`
  (`js/settings.js:1040` → `nedotify_auth_yandex_token`, `nedotify_auth_proxy_url`), i.e. **in
  cleartext on disk** in the WebView2 profile, outside `~/.nedotify`. Any script-injection in the UI
  (remote track titles / lyrics are rendered) can then read them. The masked read path makes the
  user *believe* the token is protected.
- **Evidence:**
  ```python
  # core/api.py:239-253
  # Secrets never travel back to JS: the bridge answers with "" and a has_* flag.
  _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}

  def _mask_secrets(category: str, data: dict) -> dict:
      secret_keys = _SECRET_SETTING_KEYS.get(category)
      ...
  ```
  ```python
  # core/api.py:2952  (write path - value echoed to the frontend)
  self._emit("setting_changed", {"category": category, "key": key, "value": value})
  ```
  ```javascript
  // ui/web_new_v2/js/settings.js:377-380
  inputYandexToken.addEventListener('change', (e) => {
      if (!e.target.value) return;
      saveSetting('yandex_token', e.target.value, 'auth');
  });
  ```
- **Reproduction / verification:** `verify_ssrf.py` part 5 prints the masked `auth` category:
  ```
  cookies_file_path       = 'C:\\Users\\Somebody\\AppData\\Roaming\\cookies.txt'
  yandex_token            = ''
  proxy_url               = 'http://user:hunter2@proxy.example:8080'   <- password NOT masked
  oauth_client_secret     = ''
  has_yandex_token        = True
  ```
  and `services/base_service.py:55` shows the proxy URL (userinfo included) is used verbatim as the
  dial target for every provider request.
- **Suggested fix:** apply masking at the emit boundary as well (emit `has_<key>` instead of the value
  for secret keys); add `proxy_url` (and any other credential-bearing key) to the masked set, or move
  it to a dedicated credential store; make the UI skip `localStorage` for secret keys; add a test
  that walks `DEFAULT_SETTINGS` and fails when a key whose name looks like a credential is not in
  `_SECRET_SETTING_KEYS`.
- **Fix side effects:** the settings UI must be able to show whether a proxy URL is configured without
  showing its password — a "configured / not configured" flag instead of the raw value.
- **Discovered by:** B

---

#### F-WN-03-5  [P2] — `_install_bridge_error_logging` copies the raw exception text into the `api_error` event and into the plaintext log file, with no redaction

- **File:** `core/api.py:428-441` (wrapper) and `core/api.py:434-438` (the `api_error` payload)
- **Confirmed:** yes
- **Description:** every public bridge method is wrapped; on an exception the wrapper (a) logs the
  exception **message** plus the full traceback at ERROR level and (b) pushes an `api_error` event
  whose `error` field is the raw `f"{type(exc).__name__}: {exc}"`. Nothing in that path redacts
  URLs, tokens or file paths. `describe_error` (owner WN-16) does the same for `ValueError` /
  `TypeError` (`core/user_errors.py:22` → `str(error)[:240]`).
- **Cause:** the error path treats the exception message as safe to publish, while the same codebase
  treats it as unsafe everywhere else (`core/proxy.py:489` explicitly scrubs `k=` / `auth_token=`
  from its access log).
- **Trigger conditions:** any bridge method that raises with a message containing a secret — e.g. a
  provider URL with a token in the query string, a proxy URL with a password, a yt-dlp error
  containing the source URL, a `FileNotFoundError` containing the user's home path.
- **User impact:** secrets end up in `~/.nedotify/logs/app.log` (a plaintext file that survives
  uninstall) and in the WebView (where the `api_error` handler in `js/events.js` shows a toast and
  `console.error`s the payload). A user who shares their log for support shares their token.
- **Evidence:**
  ```python
  # core/api.py:428-441
  except Exception as exc:
      logger.error(
          "bridge call %s() failed: %s: %s",
          method_name, type(exc).__name__, exc, exc_info=True,
      )
      try:
          inner_self._emit("api_error", {
              "method": method_name,
              "error": f"{type(exc).__name__}: {exc}",
              **describe_error(exc, method_name),
          })
      except Exception:
          logger.debug("api_error emit failed", exc_info=True)
      raise
  ```
- **Reproduction / verification:** make any wrapped method raise
  `ValueError("GET https://api.example/x?token=SECRET failed")` → the `api_error` payload and the
  log line both contain `SECRET`. The `api_error` consumer is
  `ui/web_new_v2/js/events.js:331-341` (toast + `console.error`), and the log sink is
  `~/.nedotify/logs/app.log`.
- **Suggested fix:** route every bridge-originated message through one redactor that strips query
  strings of credential parameters (`token`, `k`, `auth_token`, `access_token`, `password`), bearer
  headers and `user:pass@` userinfo; log the *type* + traceback server-side and publish a redacted
  message to the UI.
- **Fix side effects:** diagnostics lose the exact offending URL; keep the unredacted form at DEBUG
  level behind an explicit opt-in if a developer needs it.
- **Discovered by:** B

---

#### F-WN-03-6  [P2] — `_offline_bridge_result` is a fail-open, name-and-position keyed allowlist: new network methods are not intercepted and a JS signature change silently breaks the `request_id` correlation

- **File:** `core/api.py:461-512`
- **Confirmed:** yes
- **Description:** offline interception is implemented as one long `if`-chain over **method-name
  strings**, with argument positions hard-coded (`args[0]`, `args[1]`, `args[2]`, `args[3]`). Two
  consequences follow directly from the shape of the code:
  (a) **fail open** — the final `return False, None` means any method *not* named in the chain runs
  normally, so a newly added bridge method that touches the network is **not** blocked in offline
  mode and nobody notices;
  (b) **positional coupling to the JS signature** — the interceptor re-derives `request_id` from a
  fixed index instead of using the method's own signature, so a change in the JS call signature
  silently produces a wrong (or `None`) `request_id`.
- **Cause:** the interceptor duplicates the JS↔Python contract by string and by index, instead of
  being derived from the method (a decorator / registry / capability declaration on the method
  itself). The duplication has two sources of truth that can drift apart without any test failing.
- **Trigger conditions:** (a) any new public bridge method; (b) any change to the argument order of
  `get_artist_profile`, `get_album_details`, `get_track_wave`, `get_playlist_tracks`.
- **User impact:** (a) "offline mode" silently performs network I/O for the new method — the mode the
  user explicitly enabled is a lie; (b) the emitted event carries a `request_id` the UI is not waiting
  for → the corresponding promise/event never resolves → an endless spinner with **no traceback**
  (exactly the failure mode `AGENTS.md` warns about). The current indices *do* match the UI today
  (`js/artist_profile.js:153` → 3 args, `js/search.js:615` → 2 args, `js/main.js:165` → 4 args), but
  nothing pins that.
- **Evidence:**
  ```python
  # core/api.py:461-512 (excerpt)
  def _offline_bridge_result(self, method, args, kwargs):
      if not is_offline(getattr(self._core, 'settings', None)):
          return False, None
      feeds = {'get_feed': ('feed_ready', []), ...}
      if method in feeds: ...
      if method == 'get_artist_profile':
          name = args[0] if args else kwargs.get('artist_name', '')
          request = args[2] if len(args) > 2 else kwargs.get('request_id')
          ...
      ...
      return False, None          # <- fail open for every unlisted method
  ```
  ```python
  # core/api.py:424-426 (the interceptor runs for EVERY public bridge call)
  handled, result = inner_self._offline_bridge_result(method_name, args, kwargs)
  if handled:
      return result
  ```
- **Reproduction / verification:** `grep -rn "_offline_bridge_result" tests/` returns **no** test
  file — the ~50-line interceptor has zero Python-level coverage; only
  `tests/test_frontend_js.py` pins unrelated strings. A new public method is trivially demonstrated:
  adding `def fetch_something(self): ...` to `AppApi` makes `_install_bridge_error_logging` wrap it
  and `_offline_bridge_result` return `(False, None)` for it.
- **Suggested fix:** invert the default — declare offline behaviour per method (decorator /
  `__offline_behaviour__` attribute / explicit registry), so a new method is *forced* to declare
  whether it may run offline; take `request_id` from the keyword arguments of the actual call
  (`inspect.signature(...).bind_partial(*args, **kwargs)`) instead of a hard-coded index.
- **Fix side effects:** every existing method would need a declaration — mechanical but broad; a
  transitional "network-touching methods" list keeps the migration incremental.
- **Discovered by:** B

---

#### F-WN-03-7  [P3] — `_emit` spawns one OS thread per event on the UI thread: unbounded thread churn, no ordering guarantee, no backpressure

- **File:** `core/api.py:1147-1154`
- **Confirmed:** yes
- **Description:** the "must never run on the UI thread" contract is honoured, but the implementation
  is a **thread per event**, not the single `EmitWorker` the thread name suggests: every UI-thread
  emit creates and starts a fresh `threading.Thread`. There is no queue, no worker, no coalescing and
  no bound. `pywebview`'s `evaluate_js` marshals through `Control.Invoke`, i.e. each of those threads
  *blocks* until the UI thread drains its message queue, so a burst accumulates blocked threads
  rather than queueing them.
- **Cause:** the handoff was implemented as "spawn and forget" instead of "hand to a worker".
- **Trigger conditions:** any emit on the UI thread — the pywebview `loaded` event runs there
  (`main.py:389-404` → `engine._on_track_changed` → `_emit("track_changed", …)`), and any future UI
  callback that emits.
- **User impact:** a burst of N events costs N thread creations (~0.12 ms each measured) and N × 1 MB
  of reserved stack on Windows; the events also race each other, so their arrival order is not
  guaranteed (the worker-thread path is ordered, the UI-thread path is not).
- **Evidence:**
  ```python
  # core/api.py:1147-1154
  if threading.current_thread() is _MAIN_THREAD:
      threading.Thread(
          target=self._window.evaluate_js,
          args=(js_code,),
          daemon=True,
          name="EmitWorker",
      ).start()
      return
  ```
- **Reproduction / verification:** `verify_perf.py` (with `_MAIN_THREAD` temporarily pointed at the
  calling thread):
  ```
  UI-thread emits: 200 in 23.2 ms -> 0.12 ms/emit, 200 OS threads spawned
  alive threads after burst: 1
  ```
  — 200 emits produced 200 OS threads; they finished quickly only because the fake window returns
  immediately.
- **Suggested fix:** one long-lived worker thread per `AppApi` with a bounded queue; coalesce
  high-frequency events (`queue_updated`, `download_progress`) by key; keep the UI-thread check as the
  "enqueue instead of evaluate" trigger.
- **Fix side effects:** the queue must be bounded and must define what happens when it overflows
  (drop the oldest / drop the event) — otherwise the worker becomes a new memory leak.
- **Discovered by:** B

---

#### F-WN-03-8  [P3] — A stored secret can never be cleared: `_is_empty_secret_write` silently ignores the empty write and still reports success

- **File:** `core/api.py:267-269`, `core/api.py:1884-1885`, `core/api.py:1893-1894`,
  `core/api.py:2944-2945`
- **Confirmed:** yes
- **Description:** the rule exists so that the masked read (`""`) echoed back by the UI cannot wipe a
  stored secret. But it is implemented as "any falsy value for a secret key is ignored", which also
  swallows the user's *intentional* request to clear the secret — and the write is reported as
  **successful** although nothing was written.
- **Cause:** the two intents ("the UI echoed the masked value back" vs "the user wants to remove the
  credential") are indistinguishable because the empty value carries no intent.
- **Trigger conditions:** the user empties the Yandex-token field (the input's placeholder is
  "Токен сохранён (введите новый, чтобы заменить)" — `js/settings.js:952` — so there is no explicit
  "clear" affordance anywhere).
- **User impact:** a revoked or leaked Yandex token stays valid in `~/.nedotify` until the user edits
  the SQLite row by hand; the UI reports "saved" for a change that did not happen.
- **Evidence:**
  ```python
  # core/api.py:267-269
  def _is_empty_secret_write(category: str, key: str, value) -> bool:
      """A blank secret from the UI (masked read echoed back) must not wipe the stored one."""
      return key in _SECRET_SETTING_KEYS.get(category, ()) and not value
  ```
  ```python
  # core/api.py:2944-2945  (reports success for a write that did not happen)
  if _is_empty_secret_write(category, key, value):
      return True
  ```
- **Reproduction / verification:** `api.save_setting("yandex_token", "", category="auth")` returns
  `True` while `settings.get("auth","yandex_token")` keeps the old value; the same holds for
  `set_setting("auth","yandex_token","")` and `set_setting("auth.yandex_token","")`
  (`tests/test_api_f1_audit.py` L72-75 pins this as *intended* behaviour for the masked-read case).
- **Suggested fix:** distinguish the two intents — e.g. a dedicated "clear" action
  (`clear_setting('auth','yandex_token')`) or an explicit `null`/sentinel value from the UI — and make
  the masked-echo case return a distinct "unchanged" status instead of a plain `True`.
- **Fix side effects:** the UI must stop sending `""` as a no-op and start sending an explicit clear
  request; the settings screen needs a "remove token" button.
- **Discovered by:** B

---

#### F-WN-03-9  [P3] — `_normalize_cache_quota` silently reinterprets a bare number > 64 as megabytes, silently swallows unknown keyword arguments, and contains two provably dead lines

- **File:** `core/api.py:272-327` (and `core/api.py:294-297` for the dead lines)
- **Confirmed:** yes
- **Description:** three defects in one pure helper:
  (a) **unit heuristic** — a bare `quota_gb` above 64 is reinterpreted as megabytes
  (`core/api.py:314-316`), so a legitimate request for a 100 GB quota becomes 100 MB, with no warning;
  (b) **`**kwargs` swallows typos** — `set_cache_quota(size_mb=4096)` returns `(None, None)` and the
  quota is silently *not* applied (`tests/test_api_audit_b.py` L591 even pins this as
  "unknown key ignored");
  (c) **dead code** — `if cache_quota_gb is None: cache_quota_gb = kwargs.get("cache_quota_gb")` (and
  the same for `cache_size_mb`) can never fire: those names are already explicit parameters, so
  passing them again is a `TypeError` at call time, and `kwargs` can therefore never contain them.
- **Cause:** the helper tries to be tolerant of three different caller spellings at once (frontend
  key, legacy key, bare positional) and resolves the ambiguity with a magic threshold instead of an
  explicit unit.
- **Trigger conditions:** any caller that uses the bare `quota_gb` spelling with a value > 64, or
  misspells a keyword.
- **User impact:** a quota change is applied with the wrong unit (cache 100× smaller than intended)
  or not at all, while the UI reports success — the settings dropdown in fact never offers > 64 GB,
  which is why the threshold was chosen, but the API accepts it.
- **Evidence:**
  ```python
  # core/api.py:294-297  (provably dead)
  if cache_quota_gb is None:
      cache_quota_gb = kwargs.get("cache_quota_gb")
  if cache_size_mb is None:
      cache_size_mb = kwargs.get("cache_size_mb")
  ```
  ```python
  # core/api.py:313-316
  # Heuristic: a bare number > 64 with no explicit unit key is MB, not GB.
  if size_mb is None and val_gb is not None and val_gb > _POSITIONAL_MB_THRESHOLD:
      size_mb = val_gb
      val_gb = None
  ```
- **Reproduction / verification:** `_normalize_cache_quota(quota_gb=100)` →
  `(0.09765625, 100.0)` (i.e. 100 **MB**), `_normalize_cache_quota(quota_gb=500)` →
  `(0.48828125, 500.0)` as documented at `core/api.py:285`; `_normalize_cache_quota(size_mb=4096)` →
  `(None, None)`.
- **Suggested fix:** require the unit explicitly (drop the bare-number overload or rename it
  `quota_mb`), reject unknown keyword arguments instead of ignoring them, and delete the dead
  `kwargs.get(...)` lines.
- **Fix side effects:** `set_cache_quota` (owner WN-08) has legacy callers; the rename must be
  migrated in one step or the legacy spelling kept as an explicit, documented alias.
- **Discovered by:** B

---

#### F-WN-03-10  [P3] — The bridge error wrapper installs per-instance bound methods, so the live instance diverges from the class API (class-level patching has no effect, and a public static/class method would be mis-bound)

- **File:** `core/api.py:413-444`
- **Confirmed:** yes
- **Description:** `_install_bridge_error_logging` iterates `dir(type(self))` and installs the
  wrappers **on the instance** (`setattr(self, name, types.MethodType(...))`), capturing the function
  object it found at that moment. Three consequences: (a) `monkeypatch.setattr(AppApi, "some_method", …)`
  — the natural way to test a bridge method — has **no effect** on the live instance, because the
  instance attribute shadows the class attribute; (b) the instance `__dict__` now holds 136 bound
  closures, so the object is no longer cleanly copyable/picklable and `dir(app)` no longer reflects
  the class; (c) the wrapper calls `func(inner_self, *args, **kwargs)`, which is wrong for a
  `staticmethod`/`classmethod` (the instance would be passed as the first real argument).
- **Cause:** the wrapping strategy mutates the instance instead of the class, so the class remains
  the "unwrapped" API while the object in production is the wrapped one.
- **Trigger conditions:** (a) any future test that patches the class; (c) the day a *public*
  static/class method is added to `AppApi` — `AppApi` already contains a `@staticmethod`
  (`core/api.py:1262`, currently private and therefore skipped by the `name.startswith("_")` filter).
- **User impact:** tests can silently exercise the old code (a false green), and a future public
  static method would raise `TypeError` on its first call from JS — a crash in the bridge with no
  useful trace.
- **Evidence:**
  ```python
  # core/api.py:413-444 (excerpt)
  for name in dir(type(self)):
      if name.startswith("_") or name in self._UNWRAPPED:
          continue
      attr = getattr(type(self), name, None)
      if not callable(attr):
          continue
      def _make(func, method_name): ...
      setattr(self, name, types.MethodType(_make(attr, name), self))
  ```
- **Reproduction / verification:** `AppApi` has 174 methods, 136 public (`ast` count over
  `core/api.py`); after `AppApi(core)` the instance dict contains one bound wrapper per public
  method. `monkeypatch.setattr(AppApi, "get_settings", fake)` does not change `app.get_settings`.
- **Suggested fix:** apply the wrapper at the class level (a decorator applied to each method, or a
  metaclass/`__init_subclass__` hook) so `AppApi.get_settings` *is* the wrapped method; skip
  `staticmethod`/`classmethod` objects explicitly.
- **Fix side effects:** class-level wrapping makes the wrapper part of the public API surface and
  affects every instance (including tests that build `AppApi` directly) — the `_UNWRAPPED` set must
  keep its lifecycle exclusions.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct (brief):

- **IP-literal classification in `_is_ssrf_safe_url` (`core/api.py:169-190`)** — verified against
  Python 3.14.7's `ipaddress`: `127.0.0.1`, `::1`, `[::ffff:127.0.0.1]`,
  `[::ffff:169.254.169.254]`, `0.0.0.0`, `169.254.169.254`, `10/8`, `172.16/12`, `192.168/16`,
  `240/4`, `fc00::/7`, `fe80::/16` are all rejected; the decimal form `2130706433` → `127.0.0.1` is
  rejected; `user:pass@127.0.0.1` is rejected (the userinfo is stripped by `parsed.hostname`);
  `localhost` (case-insensitively, via `.lower()`) is rejected; a non-http(s) scheme is rejected;
  a huge decimal literal raises inside `ip_address()` and is rejected (fail-closed). `is_private`
  correctly covers IPv4-mapped IPv6 in 3.14 (`::ffff:127.0.0.1`.is_private → True), so the
  mapped-IPv6 bypass does **not** work.
- **Redirect re-validation (`core/proxy.py:368-387`)** — every redirect hop is re-checked with
  `_is_ssrf_safe_url`, the hop count is capped at 5, and the `Authorization`/`Cookie` headers are
  stripped when the redirect crosses hosts (`_host_allows_credentials`). `utils/cache_manager.py:416-421`
  does the same for cover downloads. No redirect bypass found.
- **The proxy's own authentication gate (`core/proxy.py:491-528`)** — a per-session bearer token,
  constant-time comparison, **fail-closed** when the token is unset, and CORS that only echoes a
  loopback `Origin` (no wildcard). This meaningfully limits the blast radius of the SSRF findings
  above: an external web page cannot drive the loopback proxy without the token.
- **The SSRF memo cache (`core/api.py:99-130`)** — bounded at 512 entries, TTL-based expiry
  (`time.monotonic()`), a dedicated lock, and eviction of the entry closest to expiry. It is
  correctly keyed **per hostname** (so two URLs on different hosts cannot share a verdict), and
  `_reset_ssrf_cache()` exists for tests. The eviction scan is O(n) over ≤512 entries — measured as
  negligible.
- **The plugin gate (`core/api.py:256-264`)** — I tried every write spelling the JS could use
  (`save_setting('plugins_enabled',True,'general')`, `save_setting('general.plugins_enabled',True)`,
  `save_setting('plugins_enabled',True)`, `set_setting('general.plugins_enabled',True)`,
  `set_setting('general','plugins_enabled',True)`, `update_setting('general','plugins_enabled',True)`).
  The four real spellings are blocked; the two that are not blocked write to the **wrong category**
  (`app.plugins_enabled` / `app.general.plugins_enabled`) and therefore do **not** reach
  `core/plugins.py:41` (`settings.get('general','plugins_enabled',False)`) — **no bypass of the
  third-party-code gate was found**.
- **Per-call cost of the bridge wrapper and of the pure helpers** — measured with `verify_perf.py`:
  the offline interceptor costs **0.39 µs** per bridge call, `_mask_secrets` **0.33 µs**,
  `_normalize_cache_quota` **0.55 µs**. The brief's hot-path concern about `_as_float` /
  `_normalize_cache_quota` is **not** a problem; the per-call wrapper overhead is negligible.
- **`_emit`'s serialisation guard (`core/api.py:1131-1139`)** — `json.dumps` is inside the `try`, so
  a non-serialisable payload is logged and dropped instead of raising out of the emitter; falsy
  payloads are preserved (`{}` is not substituted); `ensure_ascii=True` keeps the embedded JSON valid
  in the JS source. Pinned by `tests/test_emit_thread_safety.py`.
- **The UI-thread hand-off itself** — the contract "`_emit` must never run on the UI thread" *is*
  honoured (`core/api.py:1147-1154`); the defect is the thread-per-event *shape*, not the branch
  (see F-WN-03-7). `tests/test_emit_thread_safety.py` pins the branch.
- **`cleanup()` (`core/api.py:446-459`)** — both executors are shut down with
  `wait=False, cancel_futures=True` so app exit cannot block, and each step is individually guarded.
- **`_extract_first_url` (`core/api.py:201-220`)** — the extracted URL is always re-validated by
  `_is_ssrf_safe_url` at the call site (`core/api.py:2365`); the regex only finds the *first*
  http(s) URL, so a hostile second URL in the pasted text cannot slip through unvalidated.

---

### 4. Coverage gaps

- **`core/api.py` L520–4228** was **not** reviewed (belongs to WN-04…WN-10). Where those ranges
  implement the contract stated in this area, I traced them but did not audit them:
  `get_settings`/`save_setting` (L2922-2962, WN-08), `set_setting`/`get_setting` (L1853-1900,
  WN-08), `import_external_playlist` (L2362-2414, WN-06), `open_url` (L1109-1116, WN-04).
- **Cross-area defect observed but owned elsewhere (NOT counted as a finding above):**
  `core/api.py:2929` — the hard-coded category list of `get_settings()` is
  `['app','appearance','player','lyrics','system','general','audio','overlay','efficiency',
  'optimization','hotkeys','storage','player_appearance','personalization','interface','ui','theme',
  'equalizer','auth','services','session','zapret']`, whereas `DEFAULT_SETTINGS`
  (`core/settings.py:52-287`) also defines **`network`** (holding `offline_mode`) and `subscription`.
  `network` is missing, so `get_settings()` never returns `network.offline_mode`, and the UI reads
  exactly that (`ui/web_new_v2/js/feature-controls.js:112` →
  `applyOfflineState({ enabled: window.settings?.network?.offline_mode === true })`;
  also `js/player.js:1440,1524` and `js/utils.js:526,608`). After a restart with offline mode ON the
  frontend therefore believes the app is online. The backend side is correct
  (`core/offline.py:10-14` reads `network.offline_mode` and `_offline_bridge_result` uses it), so the
  root cause is the category list at `core/api.py:2929` → **owner WN-08**, cross-referenced from
  here. The same list also contains four categories that do not exist in `DEFAULT_SETTINGS`
  (`appearance`, `player`, `lyrics`, `system`) — evidence that the list has already drifted once.
- **Not verified (would need the live app, which the ground rules forbid):**
  the exact number of `_emit` calls issued during a real startup restore (I measured the per-emit
  cost and the thread-per-emit behaviour with a harness instead), and the real WebView2 `localStorage`
  on-disk layout.
- **Not verified:** whether a public DNS server reachable from this machine performs rebinding on
  demand — the TOCTOU finding is proven with an injected resolver (`verify_toctou.py`), which is the
  standard way to demonstrate it; no live rebinding service was contacted.
- **Not audited:** `core/proxy.py` in its own right (WN-11) — I only read the SSRF/auth/redirect
  parts needed to trace this area's callers.

---

### 5. Architecture improvements (ARCH)

No proven defect attached to the items below; they are engineering-quality proposals.

1. **Extract the security primitive out of the bridge module.**
   `core/api.py` (4228 lines, `AppApi` with 174 methods / 136 public) currently *owns* the SSRF
   guard, so `core/proxy.py:23` must import the whole JS-bridge module — and therefore `webview` — to
   get one boolean function, and `utils/url_safety.py` holds a second, stricter copy. Move the guard
   to a small dependency-free module (`core/net_safety.py` or `utils/url_safety.py`), give it the
   cache that `core/api.py` has and the fail-closed semantics that `utils/url_safety.py` has, and
   make every outbound path (bridge, proxy, cache manager, downloader, engine) call the same
   function. This is the single highest-value change in this area: it removes the duplicate,
   fixes F-WN-03-1/2/3 at once, and removes the `core.proxy → core.api → webview` dependency edge.

2. **Split `AppApi` by capability instead of growing one 174-method class.**
   The class currently mixes window management, playback, search, library, settings, lyrics, cache
   and diagnostics. A seam that pays off immediately: expose several small `js_api` objects
   (`window_api`, `playback_api`, `settings_api`, `library_api`) or at least group the methods into
   mixins/collaborators that own their own state. Today the only structural boundary is the
   string-keyed `_UNWRAPPED` set (`core/api.py:397-399`) and the string-keyed offline allowlist
   (`core/api.py:461-512`) — both are "the class is too big, so we keep a list of exceptions".

3. **Make the offline capability a declaration, not an allowlist.**
   Attach the offline behaviour to the method (decorator / class attribute) so that adding a bridge
   method forces a decision, instead of silently inheriting "network allowed". The same mechanism
   can carry the "does this method touch the network / the disk / the DB" metadata that the SSRF
   guard, the audit log and the future rate limiter would all need.

4. **Introduce a real event bus with a bounded, ordered queue for Python → JS.**
   Today `_emit` is a global function on the god object with 89 call sites, a thread-per-event
   UI-thread hand-off and no backpressure. A single `EventBus` owned by `AppApi` with one worker
   thread, per-event coalescing for high-frequency events (`queue_updated`, `download_progress`) and
   a documented overflow policy would remove F-WN-03-7 and make the event set inspectable (the
   frontend already switches on event names in `js/events.js`, so the names are an implicit,
   undocumented contract).

5. **Centralise the "secret" concept.**
   Today secrecy is enforced by two hand-maintained lists (`_SECRET_SETTING_KEYS` in `core/api.py`
   and the UI's own knowledge) that must agree with `DEFAULT_SETTINGS` in `core/settings.py`.
   Introduce one declarative notion — e.g. a `Secret` marker on the schema entry, or a
   `SECRET_KEYS` set in `core/settings.py` that both the bridge and the UI import — so that the
   read path, the write path, the log path and the localStorage mirror all derive their behaviour
   from one source. A contract test that walks `DEFAULT_SETTINGS` and fails on an unmasked
   credential-shaped key would prevent the drift.

6. **Introduce a capability/labelling convention for bridge methods and unify the error contract.**
   `_install_bridge_error_logging` re-raises after emitting `api_error`, which means the caller sees
   a rejected promise *and* an event — two different failure channels for one failure. Pick one
   (a typed error object returned to JS, or a promise rejection with a structured payload) and let
   the wrapper be the only place that decides.

7. **Give the bridge a single, tested seam for settings access.**
   `AppApi` reads `self._core.settings` in a dozen places with four different call conventions
   (`settings.get(cat,key)`, `settings.get("cat.key")`, `get_category`, `set(...)`), and the
   bridge adds a third convention on top (`_mask_secrets`, `_bridge_write_error`,
   `_is_empty_secret_write`). A single `SettingsFacade` that owns masking, read-only keys and the
   secret-write rules would remove the three parallel lists and give the UI one contract.

8. **Make the emit/bridge payloads typed and versioned.**
   Payloads are plain dicts built at 89 call sites; the frontend matches on magic keys
   (`js/events.js`). A small schema per event (or at least a documented key list per event) would
   let both sides fail loudly on a rename instead of silently doing nothing — the failure mode
   `AGENTS.md` calls out explicitly.
