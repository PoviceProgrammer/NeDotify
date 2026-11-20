## WX-06 — Lyrics cascade (`get_lyrics` → `lyrics_service` → `lyrics_lookup` → `lyrics_cache` → UI) — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read | Role in the scenario |
|---|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 | common brief, contracts, report format |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 | WX table |
| `docs/PLAYBACK_LYRICS_PERFORMANCE.md` | 1–51 | **the intent document for this cascade** (source order, TTLs, budget, UI-cache rules) |
| `ui/web_new_v2/js/lyrics.js` | 1–1225 (whole file) | the view: request, guards, LRC parser, karaoke clock, translation |
| `core/api.py` | 3150–3449, 1085–1188, 1400–1459 | `get_lyrics`, `get_lyrics_translation`, `_emit` |
| `services/lyrics_service.py` | 1–327 (whole file) | `LyricsService`, `translate_lyrics`, `_strip_variant_qualifiers` |
| `services/lyrics_lookup.py` | 1–387 (whole file) | the provider cascade, source order, memory/disk cache policy |
| `services/lyrics_cache.py` | 1–109 (whole file) | `LyricsDiskCache` |
| `services/music_matching.py` | 1–95 (whole file) | `title_metadata`, `similarity`, `credits`, `artist_matches`, `BASE_FALLBACK_VERSIONS` |
| `services/artist_identity.py` | 1–63 (whole file) | `canonical_artist`, `artist_aliases` |
| `utils/tag_parser.py` | 100–179 | `extract_embedded_lyrics` |
| `core/offline.py` | 1–77 | `is_offline` |
| `ui/web_new_v2/js/player.js` | 44–73, 560–679, 735–784, 1620–1679 | `getCurrentTrack`, `normalizeDurationMs`, `timeupdate` → `position_changed` |
| `ui/web_new_v2/js/events.js` | 85–154, 330–369 | `track_changed` / `position_changed` / `lyrics_ready` re-dispatch |
| `ui/web_new_v2/js/pages.js` | 165–175 | player page → `loadCurrentTrackLyrics()` |
| `core/app.py` | 128–136 | `LyricsService(settings, cache_path=…/lyrics_cache.db)` wiring |
| `tests/test_lyrics_performance.py` | 1–342 | the pinned intent of the cache / cascade |
| `tests/test_catalog_lyrics_ui.py`, `tests/test_frontend_js.py`, `tests/test_recommendation_ui.py` | whole | the Node `vm` harness reused for the JS experiments |

**Callees traced into other areas (list)**

- `core/api.py::_emit` → `EmitWorker` thread hop (WN-03) — checked, contract #1 respected.
- `services/music_matching.py` / `services/artist_identity.py` (WN-18) — traced for the match gate.
- `utils/tag_parser.py::extract_embedded_lyrics` (WN-27) — traced for the embedded source.
- `core/offline.py::is_offline` (WN-15) — traced for the offline gate.
- `ui/web_new_v2/js/player.js` (WN-29) — traced for `getCurrentTrack`, the duration unit and the `timeupdate` clock.
- `ui/web_new_v2/js/events.js` (WN-28) — traced for the bridge-event re-dispatch.
- `services/artist_service.py:212` (`LyricsService()` instance used only by `translate_lyrics`) — read, not exercised.

**Reproduction environment.** No repo file was modified. Experiments were run from
`%TEMP%\opencode\audit_scratch\` with the repo venv (`& ".venv_win\Scripts\python.exe"`) and
Node v24.19.0 (the same harness `tests/test_recommendation_ui.py::run_node` uses).

---

### 2. Findings

#### F-WX-06-1  [P1] — A track with no artist metadata can be served another artist's lyrics; the duration in hand is never used to reject it

- **File:** `services/lyrics_lookup.py:44-71` (the gate), `services/music_matching.py:38-46` (`credits()` drops empty *and* placeholder artists), `core/api.py:3192` (`artist_name` is optional), `ui/web_new_v2/js/lyrics.js:854` (the UI forwards `track.artist` verbatim, empty string included).
- **Confirmed:** yes.
- **Description:** `accept()` only enforces the artist when the *wanted* track has one. When the wanted track has no artist, the candidate must merely have an exact base-title match, must have *some* artist, and the form must carry a duration — and then the duration is **never compared**. The duration comparison exists only inside `synced_ok`, i.e. only for karaoke results. A plain (non-synced) hit from a *different* artist and a *different* length is therefore accepted and rendered under the current track's title.
- **Cause:** the identity gate is split in two — title score always, artist only when known, duration only when the result is synced. The one case where the artist is unknown is exactly the case where the duration should carry the match, and it does not.
- **Trigger conditions:** the track's artist metadata is empty or a placeholder. `credits()` removes `'unknown'`, `'unknown artist'`, `'неизвестный исполнитель'` → `expected['artists'] == []` → the branch at line 48 is taken. The provider then returns a same-titled recording by another artist.
- **User impact:** the lyrics of a **different song** are displayed as the current song's lyrics, with no marker at all (the UI only distinguishes `match_type: base`). The user reads the wrong words and, in karaoke mode, the wrong words are highlighted against the wrong timing.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:44-49, 61-62
  score = similarity(expected['base_title'], offered['base_title'])
  if score < .85:
      return None
  if expected['artists'] and not artist_matches(expected['artists'], offered['artists'], self.service.settings):
      return None
  if not expected['artists'] and (score != 1 or not offered['artists'] or not form['duration']):
      return None
  ...
  synced_ok = bool(synced and re.search(r'\[\d+:\d{2}(?:[.:]\d+)?\]', synced)
                   and not base and wanted > 0 and duration > 0 and abs(wanted - duration) <= max(2, wanted * .01))
  ```
  The `abs(wanted - duration)` guard is inside `synced_ok` only — a plain result never reaches it.
- **Reproduction / verification:** `exp_python.py` EXP 2 (repo venv, no network):
  ```
  expected artists     : []
  accept() result      : {'matched_title': 'Yesterday', 'matched_artist': 'Gotye',
                           'matched_duration': 190.0, 'plainLyrics': 'WRONG LYRICS OF A DIFFERENT SONG'}
  same duration result : The Beatles
  ```
  i.e. wanted "Yesterday" / no artist / 265 s accepted "Yesterday" by **Gotye** / **190 s**.
  The provider payload then flows unchanged through `offer()` → `core/api.py:3206` → `js/lyrics.js:315 renderLyrics(e.detail)`.
- **Suggested fix:** when `expected['artists']` is empty, apply the same duration gate to plain results (`abs(wanted - duration) <= max(2, wanted * .01)`), and/or require the duration to match when the candidate carries one.
- **Fix side effects:** a duration-less wanted track (unknown `duration_ms`) would then reject everything — that is already the case today (`not form['duration']` → reject), so the change only tightens the *known-duration* branch. Real-world "radio edit"/length differences of >1 % would be rejected; a slightly looser tolerance (e.g. 3 %) may be needed.
- **Discovered by:** A.

#### F-WX-06-2  [P2] — The variant-qualifier stripper is dead code on the cascade path, so "(Radio Edit)", "(Extended Mix)", "(8D Audio)" … never find lyrics

- **File:** `services/lyrics_service.py:104-176` (`_VARIANT_TOKENS`, `_strip_variant_qualifiers`) and `services/lyrics_service.py:197-234` (`_clean_track_and_artist`, its only caller) versus `services/music_matching.py:8-17, 79-92` (`VERSION_PATTERNS`, the set that is actually used).
- **Confirmed:** yes.
- **Description:** the cascade normalises the title with `services/music_matching.py::title_metadata`, whose version vocabulary is only `instrumental | cover | live | acoustic | sped | slowed | remix`. The far richer stripper in `lyrics_service.py` (which knows `radio edit`, `extended mix`, `club mix`, `bass boosted`, `8d audio`, `vip`, `edit`, `1.5x`, …) is **never called by the cascade** — `_clean_track_and_artist` has exactly two call sites in the whole repo, both in `tests/test_lyrics_netease.py:212,218`. A title carrying such a qualifier keeps the qualifier inside `base_title`, the similarity against the base recording collapses below the 0.85 floor, and the lookup returns `not_found`.
- **Cause:** two normalisation implementations coexist; the cascade was moved to `music_matching.py` but the old, broader one was left in place, unreferenced.
- **Trigger conditions:** the track title contains a bracketed/dashed qualifier that is a mix/edit name but not one of the six `VERSION_PATTERNS`. This is routine YouTube/SoundCloud metadata ("Song (Radio Edit)", "Song (Extended Mix)", "Song (Bass Boosted)", "Song (8D Audio)", "Song (VIP)").
- **User impact:** "Текст песни не найден" for a whole class of tracks whose plain lyrics *are* indexed — while the shipped helper that would strip the qualifier sits unused one file away.
- **Evidence:**
  ```python
  # services/music_matching.py:8-17 — the vocabulary the cascade actually applies
  VERSION_PATTERNS = {
      'instrumental': r'\b(?:instrumental|инструментал\w*|минус|без\s+слов)\b',
      'cover': r'\b(?:cover|кавер\w*)\b',
      'live': r'\b(?:live|концерт\w*)\b',
      'acoustic': r'\b(?:acoustic|акустич\w*)\b',
      'sped': r'\b(?:sped\s*up|speed\s*up|speedup|nightcore|ускоренн\w*|ускорено)\b',
      'slowed': r'\b(?:slowed(?:\s*\+?\s*reverb)?|замедленн\w*|замедлено)\b',
      'remix': r'\b(?:remix|rmx|bootleg|rework|ремикс\w*)\b',
  }
  ```
  ```python
  # services/lyrics_service.py:216 — the unused call
          track = _strip_variant_qualifiers(track)
  ```
  (`_clean_track_and_artist` is reached only from the test file.)
- **Reproduction / verification:** `exp_python3.py` EXP 5 — `accept()` of the provider's plain "Song" against the wanted title:
  ```
  raw title                          base_title (used)          version      accept() vs "Song"
  Song (Radio Edit)                  Song (Radio Edit)          -            rejected   (unused helper -> 'Song')
  Song (Extended Mix)                Song (Extended Mix)        -            rejected   (unused helper -> 'Song')
  Song (Bass Boosted)                Song (Bass Boosted)        -            rejected   (unused helper -> 'Song')
  Song (8D Audio)                    Song (8D Audio)            -            rejected   (unused helper -> 'Song')
  Song (VIP)                         Song (VIP)                 -            rejected   (unused helper -> 'Song')
  Song (Edit)                        Song (Edit)                -            rejected   (unused helper -> 'Song')
  Song (Club Mix)                    Song (Club Mix)            -            rejected   (unused helper -> 'Song')
  Song (Official Video)              Song                       -            ACCEPTED
  Song (Remix)                       Song                       remix        ACCEPTED
  ```
- **Suggested fix:** either wire `_strip_variant_qualifiers` into the cascade (before `title_metadata`) or extend `music_matching.VERSION_PATTERNS` with the mix/edit vocabulary, keeping one implementation.
- **Fix side effects:** stripping a qualifier also has to keep the *version* semantics: "Slowed"/"Remix" must keep their karaoke-suppressing `match_type: 'base'` behaviour, and "Live"/"Acoustic"/"Instrumental" must keep being rejected. Folding the stripper in without the version bookkeeping would start serving the studio cut for a live recording.
- **Discovered by:** A.

#### F-WX-06-3  [P2] — The duration refinement fires a second, uncached provider cascade and throws the first one away

- **File:** `ui/web_new_v2/js/lyrics.js:304-311` (the refinement trigger), `ui/web_new_v2/js/lyrics.js:764-883` (`loadCurrentTrackLyrics`), `core/api.py:3196-3201` (the cascade counter), `services/lyrics_lookup.py:257-258` (the duration is part of the cache key) and `services/lyrics_lookup.py:346-353` (the job list).
- **Confirmed:** yes.
- **Description:** when the provider metadata carries no duration, the UI issues the first lookup with `duration_ms = 0`. The first `timeupdate` then supplies the real duration and the UI issues a **second** lookup. The second request has a different identity (the duration is part of the cache key), so it is a cold network cascade, and it supersedes the first one: the backend's `_lyrics_cascade_count` makes the first thread's `current()` false, and the UI's `activeLyricsRequestId` is replaced, so the first cascade's result is discarded.
- **Cause:** the refinement is modelled as "start a new request" rather than "re-target the running one". Nothing tells the backend that the second request refines the first, so the first cascade is neither cancelled nor reused.
- **Trigger conditions:** `track.duration` is absent/0 (streamed tracks whose provider metadata has no length) — the normal case for YouTube/SoundCloud catalogue entries. A track that *does* carry a duration produces exactly one call.
- **User impact:** every such track costs **two** full cascades (5 providers × search + lyric fetch) instead of one; the lyrics panel sits on the spinner roughly twice as long; the shared 6-worker lyrics pool is loaded twice, so rapid track switching can starve it (`submit()` returns `None` → the lookup degrades to `unavailable`).
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/lyrics.js:304-311
  document.addEventListener('nedotify:position_changed', (e) => {
      const posMs = e.detail?.posMs !== undefined ? e.detail.posMs : (typeof e.detail?.pos === 'number' ? e.detail.pos : 0);
      updateLyricsPosition(posMs);
      const durationMs = Number(e.detail?.durationMs ?? e.detail?.duration);
      if (!requestedLyricsDurationMs && durationMs > 0 && lastLoadedTrackKey) {
          loadCurrentTrackLyrics(durationMs);
      }
  });
  ```
  ```python
  # core/api.py:3196-3201 — every new request invalidates the previous one
  with self._lyrics_lock:
      self._lyrics_cascade_count += 1
      cascade_no = self._lyrics_cascade_count
  def current():
      with self._lyrics_lock:
          return cascade_no == self._lyrics_cascade_count
  ```
  ```python
  # services/lyrics_lookup.py:257-258 — the duration is part of the identity
  key = (normalize(metadata['title']), tuple(canonical_artist(a, aliases) for a in metadata['artists']), metadata['version'],
         normalize(album), round(duration, 2), str(file_path or ''), file_stamp)
  ```
- **Reproduction / verification:** `exp_js.mjs` EXP A runs the shipped `loadCurrentTrackLyrics` in a Node `vm` with a stubbed bridge:
  ```
  after track_changed   : calls=1  request_id=lyrics-…-1  duration_arg=0
  after position_changed: calls=2  request_id=lyrics-…-2  duration_arg=210000
  request_id changed?    : true
  -> bridge calls for ONE track: 2
  ```
  and with a provider duration present (`track.duration = 210`): `bridge calls for ONE track: 1`.
- **Suggested fix:** when the refinement fires for the same track, let the backend *re-target* the in-flight lookup (pass the new duration as an update to the running flight) instead of starting a second cascade; or defer the first request until the duration is known (the audio element knows it within one `timeupdate`).
- **Fix side effects:** deferring the first request delays the *plain* lyrics by one `timeupdate` (~250 ms); re-targeting a running flight requires the flight to accept a mutated duration, which touches the identity key that the disk cache is written under.
- **Discovered by:** A.

#### F-WX-06-4  [P2] — One failing provider out of five turns "this song has no lyrics" into "the sources are unavailable"

- **File:** `services/lyrics_lookup.py:358-374` (the `failed` flag), `core/api.py:3223` (the `unavailable` payload), `ui/web_new_v2/js/lyrics.js:928-935` (the two different messages).
- **Confirmed:** yes.
- **Description:** the lookup keeps a single boolean `failed` for the whole cascade and sets it as soon as **any** provider future raises. The final status is then `unavailable` even when four providers answered cleanly and reported that the song simply has no lyrics. The UI then shows "Не удалось загрузить текст: источники временно недоступны" ("could not load: the sources are temporarily unavailable") instead of "Текст песни не найден".
- **Cause:** `failed` is a per-lookup flag where the semantics require a per-provider distinction (no-result vs error). A single blocked host (Genius is region-blocked, NetEase returns `code != 200` outside its market, LRCLIB answers 429) is enough to reclassify the whole answer.
- **Trigger conditions:** any one of the five providers raises — an HTTP error other than LRCLIB's 400/404, a DNS failure, a `ValueError('Netease search unavailable')`, a `TimeoutError('Lyrics deadline exceeded')`.
- **User impact:** the user is told the providers are down when the real answer is "this song has no lyrics", is invited to press "Повторить", and the negative is (correctly) not cached, so every retry re-queries the whole cascade.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:360-364, 374
                  for future in done:
                      try:
                          offer(future.result())
                      except Exception:
                          failed = True
  ...
              result = flight['best'] or {'status': 'unavailable' if failed else 'not_found', 'syncedLyrics': None, 'plainLyrics': None, 'instrumental': False, 'weight': 3}
  ```
  ```javascript
  // ui/web_new_v2/js/lyrics.js:931
  const message = normalizedData.instrumental ? 'Инструментальная версия — без текста' : (normalizedData.status === 'unavailable' ? 'Не удалось загрузить текст: источники временно недоступны' : 'Текст песни не найден');
  ```
- **Reproduction / verification:** `exp_python4.py` EXP 6 — four providers return "no result", one raises:
  ```
  4 providers say "no lyrics", 1 raises  ->  status = unavailable
  --- all providers clean ---            status = not_found
  ```
- **Suggested fix:** count successes and errors per provider; report `unavailable` only when *every* provider failed, and keep `not_found` when at least one provider answered authoritatively with no match.
- **Fix side effects:** a song that genuinely has no lyrics but whose providers are all erroring would now be reported as "not found" — the user loses the "try again later" hint. A per-provider status list in the payload would be the richer fix.
- **Discovered by:** A.

#### F-WX-06-5  [P2] — The translation is aligned to the lyrics by index and shifts whenever the source text has lines the renderer drops

- **File:** `ui/web_new_v2/js/lyrics.js:57-88` (`toggleTranslation`), `ui/web_new_v2/js/lyrics.js:885-892` (`cleanPlainLyrics`), `ui/web_new_v2/js/lyrics.js:1029-1057` (`parseLrc`), `ui/web_new_v2/js/lyrics.js:956-960` / `1010-1014` (where the map is consumed).
- **Confirmed:** yes.
- **Description:** the translation is requested for the *raw* text (timestamps stripped, but **LRC metadata headers kept**), and the result is mapped back to the lyric lines **by array index**. The two lists are not the same length: `origLines` drops blank lines (`filter(Boolean)`) and `parsedLyrics` drops `[ar:]`/`[al:]`/`[offset:]` headers, while `transLines` (the split of the translated payload) keeps both. Every dropped line shifts the rest of the song by one.
- **Cause:** positional alignment between a sanitised line list and an unsanitised one; the sanitiser used for rendering (`cleanPlainLyrics`, `parseLrc`) is not applied to the text that is sent for translation.
- **Trigger conditions:** (a) plain lyrics that contain a blank line — the norm for verse-separated plain lyrics; (b) any synced LRC that carries metadata headers (`[ar:]`, `[al:]`, `[ti:]`, `[offset:]`, `[length:]`) — the norm for QQ Music / Megalobiz LRC payloads.
- **User impact:** the translation is displayed against the **wrong lyric line** — for a whole verse from the first blank line on. In case (b) the first lines show the raw tag (`[ar:Artist]`) as their "translation", and every subsequent line is shifted.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/lyrics.js:61-75
  const cleanText = String(currentRawLyricsText).replace(/\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]/g, '').replace(/^\s*\n/gm, '\n').trim();
  ...
          const transLines = res.split(/\r?\n/).map(s => s.trim());
          const origLines = cleanText.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
          const map = {};
          const keys = parsedLyrics.length > 0 ? parsedLyrics.map(l => l.text) : origLines;
          keys.forEach((k, i) => {
              if (k && transLines[i] && transLines[i] !== k) map[k] = transLines[i];
              else if (k && origLines[i] && transLines[i]) map[origLines[i]] = transLines[i];
          });
  ```
  The timestamp regex does not match `[ar:…]`, so the header survives into `cleanText` → into `transLines` → and shifts `keys`.
- **Reproduction / verification:** `exp_js2.mjs` EXP C / EXP D, executing the shipped `toggleTranslation` + `parseLrc` + `cleanPlainLyrics` in a Node `vm`:
  ```
  EXP C  parsedLyrics texts   : ["First line","Second line","Third line"]
        translation map      : {"First line":"[ar:Artist Name]","Second line":"[al:Album Name]","Third line":"[offset:0]"}
  EXP D  source lines         : ["Verse one line A","Verse one line B","","Verse two line A","Verse two line B"]
        translation map      : {"Verse one line A":"Verse one line A","Verse one line B":"Verse one line B",
                                "Verse two line B":"Verse two line A"}
  ```
  EXP D: "Verse two line A" gets **no** translation and "Verse two line B" gets the translation of "Verse two line A".
- **Suggested fix:** build the translation from the same sanitised line list that is rendered (strip metadata headers and blank lines before sending, and translate line-by-line or in blocks), or return a numbered/aligned structure from the backend instead of a flat blob.
- **Fix side effects:** translating per line costs one request per line unless batched; sanitising before translation removes the blank lines that give the translator its verse structure, which slightly degrades the machine translation quality.
- **Discovered by:** A.

#### F-WX-06-6  [P3] — The "Повторить" (Retry) button is a no-op for 30 seconds after a genuine "not found"

- **File:** `services/lyrics_lookup.py:225-235` (`_remember`, negative TTL) and `services/lyrics_lookup.py:377-378` (the call), `ui/web_new_v2/js/lyrics.js:928-935` (the button) and `ui/web_new_v2/js/lyrics.js:804-848` (the retry path).
- **Confirmed:** yes.
- **Description:** a `not_found` result is stored in the service's memory cache for 30 s. The Retry button calls `loadCurrentTrackLyrics()`, which reaches the backend with the **same** identity, so the backend answers from the negative memory cache and contacts **no** provider. The user sees the identical "Текст песни не найден" panel and cannot tell that nothing was searched. (The disk cache is *not* poisoned — `not_found` is never written to it — but the in-memory negative cache is enough to make the button useless.)
- **Cause:** the negative cache has no "user asked again" bypass; the UI cannot invalidate the backend's memory cache.
- **Trigger conditions:** press Retry within 30 s of a "not found" for the same title/artist/album/duration.
- **User impact:** the recovery affordance offered by the UI does not recover. If the provider had a transient outage, the user must wait 30 s (or change the track) for a real search.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:226-228, 377-378
          if result['status'] not in ('found', 'not_found'):
              return
          ttl = self._ttl(result) if result['status'] == 'found' else 30
  ...
              if result.get('status') == 'found' or not is_offline(self.service.settings):
                  self._remember(key, result)
  ```
- **Reproduction / verification:** `exp_python2.py` EXP 4:
  ```
  1st lookup status   : not_found | provider calls: 5
  2nd lookup status   : not_found | provider calls: 5 (retry button path)   <- no new calls
  memory cache entries: 1 -> ttl left: 30.0 s
  --- a network error is NOT cached as "not found" ---
  status              : unavailable | memory entries: 0
  ```
- **Suggested fix:** let an explicit retry bypass the negative cache (e.g. a `force` flag on `get_lyrics`, or skip the memory cache when the caller asks for a refresh), and/or drop the negative TTL to a few seconds.
- **Fix side effects:** a user hammering Retry would generate unbounded provider traffic against LRCLIB (whose rate limit is tight) — the negative cache exists for a reason. A `force` flag that only bypasses the *memory* negative cache keeps the disk cache untouched.
- **Discovered by:** A.

#### F-WX-06-7  [P3] — The translation ships the lyrics to a third party, with no offline-mode check and no user-visible disclosure

- **File:** `services/lyrics_service.py:243-272` (`translate_lyrics`), `core/api.py:3286-3291` (`get_lyrics_translation`), `ui/web_new_v2/js/lyrics.js:57-63` (the caller).
- **Confirmed:** yes.
- **Description:** `translate_lyrics` sends the whole lyric text to `translate.googleapis.com` in the **URL query string**, with no offline-mode check (unlike the lyrics lookup, which consults `core/offline.py::is_offline` before every provider request) and no setting that governs it. The transfer is triggered by the user's toggle — but the toggle is a module-level flag that is re-armed automatically for every subsequent track (`lyrics.js:940` calls `toggleTranslation(true)` whenever new lyrics arrive), so one click authorises a standing stream of lyric texts to Google.
- **Cause:** the translation path reuses the lyrics service's HTTP helper without reusing its offline gate, and the "translation on" state is sticky across tracks.
- **Trigger conditions:** the user enables the translation once; the app then contacts Google for every track afterwards. In offline mode the request is still attempted (and fails after the 6 s socket timeout, per chunk — up to 10 chunks).
- **User impact:** song lyrics (and, for the artist-profile path, the artist biography — `services/artist_service.py:212`) leave the machine for a third party; in offline mode the app still attempts outbound traffic, contradicting the offline contract.
- **Evidence:**
  ```python
  # services/lyrics_service.py:264-266
                  url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(ch)}"
                  req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                  with self._open_url(req, timeout=HTTP_TIMEOUT) as resp:
  ```
  No `is_offline(self.settings)` check anywhere in `translate_lyrics` (contrast `services/lyrics_lookup.py:74-75`, which raises `ConnectionError('Включён офлайн-режим')`).
- **Reproduction / verification:** read `services/lyrics_service.py:243-272` and `core/offline.py:10-14`; `translate_lyrics` never calls `is_offline`. The lyric text is also placed in the query string rather than a request body, so it lands in proxy/access logs of any TLS-inspecting middlebox.
- **Suggested fix:** gate the translation on `is_offline()`, move the text into a POST body, make the "translation on" state explicit and persisted (with a one-line disclosure that a third party receives the text), and reset the flag per track if the product does not want a standing consent.
- **Fix side effects:** Google's `translate_a/single` GET endpoint is the only one used today; a POST variant may behave differently or need another endpoint, so the translation may need a fallback. Blocking it offline makes the toggle silently do nothing in offline mode — the UI should say so.
- **Discovered by:** A.

#### F-WX-06-8  [P3] — The two duration→millisecond heuristics disagree, so the lyrics request can carry a duration 1000× the player's

- **File:** `ui/web_new_v2/js/lyrics.js:786` versus `ui/web_new_v2/js/player.js:46-52`; the consumer `services/lyrics_lookup.py:245` (`duration_ms / 1000`) and `services/lyrics_lookup.py:62` (the ±1 %/±2 s gate).
- **Confirmed:** yes.
- **Description:** the lyrics module converts a track's duration with the threshold `> 10000` (ms above the threshold, seconds below), while the player converts the same field with `> 50000`. A duration expressed in **milliseconds** between 10 001 and 50 000 (a 10–50 s track) is therefore read as ms by the lyrics path and as seconds by the player. The lyrics request then carries a correct 20 000 ms while the player's clock carries 20 000 000 ms — a 1000× disagreement about the same field.
- **Cause:** the heuristic exists because the field's unit is not fixed (the DB stores seconds, some providers supply ms). Two modules each re-implemented the heuristic with a different threshold.
- **Trigger conditions:** `track.duration` between 10 001 and 50 000 with the unit being ms (a 10–50 s track, or a provider that reports ms). Rare, but the failure mode is not cosmetic: the duration is part of the identity key and of the ±1 %/±2 s acceptance gate, so a wrong duration produces a wrong identity and a rejected match.
- **User impact:** a wrong duration both splits the cache identity (two disk entries for one song) and, on the provider side, lets a same-title/different-length recording pass or rejects the right one.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/lyrics.js:786
  const metadataDurationMs = track.duration ? (track.duration > 10000 ? track.duration : Math.round(track.duration * 1000)) : 0;
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:46-52
  // Duration units normalizer: the backend persists seconds; anything already
  // looking like milliseconds (a >50000s "track" is impossible) passes through.
  function normalizeDurationMs(dur) {
      const d = Number(dur);
      if (!d || isNaN(d) || d <= 0) return 0;
      return d > 50000 ? Math.round(d) : Math.round(d * 1000);
  }
  ```
- **Reproduction / verification:** read both call sites; `track.duration` is consumed by `js/player.js:1656` (`currentDuration = normalizeDurationMs(track.duration)`) and by `js/lyrics.js:786`. The backend treats the value as ms (`services/lyrics_lookup.py:245`), so the two modules feed the same field into different units.
- **Suggested fix:** normalise the duration once (in `player.js` or a shared util) and export the millisecond value; the lyrics module should consume it instead of re-deriving it.
- **Fix side effects:** a single shared threshold changes which of the two interpretations wins for durations in (10 000, 50 000]; picking the player threshold would turn a correct 20 s into 5.5 h. The real fix is to carry an explicit unit, not to tune the threshold.
- **Discovered by:** A.

#### F-WX-06-9  [P3] — A bridge-level failure is rendered as "lyrics not found", not as an error

- **File:** `ui/web_new_v2/js/lyrics.js:855-881` (the promise rejection / non-promise paths → `renderLyrics(null)`), `ui/web_new_v2/js/lyrics.js:901-908` (the `null` branch), `services/lyrics_lookup.py:374` (the backend's `unavailable` status).
- **Confirmed:** yes.
- **Description:** the backend distinguishes `not_found` ("the song has no lyrics") from `unavailable` ("the providers could not be reached") and the UI has two different sentences for them. But every transport-level failure on the JS side (`get_lyrics` rejects, the bridge returns a non-promise, `window.pywebview.api` is missing) funnels into `renderLyrics(null)`, which prints **"Текст песни не найден"** — the "no lyrics" message — for what is actually an error.
- **Cause:** the `unavailable` state is only reachable through the backend payload; the JS has no error state of its own and collapses every failure into the empty state.
- **Trigger conditions:** the bridge rejects (the pywebview bridge is not ready, the API method raised), or `window.pywebview.api.get_lyrics` is unavailable (the page loaded before pywebview finished booting).
- **User impact:** the user is told the song has no lyrics when the app simply failed to ask; the Retry button is shown in both cases, so the distinction is lost at the exact moment it would help.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/lyrics.js:872-881
              }).catch(err => {
                  if (loadGen !== lyricsLoadGeneration) return;
                  console.error("get_lyrics error:", err);
                  renderLyrics(null);
              });
          } else if (p?.status !== 'loading') {
              renderLyrics(p || null);
          }
      } else {
          renderLyrics(null);
      }
  ```
  ```javascript
  // ui/web_new_v2/js/lyrics.js:901-908
      if (!data) {
          lastLyricsData = null;
          resetLyricsScroll();
          containers.forEach(c => c.innerHTML = '<div class="empty-state">Текст песни не найден</div>');
          return;
      }
  ```
- **Reproduction / verification:** read `ui/web_new_v2/js/lyrics.js:850-882`; every `catch` and the `else` branch call `renderLyrics(null)`, which has only the "not found" message. (The backend's own error path is correct — `core/api.py:3220-3223` publishes `status: 'unavailable'`, which the UI renders with the correct message at line 931.)
- **Suggested fix:** give `renderLyrics` an explicit error state (e.g. `renderLyrics({status: 'unavailable'})` from the catch paths) so the JS-side failure uses the same "sources unavailable" wording as the backend.
- **Fix side effects:** the "not found" panel would then also need a distinct retry affordance; the two messages already differ only in wording, so the change is cosmetic in scope but behavioural in the cache policy (the `unavailable` status is not negatively cached).
- **Discovered by:** A.

---

### 3. Clean areas

**Source order — correct, and the embedded source is not lost.** The effective order is
**memory cache → disk cache → embedded tag → network providers** (`services/lyrics_lookup.py:260-278, 309-319, 320-326, 327`).
Verified by EXP 1: with an embedded tag present the provider is **never called** (`provider called with duration: []`), the embedded text wins, and the *embedded* result is what lands in the disk cache (`disk cache entry: source=Embedded plain='EMBEDDED LYRICS'`). A network result therefore never overwrites the embedded source. The disk key includes the file path **and** `st_mtime_ns`, so re-tagging a file invalidates the entry (pinned by `tests/test_lyrics_performance.py:331`). The order matches the intent in `docs/PLAYBACK_LYRICS_PERFORMANCE.md:24`.

**Cache key — identity-complete and filesystem-safe.** `services/lyrics_lookup.py:257-258` builds the key from normalised title, canonicalised artists, version, album, duration, file path and mtime — exactly the set the design document lists ("Исполнитель, редакция, альбом и длительность продолжают участвовать в проверке", `docs/PLAYBACK_LYRICS_PERFORMANCE.md:24`). `services/lyrics_cache.py:31-36` hashes it with SHA-256 into a hex digest, so the track title never reaches the filesystem: a track named `AC/DC` or `Don't Stop` cannot break contract #8. The cache is a single SQLite file at `~/.nedotify/lyrics_cache.db` (`core/app.py:132-133`), so no per-track filename exists at all. The artist is part of the key, so the same title by a different artist never shares an entry.

**Cache poisoning — absent.** `not_found` is never written to the disk cache (`services/lyrics_lookup.py:234-235`: `if self.disk_cache and result['status'] == 'found'`), and `unavailable` is never written to either store (`services/lyrics_lookup.py:226-227`). EXP 4 confirms: a provider explosion yields `unavailable` with `memory entries: 0`. Every disk record is re-validated on read (`services/lyrics_cache.py:38-57`: status, match_type, confidence range, timing shape, "a base recording may not supply karaoke timing"). TTLs are applied on both stores (30 d synced / 1 d plain on disk, 30 s negative in RAM) and the disk promotion deliberately does **not** extend the expiry (`services/lyrics_lookup.py:314-318`, pinned by `test_disk_promotion_does_not_extend_expiration`).

**request_id contract — sound; no stale-lyrics-for-the-new-track path found.** The id is generated in the UI (`js/lyrics.js:823 activeLyricsRequestId = 'lyrics-${Date.now()}-${loadGen}'`) and sent as the **6th positional argument** (`js/lyrics.js:854`), which is exactly the `request_id` parameter of `core/api.py:3192` — the argument order matches, there is no off-by-one. The backend echoes it into the payload (`core/api.py:3206 payload = dict(data or {}, request_id=rid, …)`), and the JS drops any event whose id is not the active one, in **two** places: `js/lyrics.js:314` (the event handler) and `js/lyrics.js:896` (inside `renderLyrics`, which additionally enforces a monotonically increasing `revision`). The backend independently aborts superseded lookups through `_lyrics_cascade_count` (`core/api.py:3196-3201`), so a superseded request never publishes at all. The UI's own memory cache is keyed by track identity (`js/lyrics.js:26-32`), so it cannot leak one track's text into another. `lastLyricsData` is cleared whenever the track changes (`js/lyrics.js:809`). **Conclusion: rapid track switching cannot render the old lyrics for the new track.**

**Provider cascade — bounded, parallel and failure-isolated.** Five providers (LRCLIB, NetEase, QQ Music, Genius, Megalobiz) run on a shared 6-worker pool (`services/lyrics_service.py:87`), each on its own future, inside one 8 s budget (`services/lyrics_lookup.py:25 BUDGET = 8.0`), with a per-request socket timeout of `min(6.0, remaining)` (`services/lyrics_lookup.py:73-81`). A single provider's exception is caught per future (`services/lyrics_lookup.py:360-364`) and cannot abort the others; the slow-provider escape hatch is implemented (the plain-only break at `services/lyrics_lookup.py:368-369`, pinned by `test_plain_exact_unknown_duration_finishes_before_slow_sources`). No provider can block the lyrics view indefinitely. `_emit` is called from pool threads, so contract #1 (never on the UI thread) holds.

**Duration unit — consistent end to end.** The bridge parameter is `duration_ms` (`core/api.py:3192`), the UI sends milliseconds (`js/lyrics.js:786, 854`), the lookup converts to seconds exactly once (`services/lyrics_lookup.py:245 duration = max(0, float(duration_ms or 0) / 1000)`), and the provider payloads are seconds (NetEase ms→s at `services/lyrics_lookup.py:130`, QQ `interval` in s at `:158`, LRCLIB in s at `:96`). The one divergence is F-WX-06-8 (a JS-side heuristic, not a unit error in the call chain).

**Karaoke clock — no drift.** The active line is driven by the audio element itself: `audio.addEventListener('timeupdate', …)` → `nedotify:position_changed` (`js/player.js:580-609`, milliseconds) → `updateLyricsPosition(posMs)` (`js/lyrics.js:1068`). There is no separate timer anywhere in the module; the only `setTimeout`/`setInterval` in `lyrics.js` are the manual-browse resume (`js/lyrics.js:674-690`) and the pointer-hold repeat (`js/lyrics.js:264-284`), neither of which drives the highlight. The LRC parser (`js/lyrics.js:1029-1057`) works in milliseconds and accepts the same timestamp shapes the backend accepts (`services/lyrics_lookup.py:61` and `services/lyrics_cache.py:55` both require `\[\d+:\d{2}([.:]\d+)?\]`), so the two ends agree.

**UI states.** Loading (spinner "Ищем текст…"), "not found", "sources unavailable" and "instrumental" are four distinct renderings (`js/lyrics.js:813, 928-936`); the offset controls are disabled when there is nothing to time (`js/lyrics.js:143-158, 994`); the Retry button exists for the two failure states. (The one gap is F-WX-06-9: a *bridge* error is collapsed into "not found".)

**Translation failure mode — the original lyrics survive.** `translate_lyrics` swallows every exception and returns the original text (`services/lyrics_service.py:270-272 return lyrics`), and the JS only creates map entries when the translated line differs from the original (`js/lyrics.js:73-74`), so a failed translation leaves the original text on screen. The `translationTrackKey` guard (`js/lyrics.js:62-64`) prevents a late translation from being applied to a different track.

---

### 4. Coverage gaps

- **No live provider traffic.** The `network` marker is deselected and no outbound request was made; the provider response shapes (LRCLIB / NetEase / QQ / Genius / Megalobiz) are taken from the code and from the mocks in `tests/test_lyrics_netease.py` / `tests/test_lyrics_performance.py`. A real LRC from LRCLIB with `[ar:]` headers was not fetched — F-WX-06-5 case (b) was demonstrated with a hand-built LRC of the documented shape.
- **No WebView2 runtime.** The JS conclusions come from executing the shipped source in a Node `vm` with stubs (`tests/test_recommendation_ui.py::run_node` harness), not from the real WebView2/Electron-less renderer. DOM-dependent paths (kinetic scrolling, the mini-karaoke widget at `js/lyrics.js:1139+`) were read but not exercised.
- **The WebView2 timer granularity of `timeupdate`** (≈4 Hz) was not measured; the ≤250 ms karaoke lag that follows from it was judged acceptable and therefore not reported as a finding.
- **`core/api.py`'s other WN-09 methods** (cover fetch, artist profile, waveform) and `services/artist_service.py:212`'s private `LyricsService()` instance were read but not exercised.
- **The Windows filesystem edge of contract #8** was verified analytically (SHA-256 keys, single SQLite file) rather than by creating a file named `AC/DC`; a targeted test was not run.
- **Long-running behaviour** (the 20 000-entry disk-cache eviction, the 96 MiB byte budget) was not exercised at scale; only the code path and the two bounded unit tests were read.
- **The `services/lyrics_service.py` dead code** (`_clean_track_and_artist`, `_strip_variant_qualifiers`, `_fetch_*`, `_compat_lookup`, `_make_result`, `_clean_str`) is reported only insofar as it explains F-WX-06-2; a full dead-code inventory belongs to the architecture review (Role B).
