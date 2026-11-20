## AREA WN-22 — Lyrics services — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read):**

- `services/lyrics_service.py:1-327` (full)
- `services/lyrics_lookup.py:1-387` (full)
- `services/lyrics_cache.py:1-109` (full)
- `core/api.py:3192-3309` (`get_lyrics`, `get_lyrics_translation`), `core/api.py:488-527` (offline interception), `core/api.py:1100-1179` (`_emit`)
- `ui/web_new_v2/js/lyrics.js:1-1262` (full — render path, translation path, mini-widget)
- `ui/web_new_v2/js/events.js:97-100, 344-345` (`track_changed` / `lyrics_ready` dispatch)
- `ui/web_new_v2/js/pages.js:170-171` (player page → `loadCurrentTrackLyrics`)
- `core/app.py:110-169` (service wiring), `core/app.py:540-586` (`cleanup()` / pool shutdown list)
- `core/offline.py:1-77` (`is_offline`)
- `core/settings.py` (grep: only `network.offline_mode` and the `toggle_lyrics` hotkey — **no** lyrics-provider setting)
- `services/base_service.py:65-118, 121-134` (`_SharedExecutor`, `BaseMusicService`)
- `services/music_matching.py:1-95` (`normalize`, `similarity`, `title_metadata`, `artist_matches`, `BASE_FALLBACK_VERSIONS`)
- `services/artist_service.py:196-219` (bio → `translate_lyrics`)
- `services/track_resolver.py:241-244` (consumer of `LyricsService._title_match_score`)
- `tests/test_lyrics_performance.py:1-342` (full)
- `tests/test_verified_lyrics.py:1-174` (full)
- `tests/test_lyrics_netease.py:1-235` (full)
- `tests/test_catalog_lyrics_ui.py:1-83` (full)
- `tests/benchmark_lyrics_cache.py:1-70` (full)
- `docs/PLAYBACK_LYRICS_PERFORMANCE.md:1-51` (the design intent this area is measured against)
- `docs/audits/independent_verification/VERIFIED_FINDINGS_PART1.md:245-270, 730-756` (prior register, to avoid re-reporting an already-closed item)
- `.venv_win/Lib/site-packages/webview/util.py:234-315`, `webview/platforms/winforms.py:354-356`, `webview/platforms/edgechromium.py:110-135` (pywebview bridge + `evaluate_js` threading model)

**Callees traced into other areas (not owned by WN-22):**

- `core/api.py::AppApi.get_lyrics` / `get_lyrics_translation` — owner **WN-09** (bridge lyrics surface). The bridge method itself is a thin, correct adapter (off-thread thread + progressive `lyrics_ready` event). Defects found *inside* the lyrics service are attributed here.
- `core/api.py::_emit` — owner **WN-03**. Used correctly by the lyrics path (never called on the UI thread).
- `ui/web_new_v2/js/lyrics.js` — owner **WN-32**. The lyrics text rendering is XSS-clean (see §3).
- `core/app.py::AppCore.cleanup()` — owner **WN-02**. The *missing* lyrics-pool shutdown is attributed to WN-22 because `LyricsService.shutdown_executor()` is the callee that nobody calls (F-WN-22-7).
- `services/music_matching.py` / `services/artist_identity.py` — owner **WN-18**. The identity gate is correct; the defect is the duplicated/divergent normaliser in WN-22 (F-WN-22-4).
- `services/base_service.py` — owner **WN-18**. The executor duplication is reported as ARCH here (ARCH-2).
- `main.py:539` `os._exit(3)` watchdog path — owner **WN-01**; referenced only as an amplifier of F-WN-22-7.

**Probes written (read-only, outside the repo):**
`%TEMP%\opencode\wn22_probe.py` (HTTP round-trip count), `wn22_probe2.py` (offline translation, disk-key shape, pool starvation, translation chunking), `wn22_probe3.py` (dead-vs-live title normaliser). All probes only import the repo modules; nothing in the repo was modified. Baseline suite re-run: `pytest tests/test_lyrics_performance.py tests/test_verified_lyrics.py tests/test_lyrics_netease.py tests/test_catalog_lyrics_ui.py -q` → **109 passed in 0.96 s**.

---

### 2. Findings

#### F-WN-22-1  [P1] — Offline mode does not cover the translation path: the whole lyric text is shipped to translate.googleapis.com

- **File:** `services/lyrics_service.py:243-272` (esp. `264-266`); contrast `services/lyrics_lookup.py:74-75`; consumer `core/api.py:3286-3291`; second consumer `services/artist_service.py:213`
- **Confirmed:** yes
- **Description:** `LyricsLookup._read` refuses every provider request while offline mode is on, but `LyricsService.translate_lyrics` performs no `is_offline()` check at all. With `network.offline_mode = True` the backend still issues `GET https://translate.googleapis.com/translate_a/single?...&q=<entire lyric text>` — the full third-party lyric text plus the track's language, URL-quoted into the query string.
- **Cause:** the offline guard lives in the *provider transport* (`_read`), not in the shared HTTP helper (`_open_url`, `services/lyrics_service.py:236-241`) that `translate_lyrics` uses. Two egress paths, one guard.
- **Trigger conditions:** the user enables offline mode and then presses the "translate" button on the lyrics panel (or opens an artist profile, which calls the same helper at `services/artist_service.py:213`). No network failure is required — the request is sent.
- **User impact:** offline mode is a user-facing "do not talk to the network" switch; the app's own docs treat it as such (`core/api.py:502-503` intercepts `get_lyrics_translation` in the offline path for *other* bridge methods but lets this one through). The user's lyric text still leaves the machine, silently, in the one mode where the user expects it not to.
- **Evidence:**
  ```python
  # services/lyrics_service.py:243-266
  def translate_lyrics(self, lyrics: str, target_lang="ru") -> str:
      if not lyrics:
          return ""
      ...
      url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(ch)}"
      req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
      with self._open_url(req, timeout=HTTP_TIMEOUT) as resp:
  ```
  vs. the provider transport, which does guard:
  ```python
  # services/lyrics_lookup.py:73-75
  def _read(self, url, deadline, headers=None):
      if is_offline(self.service.settings):
          raise ConnectionError('Включён офлайн-режим')
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe2.py` §1 — with `settings.get('network','offline_mode')` returning `True`, `translate_lyrics('Hello world\nsecond line')` still produced **1** request to `https://translate.googleapis.com/translate_a/single?...&q=Hello%20world%0Asecond%20l...`. The same probe with `offline_mode=False` produced 1 request — i.e. the flag makes no difference.
- **Suggested fix:** move the offline gate into `LyricsService._open_url` (the single egress chokepoint) or add an explicit `is_offline(self.settings)` short-circuit at the top of `translate_lyrics` that returns the original text unchanged.
- **Fix side effects:** the translate button would silently produce no translation while offline; the UI must show a distinct "offline" state rather than "translation failed" (`ui/web_new_v2/js/lyrics.js:85-87` currently only logs to the console).
- **Discovered by:** B

#### F-WN-22-2  [P1] — One lyrics lookup costs 16–27 outbound HTTPS requests to five third-party hosts, and nothing in the repo bounds that number

- **File:** `services/lyrics_lookup.py:346-357` (job fan-out), `86-213` (per-provider request counts), `25` (`BUDGET = 8.0`), `services/lyrics_service.py:87` (6 workers)
- **Confirmed:** yes
- **Description:** a single cold lookup issues **16** requests for a plain title, **23** when a base-version fallback form is added, and **27** in the worst case the title parser can construct (5 query forms). The count is a *product*, not a sum: LRCLIB issues 2, Netease up to 5 (1 search + 4 lyric fetches), Genius 2, QQ Music up to 5, Megalobiz up to 3 — and the alternate query forms re-run LRCLIB and Netease again. No test, benchmark or constant bounds this.
- **Cause:** the fan-out at `lyrics_lookup.py:346-349` multiplies a 5-provider list by up to 5 query forms, and each provider internally loops over up to 12 candidates / 4 lyric fetches, with no shared round-trip budget.
- **Trigger conditions:** every track change. `ui/web_new_v2/js/lyrics.js:297-299` dispatches `loadCurrentTrackLyrics()` on every `nedotify:track_changed`, which calls `get_lyrics` at `ui/web_new_v2/js/lyrics.js:854`. A cache miss therefore means 16+ third-party requests per track.
- **User impact:** the app talks to five lyric providers 16+ times per new song; on a metered or restricted connection this is slow, and any provider-side rate limiting degrades the cascade. There is no regression guard, so a change that doubles the candidate loop (e.g. `attempts >= 4` → `>= 8`) would ship silently.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:346-357
  jobs = [(self.lrclib, forms[0]), (self.netease, forms[0]), (self.genius, forms[0])]
  jobs += [(self.lrclib, f) for f in forms[1:]]
  jobs += [(self.qqmusic, forms[0]), (self.megalobiz, forms[0])]
  jobs += [(self.netease, f) for f in forms[1:]]
  ```
  ```python
  # services/lyrics_lookup.py:145-146 (netease) and 171-172 (qqmusic) — up to 4 lyric fetches each
  if attempts >= 4:
      break
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe.py` stubs the transport and counts `_read` calls per lookup: `'Song'/'Artist'` → **16**; `'Song (Remix)'/'Artist'` → **23**; `'Artist - Song (Remix) feat. Guest'/'Uploader'` (5 forms) → **27**.
  The two artefacts the brief names do **not** measure this:
  - `tests/test_lyrics_performance.py` asserts cache behaviour and *fast-path latency* (`elapsed < .5`, line 162) but never counts provider round-trips.
  - `tests/benchmark_lyrics_cache.py:35-43` replaces four of the five providers with `lambda *args: None` and mocks a single 150 ms provider — its own docstring admits it "measure[s] cache overhead/reuse, not the speed or availability of real LRCLIB/Netease/Genius servers". The design doc repeats the caveat (`docs/PLAYBACK_LYRICS_PERFORMANCE.md:47`). It is also not collected by pytest (filename does not match `test_*.py`), so it never runs in CI.
- **Suggested fix:** introduce an explicit round-trip budget object (e.g. `max_requests`) threaded through the provider calls, and add a regression test that asserts the number of `_read` calls for a canonical title stays under a stated ceiling.
- **Fix side effects:** a hard ceiling lowers the hit rate for hard-to-match tracks (the 12-candidate / 4-attempt loops are what find Netease/QQ releases at all); the ceiling must be per-cascade, not per-provider.
- **Discovered by:** B

#### F-WN-22-3  [P2] — The 8-second cascade budget starts before the job owns a pool slot, so a superseded cascade can starve the current one into a false "unavailable"

- **File:** `services/lyrics_lookup.py:284` (deadline), `:350-357` (submit), `:358-369` (wait loop), `:374` (result), `services/lyrics_service.py:87` (6-worker pool), `core/api.py:3196-3201` (cascade supersession counter)
- **Confirmed:** mechanism yes; real-world trigger is a hypothesis (see Reproduction)
- **Description:** the cascade budget is `time.monotonic() + self.BUDGET` computed *before* the jobs are queued (line 284) and the jobs are submitted to a shared 6-worker pool (line 351). If all six slots are occupied, the new cascade's jobs sit in the pool's unbounded queue while its budget burns down; when the budget expires the wait loop exits with `futures` still pending, `failed = True` is set (line 371) and the result becomes `{'status': 'unavailable'}` — even though no provider was ever contacted and the providers are healthy. A superseded cascade keeps its already-running jobs (up to 6 of them) until their own HTTP timeout (up to 6 s), so skipping tracks leaves the pool occupied by work nobody will read.
- **Cause:** the budget is wall-clock from *request* time, but the resource is a *worker slot*; the two are not the same clock, and the pool has no per-cascade admission control or queue bound.
- **Trigger conditions:** the user skips through tracks faster than a cascade completes while the network is slow (each superseded cascade holds up to 6 workers for up to 8 s). The frontend triggers a new cascade on every `nedotify:track_changed` (`ui/web_new_v2/js/lyrics.js:297`).
- **User impact:** the current track shows *"Не удалось загрузить текст: источники временно недоступны"* with a Retry button (`ui/web_new_v2/js/lyrics.js:931-935`) although nothing is actually unavailable — the app gave up waiting for a free worker.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:284
  deadline = time.monotonic() + self.BUDGET
  ...
  # services/lyrics_lookup.py:350-357
  for provider, form in jobs:
      future = self.service.submit(run, provider, form)
  ...
  # services/lyrics_lookup.py:358-371
  while futures and current() and time.monotonic() < deadline:
      ...
  if futures:
      failed = True
  ```
  ```python
  # services/lyrics_lookup.py:370-374
  result = flight['best'] or {'status': 'unavailable' if failed else 'not_found', ...}
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe2.py` §3 — occupying all six pool slots with sleeping tasks and then calling `get_lyrics('Song','Artist',120000)` returned after **8.01 s** with `status='unavailable'` and **zero** provider invocations. *Missing evidence for a CONFIRMED user-facing trigger:* I did not run the real app (ground rules) and did not replay real track-skipping against live providers; the "skip quickly on a slow link" scenario is therefore a hypothesis built on the confirmed mechanism.
- **Suggested fix:** start the budget when the cascade actually acquires its first worker slot (or reserve a slot up-front), and/or cancel the in-flight jobs of a superseded cascade instead of letting them hold the pool until their socket timeout.
- **Fix side effects:** cancelling superseded jobs shortens the life of a partially useful provider call; a superseded cascade is by definition unwanted, so the trade is favourable, but the `offer()` path must keep its `current()` guard so a late result is still discarded.
- **Discovered by:** B

#### F-WN-22-4  [P2] — The live title normaliser and the unit-tested one are different implementations, and the tested one is dead code

- **File:** `services/lyrics_service.py:91-103` (the promise), `:104-134` (`_VARIANT_TOKENS` / `_WEAK_` / `_STRONG_`), `:137-176` (`_strip_variant_qualifiers`), `:197-234` (`_clean_track_and_artist`); live path `services/lyrics_lookup.py:243` → `services/music_matching.py:55-95` (`title_metadata`); test that pins the dead copy `tests/test_lyrics_netease.py:211-213`
- **Confirmed:** yes
- **Description:** `services/lyrics_service.py:91-103` documents a deliberate capability — "these have to be stripped from a title before querying — otherwise a bootleg/slowed/remix is looked up verbatim, matches nothing, and the app reports 'lyrics not found'". The implementation of that capability (`_strip_variant_qualifiers` + a 60-token variant vocabulary) exists and is unit-tested — but it is **never called on the production path**. The live path is `title_metadata()` (`services/music_matching.py:55-95`), whose `VERSION_PATTERNS` cover only `instrumental|cover|live|acoustic|sped|slowed|remix`. Qualifiers such as *Radio Edit*, *Extended Mix*, *1.5x*, *8D Audio*, *VIP*, *Mashup*, *Club Mix*, *Bass Boosted* are therefore neither stripped from the provider query nor from `base_title`, so the `accept()` identity gate (`.85` similarity, `services/lyrics_lookup.py:43-45`) rejects the provider's own correct answer.
- **Cause:** two normalisers with different vocabularies; the one the code documents and the tests exercise is not the one the cascade uses. The divergence is invisible because the test pins the dead copy and therefore passes.
- **Trigger conditions:** any track whose title carries one of the ~50 qualifiers that `title_metadata` does not know. Typical for YouTube-derived titles ("… (Radio Edit)", "… [Extended Mix]", "… (1.5x)").
- **User impact:** *"Текст песни не найден"* for songs whose lyrics the provider **did** return — the provider's result is discarded by the identity gate, and the user is shown a false negative. The extra request also goes out with the raw qualifier in the query string (`track_name=Sandstorm+%28Radio+Edit%29`).
- **Evidence:**
  ```python
  # services/lyrics_service.py:216 — the only call site of the stripper
  track = _strip_variant_qualifiers(track)
  # ...inside _clean_track_and_artist (services/lyrics_service.py:197), which nothing calls
  ```
  ```python
  # services/music_matching.py:8-16 — the vocabulary the LIVE path actually uses
  VERSION_PATTERNS = {
      'instrumental': ..., 'cover': ..., 'live': ..., 'acoustic': ...,
      'sped': ..., 'slowed': ..., 'remix': r'\b(?:remix|rmx|bootleg|rework|ремикс\w*)\b',
  }
  ```
  ```python
  # services/lyrics_lookup.py:328-329 — the live query uses metadata['title'], i.e. the UNSTRIPPED title
  forms = [{'metadata': metadata, 'query_title': metadata['title'], 'query_artist': ', '.join(metadata['artists']),
            'duration': duration, 'album': album, 'fallback': False}]
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe3.py`:
  - §A — `get_lyrics('Sandstorm (Radio Edit)', 'Artist', 120000)` returned `status='not_found'` while `_clean_track_and_artist` was monkey-patched to raise `AssertionError`; the patched method was **never called** → it is not on the production path. The provider URL was `https://lrclib.net/api/get?artist_name=Artist&track_name=Sandstorm+%28Radio+Edit%29&duration=120`.
  - §B — the stubbed provider *did* return `{'trackName':'Sandstorm','artistName':'Artist','duration':120,'syncedLyrics':'[00:01.00] words'}`; `accept()` returned `None` because `expected['base_title'] == 'Sandstorm (Radio Edit)'` vs offered `'Sandstorm'` → similarity 0.62 < 0.85.
  - §D — the live normaliser strips `remix`/`slowed`/`sped`/`live` but leaves `Radio Edit`, `Extended Mix`, `1.5x`, `8D Audio`, `VIP`, `Mashup`, `Club Mix`, `Bass Boosted` intact (verified against `title_metadata` directly).
  - Note: the *dead-code* fact is already recorded in `docs/audits/independent_verification/VERIFIED_FINDINGS_PART1.md:741-746`; what is new here is the **behavioural consequence** and the **test that pins the wrong copy** (`tests/test_lyrics_netease.py:211-213` asserts `_clean_track_and_artist` strips "Radio Edit" — a property the shipped app does not have).
- **Suggested fix:** give the identity layer one owner. Either widen `services/music_matching.py::VERSION_PATTERNS` to cover the variant vocabulary and delete `_strip_variant_qualifiers`/`_clean_track_and_artist`, or call the stripper from `LyricsLookup.get()` before `title_metadata()` and make `base_title` derive from the stripped title. Move the test to assert through `LyricsLookup.get()` instead of the private cleaner.
- **Fix side effects:** widening the version vocabulary changes `match_type` semantics (`exact` vs `base`) and the `BASE_FALLBACK_VERSIONS` gate (`sped|slowed|remix`) — a title newly classified as a version may legitimately be served base lyrics. Both reviewers of WN-22 should agree on the normalisation owner before the change lands.
- **Discovered by:** B (the behavioural half is likely to be reported by Role A as well; the architectural root cause — two divergent normalisers plus a test pinning the dead one — is the Role B half)

#### F-WN-22-5  [P2] — The user's listening history is broadcast to five third-party providers on every track change, with no setting and no consent gate

- **File:** `services/lyrics_lookup.py:95, 122, 152, 177, 195` (the query URLs), `services/lyrics_service.py:264` (Google Translate), trigger `ui/web_new_v2/js/lyrics.js:297-299` + `:854`, `core/api.py:3192`
- **Confirmed:** yes
- **Description:** each cold lookup sends the pair *artist + title* (and, for LRCLIB, the track duration) to five unrelated companies — LRCLIB, NetEase Cloud Music, QQ Music, Genius and Megalobiz — plus the entire lyric text to Google Translate. The lookup is triggered unconditionally by the `track_changed` event, whether or not the user has ever opened the lyrics panel, and there is no setting that selects, limits or disables the providers: `core/settings.py` contains only the `toggle_lyrics` hotkey and `network.offline_mode`.
- **Cause:** the cascade has no provider-allowlist, no per-provider opt-in and no "only when the panel is open" gate; the only privacy switch (`offline_mode`) blocks the providers but not the translation (F-WN-22-1).
- **Trigger conditions:** every track change while the app is online. The RAM/disk cache suppresses repeats for the *same* track, but each new song is a fresh 5-provider broadcast.
- **User impact:** the user's complete listening history is disclosed to five third parties as a by-product of playback — including for tracks the user never asks lyrics for. A user who never touches the lyrics feature still leaks it. The offline switch does not reliably stop this (F-WN-22-1).
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:95, 122, 152, 177, 195
  data = self._json('https://lrclib.net/api/get?' + urllib.parse.urlencode(params), deadline)
  data = self._json(f'https://music.163.com/api/cloudsearch/pc?type=1&offset=0&limit=12&s={query}', deadline, headers)
  data = self._json(f'https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={query}&format=json&p=1&n=12', deadline, headers)
  data = self._json(f'https://genius.com/api/search/multi?per_page=5&q={query}', deadline)
  page = self._read(f'https://www.megalobiz.com/search/all?qry={query}', deadline)
  ```
  ```javascript
  // ui/web_new_v2/js/lyrics.js:297-299 — fires on every track change
  document.addEventListener('nedotify:track_changed', () => {
      loadCurrentTrackLyrics();
  });
  ```
- **Reproduction / verification:** static reading of the five call sites above plus `ui/web_new_v2/js/lyrics.js:297-299, 854`; confirmed that `core/settings.py` contains no lyrics-provider key (grep for `lyrics` returns only the hotkey at `core/settings.py:140`). *Not measured:* how many distinct users/tracks this affects in practice.
- **Suggested fix:** gate the cascade on an explicit user-visible setting (e.g. `lyrics.providers` / `lyrics.auto_lookup`), and at minimum do not query providers until the lyrics panel has been opened at least once for that track.
- **Fix side effects:** delaying the lookup until the panel is opened removes the "lyrics are already there when you switch to the player page" behaviour (`ui/web_new_v2/js/pages.js:170-171`); a prefetch-on-track-change flag would preserve it while keeping the data local until needed.
- **Discovered by:** B

#### F-WN-22-6  [P2] — `translate_lyrics` silently truncates long lyrics and can run for 60 s with no UI-side timeout or cancel

- **File:** `services/lyrics_service.py:243-272` (esp. `248-261`), `core/api.py:3286-3291`, `ui/web_new_v2/js/lyrics.js:57-92`
- **Confirmed:** yes
- **Description:** the text is chunked at 1500 characters but the loop stops after 10 chunks (`if len(chunks) >= 10: break`) and **discards the remainder without any signal**. A 27 889-character lyric loses 13 309 characters (48 %). The frontend then aligns the truncated translation to the original line-by-line (`ui/web_new_v2/js/lyrics.js:67-79`), so the tail of the song simply has no translation and no error is shown. In the worst case the helper performs 10 *sequential* HTTPS requests with a 6-second timeout each (`HTTP_TIMEOUT = 6.0`, `services/lyrics_service.py:28`) — 60 s of work on one bridge call.
- **Cause:** the chunk cap was introduced to survive a 414 from the translate endpoint, but it is a silent truncation rather than an explicit "partial translation" result; and the call is a blocking promise with no timeout, no cancellation and no progress signalling on the frontend.
- **Trigger conditions:** a long song (many verses / a translated karaoke file) — 10 chunks ≈ 15 000 characters, i.e. roughly 250+ lines of lyric. A stalled or rate-limited translate endpoint additionally stretches the call to the full 60 s.
- **User impact:** the translation toggle appears to work but silently stops part-way through the song; and in the stalled case the user stares at the toast *"Переводим текст песни..."* for up to a minute with no way to cancel (`ui/web_new_v2/js/lyrics.js:59-63` — the promise has no `.finally` reset and no AbortController).
- **Evidence:**
  ```python
  # services/lyrics_service.py:248-261
  chunks = []
  text = str(lyrics)
  while text:
      if len(text) <= 1500:
          chunks.append(text)
          break
      cut = text.rfind("\n", 0, 1500)
      if cut <= 0:
          cut = 1500
      chunks.append(text[:cut])
      text = text[cut:].lstrip("\n")
      if len(chunks) >= 10:
          break            # <-- tail dropped, no flag, no log
  ```
  ```python
  # services/lyrics_service.py:269
  return "\n".join(out) if out else lyrics
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe2.py` §4 — a 27 889-character input produced 10 chunks covering 14 580 characters; 13 309 characters were dropped. The same section computes the worst case: 10 sequential requests × `HTTP_TIMEOUT` 6.0 s = **60 s**. The frontend has no timeout on the promise (`ui/web_new_v2/js/lyrics.js:63-87` — only `.catch(err => console.error(...))`).
- **Suggested fix:** return an explicit `{text, truncated: bool}` (or raise) instead of silently truncating, surface `truncated` in the UI, and put a wall-clock deadline plus a per-request timeout on the translation call; the frontend should apply its own timeout so the toast can be dismissed.
- **Fix side effects:** changing the return type of `translate_lyrics` breaks `core/api.py:3289` and `services/artist_service.py:213`, which both expect a plain string.
- **Discovered by:** B

#### F-WN-22-7  [P2] — The lyrics thread pool is never shut down by `AppCore.cleanup()`, so closing the app with a lookup in flight stalls the process exit

- **File:** `services/lyrics_service.py:87-88` (pool + `atexit`), `:192-195` (`shutdown_executor` — dead), `core/app.py:562-586` (the cleanup pool list — lyrics is absent)
- **Confirmed:** yes
- **Description:** `AppCore.cleanup()` explicitly shuts down the `BaseMusicService` pool and seven other pools (`core/app.py:562-586`) but **not** the lyrics pool. `LyricsService.shutdown_executor()` exists for exactly this purpose and has **no caller anywhere in the repository**. The only shutdown is `atexit.register(_lyrics_pool.shutdown, wait=False, cancel_futures=True)` (`services/lyrics_service.py:88`), but CPython runs `threading._shutdown()` — which joins `ThreadPoolExecutor` workers via `concurrent.futures.thread._python_exit` — *before* the `atexit` handlers. The cancel therefore arrives after the join, so an in-flight provider read is awaited in full.
- **Cause:** the lyrics pool is a private module global rather than a pool registered with `AppCore`, so the cleanup list does not know about it; and the atexit-based fallback is ordered after the interpreter's own executor join.
- **Trigger conditions:** the user closes the app while a lyrics lookup is running — which is the normal case, since a lookup is started on every track change (`ui/web_new_v2/js/lyrics.js:297`).
- **User impact:** the window closes but the process lingers in the task manager for up to the socket timeout (6 s) — and unboundedly longer against a server that trickles bytes, since `response.read(2 * 1024 * 1024)` (`services/lyrics_lookup.py:81`) restarts the per-recv timer on every chunk. The watchdog path `os._exit(3)` (`main.py:539`) skips `atexit` entirely, so on that path the pool is never cancelled at all.
- **Evidence:**
  ```python
  # services/lyrics_service.py:87-88
  _lyrics_pool = _LyricsSharedExecutor(max_workers=6, thread_name_prefix="LyricsPool")
  atexit.register(_lyrics_pool.shutdown, wait=False, cancel_futures=True)
  ```
  ```python
  # core/app.py:571-580 — the pool list; the lyrics pool is absent
  _step("base_service pool", _shutdown_shared_pool)
  for _pool in (
      getattr(self, "downloader", None) and getattr(self.downloader, "_pool", None),
      getattr(self, "cache", None) and getattr(self.cache, "_executor", None),
      ... 7 pools, no lyrics pool ...
  ):
  ```
  Repo-wide grep for `shutdown_executor` returns only its definitions in `services/base_service.py:175`, `services/lyrics_service.py:193` and `services/track_resolver.py:111` plus the single call site `core/app.py:565` (which calls the **BaseMusicService** one).
- **Reproduction / verification:** static — the grep above plus `core/app.py:562-586`. *Not measured:* the wall-clock exit delay in the real app (the ground rules forbid running it); the ordering claim is from CPython's documented finalisation sequence (`Py_FinalizeEx` → `wait_for_thread_shutdown` → `call_py_exitfuncs`).
- **Suggested fix:** call `LyricsService.shutdown_executor()` from `AppCore.cleanup()` (it is already written and safe), and/or register the lyrics pool in the same list the other pools use.
- **Fix side effects:** cancelling in-flight provider reads at shutdown is correct (the results are discarded anyway), but any caller that expects a lyrics result during teardown would now get `None` — `core/api.py:3209` already guards with `if not current(): return`.
- **Discovered by:** B (the missing call is owned by WN-02's `cleanup()`; the unused shutdown API and the aexit-ordering bug are owned by WN-22)

#### F-WN-22-8  [P3] — Every disk-cache write performs two unindexed full-table scans

- **File:** `services/lyrics_cache.py:91-107` (table + index + the per-write scans), `:20-22` (limits)
- **Confirmed:** yes
- **Description:** each `put()` first runs `DELETE FROM lyrics_cache WHERE expires <= ?` — a predicate on `expires`, for which **no index exists** (the only index is on `updated`, line 92) — and then runs `SELECT COUNT(*), COALESCE(SUM(length(payload)), 0) FROM lyrics_cache` over every row. The eviction scan (line 101) adds a third full scan ordered by `updated` whenever a limit is exceeded.
- **Cause:** the expiry purge was written without an index on `expires`, and the size accounting was designed for a small table; the documented ceiling is 20 000 entries / 96 MiB of payload (`services/lyrics_cache.py:20-21`, `docs/PLAYBACK_LYRICS_PERFORMANCE.md:20`).
- **Trigger conditions:** any lookup that ends in a `found` result writes to the cache (`services/lyrics_lookup.py:234-235`).
- **User impact:** cache-write latency grows linearly with the number of cached songs; at the 20 000-entry ceiling every write scans the whole table twice. The work happens on the per-request thread (`core/api.py:3224`), not on the UI thread, so it does not freeze the window — it lengthens the lookup that follows.
- **Evidence:**
  ```python
  # services/lyrics_cache.py:92-96
  conn.execute('CREATE INDEX IF NOT EXISTS lyrics_cache_updated ON lyrics_cache(updated)')
  now = time.time()
  conn.execute('DELETE FROM lyrics_cache WHERE expires <= ?', (now,))
  conn.execute('INSERT OR REPLACE INTO lyrics_cache VALUES (?, ?, ?, ?)', (self._key(key), payload, now + ttl, now))
  count, size = conn.execute('SELECT COUNT(*), COALESCE(SUM(length(payload)), 0) FROM lyrics_cache').fetchone()
  ```
- **Reproduction / verification:** static reading of `services/lyrics_cache.py:91-107` against the `MAX_ENTRIES = 20_000` ceiling. `tests/test_lyrics_performance.py:262-281` pins eviction *behaviour* (bounded count and bytes) but never measures write cost at the ceiling — the test uses `max_entries=2` / `max_entries=10`.
- **Suggested fix:** add `CREATE INDEX IF NOT EXISTS lyrics_cache_expires ON lyrics_cache(expires)` and replace the per-write `COUNT/SUM` aggregate with a maintained counter table or an occasional (e.g. every Nth write) full accounting pass.
- **Fix side effects:** one more index costs a little write throughput and disk; the aggregate is also used as the eviction trigger, so it must remain correct.
- **Discovered by:** B

#### F-WN-22-9  [P3] — Progressive lyrics publication blocks a network-pool worker on a full UI-thread round trip

- **File:** `services/lyrics_lookup.py:300-305` (listener invoked in the worker thread), `core/api.py:3203-3207` (`publish`), `core/api.py:1156-1159` (`_emit` from a non-main thread), `.venv_win/Lib/site-packages/webview/platforms/edgechromium.py:126-130` (`webview.Invoke` + `semaphore.acquire()`)
- **Confirmed:** yes
- **Description:** `offer()` calls the listener callback **synchronously on the provider worker thread**. The listener is `publish` → `AppApi._emit('lyrics_ready', ...)` → `evaluate_js` → pywebview's `Control.Invoke` followed by `semaphore.acquire()`, i.e. the worker **blocks until the UI thread has executed the script**. So the 6-worker lyrics network pool is throttled by UI-thread latency, and each cascade publishes up to 13 times (partial + final per provider).
- **Cause:** the bridge has no non-blocking publish path for worker threads; `_emit` only special-cases the *main* thread (it spawns an `EmitWorker`), and every other thread calls `evaluate_js` inline.
- **Trigger conditions:** a slow/busy UI thread (large library grid, scroll, resize) while several lyrics cascades publish partial results.
- **User impact:** lyrics publication latency is coupled to UI responsiveness; in the worst case all six network workers are parked waiting for the UI thread, which compounds F-WN-22-3.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:300-305
  for callback, check in listeners:
      if callback and check():
          try:
              callback(copy.deepcopy(payload))
          except Exception:
              logger.debug('Lyrics listener failed', exc_info=True)
  ```
  ```python
  # core/api.py:1156-1159
  try:
      self._window.evaluate_js(js_code)
  except Exception as e:
      logger.error("emit %s failed: %r", event_name, e, exc_info=True)
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/platforms/edgechromium.py:126-130
  self.webview.Invoke(Func[Object](lambda: self.webview.ExecuteScriptAsync(script)...))
  semaphore.acquire()
  ```
- **Reproduction / verification:** static chain read; the `evaluate_js` blocking behaviour was confirmed by reading the installed pywebview source. *Not measured:* the actual UI-thread latency contribution in the running app.
- **Suggested fix:** have `publish` hand the payload to a dedicated, bounded emit queue (or reuse the existing `EmitWorker` pattern) so a provider worker never waits on the UI thread.
- **Fix side effects:** an emit queue adds ordering/latency questions — the `revision` counter (`services/lyrics_lookup.py:296-297`) already provides monotonic ordering, but a queue must preserve it and must not delay the *final* frame.
- **Discovered by:** B

#### F-WN-22-10  [P3] — A second, test-only provider-dispatch layer duplicates the live one and pins the tests to a path production never runs

- **File:** `services/lyrics_service.py:300-327` (`_compat_lookup` + `_fetch_lrclib/_fetch_netease/_fetch_qqmusic/_fetch_genius/_fetch_megalobiz/_fetch_duckduckgo`), live dispatch `services/lyrics_lookup.py:346-349`; tests `tests/test_lyrics_netease.py:59, 76, 123, 142`
- **Confirmed:** yes
- **Description:** `LyricsService` carries its own provider wrappers, and `_compat_lookup` builds a *different* query form from the live cascade: `query_title` is the **raw** title instead of `metadata['title']`, `query_artist` is the raw artist string instead of the joined artist list, and `duration` is hard-coded to 0. Nothing in production calls these methods; only `tests/test_lyrics_netease.py` does.
- **Cause:** the wrappers were introduced to make the Netease endpoint testable and were never retired when the orchestration moved into `LyricsLookup`.
- **Trigger conditions:** always — the dead layer exists in the shipped module.
- **User impact:** no direct impact, but the Netease regression tests assert behaviour of a code path the app does not use, so they can pass while the real Netease path is broken (they build a different query URL than production).
- **Evidence:**
  ```python
  # services/lyrics_service.py:300-314
  def _compat_lookup(self, provider, track, artist):
      from services.music_matching import title_metadata
      form = {'metadata': title_metadata(track, artist), 'query_title': track, 'query_artist': artist,
              'duration': 0, 'album': '', 'fallback': False}
      try:
          return getattr(self._lookup, provider)(form, time.monotonic() + self._lookup.BUDGET, lambda result: None)
      except Exception as exc:
          logger.debug('Lyrics source %s unavailable: %s', provider, exc)
          return None
  ```
  vs. the live form construction at `services/lyrics_lookup.py:328-329` (`query_title=metadata['title']`, `query_artist=', '.join(metadata['artists'])`, `duration=duration`).
- **Reproduction / verification:** repo-wide grep for `_fetch_lrclib|_fetch_netease|_fetch_qqmusic|_fetch_genius|_fetch_megalobiz|_fetch_duckduckgo` returns only the definitions in `services/lyrics_service.py` and four call sites in `tests/test_lyrics_netease.py`.
- **Suggested fix:** delete `_compat_lookup` and the `_fetch_*` wrappers, and re-point the Netease tests at `LyricsLookup.netease` with a production-shaped form (the shape already exists in `tests/test_lyrics_performance.py:32-34`).
- **Fix side effects:** `tests/test_lyrics_netease.py` must be rewritten; the assertions on `weight == 2` depend on the `duration: 0` form and will need the real duration semantics.
- **Discovered by:** B

---

### 3. Clean areas

- **No XSS path from third-party lyrics text (checked end to end, both ends quoted).** `core/api.py::get_lyrics` returns the provider's raw text (`services/lyrics_lookup.py:68`, `{'plainLyrics': text or None}`), and `ui/web_new_v2/js/lyrics.js` inserts it **only** through `textContent`:
  ```javascript
  // ui/web_new_v2/js/lyrics.js:953, 959, 1009, 1013
  origSpan.textContent = line.text;
  subEl.textContent = currentTranslationMap[line.text];
  el.textContent = line;
  subEl.textContent = currentTranslationMap[line];
  ```
  Every `innerHTML` assignment in the module carries a **static literal**: `ui/web_new_v2/js/lyrics.js:781, 813, 907, 933, 946, 995` (fixed Russian strings) and `:1002` (`warnEl.innerHTML = \`<i data-lucide="info" ...></i><span>${message}</span>\`` where `message` is a two-way literal ternary, not provider data). The translated text — the second untrusted input — is rendered through `textContent` at `:959` and `:1013`, and the mini-widget through `textContent` at `:1236, 1241`. A repo-wide grep for `plainLyrics|syncedLyrics` in `ui/web_new_v2/js` shows no other consumer. **No injection path exists today.**
- **The Genius provider allow-lists the host before fetching**, so a hostile search response cannot redirect the fetch: `services/lyrics_lookup.py:185` — `if urllib.parse.urlparse(url).hostname not in ('genius.com', 'www.genius.com'): continue`. The Megalobiz links are relative (`/lrc/maker/...`) and are re-prefixed with a fixed host (`services/lyrics_lookup.py:196-198`).
- **TLS verification is on for every lyrics request** — `ssl_ctx = ssl.create_default_context()` (`services/lyrics_service.py:25`) is passed to every `urlopen` (`:241`), so the certificate check is never disabled.
- **The disk-cache key is filesystem-safe (contract #8).** The identity is a SHA-256 hex digest stored as a `TEXT PRIMARY KEY` in SQLite; **no filename is ever derived from a title**, so a title containing `< > : " / \ | ? *` cannot break a write. Verified: `LyricsDiskCache._key(('a/b\\c:d*e?f"g<h>i|j', ...))` → `b1c49e0b…fe6` (64 lowercase hex chars, raw title absent). `services/lyrics_cache.py:32-36`, `:91`.
- **The disk cache is not poisoned by failures.** `LyricsLookup._remember` writes to disk only when `result['status'] == 'found'` (`services/lyrics_lookup.py:234`), and `LyricsDiskCache.valid()` independently re-requires `status == 'found'` (`services/lyrics_cache.py:40`). `not_found` is kept only in RAM with a 30 s TTL (`services/lyrics_lookup.py:228`); `unavailable` is never cached at all (`services/lyrics_lookup.py:226-227`).
- **One provider failing does not abort the cascade, and all providers failing yields a clean "no lyrics".** Each provider runs in its own future and its exception is caught per-future (`services/lyrics_lookup.py:360-364`), so the remaining providers still run; if nothing succeeds the result is `{'status': 'unavailable', 'syncedLyrics': None, 'plainLyrics': None, 'weight': 3}` (`services/lyrics_lookup.py:374`), which the UI renders as *"Не удалось загрузить текст: источники временно недоступны"* with a Retry button (`ui/web_new_v2/js/lyrics.js:931-935`). Pinned by `tests/test_verified_lyrics.py:87-100` and `tests/test_lyrics_performance.py:284-296`.
- **The disk-cache read/write do not run on the pywebview bridge thread.** `core/api.py:3192-3225` starts a dedicated `threading.Thread(target=run, …)` and returns `{'status': 'loading'}` immediately; the cache I/O happens inside that thread (`services/lyrics_lookup.py:309` and `:235`). pywebview additionally dispatches each bridge call on its own thread (`webview/util.py:308`), so neither the SQLite open nor the provider I/O can freeze the window.
- **The in-memory cache is bounded and LRU.** `MEMORY_ENTRIES = 2048` with `OrderedDict.move_to_end` + `popitem(last=False)` (`services/lyrics_lookup.py:26, 230-233, 317-318`).
- **The cascade latency is bounded in wall-clock and every HTTP timeout is clamped to the remaining budget.** `BUDGET = 8.0` (`services/lyrics_lookup.py:25`), `timeout=min(6.0, remaining)` (`services/lyrics_lookup.py:80`), and each provider additionally checks the deadline before starting (`services/lyrics_lookup.py:343-344`).
- **Offline mode does block the provider path** (`services/lyrics_lookup.py:74-75`) and the bridge's offline interception (`core/api.py:502-503`) lists `get_lyrics_translation` among the methods it lets through — the *provider* side is correctly guarded (the translation side is F-WN-22-1).
- **Listener callbacks are invoked outside the cache lock** (`services/lyrics_lookup.py:290-305` releases `_cache_lock` before calling the listener), pinned by `tests/test_lyrics_performance.py:91-107`.
- **In-flight requests for the same identity are de-duplicated** (`services/lyrics_lookup.py:268-273, 279-283`), pinned by `tests/test_verified_lyrics.py:103-118`.
- **The disk cache treats a corrupt/broken file as a miss, never as an error** (`services/lyrics_cache.py:66-74` catches `OSError, sqlite3.Error, ValueError, TypeError`), pinned by `tests/test_lyrics_performance.py:247-259`.

---

### 4. Coverage gaps

- **No live-provider measurement.** `pytest.ini` deselects the `network` marker, so LRCLIB / NetEase / QQ / Genius / Megalobiz were never contacted. Their real latency, availability and rate-limit behaviour — the inputs F-WN-22-2 and F-WN-22-3 depend on — are unmeasured; the round-trip counts in F-WN-22-2 are exact for the *code*, not for the *services*.
- **The real app was not run** (ground rules), so the pool-starvation trigger in F-WN-22-3 was demonstrated with a synthetic probe (all six pool slots occupied), not by skipping tracks in the UI, and the exit stall in F-WN-22-7 was not timed in a live shutdown.
- **The cost of the disk-cache scans at the 20 000-entry ceiling was not measured** — F-WN-22-8 is established from the SQL and the index list, not from a populated 20 000-row table.
- **The translation path was not exercised against the live Google endpoint** — the 60 s worst case and the 48 % truncation are computed from the code and a 27 889-character synthetic input.
- **The HTML scrapers were not run against real markup.** `services/lyrics_lookup.py:188` (Genius `data-lyrics-container` regex) and `:196-199` (Megalobiz `href="/lrc/maker/..."` and `id="lrc_..."` regexes) are brittle by construction, but their breakage rate is unmeasured and their markup is not in the repo.
- **The WebView2 rendering of the lyrics sheet was not exercised** — `ui/web_new_v2/js/lyrics.js` was reviewed statically and via the Node-based harness in `tests/test_catalog_lyrics_ui.py`, not in a real browser.
- **The `android/` subtree was deliberately not opened** (out of scope for this run). `docs/audits/independent_verification/VERIFIED_FINDINGS_PART1.md:741-746` records that the Android port merged the two title layers and dropped the artist-conditioned prefix rule; that comparison was not re-verified here.
- **`services/artist_identity.py` and `services/music_matching.py` were read only as far as the lyrics path requires** (their own area is WN-18).

---

### 5. Architecture improvements (ARCH)

*(No proven defect — improvement proposals only; kept separate from the defect list.)*

- **ARCH-1 — There is no provider abstraction; the provider list is a literal inside one method.** `services/lyrics_lookup.py:346-349` builds the job list inline, and the alternate query forms are given to **only two** of the five providers (`lrclib` and `netease`); `qqmusic`, `genius` and `megalobiz` only ever see `forms[0]`. Adding a provider requires editing three statements in one method, and the asymmetry (why only two providers get the fallback forms) is undocumented. A `PROVIDERS = (Provider(name, fn, accepts_alternate_forms=True), …)` tuple plus a single fan-out loop would make the list data, make the asymmetry explicit, and remove the hard-coded `jobs +=` lines. *Note the tension with F-WN-22-2: a data-driven list makes the round-trip count easier to bound, but it also makes it easier to grow.*
- **ARCH-2 — `_LyricsSharedExecutor` is a near-verbatim second copy of `services/base_service.py::_SharedExecutor`.** `services/lyrics_service.py:31-88` and `services/base_service.py:65-118` implement the same lazy-create / shutdown-safe / `submit`-returns-`None` contract (~50 duplicated lines). `LyricsService` does not extend `BaseMusicService`, so it also does not participate in the class-level `_cache_lock` and cannot reuse the shared pool. One shared executor with a per-service worker budget would remove the duplication — and, directly, would put the lyrics pool on the list that `core/app.py:562-586` already shuts down (F-WN-22-7).
- **ARCH-3 — The module names do not match the responsibilities.** `LyricsService` ("service") is a façade plus ~200 lines of production-dead code, while `LyricsLookup` ("lookup") performs the *orchestration*: the RAM cache, the in-flight registry, the provider fan-out, the progressive publication and the disk-cache orchestration all live in `services/lyrics_lookup.py:225-387`. Either rename the modules (`lyrics_service` = the orchestrator, `lyrics_providers` = the provider clients) or move the orchestration back into the service and leave the lookup holding only provider clients.
- **ARCH-4 — `LyricsLookup` mutates `LyricsService`'s private attributes.** `services/lyrics_lookup.py:30-32` assigns `self.service._cache` and `self.service._inflight`, while `services/lyrics_service.py:182` allocates `self._cache = {}` that is discarded one line later. `LyricsService` has no `_inflight` of its own — it exists only as a side effect of constructing the lookup, so any other construction path would `AttributeError` at `services/lyrics_lookup.py:268`. The lookup should own the cache/in-flight state and expose it, or the service should own it and pass it in explicitly.
- **ARCH-5 — A generic string-similarity helper is exported from the lyrics service and consumed by the track resolver.** `services/lyrics_service.py:295-298` (`_title_match_score`) is used at `services/track_resolver.py:241-244` for generic title/artist matching. The resolver (WN-18) should depend on `services/music_matching.py` directly; a lyrics module should not be a dependency of track resolution.
- **ARCH-6 — Two different async contracts on the bridge for one feature.** `get_lyrics` is asynchronous-progressive (returns `{'status':'loading'}` and streams `lyrics_ready` events with a `revision`), while `get_lyrics_translation` is a blocking promise that resolves with the whole translation (`core/api.py:3286-3291`). The frontend has to treat the two halves of the same panel differently (`ui/web_new_v2/js/lyrics.js:63` vs `:313-316`), and only the progressive half has cancellation, ordering and staleness handling. A progressive `lyrics_translation_ready` event (chunked) would unify the model and remove the 60 s and truncation problems of F-WN-22-6 at the same time.
- **ARCH-7 — The five providers have five different response contracts.** LRCLIB returns JSON with explicit fields, Netease/QQ return a candidate list plus a per-candidate lyric fetch, Genius and Megalobiz are HTML scrapers with ad-hoc regexes. `accept()` (`services/lyrics_lookup.py:40-71`) is the only place that understands this, and it is also the identity gate, the version gate, the duration gate and the karaoke-timing gate. Splitting "identity/timing validation" from "candidate normalisation" would let the HTML scrapers be replaced by a JSON API without touching the security-relevant gate.
