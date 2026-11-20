## AREA WN-22 — Lyrics services — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `services/lyrics_service.py` L1–327 (whole file) — `_LyricsSharedExecutor` (L31), `_VARIANT_TOKENS`/`_WEAK_VARIANT_TOKENS` (L104–134), `_strip_variant_qualifiers` (L137–176), `LyricsService` (L179–327: `_clean_track_and_artist`, `_open_url`, `translate_lyrics`, `get_lyrics`, `_make_result`, `_clean_str`, `_title_match_score`, `_compat_lookup`, `_fetch_*`).
- `services/lyrics_lookup.py` L1–387 (whole file) — `LyricsLookup` (L24): `accept` (L40), `_read`/`_json` (L73–84), `lrclib` (L86), `netease` (L119), `qqmusic` (L149), `genius` (L175), `megalobiz` (L193), `_quality` (L215), `_ttl` (L219), `_remember` (L225), `get` (L237–387).
- `services/lyrics_cache.py` L1–109 (whole file) — `LyricsDiskCache` (L19): `_key` (L31), `valid` (L38), `get` (L59), `put` (L76).
- `core/api.py` L480–539 (offline interception table), L1118–1160 (`_emit`), L3192–3292 (`get_lyrics`, `get_lyrics_translation`) — caller trace only.
- `core/app.py` L120–159 (service wiring, `lyrics_cache.db` path), L540–586 (`cleanup` / pool shutdown list).
- `core/offline.py` L1–77 (`is_offline`).
- `ui/web_new_v2/js/lyrics.js` L1–1225 — caller trace only (`loadCurrentTrackLyrics` L764, `renderLyrics` L894, `parseLrc` L1029, `toggleTranslation` L43).
- `utils/tag_parser.py` L100–169 (`extract_embedded_lyrics` L121).
- `services/music_matching.py` L1–95, `services/artist_identity.py` L1–63 — callees (WN-18).
- `tests/test_verified_lyrics.py` L1–174, `tests/test_lyrics_performance.py` L1–342, `tests/test_lyrics_netease.py` L1–235, `tests/test_lyrics_netease.py` fixtures — read to establish what "verified" is pinned to.

**Callees traced into other areas**

- `services/music_matching.py::title_metadata / similarity / artist_matches / normalize / BASE_FALLBACK_VERSIONS` — **WN-18**. Owns the *vocabulary* of version qualifiers; WN-22 owns the fact that its own stripper is not used (see F-WN-22-3).
- `services/artist_identity.py::artist_aliases / canonical_artist` — **WN-18**.
- `core/offline.py::is_offline` — **WN-15/WN-10**.
- `utils/tag_parser.py::extract_embedded_lyrics` — **WN-27**. No defect found there; the WN-22 defect is in *how* it is used (F-WN-22-10).
- `core/api.py::get_lyrics / get_lyrics_translation` — **WN-09**. Callers only; a callee defect is attributed here, not there.
- `ui/web_new_v2/js/lyrics.js` — **WN-32**. The translation-alignment / duplicate-render amplification of F-WN-22-6 is owned by WN-32; the backend contract defect is owned here.

**Verification runs**

- `pytest tests/test_verified_lyrics.py tests/test_lyrics_performance.py tests/test_lyrics_netease.py -q` → **106 passed** (0.88 s). Every finding below is therefore a *gap in the test suite*, not a known-failing test.
- Eight scratch probes under `%TEMP%\opencode\wn22_probe*.py` (read-only, no network, no `~/.nedotify/` access). Their output is quoted inline in each finding.

### 2. Findings

#### F-WN-22-1  [P1] — One provider's `instrumental: true` flag aborts the whole cascade and is cached for 30 days

- **File:** `services/lyrics_lookup.py:66-67`, `services/lyrics_lookup.py:287-305`, `services/lyrics_lookup.py:366-376`; `services/lyrics_lookup.py:219-223`; `services/lyrics_cache.py:50`
- **Confirmed:** yes
- **Description:** `accept()` returns an instrumental record with empty lyrics but `status: 'found'`. The wait loop treats *any* `instrumental` best-result as terminal and `break`s; the subsequent `offer(result, final=True)` bypasses the `_quality` comparison, so the instrumental record becomes the **final** answer. Every other provider's real answer that arrives afterwards is dropped because `flight['closed']` is already `True`. The instrumental record is then written to the disk cache with a **30-day** TTL and re-shown as `match_type: 'exact'`, `confidence: 1.0`.
- **Cause:** `accept()` L66-67 collapses the lyrics to `''`/`None` but keeps `status: 'found'`; the "good enough, stop waiting" predicate at L368 treats `instrumental` as final; `offer(..., final=True)` skips the quality gate at L294 (`if not final and best and ...`), so a worse payload overwrites a better one.
- **Trigger conditions:** LRCLIB (the only provider that sets the flag — `data.get('instrumental', False)` at L97/L112) has a contributor-marked instrumental entry for the requested title, and it answers *before* Netease/QQ Music/Genius/MegaLobiz. Any track whose lyrics genuinely exist elsewhere then shows "Инструментальная версия — без текста".
- **User impact:** The lyrics panel shows "Instrumental version — no text" and, because `js/lyrics.js:933` renders the retry button only when `instrumental` is false, **no retry button is offered at all**. The wrong answer survives an app restart for 30 days.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:66-67
  if instrumental:
      text, synced, synced_ok = '', None, False
  # services/lyrics_lookup.py:366-369
  best = flight['best']
  if best and (best.get('syncedLyrics') or best.get('instrumental') or not duration) \
          and best.get('match_type') == 'exact' and best.get('confidence') == 1:
      break
  # services/lyrics_lookup.py:294  (skipped because final=True)
  if not final and best and self._quality(result) <= self._quality(best):
      return
  # services/lyrics_lookup.py:219-223  -> 30 days for an instrumental record
  return 30 * 86400 if result.get('syncedLyrics') or result.get('instrumental') else 86400
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe3.py`, section D4 — LRCLIB returns `instrumental=True` immediately, Netease returns real synced lyrics after 0.3 s:
  ```
  final: {'status': 'found', 'instrumental': True, 'plainLyrics': None, 'syncedLyrics': None, 'source': 'LRCLIB'}
  published phases: [('partial', 'LRCLIB', True), ('final', 'LRCLIB', True)]
  ```
  The Netease provider *ran* and its answer was discarded (`offer` returns early on `flight.get('closed')`).
- **Suggested fix:** Do not let a single provider's instrumental flag terminate the cascade. Either (a) treat `instrumental` as a lower-priority result that does not satisfy the "stop waiting" predicate, or (b) require the instrumental declaration to be corroborated (e.g. by a second source) before it is published as `found`, and never let a `final=True` offer overwrite a strictly better payload.
- **Fix side effects:** Waiting for corroboration lengthens the "instrumental" case (it would no longer return in < 0.5 s — see `tests/test_lyrics_performance.py:165`), so `test_instrumental_finishes_without_waiting_for_lyrics_hosts` would need to change. If `instrumental` stops short-circuiting, genuinely instrumental tracks pay the full 8 s budget before the UI settles.
- **Discovered by:** A

#### F-WN-22-2  [P1] — The Genius provider truncates the lyrics to the first line, and the truncated text is cached as an exact, verified match

- **File:** `services/lyrics_lookup.py:188-190`
- **Confirmed:** yes (for the regex behaviour and the end-to-end result); the *live* Genius markup still needs one network check (see Coverage gaps)
- **Description:** Genius renders each lyric line as its own nested `<div>` inside the `data-lyrics-container` element. The extraction regex is non-greedy (`(.*?)</div>`), so it stops at the **first** `</div>` — i.e. at the end of the first line. `accept()` then verifies the truncated fragment (title/artist/duration all match) and returns it as `match_type: 'exact'`, `confidence: 1.0`, `status: 'found'`. The result is cached in memory (24 h) and on disk (24 h) as a complete, "verified" lyric.
- **Cause:** A regular expression cannot span nested `<div>` elements; the pattern assumes the container's content has no block-level children.
- **Trigger conditions:** Any Genius hit whose container holds more than one line — i.e. essentially every real Genius result.
- **User impact:** The lyrics panel shows a single line ("[Verse 1] / First line of the song") for a song that has a full lyric sheet; the user sees a nearly-empty lyrics page, and the wrong content is not re-fetched for a day.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:188-190
  parts = re.findall(r'<div[^>]*data-lyrics-container="true"[^>]*>(.*?)</div>', page, re.S)
  text = html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', '\n', '\n'.join(parts), flags=re.I))).strip()
  return self.accept(form, song.get('title', ''), people, 0, None, text, 'Genius')
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe7.py` feeds representative Genius markup (one `<div class="Lyrics__Line…">` per line) through `LyricsLookup.genius` end-to-end:
  ```
  captured groups: 1
  extracted text: '[Verse 1]\nFirst line of the song'
  genius result plainLyrics: '[Verse 1]\nFirst line of the song'
  ```
  The same non-greedy pattern is used by the MegaLobiz scraper (`services/lyrics_lookup.py:199`) and truncates at the first `</span>` if the LRC body uses nested spans (MegaLobiz uses `<br>`, so that one is currently safe).
- **Suggested fix:** Parse the container by locating its balanced end tag (or use an HTML parser / `BeautifulSoup`), then convert `<br>` and block boundaries to newlines. Do not use a non-greedy `</div>` terminator for a container known to nest elements.
- **Fix side effects:** A correct parse yields much longer payloads — the 512 KB `MAX_RECORD_BYTES` and the 96 MB disk budget must still hold (they will: a full lyric sheet is a few KB). The `plain()` helper at L37-38 strips `[...]` groups, so bracketed section markers are unaffected.
- **Discovered by:** A

#### F-WN-22-3  [P1] — The variant-qualifier stripper is dead code: the live query keeps the qualifier, so the identity check rejects the real recording

- **File:** `services/lyrics_service.py:137-176` (dead), `services/lyrics_service.py:197-234` (dead), `services/lyrics_lookup.py:328-331` (live query), `services/music_matching.py:8-17` (the narrow vocabulary that *is* used, WN-18)
- **Confirmed:** yes
- **Description:** `services/lyrics_service.py` carries a complete, token-based variant stripper (`_strip_variant_qualifiers`, `_VARIANT_TOKENS`, `_MAX_VARIANT_WORDS`, `_WEAK_VARIANT_TOKENS`) that handles "Hardstyle Bootleg", "Radio Edit", "Extended Mix", "Remastered 2009", "8D Audio", "1.5x", "VIP", "Mashup", "Bass Boosted", "Club Mix", the trailing-dash form and the remixer's name inside the group. It is called from exactly one place — `LyricsService._clean_track_and_artist` (L216) — and **that method is never called by anything in production**. The live path is `LyricsService.get_lyrics` → `LyricsLookup.get`, which queries the providers with `metadata['title']` (L328) and relies on `music_matching.VERSION_PATTERNS` — a 7-kind vocabulary (`instrumental, cover, live, acoustic, sped, slowed, remix`) of which only `sped/slowed/remix` get a base-title fallback (`BASE_FALLBACK_VERSIONS`).
- **Cause:** A refactor moved normalisation into `services/music_matching.title_metadata` and left the WN-22 stripper behind, but only ported 7 of the ~60 markers. The live `title` therefore still carries the qualifier, the provider either 404s on the exact title or fuzzy-matches the base recording, and `accept()` then rejects the base recording because `similarity(expected['base_title'], offered['base_title']) < 0.85`.
- **Trigger conditions:** Track titles carrying any variant marker outside `{Remix, rmx, Bootleg, rework, ремикс, Sped Up, speedup, Nightcore, ускоренн*, slowed, замедленн*}` — e.g. "Radio Edit", "Extended Mix", "Club Mix", "Bass Boosted", "8D Audio", "VIP", "Mashup", "Remastered 2009", "1.5x", "(Live)" (no base fallback exists for `live`).
- **User impact:** "Текст песни не найден" for songs whose words are indexed normally — the exact regression the module's own test comment describes as fixed.
- **Evidence:**
  ```python
  # services/lyrics_service.py:216 (inside the never-called _clean_track_and_artist)
  track = _strip_variant_qualifiers(track)
  # services/lyrics_service.py:274-276 (the live entry point — no normalisation at all)
  def get_lyrics(self, track_name, artist_name='', duration_ms=0, file_path=None, album_name='', on_update=None, is_current=None):
      return self._lookup.get(track_name, artist_name, duration_ms, file_path, album_name, on_update, is_current)
  # services/lyrics_lookup.py:328-331 (what is actually sent to the providers)
  forms = [{'metadata': metadata, 'query_title': metadata['title'], 'query_artist': ', '.join(metadata['artists']), ...}]
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe.py` compares the live `title_metadata` against the dead `_strip_variant_qualifiers`:
  ```
  'Sandstorm (Radio Edit)'    title='Sandstorm (Radio Edit)'   base='Sandstorm (Radio Edit)'  version=''            base_fallback=False
  'Track [Extended Mix]'      title='Track [Extended Mix]'     base='Track [Extended Mix]'    version=''            base_fallback=False
  'Song (Remastered 2009)'    title='Song (Remastered 2009)'   base='Song (Remastered 2009)'  version=''            base_fallback=False
  'Song (VIP)'                title='Song (VIP)'               base='Song (VIP)'              version=''            base_fallback=False
  'Song (Live)'               title='Song (Live)'              base='Song'                    version='live'        base_fallback=False
  ```
  and `%TEMP%\opencode\wn22_probe2.py` shows the gate that then rejects the real recording:
  ```
  similarity('Song (Radio Edit)', 'Song') = 0.000   (accept() needs >= 0.85)
  similarity('Track [Extended Mix]', 'Track') = 0.435
  ```
  The dead stripper, by contrast, handles all of the above correctly (`'Sandstorm (Radio Edit)' -> 'Sandstorm'`, `'Track [Extended Mix]' -> 'Track'`, `'Song (Remastered 2009)' -> 'Song'`). Note the dead stripper does **not** handle Cyrillic qualifiers: its token regex `r'[0-9]+(?:[._][0-9]+)?[a-z]+|[0-9]{4}|[a-z]+'` matches no Cyrillic word, so `re.findall(...)` on `'ремикс'` returns `[]` and the group is never stripped.
- **Suggested fix:** Port the WN-22 token vocabulary into the live matcher (`music_matching.VERSION_PATTERNS` / `title_metadata`) or wire `_strip_variant_qualifiers` into `LyricsLookup.get` before `title_metadata` is computed — and extend the token regex to `\w` with a Unicode word class so Cyrillic markers are covered.
- **Fix side effects:** Widening the version vocabulary changes `accept()`'s version gate (L50-53): more titles would get `version != ''`, so a vocal recording can no longer silently substitute for a "Radio Edit" — that is the intent, but it also means *more* tracks will legitimately answer "not found" unless the providers have the exact variant. The `music_matching` vocabulary is owned by **WN-18**; the WN-22 part is that its own stripper is unused.
- **Discovered by:** A

#### F-WN-22-4  [P2] — The single global 6-worker pool lets one lookup's stalled HTTP reads starve the next lookup into `unavailable`

- **File:** `services/lyrics_service.py:31-88` (`_LyricsSharedExecutor`), `services/lyrics_service.py:87` (`max_workers=6`), `services/lyrics_lookup.py:284` (deadline), `services/lyrics_lookup.py:342-357` (submit), `services/lyrics_lookup.py:358-371` (wait loop)
- **Confirmed:** yes
- **Description:** There is exactly one `ThreadPoolExecutor` for all lyrics work. One lookup submits 5–13 provider jobs; a stalled host holds its worker for the full socket timeout (`min(6.0, remaining)`, `services/lyrics_lookup.py:80`). The *next* lookup (the user switched track) queues behind those workers, but its 8 s `BUDGET` clock starts when *it* starts — so the time spent waiting for a free worker is charged against its own budget and it returns `unavailable` without most of its providers ever running.
- **Cause:** No per-lookup isolation and no queue-depth guard; the deadline is started before the jobs are queued rather than when a worker actually starts running them.
- **Trigger conditions:** A slow/unreachable lyrics host (the exact situation in which lyrics matter) **and** a second lookup within the stall window (track skip, or the lyrics panel reopened). `core/api.py:3196-3201` supersedes the previous cascade but cannot interrupt in-flight `urlopen` reads.
- **User impact:** The newly selected track shows "Не удалось загрузить текст: источники временно недоступны" (or a wrong "not found") even though the providers have the lyrics; the user must press "Повторить" after the pool drains.
- **Evidence:**
  ```python
  # services/lyrics_service.py:87
  _lyrics_pool = _LyricsSharedExecutor(max_workers=6, thread_name_prefix="LyricsPool")
  # services/lyrics_lookup.py:284  (clock starts before the jobs are queued)
  deadline = time.monotonic() + self.BUDGET
  # services/lyrics_lookup.py:358  (loop ends at the deadline whatever the state of the queue)
  while futures and current() and time.monotonic() < deadline:
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe6.py` — lookup #1 blocks in a 6 s read (the real `HTTP_TIMEOUT`), lookup #2 starts 0.5 s later:
  ```
  lookup#2 status: unavailable  wall=8.01s
  lookup#2 result: {'status': 'unavailable', 'syncedLyrics': None, 'plainLyrics': None, 'instrumental': False, 'weight': 3, ...}
  ```
  Control run (`wn22_probe5.py`, 3 s block): lookup #2 returns `not_found` at 5.50 s — its providers only started at t=3.0 s instead of t=0.5 s.
- **Suggested fix:** Give each lookup its own bounded worker set, or start the deadline when the first provider actually starts; alternatively bound the shared queue depth so a lookup that cannot be served within the budget fails fast with a distinguishable status.
- **Fix side effects:** Per-lookup executors multiply threads (one pool per in-flight track switch) and weaken the "one slow provider starves the others" bound; a queue-depth cap would make rapid track switching return `unavailable` more often, which is honest but noisier for the user.
- **Discovered by:** A

#### F-WN-22-5  [P2] — `not_found` is negatively cached for 30 s, so the "Повторить" button is a no-op for 30 seconds

- **File:** `services/lyrics_lookup.py:225-235` (`_remember`), `services/lyrics_lookup.py:374-378`; `ui/web_new_v2/js/lyrics.js:932-935`
- **Confirmed:** yes
- **Description:** `_remember` stores every `not_found` result in the in-memory cache with a **30 s** TTL, and `get()` calls `_remember` for `not_found` whenever the app is online. The JS "Повторить" button re-issues `get_lyrics`, which hits that memory entry and returns the same `not_found` **without contacting any provider**.
- **Cause:** The negative TTL was chosen to rate-limit repeated misses, but the same entry is what the user's explicit retry hits; there is no way to invalidate it.
- **Trigger conditions:** The first lookup misses (provider outage, a genuinely unindexed song, or F-WN-22-3). The user clicks "Повторить" within 30 s.
- **User impact:** The retry button appears broken — nothing happens, no network traffic, the same "Текст песни не найден" message. After 30 s it starts working again.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:225-235
  def _remember(self, key, result):
      if result['status'] not in ('found', 'not_found'):
          return
      ttl = self._ttl(result) if result['status'] == 'found' else 30
      with self.service._cache_lock:
          self.service._cache[key] = (time.monotonic() + ttl, dict(result))
  # services/lyrics_lookup.py:377-378
  if result.get('status') == 'found' or not is_offline(self.service.settings):
      self._remember(key, result)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe2.py`, section B — five providers stubbed to return `None`:
  ```
  first call : not_found provider calls: 5
  second call: not_found provider calls: 5   (no new network call -> 'Повторить' is a no-op)
  ttl of cached entry: 30.0 s
  ```
  (By contrast, `unavailable` is **not** cached — section C shows `cache size: 0` — so a provider outage is *not* permanently poisoning the cache. That part is correct.)
- **Suggested fix:** Do not negatively cache `not_found` in the path an explicit retry takes — e.g. let the retry bypass the negative entry, or shorten/drop the negative TTL and rate-limit at the provider level instead.
- **Fix side effects:** Removing the negative TTL means a repeated miss re-hits five providers every time the same track is opened, which is exactly what the 30 s TTL was there to prevent.
- **Discovered by:** A

#### F-WN-22-6  [P2] — `translate_lyrics` signals failure by returning the input unchanged; the caller cannot tell success from failure

- **File:** `services/lyrics_service.py:243-272`; `core/api.py:3286-3291`; `ui/web_new_v2/js/lyrics.js:63-83`
- **Confirmed:** yes
- **Description:** The translation API returns a bare `str` with no status. On any exception the method returns the **original** text. The JS then treats the returned string as a translation and builds an index-aligned map; because `transLines[i] === origLines[i]`, the map degenerates to an identity map and every lyric line is rendered twice — once as the original and once as its own "translation". The failure is visible only in the browser console.
- **Cause:** The return contract has no error channel, and the failure value is indistinguishable from a legitimate result (a translation that happens to equal the source, e.g. a Russian song translated to Russian).
- **Trigger conditions:** Any network error, HTTP error, JSON error or empty response from `translate.googleapis.com` — including the 414 of F-WN-22-7.
- **User impact:** The translation toggle appears to work but shows the source text duplicated under each line; the user is never told that the translation failed.
- **Evidence:**
  ```python
  # services/lyrics_service.py:269-272
  return "\n".join(out) if out else lyrics
  except Exception as e:
      logger.debug(f"Translation error: {e}")
      return lyrics
  # core/api.py:3286-3291  (bare string, no status)
  def get_lyrics_translation(self, lyrics_text: str, target_lang: str = "ru"):
      try:
          return self._core.lyrics.translate_lyrics(lyrics_text, target_lang=target_lang)
      except Exception as e:
          return {"error": str(e)}
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe3.py`, section H:
  ```
  returned: 'Hello world\nSecond line'
  identical to input: True -> caller cannot detect failure
  ```
  The identity-map behaviour follows from `js/lyrics.js:72-75`: `if (k && transLines[i] && transLines[i] !== k) map[k] = transLines[i]; else if (k && origLines[i] && transLines[i]) map[origLines[i]] = transLines[i];` — the else-branch fires and maps each line to itself.
- **Suggested fix:** Return a structured result (`{"ok": bool, "text": str, "error": str|None}`) or raise/return a sentinel the JS can distinguish; the JS identity-map guard belongs to WN-32 but needs the backend to expose the failure.
- **Fix side effects:** `services/artist_service.py:213` also consumes `translate_lyrics` for artist bios and expects a plain string — changing the return type breaks that caller (WN-24).
- **Discovered by:** A

#### F-WN-22-7  [P2] — The translation chunk size is measured in characters, not encoded bytes: a Cyrillic chunk produces a 9 kB URL

- **File:** `services/lyrics_service.py:246-268`
- **Confirmed:** yes for the arithmetic; the resulting HTTP status is a hypothesis (no network access in this run)
- **Description:** The code caps a chunk at **1500 characters** and comments that this "keeps each GET well under 8KB quoted". `urllib.parse.quote` percent-encodes every non-ASCII byte as `%XX`, so a Cyrillic character (2 UTF-8 bytes) becomes **6** URL characters. A 1500-character Cyrillic chunk therefore yields a **9084-character** request line, over the 8 KB limit the comment assumes — exactly the 414 the comment was written to avoid.
- **Cause:** The chunk bound is expressed in source characters while the constraint is on the percent-encoded request line.
- **Trigger conditions:** A chunk whose text is largely non-ASCII (a Russian-language song or artist bio translated to Russian, or any chunk with many Cyrillic/CJK characters).
- **User impact:** The translation request fails with HTTP 414, which is swallowed by F-WN-22-6 → the user sees the duplicated original instead of a translation.
- **Evidence:**
  ```python
  # services/lyrics_service.py:246-247
  # Chunk long lyrics: a whole song in one ?q= blows past URL limits (414)
  # and gets rate-limited. 1500 chars keeps each GET well under 8KB quoted.
  ...
  url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(ch)}"
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe2.py`, section F:
  ```
  ascii 1500 chars     -> URL len 1584
  cyrillic 1500 chars  -> URL len 9084   (8192 = common request-line limit)
  mixed ru lyrics 1500 -> URL len 8442
  ```
- **Suggested fix:** Bound the chunk by the *encoded* length (`len(urllib.parse.quote(ch).encode())`), or switch to a POST / `urllib.request.Request(data=…)` form so the payload is not in the URL.
- **Fix side effects:** A smaller byte budget means more chunks for non-ASCII text, which interacts with F-WN-22-8 (the 10-chunk cap) — both limits must be re-derived together.
- **Discovered by:** A

#### F-WN-22-8  [P2] — `translate_lyrics` silently drops everything after the 10th chunk and can split a line in half

- **File:** `services/lyrics_service.py:248-260`
- **Confirmed:** yes
- **Description:** Two independent losses in the chunker: (a) `if len(chunks) >= 10: break` abandons the remaining text with no error and no marker; (b) when a chunk contains no newline, `cut = 1500` splits a line in the middle, so the joined result gains a newline that was not in the source and the caller's line indices shift.
- **Cause:** The chunker optimises for URL length but has no completeness check and no line-boundary guarantee.
- **Trigger conditions:** (a) any text longer than ~10 × 1500 ≈ 15 000 characters (a long song, a bonus track, a very repetitive lyric); (b) a lyrics payload whose first 1500 characters contain no newline (single-line plain lyrics — exactly what the truncated Genius output of F-WN-22-2 looks like).
- **User impact:** The translation silently covers only the first part of the song; the rest keeps the source language, and (b) shifts the whole index alignment so the remaining lines show the *wrong* translation.
- **Evidence:**
  ```python
  # services/lyrics_service.py:250-260
  while text:
      if len(text) <= 1500:
          chunks.append(text); break
      cut = text.rfind("\n", 0, 1500)
      if cut <= 0:
          cut = 1500
      chunks.append(text[:cut])
      text = text[cut:].lstrip("\n")
      if len(chunks) >= 10:
          break
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe3.py`, section G — a 19 889-character / 400-line lyric:
  ```
  input chars: 19889  chunks requested: 10
  output chars: 14889  input lines: 400  output lines: 300
  -> tail dropped: True
  ```
- **Suggested fix:** Continue chunking until the text is exhausted (with a sane total-bytes ceiling and a progress/error signal), and never split inside a line — use the last newline that fits, or send the remainder as its own chunk.
- **Fix side effects:** Removing the 10-chunk cap makes a pathological input produce many HTTP requests on one bridge thread (each up to 6 s). A total time budget for the translation is needed at the same time.
- **Discovered by:** A

#### F-WN-22-9  [P3] — `megalobiz` reads LRC header names case-sensitively, so uppercase `[TI:]`/`[AR:]`/`[Length:]` files yield nothing

- **File:** `services/lyrics_lookup.py:203-210`
- **Confirmed:** yes
- **Description:** `re.findall(r'\[(ti|ar|length):([^\]]+)\]', text, re.I)` matches the tag name case-insensitively, but `dict(...)` keeps the **original** casing as the key, so `tags.get('ti')`, `tags.get('ar')` and `tags.get('length')` all miss for `[TI:…]`, `[AR:…]`, `[Length:…]`. The provider then offers an empty title/artist and `accept()` rejects it, so the provider silently returns nothing.
- **Cause:** The `re.I` flag was assumed to normalise the captured key; it only normalises the *match*.
- **Trigger conditions:** An LRC file whose metadata headers are not lowercase. The LRC spec uses lowercase, so this fires only on non-conforming files.
- **User impact:** The MegaLobiz provider contributes nothing for those tracks (one provider fewer in the cascade).
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:203-210
  tags = dict(re.findall(r'\[(ti|ar|length):([^\]]+)\]', text, re.I))
  ...
  result = self.accept(form, tags.get('ti', ''), tags.get('ar', ''), duration, text, self.plain(text), 'Megalobiz')
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn22_probe3.py`, section E2:
  ```
  lowercase [ti:]/[ar:]/[length:]  -> {'status': 'found', 'syncedLyrics': '[ti:Song]\n[ar:Artist]\n[length:02:00]\n[00:01.00] Hello', ...}
  uppercase [TI:]/[AR:]/[Length:]  -> None
  ```
- **Suggested fix:** Lower-case the captured key (`{k.lower(): v for k, v in ...}`) or capture with an explicit case-normalising group.
- **Fix side effects:** None; the lowercase behaviour is already the tested path.
- **Discovered by:** A

#### F-WN-22-10  [P3] — Embedded lyrics preempt the entire provider cascade, including karaoke, and are never identity-checked

- **File:** `services/lyrics_lookup.py:320-327`
- **Confirmed:** yes
- **Description:** When the file has embedded lyrics, the result is offered *before* the provider cascade and `flight['best']` becomes non-empty, so the guard at L327 (`if not flight['best'] and not is_offline(...)`) **skips every provider**. The embedded text is accepted verbatim as `match_type: 'exact'`, `confidence: 1` — it is never passed through `accept()`, so no title/artist/duration check is applied to it.
- **Cause:** The embedded path bypasses the verification gate that every network result goes through.
- **Trigger conditions:** Any local file whose tags carry a `USLT`/`©lyr`/`LYRICS` frame (the app's own library, since it writes tags on import — WN-07).
- **User impact:** (a) A file with unsynced embedded lyrics permanently prevents the app from fetching the *karaoke* version from LRCLIB — the karaoke feature silently never activates for that track; (b) a file whose tags were copied from another song is displayed as an exact, confidence-1.0 match with no verification at all.
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:320-327
  if file_path and file_stamp is not None:
      from utils.tag_parser import extract_embedded_lyrics
      text = extract_embedded_lyrics(file_path).strip()
      if text:
          synced = text if duration and re.search(r'\[\d+:\d+', text) else None
          offer({'status': 'found', 'source': 'Embedded', 'match_type': 'exact', 'confidence': 1,
                 'syncedLyrics': synced, 'plainLyrics': self.plain(text), 'weight': 1 if synced else 2, 'instrumental': False})
  # services/lyrics_lookup.py:327  (network cascade is skipped once flight['best'] is set)
  if not flight['best'] and not is_offline(self.service.settings):
  ```
- **Reproduction / verification:** Code reading + `tests/test_lyrics_performance.py:331-342` (`test_embedded_lyrics_cache_changes_when_file_changes`) which confirms the embedded text is what the caller receives for a local file.
- **Suggested fix:** Let the cascade run when the embedded text has no timestamps (so karaoke can still be found), and run the embedded text through the same `accept()` gate used for network results, or mark it as `match_type: 'embedded'` so the UI can label it as untagged local metadata.
- **Fix side effects:** Running the providers for tagged files adds network traffic for every library track and lengthens the time to first paint of the lyrics panel (the embedded text is currently returned immediately).
- **Discovered by:** A

### 3. Clean areas

- **Disk cache key is filesystem-safe; the Windows forbidden-character contract (#8) does not apply.** The cache is a *single SQLite database* (`~/.nedotify/lyrics_cache.db`, wired in `core/app.py:132-133`), not one file per title. The identity is hashed: `hashlib.sha256(json.dumps([SCHEMA_VERSION, key], ...)).hexdigest()` (`services/lyrics_cache.py:31-36`). No raw title, artist or file path ever reaches a filename, so a track called `AC/DC` cannot break a write.
- **The cache directory is created on write, never on read.** `get()` returns `None` immediately when the file does not exist (`services/lyrics_cache.py:61-62`), so a lookup on a fresh profile does not create a stray directory; `put()` does `os.makedirs(..., exist_ok=True)` (`L84`).
- **Disk-cache writes are atomic and always fail as a miss.** Single SQLite transaction + WAL (`PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`) with `with closing(conn), conn:`; every exception path (`OSError, sqlite3.Error, ValueError, TypeError`) is caught and turned into "no cache" (`L108-109`). A corrupt cache file cannot break playback (pinned by `tests/test_lyrics_performance.py:247-259`).
- **The disk cache is bounded with oldest-first eviction.** `MAX_ENTRIES = 20_000`, `MAX_PAYLOAD_BYTES = 96 MB`, `MAX_FILE_BYTES = 128 MB` enforced via `PRAGMA max_page_count`, `MAX_RECORD_BYTES = 512 KB` per record; expired rows are purged on every write and victims are chosen `ORDER BY updated` (oldest first). Eviction works for both the entry-count and the byte budget (`tests/test_lyrics_performance.py:262-281`).
- **`valid()` re-verifies every record read back from disk** (`services/lyrics_cache.py:38-57`): status, `match_type`, a finite confidence in `[0.85, 1.0]`, string types, non-empty payload, no karaoke timing on a `base` match, and a real LRC timestamp shape. A hand-edited or stale-schema row is rejected.
- **Contract #2 (one lock per class) is respected.** `LyricsLookup` reuses `LyricsService._cache_lock` (an `RLock`) for `_cache` and `_inflight` (`services/lyrics_lookup.py:229-233`, `L260`, `L290`, `L383`) instead of opening a second lock. The listener callback is invoked **outside** the lock (`L300-305`), so a slow bridge notification cannot block other cache readers (pinned by `tests/test_lyrics_performance.py:91-107`).
- **The in-memory cache is LRU-bounded** (`MEMORY_ENTRIES = 2048`, `OrderedDict` + `move_to_end` + `popitem(last=False)`).
- **The total lookup budget is genuinely enforced.** `BUDGET = 8.0` (`L25`); the wait loop exits at the deadline (`L358`); every request is bounded by `min(6.0, deadline - now)` (`L76-80`) and `_read` refuses to start after the deadline (`L77-78`). A hung host cannot make the request hang forever — the caller always gets a final result within roughly the budget. The response body is capped at 2 MB (`L81`).
- **A provider outage does not poison the cache.** `unavailable` is rejected by `_remember` (`L226-227`), so the failure is not memoised; only `not_found` is (see F-WN-22-5 for the downside). Pinned by `tests/test_lyrics_performance.py:284-296`.
- **Single-flight de-duplication is correct.** Concurrent identical requests share one flight (`L268-273`), the waiter is woken by `flight['event']` which is set under the lock in `finally` (`L383-387`), and the flight is popped from `_inflight` in the same critical section, so there is no window in which two owners can exist.
- **The "verified" contract itself is sound.** `accept()` (`L40-71`) requires a title similarity ≥ 0.85 *and* an artist-set intersection *and* a version match, refuses to attach karaoke timings to a `base` (remix/slowed/sped) recording (`L61-62`), refuses to let a vocal recording substitute for an instrumental (`L54-55`), and requires an exact title score plus a known duration when the artist is unknown (`L48`). A "base" hit is explicitly labelled `match_type: 'base'` and the UI states "Текст оригинальной версии — без таймкодов" (`js/lyrics.js:1001`), so the user is told when the words are not the requested version.
- **The embedded path is preferred over the network** (F-WN-22-10 documents the downside), the local file identity (path + `st_mtime_ns`) is part of the cache key (`L257-258`), and a re-tagged file therefore invalidates the cache — pinned by `tests/test_lyrics_performance.py:331-342`.
- **The executor is shut down at exit and refuses work afterwards.** `atexit.register(_lyrics_pool.shutdown, wait=False, cancel_futures=True)` (`services/lyrics_service.py:88`), `submit()` returns `None` after shutdown or during interpreter finalisation (`L43-49`), and a `RuntimeError` from `pool.submit` is caught (`L67-70`) so it degrades to `unavailable` rather than an exception (pinned by `tests/test_lyrics_performance.py:292-296`).
- **`_emit` is never called on the UI thread from the lyrics path.** `core/api.py:3208-3224` runs the lookup on its own daemon thread and `AppApi._emit` (`core/api.py:1147-1154`) hands off to an `EmitWorker` when it is on the main thread. The lyrics lookup therefore never touches the pywebview WinForms marshalling from the UI thread.
- **Failures are surfaced to the user as text, not as an exception.** The backend swallows provider errors into `logger.debug` and returns a status; `js/lyrics.js:928-936` renders "Текст песни не найден" vs "Не удалось загрузить текст: источники временно недоступны" and offers a retry button. Nothing raises out of `get_lyrics` into the bridge.
- **`lyrics_cache.db` is not touched by the app's cache-cleaning UI** (`utils/cache_manager.py` clears only `cache_dir`, `covers_dir`, `streams_dir` and `temp_dir`). It is bounded at 96 MB / 20 000 entries, so it cannot grow without limit, but the user has no way to see or reclaim it from the Storage page — that visibility gap belongs to **WN-10**.
- **The lyrics cache is local and unencrypted**, holding the lyrics plus the matched title/artist/album. Lyrics are not secret, so this is not a privacy defect; there is simply **no user-visible privacy/clear-lyrics-cache setting**. Noted, not filed.

### 4. Coverage gaps

- **No live network verification.** `pytest.ini` deselects the `network` marker, and this run made no outbound requests. Two findings rest on unverified external facts: (a) F-WN-22-2 assumes Genius still renders one nested `<div>` per lyric line — the regex truncation is confirmed locally, the live markup is not; (b) F-WN-22-7 assumes Google's front end rejects a >8 KB request line with 414 — the URL length is confirmed locally, the status code is not.
- **No live HTTP capture of the providers**, so the exact response shapes for LRCLIB `/api/get` vs `/api/search`, Netease `cloudsearch`, QQ Music `fcgi-bin` and MegaLobiz were taken from the code, not from a packet capture.
- **`services/music_matching.py` and `services/artist_identity.py` (WN-18) were read only as callees.** The *vocabulary* of version qualifiers (`VERSION_PATTERNS`, `BASE_FALLBACK_VERSIONS`) and the artist-alias logic are owned by WN-18; F-WN-22-3 is filed here only because the WN-22 module carries a stripper that is never used.
- **`ui/web_new_v2/js/lyrics.js` was read only as a caller.** The translation index alignment (`js/lyrics.js:63-83`), the identity-map amplification of F-WN-22-6, the `parseLrc` timestamp regex (`L1033`) and the retry-button rule (`L932-935`) are owned by **WN-32**. One cross-check is worth flagging there: the backend accepts a synced payload when `re.search(r'\[\d+:\d{2}(?:[.:]\d+)?\]', synced)` matches (`services/lyrics_lookup.py:61`), i.e. the centisecond form `[mm:ss:xx]`, but the frontend regex `\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]` (`js/lyrics.js:1033`) cannot parse that form — such a line is silently dropped from `parsedLyrics`.
- **`core/api.py` was read only as a caller** (WN-09). The cascade counter (`_lyrics_cascade_count`, `core/api.py:3196-3201`) and the `publish`/`current` contract were traced and behave as intended; the "one cascade per request" invariant is owned by WN-09.
- **`core/offline.py::is_offline`** (WN-15) was checked only for the lyrics call sites; the offline-mode behaviour of the whole bridge is out of scope.
- **`android/` was not opened** (out of scope for this run).
- **The existing lyrics test suite was run but not extended**: `106 passed` for `tests/test_verified_lyrics.py`, `tests/test_lyrics_performance.py` and `tests/test_lyrics_netease.py`. Every finding above is therefore a coverage gap in the suite, not a failing test. Note that `tests/test_lyrics_netease.py:211-219` pins the behaviour of the **dead** `_clean_track_and_artist`/`_strip_variant_qualifiers`, so the suite currently protects code that production never runs.
- **Load/soak behaviour of the shared pool was not measured** beyond the two-lookup probe; the number of concurrently queued jobs (up to 13 per lookup, 5 providers × up to 5 identity forms) was derived from the code, not from a stress run.
