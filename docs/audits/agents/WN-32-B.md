## AREA WN-32 — UI library, downloads, smart playlists, lyrics, artist profile, profile, onboarding — ROLE B

### 1. Scope reviewed

**Files opened (read in full; physical line counts as found on disk — note the area map
`WIN_AUDIT_AREAS.md` understates them by 60–120 lines each):**

| File | Lines read | Lines on disk |
|---|---|---|
| `ui/web_new_v2/js/library.js` | 1–967 | 967 |
| `ui/web_new_v2/js/library-view.js` | 1–215 | 215 |
| `ui/web_new_v2/js/downloads-view.js` | 1–193 | 193 |
| `ui/web_new_v2/js/smart-playlists.js` | 1–185 | 185 |
| `ui/web_new_v2/js/lyrics.js` | 1–1262 | 1262 |
| `ui/web_new_v2/js/artist_profile.js` | 1–811 | 811 |
| `ui/web_new_v2/js/profile.js` | 1–188 | 188 |
| `ui/web_new_v2/js/profile-comparison.js` | 1–56 | 56 |
| `ui/web_new_v2/js/onboarding.js` | 1–238 | 238 |

**Supporting files read (not WN-32 owned, used as evidence / cross-checks):**
`ui/web_new_v2/js/utils.js` (1–1176 — `createTrackElement`, `renderIcons`, `coverImgHtml`,
`escapeHtml`, `safeCssImageUrl`), `ui/web_new_v2/js/events.js` (1–420 — the Python→JS
dispatcher), `ui/web_new_v2/js/player.js` (576–618 — `timeupdate` → `position_changed`),
`ui/web_new_v2/js/search.js` (470–505 — the *other* batch renderer),
`ui/web_new_v2/js/queue.js` (140–175 — the *third* row implementation),
`ui/web_new_v2/js/home-shell.js` (50–60), `ui/web_new_v2/js/feature-controls.js` (90–125),
`ui/web_new_v2/index.html` (10 — CSP; 490–495 — library DOM), `ui/web_new_v2/js/lucide.min.js`
(whole file — `createIcons` implementation),
`ui/web_new_v2/css/components/library-refresh.css` (1–170 — scroll container topology),
`core/api.py` (2267–2292 `get_library`/`get_favorites`/`get_downloaded_tracks`,
2362–2400 `import_external_playlist`, 2513–2582 `get_playlist_tracks`,
2756+ `complete_onboarding`, 3192–3225 `get_lyrics`, 3286–3291 `get_lyrics_translation`,
3388–3398 `get_profile_stats`, 3477–3536 `get_artist_profile`, 4176–4226 `get_downloads` /
`get_smart_playlist_tracks` / `get_listening_comparison`),
`core/database.py` (`get_all_tracks`, `get_playlist_tracks` — both unbounded),
`core/downloader.py` (145–200 — progress throttle + `_emit`),
`services/lyrics_service.py` (243–272 — `translate_lyrics`),
`services/listening_comparison.py` (82),
`core/proxy.py` (40, 115–140 — `/api/cover`, `/api/avatar` path allow-lists).

**Tests read:** `tests/test_library_view_ui.py`, `tests/test_profile_view_ui.py`,
`tests/test_onboarding_ui.py`, `tests/test_onboarding.py`, `tests/test_recommendation_ui.py`,
`tests/test_recommendation_feedback_ui.py`, `tests/test_smart_playlists.py`,
`tests/test_smart_search_ui.py`, `tests/test_catalog_lyrics_ui.py`,
`tests/test_lyrics_performance.py`, `tests/test_frontend_js.py`, `tests/test_feature_controls_ui.py`.

**Callees traced into other areas (defects there are attributed there, not here):**
- `core/api.py::get_library` → `core/database.py::get_all_tracks` (WN-06 / WN-12) — returns the
  **entire** `tracks` table with no `LIMIT`; the UI cannot bound it.
- `core/api.py::get_playlist_tracks` → `core/database.py::get_playlist_tracks` (WN-06 / WN-12) —
  the `limit=50` parameter is **ignored** on the `source="local"` path, so a playlist returns
  every one of its tracks.
- `core/api.py::get_lyrics_translation` → `services/lyrics_service.py::translate_lyrics`
  (WN-09 / WN-22) — returns the *untranslated original* on provider failure (see F-WN-32-4).
- `core/downloader.py` (WN-13) — `download_progress` is throttled to 0.75 s/track; this is why
  the download manager's event handling is acceptable.
- `ui/web_new_v2/js/utils.js::renderIcons` / `createTrackElement` (WN-28) — the shared row
  factory; WN-32 consumes them, but WN-32's *call sites* determine the cost.
- `ui/web_new_v2/js/events.js` (WN-28) — the `download_complete` fan-out that WN-32's
  `library.js` subscribes to (see F-WN-32-1).
- `ui/web_new_v2/js/player.js` (WN-29) — the `timeupdate` → `nedotify:position_changed` producer
  that drives `lyrics.js::updateLyricsPosition`.

### 2. Findings

#### F-WN-32-1  [P1] — Every completed download re-renders the entire library three times, each time re-fetching the whole `tracks` table over the bridge

- **File:** `ui/web_new_v2/js/events.js:258-263` (the dispatcher), `ui/web_new_v2/js/library.js:548-550` (`loadDownloaded`), `ui/web_new_v2/js/library.js:379-391` (`refreshActiveLibraryView`), `ui/web_new_v2/js/library.js:962-964` (the `nedotify:track_downloaded` subscriber), `ui/web_new_v2/js/library.js:501-520` (`selectSection` → `get_library`)
- **Confirmed:** yes
- **Description:** On the Python `download_complete` event, the library view is rebuilt **three
  times** and the sidebar playlist list **twice**. Each rebuild calls
  `AppApi.get_library()` → `db.get_all_tracks()` with **no `LIMIT`**, i.e. the whole
  `tracks` table is JSON-serialised across the pywebview bridge and pushed into the DOM.
  The rebuild is **not** gated on the library page being visible.
- **Cause:** `events.js` calls `loadDownloaded()` (→ `refreshActiveLibraryView()`), then calls
  `window.refreshActiveLibraryView()` directly (the *same* function again), then dispatches
  `nedotify:track_downloaded`, whose subscriber in `library.js` calls `loadDownloaded()` a
  third time. `events.js` has an `isPageVisible(pageId)` helper (used at `events.js:223`) but
  the `download_complete` branch does not use it.
- **Trigger conditions:** Any download completing. During "Скачать всё" (batch download of the
  favourites) or any multi-track download, this fires once per track. The library view need
  not even be open.
- **User impact:** With a 5 000-track library, one batch download of 200 tracks causes 600
  `get_library()` round trips (each shipping ~5 000 rows) and 600 full list rebuilds on the
  UI thread. The window stutters/freeze for seconds, the download queue visibly stalls, and
  memory churns. It also means the library DOM is rebuilt from scratch 600 times even if the
  user is on the Home page.
- **Evidence:**
  ```js
  // events.js:258-263
  case 'download_complete':
  case 'track_downloaded':
      loadDownloaded();
      loadPlaylists();
      if (window.refreshActiveLibraryView) window.refreshActiveLibraryView();
      document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
      break;
  ```
  ```js
  // library.js:548-550
  export async function loadDownloaded() {
      refreshActiveLibraryView();
  }
  ```
  ```js
  // library.js:962-964  (the third rebuild)
  document.addEventListener('nedotify:track_downloaded', () => {
      loadDownloaded();
  });
  ```
  ```python
  # core/api.py:2267-2271
  def get_library(self):
      """Get all tracks in local library."""
      if is_offline(self._core.settings):
          return offline_library(self._core.db)
      return self._core.db.get_all_tracks()      # <- no LIMIT, whole table
  ```
- **Reproduction / verification:** Import 2 000 tracks, open the **Home** page, and start a
  10-track download. Instrument `core/api.py::get_library` with a counter (or set a
  breakpoint) — it is entered 30 times for 10 downloads, not 0. Alternatively, in
  DevTools set a breakpoint on `core/api.py:2271` and watch it hit three times per
  `download_complete`. Note also that `case 'track_downloaded':` at `events.js:260` is dead
  code: the backend never emits a `track_downloaded` event (only `download_complete` /
  `download_failed` — `grep -r "track_downloaded" core/` matches only
  `db.mark_track_downloaded`).
- **Suggested fix:** Collapse the three rebuilds into one and make it visible-page-gated:
  drop the `window.refreshActiveLibraryView()` call and the `nedotify:track_downloaded`
  dispatch from the `download_complete` branch (or make the subscriber a no-op), and wrap the
  refresh in `isPageVisible('library')`. Coalesce bursts with a short debounce so a batch
  download causes one refresh, not one per track.
- **Fix side effects:** The download spinner on the individual track rows is cleared by
  `utils.js`'s `nedotify:track_downloaded` / `nedotify:track_download_failed` handlers
  (`utils.js:1008`, `utils.js:1019`) — those must keep firing, so the *custom event* has to
  stay even if the *library refresh* moves out of it. Any refresh coalescing must not delay
  the `download_complete` → "Скачан" state for more than one frame.
- **Discovered by:** B

#### F-WN-32-2  [P2] — The library list is batched but never virtualised: a 10 000-track library becomes 10 000 DOM rows, ~80 000 listeners, and one document-wide icon scan per 50-row batch

- **File:** `ui/web_new_v2/js/library.js:394-454` (batch renderer + scroll loader), `ui/web_new_v2/js/library.js:409`, `ui/web_new_v2/js/library.js:413`, `ui/web_new_v2/js/utils.js:688-890` (`createTrackElement`), `ui/web_new_v2/js/utils.js:943-958` (`renderIcons`)
- **Confirmed:** yes
- **Description:** There is **no virtualisation and no upper bound**. The batch renderer
  defers *when* rows are created (50 at a time) but never recycles them: every scroll to the
  bottom permanently appends 50 more rows to the same container. Each row is ~25–30 DOM
  nodes and ~8 event listeners (row `click`, `contextmenu`, download, like, add, more, artist
  spans, plus the row `keydown` added by `decorateLibraryRow`). Each 50-row batch ends with
  a **document-wide** `renderIcons()` call, which is `document.body.querySelectorAll('[data-lucide]')`
  — a full-document scan per batch, so the cost is quadratic in the number of rendered rows.
- **Cause:** `attachLibraryScrollLoader` (`library.js:420-445`) has a drain loop and an
  `onScroll` handler but **no eviction / windowing**. `makeLibraryBatchRenderer.renderNext`
  calls `renderIcons()` with **no argument** (`library.js:413`), and `renderIcons()` defaults
  `root` to `document.body` (`utils.js:945-950`). The sibling implementation in `search.js`
  does it correctly (`search.js:495` → `renderIcons(list)`, scoped to the list, and it also
  chunks via `requestAnimationFrame` with `SEARCH_BATCH_SIZE = 30`).
- **Trigger conditions:** Any library/playlist with more than a few hundred tracks. The
  `all` section returns the whole `tracks` table; a regular playlist returns all of its
  tracks (the `limit=50` parameter of `AppApi.get_playlist_tracks` is *ignored* on the
  `source="local"` path — `core/api.py:2549-2565`).
- **User impact:** Scrolling a large library degrades progressively (each batch is slower
  than the last), the window becomes unresponsive, and memory grows monotonically — the
  library DOM is never released until the section is re-selected.
- **Evidence:**
  ```js
  // library.js:408-414
  for (let i = start; i < end; i++) {
      fragment.appendChild(decorateLibraryRow(createTrackElement(tracks[i], i, tracks, getCurrentTrack()),tracks[i],i));
  }
  container.appendChild(fragment);
  rendered = end;
  renderIcons();            // <-- document.body.querySelectorAll('[data-lucide]') every batch
  return end;
  ```
  ```js
  // utils.js:945-951
  const root = (targetEl && targetEl.nodeType) ? targetEl : document.body;
  window.lucide.createIcons({ nameAttr: 'data-lucide', attrs: {}, root: root });
  ```
  ```js
  // lucide.min.js (createIcons)
  const elements = root.querySelectorAll(`[${nameAttr}]`);
  elements.forEach(el => renderElement(el, nameAttr));
  ```
  Cost model: `createTrackElement` (`utils.js:718-748`) emits ~25 elements and attaches
  listeners at `utils.js:751, 767, 794, 818, 863, 875, 883`; `decorateLibraryRow` adds one
  more (`library-view.js:113`). At 10 000 rows that is ~250 000 DOM nodes and ~80 000
  listeners, produced in 200 batches, each preceded by a full-document `querySelectorAll`
  (≈25 million node visits in total).
- **Reproduction / verification:** Put 5 000 rows in `tracks` (or create a playlist with
  5 000 tracks), open Library → "Вся музыка", then scroll to the bottom repeatedly. In
  DevTools → Performance, each scroll batch shows a growing `Recalculate Style`/
  `Layout` cost and an `Attributing`/`querySelectorAll` entry from
  `lucide.createIcons`; `document.querySelectorAll('.track-item').length` grows to 5 000
  and never shrinks.
- **Suggested fix:** Introduce windowing: keep a bounded window of rows around the scroll
  position (e.g. 200 live rows, recycling the row DOM), and scope the icon pass
  (`renderIcons(container)`) exactly as `search.js:495` already does. Alternatively, render
  the icon set once per section rather than per batch.
- **Fix side effects:** Recycling rows breaks the current "the DOM node is the row" model —
  `utils.js::updatePlayingTrackInDOM` (`utils.js:676-686`) and
  `utils.js::matchDownloadTarget` (`utils.js:977-992`) address rows via
  `document.querySelectorAll('.track-item')` and read `el._trackData`; recycled nodes would
  need their `_trackData` refreshed on every bind. The `.playing` highlight also depends on
  `isSameTrack()` string comparison against the whole list.
- **Discovered by:** B

#### F-WN-32-3  [P2] — The batch renderer's scroll listener is only torn down on the success path; on the empty/failure path the previous collection stays live and can be appended into the error box

- **File:** `ui/web_new_v2/js/library.js:447-454` (`renderLibraryList` — the only place `libraryScrollCleanup` is reset), `ui/web_new_v2/js/library.js:519` (empty path), `ui/web_new_v2/js/library.js:541-545` (failure path), `ui/web_new_v2/js/library.js:437-444` (`onScroll` → `renderNext`), `ui/web_new_v2/js/library.js:420-427` (scroll-parent resolution)
- **Confirmed:** yes (retention is unconditional; the stale-append needs a scrollable parent)
- **Description:** `libraryScrollCleanup` is the only handle on the scroll listener installed
  by `attachLibraryScrollLoader`, and it is reset **only** inside `renderLibraryList`
  (`library.js:448`). Two exit paths of `selectSection` never reach it:
  `library.js:519` (`renderLibraryEmpty` → `return`) and `library.js:541-545`
  (the `catch` → `renderLibraryFailure`). In both cases the container is replaced with a
  short message, but the previous batch renderer's `onScroll` stays attached to
  `.lib-right-content` and keeps a closure over the **previous** collection's full `tracks`
  array and the same container element.
- **Cause:** Teardown is coupled to the *renderer creation* path instead of the *view
  lifecycle* path. `selectSection` already computes a `viewGen` generation counter
  (`library.js:483`) that guards stale renders, but that guard is not applied to the scroll
  listener.
- **Trigger conditions:** Select a collection that renders successfully, then select another
  collection that is empty or whose bridge call fails, then scroll the library view. Also
  triggered by merely leaving the library page: the listener and the whole previous track
  array stay reachable.
- **User impact:** (a) The previous collection's rows can be appended *after* the
  "Не удалось загрузить коллекцию" message, so the user sees stale tracks under an error
  banner — the exact "silently wrong data" failure AGENTS.md warns about; (b) the previous
  collection's array (up to the whole `tracks` table) is retained by the listener closure for
  as long as the app lives, which is a real memory leak on large libraries.
- **Evidence:**
  ```js
  // library.js:447-454
  function renderLibraryList(tracksContainer, tracks) {
      if (libraryScrollCleanup) { libraryScrollCleanup(); libraryScrollCleanup = null; }   // <-- only teardown point
      tracksContainer.innerHTML = '';
      const renderer = makeLibraryBatchRenderer(tracksContainer, tracks);
      renderer.renderNext();
      libraryScrollCleanup = attachLibraryScrollLoader(tracksContainer, renderer.renderNext, renderer.getRendered, renderer.getTotal);
      return renderer;
  }
  ```
  ```js
  // library.js:519 (empty path — returns before renderLibraryList)
  if(!tracks.length){renderLibraryEmpty(container, ...);return;}
  ```
  ```js
  // library.js:541-545 (failure path)
  } catch(error) {
      if(viewGen!==libraryGeneration)return;
      console.warn('Library collection unavailable:',error);
      sub.textContent='Не удалось загрузить';renderLibraryFailure(container,()=>selectSection(type,data));
  }
  ```
  ```js
  // library.js:437-444 (the surviving listener)
  const onScroll = () => {
      const sc = scrollParent.scrollTop + scrollParent.clientHeight;
      if (sc >= scrollParent.scrollHeight - 200 && getRendered() < getTotal()) {
          renderNext();       // <-- appends the PREVIOUS collection's rows into the current container
      }
  };
  scrollParent.addEventListener('scroll', onScroll, { passive: true });
  ```
- **Reproduction / verification:** Open Library → "Вся музыка" (populated), then open a
  playlist whose tracks cannot be loaded (e.g. stop the backend, or pick a section whose
  bridge call raises) → the error box appears. Scroll the library panel: rows from the
  previous collection are appended below the error message. In DevTools, the
  `.lib-right-content` scroll listener stays registered across page navigations
  (`getEventListeners` is available in the Chromium console).
- **Suggested fix:** Move the teardown out of `renderLibraryList` into the top of
  `selectSection` (and into `showLibraryOverview`), so the listener is released before any
  new request starts, and abort the previous renderer via the existing `viewGen` counter.
- **Fix side effects:** The "Показать ещё" flow for smart playlists
  (`library.js:525-539`) calls `renderer.renderNext()` on a renderer created by
  `renderLibraryList`; the teardown must not invalidate *that* renderer while the section
  is still current — i.e. the cleanup has to be keyed on the generation, not merely on
  "a new selection started".
- **Discovered by:** B

#### F-WN-32-4  [P2] — The lyrics translation has no failure signal: a provider outage produces an identity map and duplicates every line under itself as a "translation"

- **File:** `ui/web_new_v2/js/lyrics.js:57-91` (`toggleTranslation`), `ui/web_new_v2/js/lyrics.js:956-961` and `ui/web_new_v2/js/lyrics.js:1010-1015` (where the map is rendered), `services/lyrics_service.py:269-272` (the silent failure), `core/api.py:3286-3291`
- **Confirmed:** yes (reproduced with Node — see below)
- **Description:** `services/lyrics_service.py::translate_lyrics` swallows every provider
  exception and **returns the original, untranslated lyrics**. The UI cannot tell that
  apart from a successful translation, so it builds a translation map from
  `original → original`. Every karaoke line then gets a second `.lyric-translation` div
  containing *the same text*, and the user sees each line duplicated. The
  "Переводим текст песни…" toast that was shown at `lyrics.js:59` never resolves and no
  error is ever displayed.
- **Cause:** The bridge contract has no success/failure discriminator. `core/api.py:3286-3291`
  *does* return `{"error": ...}` if `translate_lyrics` raises — but `translate_lyrics` never
  raises (it catches everything), so that error branch is effectively dead. The JS
  therefore only ever receives a string, and `lyrics.js:73` only skips a line when
  `transLines[i] === k`; the fallback at `lyrics.js:77-79` then rebuilds the map as an
  identity mapping.
- **Trigger conditions:** `translate.googleapis.com` unreachable, rate-limited (HTTP 429),
  or returning a shape the parser does not understand — i.e. any transient network failure
  while the user has translation enabled.
- **User impact:** The user clicks "перевести", waits, and is shown the *same* English text
  duplicated under every line with no indication that translation failed. They may believe
  the app is broken, or that the track is "already translated".
- **Evidence:**
  ```python
  # services/lyrics_service.py:269-272
              return "\n".join(out) if out else lyrics
          except Exception as e:
              logger.debug(f"Translation error: {e}")
              return lyrics          # <-- original text, indistinguishable from success
  ```
  ```js
  // lyrics.js:72-79
  keys.forEach((k, i) => {
      if (k && transLines[i] && transLines[i] !== k) map[k] = transLines[i];
      else if (k && origLines[i] && transLines[i]) map[origLines[i]] = transLines[i];
  });
  // If line counts mismatch, fall back to index alignment with origLines
  if (Object.keys(map).length === 0) {
      origLines.forEach((k, i) => { if (k && transLines[i]) map[k] = transLines[i]; });
  }
  ```
  ```js
  // lyrics.js:956-961
  if (isTranslationEnabled && currentTranslationMap[line.text]) {
      const subEl = document.createElement('div');
      subEl.className = 'lyric-translation';
      subEl.textContent = currentTranslationMap[line.text];
      el.appendChild(subEl);
  }
  ```
- **Reproduction / verification:** Re-run the shipped mapping logic against a failing
  backend (the reproduction script was executed during this audit):
  ```
  parsedLyrics : [ 'First line', 'Second line', 'Third line', 'Fourth line' ]
  origLines    : [ 'First line', 'Second line', 'Third line', 'Fourth line' ]
  transLines   : [ 'First line', 'Second line', 'Third line', 'Fourth line' ]
  translation map (what the UI renders under every line):
     "First line"  ->  "First line"
     "Second line"  ->  "Second line"
     "Third line"  ->  "Third line"
     "Fourth line"  ->  "Fourth line"
  entries identical to the original: 4 of 4
  ```
  End-to-end: block `translate.googleapis.com` in the firewall, enable translation on a
  synced track → every line is rendered twice, identically.
- **Suggested fix:** Make the failure observable on both sides. Python (WN-09 / WN-22):
  return a structured result, e.g. `{"ok": False, "error": ...}`, instead of the original
  text. JS (WN-32): check for the error/`ok` field and surface it (a toast plus leaving
  the translation toggle off) instead of storing the payload as a translation map; also
  refuse to store entries where the "translation" equals the source line.
- **Fix side effects:** `toggleTranslation` currently only re-requests a translation when
  `Object.keys(currentTranslationMap).length === 0` (`lyrics.js:57`); if a failure leaves the
  map empty, every toggle click would re-issue the request — that needs a "failed" flag so
  the button does not hammer the provider. Python-side change touches
  `services/lyrics_service.py` and its callers in WN-09/WN-22.
- **Discovered by:** B

#### F-WN-32-5  [P2] — `createPlaylist` swallows a bridge failure: the dialog closes and the UI behaves as if the playlist was created

- **File:** `ui/web_new_v2/js/library.js:931-945`
- **Confirmed:** yes
- **Description:** The "Создать плейлист" dialog's submit handler catches every exception
  from `create_playlist` / `add_to_playlist` and only writes to the console, then closes the
  dialog and reloads the playlist list unconditionally. The user sees the dialog close and
  the sidebar reload — with **no** toast and **no** error message.
- **Cause:** The `catch` block at `library.js:939-941` uses `console.error` instead of the
  app's `nedotify:toast` convention, and `closeModal()` at `library.js:944` is outside the
  `try/catch`, so the success path is taken regardless of the outcome.
- **Trigger conditions:** Any Python exception in `AppApi.create_playlist`
  (`core/api.py`, WN-07) — e.g. a duplicate-name constraint, a locked DB, or a disk error.
- **User impact:** The user types a playlist name, presses Enter, the dialog closes, and the
  playlist does not exist. No feedback whatsoever — a textbook "failure mode is silence"
  (AGENTS.md). The user is likely to retry and create duplicates.
- **Evidence:**
  ```js
  // library.js:931-945
  const handleSubmit = async () => {
      const name = input.value.trim();
      if (name) {
          try {
              const plId = await window.pywebview.api.create_playlist(name);
              if (plId && contextTrack) {
                  await window.pywebview.api.add_to_playlist(plId, contextTrack);
              }
          } catch (e) {
              console.error("Failed to add track to new playlist:", e);
          }
          loadPlaylists();
      }
      closeModal();
  };
  ```
  Contrast with the sibling handlers in the same file, which do surface errors:
  `library.js:57-62` (`catch(e) { …toast 'Ошибка вызова скачивания' }`) and
  `library.js:222-225` (quick-add → toast 'Не удалось создать плейлист').
- **Reproduction / verification:** Monkey-patch the bridge from the WebView console
  (`window.pywebview.api.create_playlist = async () => { throw new Error('boom') }`), then
  create a playlist through the Library sidebar → the dialog closes, no toast appears, and
  the playlist is not created. Alternatively, make `create_playlist` raise in
  `core/api.py` (WN-07) and repeat.
- **Suggested fix:** Dispatch a `nedotify:toast` with `type:'error'` in the `catch`, and
  only close the modal on success (or keep it open with the error shown inline, as
  `smart-playlists.js` does at `smart-playlists.js:176`).
- **Fix side effects:** The dialog's Enter-key path (`library.js:947-954`) calls
  `handleSubmit()`; keeping the modal open on failure must not leave the submit button
  disabled or the focus trap armed (`openModalFocusTrap` at `library.js:920`).
- **Discovered by:** B

#### F-WN-32-6  [P2] — The inline `onerror` on the artist album cover is dead under the app's CSP: a failed album cover leaves a broken-image icon

- **File:** `ui/web_new_v2/js/artist_profile.js:479-480`, `ui/web_new_v2/index.html:10` (CSP), `ui/web_new_v2/js/utils.js:546-548` (the codebase already knows about this)
- **Confirmed:** yes
- **Description:** The album carousel renders its cover with an inline event handler:
  `onerror="this.onerror=null;this.style.display='none'"`. The shipped document declares
  `script-src 'self'` **without** `'unsafe-inline'`, which blocks inline event-handler
  attributes. The handler therefore never runs, and a cover URL that fails to load leaves
  Chromium's broken-image placeholder on screen instead of the intended gradient+note
  fallback. The codebase already documents this exact trap elsewhere.
- **Cause:** The handler was written as an attribute instead of using the delegated
  capture-phase `error` listener that `utils.js` already installs
  (`utils.js:533-543`), which handles `data-cover-url` / `data-source-id` / `data-source`
  fallbacks.
- **Trigger conditions:** Any album whose `cover` / `cover_url` is dead, blocked, or slow
  enough to error — common for provider artwork URLs that expire.
- **User impact:** The artist profile's album carousel shows broken-image icons where the
  designed gradient/note fallback should be. It is cosmetic but it is the *only* cover
  surface in WN-32 that does not use the delegated fallback.
- **Evidence:**
  ```js
  // artist_profile.js:479-480
  const coverSrc = (album.cover && album.cover !== 'null') ? escapeHtml(album.cover) : ((album.cover_url && album.cover_url !== 'null') ? escapeHtml(album.cover_url) : '');
  const imgTag = coverSrc ? `<img src="${coverSrc}" alt="${escapeHtml(album.title)}" onerror="this.onerror=null;this.style.display='none'" loading="lazy">` : '';
  ```
  ```html
  <!-- index.html:10 -->
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; ...">
  ```
  ```js
  // utils.js:546-548 — the same trap is already documented in this codebase
  // It replaces inline onload/onerror attributes, which `script-src 'self'`
  // (no 'unsafe-inline') silently blocks: #mp-cover ships with display:none and
  // an inline onload that could never run.
  ```
- **Reproduction / verification:** Open an artist profile whose album cover 404s. The
  console reports `Refused to execute inline event handler` (blocked by CSP) and the broken
  image stays visible. Programmatically: `new Function` is blocked, so verify in DevTools →
  Console → the CSP violation message, and check `img.onerror === null` after the error
  fires.
- **Suggested fix:** Drop the inline attribute and emit the same `data-cover-url` /
  `data-source-id` attributes that `coverImgHtml` (`utils.js:522-530`) emits, so the
  delegated capture-phase listener in `utils.js:533-543` handles the fallback; or set
  `img.onerror` from JS after insertion (as `artist_profile.js:606-611` already does for the
  track covers).
- **Fix side effects:** The delegated handler in `utils.js` needs a `data-cover-url` to
  retry with; album rows currently have none, so the fallback would simply hide the image
  and let the CSS gradient (`fallback-gradient` + `SVG_NOTE_FALLBACK`) show through.
- **Discovered by:** B

#### F-WN-32-7  [P3] — The library counters silently keep stale values when the bridge calls fail

- **File:** `ui/web_new_v2/js/library.js:329-371` (`loadLibrarySummary`), specifically `library.js:359` and `library.js:370`
- **Confirmed:** yes
- **Description:** `loadLibrarySummary` wraps both `get_favorites()` and
  `get_downloaded_tracks()` in `try { … } catch (e) {}` with an **empty** catch. When the
  bridge rejects, the "N треков" counters under "Любимые" and "Офлайн" keep whatever value
  they had, and nothing tells the user the number is stale.
- **Cause:** Empty catch blocks — the AGENTS.md "failure mode is silence" antipattern. The
  rest of the module surfaces failures (`library.js:541-545` renders a failure box,
  `library.js:631-635` renders a retry button).
- **Trigger conditions:** A Python exception in `AppApi.get_favorites` or
  `AppApi.get_downloaded_tracks` (WN-06). Note `get_downloaded_tracks` does an
  `os.path.exists()` stat per row (`core/api.py:2289-2291`), so it is the more likely of
  the two to fail on a large offline library.
- **User impact:** The user sees an outdated favourite/offline count with no indication
  that it is wrong. Low severity, but it is exactly the class of silent divergence the
  project rules call out.
- **Evidence:**
  ```js
  // library.js:344-359
  let backendFavs = [];
  if (window.pywebview?.api?.get_favorites) {
      backendFavs = await window.pywebview.api.get_favorites() || [];
  }
  …
  updateLibraryFavoriteCount(favCount);
  …
  } catch (e) {}          // <-- silent
  ```
  ```js
  // library.js:362-370
  try {
      if (window.pywebview?.api?.get_downloaded_tracks) {
          const downloaded = await window.pywebview.api.get_downloaded_tracks() || [];
          …
      }
  } catch (e) {}          // <-- silent
  ```
- **Reproduction / verification:** Stub `window.pywebview.api.get_favorites = async () => { throw new Error('x') }`
  from the console, then trigger `refreshActiveLibraryView()`. The counter keeps its old
  value and no error is logged or displayed.
- **Suggested fix:** Log the error and mark the counter as unavailable (e.g. show "—" or a
  warning style) rather than leaving the previous number in place.
- **Fix side effects:** `refreshActiveLibraryView()` is called on every `download_complete`
  (F-WN-32-1); adding a visible warning state could flash on every download, so the warning
  must be sticky (only shown when the value actually could not be refreshed).
- **Discovered by:** B

#### F-WN-32-8  [P3] — The lyrics sheet is always built twice and fully rebuilt on every translation toggle

- **File:** `ui/web_new_v2/js/lyrics.js:381-386` (`getContainers`), `ui/web_new_v2/js/lyrics.js:942-987` (synced rendering), `ui/web_new_v2/js/lyrics.js:57-91` (translation toggle re-render)
- **Confirmed:** yes
- **Description:** `getContainers()` always returns **both** `#lyrics-content` (the player
  panel) and `#overlay-lyrics-content` (the full-screen overlay) when both exist in the
  document, and `renderLyrics` builds the complete sheet in each: one `.lyric-line`
  element per LRC line **per container**, each with its own `click` listener. Toggling the
  translation calls `renderLyrics(lastLyricsData, true)` (`lyrics.js:84` / `lyrics.js:90`),
  which throws the whole sheet away and rebuilds it — twice — just to add or remove the
  `.lyric-translation` spans.
- **Cause:** The two sheets share one render function but have separate DOM trees and
  separate per-line event handlers; the translation toggle is implemented as a full
  re-render instead of a targeted span update.
- **Trigger conditions:** Any track with synced lyrics (typically 150–400 lines → 300–800
  elements and listeners per container) and any use of the translation toggle.
- **User impact:** A visible hitch on every translation toggle, and double the DOM/listener
  cost for a feature where only one sheet is ever visible. The lyric-line `click` handlers
  are also duplicated (`lyrics.js:964-978` runs once per container).
- **Evidence:**
  ```js
  // lyrics.js:381-386
  function getContainers() {
      return [
          document.getElementById('lyrics-content'),
          document.getElementById('overlay-lyrics-content')
      ].filter(Boolean);
  }
  ```
  ```js
  // lyrics.js:945-981
  containers.forEach(c => {
      c.innerHTML = '';
      parsedLyrics.forEach((line, i) => {
          const el = document.createElement('div');
          el.className = 'lyric-line';
          …
          el.addEventListener('click', (e) => { e.stopPropagation(); seekTo(line.timeMs); … });
          c.appendChild(el);
      });
  });
  ```
- **Reproduction / verification:** Open the lyrics overlay on a track with synced lyrics,
  run DevTools → Performance → record, then click the translation button: a single
  `renderLyrics` pass appears in the flame chart, with ~2 × N element creations and
  ~2 × N listener registrations. `document.querySelectorAll('.lyric-line').length` is twice
  the line count of the song.
- **Suggested fix:** Render the sheet once per container but keep the parsed line model
  shared; update the translation spans in place (toggle a class / append-remove only the
  `.lyric-translation` child) instead of rebuilding; and skip rendering into a container
  that is not currently displayed.
- **Fix side effects:** `updateLyricsPosition` (`lyrics.js:1092-1099`) keeps a per-container
  kinetic state (`track._kinetic`) and a per-container line cache; skipping a hidden
  container requires that `ensureKineticState`/`refreshKineticState` tolerate a container
  whose lines were never built (`st.measured` is already guarded by `measureViewport`'s
  `clientHeight === 0` check at `lyrics.js:446`).
- **Discovered by:** B

### 3. Clean areas

- **XSS — the dominant risk in this area is handled correctly.** Every `innerHTML` sink in
  the nine WN-32 files was enumerated (`library.js` 13, `library-view.js` 11,
  `downloads-view.js` 2, `smart-playlists.js` 4, `lyrics.js` 8, `artist_profile.js` 16,
  `profile.js` 5, `profile-comparison.js` 2, `onboarding.js` 0) and every one that
  interpolates provider/user data passes it through `escapeHtml()`
  (`ui/web_new_v2/js/utils.js:17-25`), which escapes `& < > " '` and therefore prevents
  attribute breakout in the quoted attributes used here. No `insertAdjacentHTML`,
  `outerHTML`, `document.write`, `new Function` or `eval` exists in any of the nine files.
  No `href=` is built from a variable anywhere in the area.
- **The lyrics body — the highest-risk text in the area — is rendered with `textContent`,
  never `innerHTML`**: `lyrics.js:953` (`.lyric-orig-text`), `lyrics.js:959`
  (`.lyric-translation`), `lyrics.js:1009` and `lyrics.js:1013` (plain-lyrics path). A
  hostile LRC payload such as `<img src=x onerror=alert(1)>` is displayed as text.
- **The artist biography is escaped at the sink**: `artist_profile.js:405`
  (`<p id="artist-bio-text">${escapeHtml(...)}</p>`) and the language switch writes with
  `textContent` (`artist_profile.js:426`).
- **Track titles / artist names / album names** are escaped in `utils.js:718-748`
  (`createTrackElement`) and set with `textContent` in `library-view.js:115-118`.
- **Playlist names** are escaped at every sink: `library.js:606`, `library.js:863`,
  `library-view.js:62`, `library-view.js:87`, `library-view.js:155`,
  `smart-playlists.js:57`, `smart-playlists.js:114`.
- **The search / filter query is never echoed into markup**: the playlist filter
  (`library-view.js:204-207`) only toggles `item.hidden` — no `innerHTML`, no injection
  path.
- **The onboarding URL validator is strict and correct**: `onboarding.js:36-46` requires
  `https:`, rejects credentials, and matches an exact host allow-list
  (`youtube.com`, `music.youtube.com`, `open.spotify.com`, `music.yandex.ru`,
  `music.yandex.com`) with a path pattern — `youtube.com.evil.test` is rejected. The
  corresponding Python entry point also has an SSRF guard
  (`core/api.py:2364-2367`, `_is_ssrf_safe_url`).
- **Cover images are lazy-loaded** everywhere in the area: `utils.js:529`
  (`coverImgHtml` → `loading="lazy"`), `utils.js:601` (collage cells),
  `artist_profile.js:480` (album covers).
- **`utils.js::safeCssImageUrl`** (`utils.js:40-50`) correctly validates the scheme
  before a URL is placed inside `url('…')` in a style attribute — this is the one place
  where HTML escaping would *not* have been enough, and it is handled.
- **`downloads-view.js` is well designed.** It caps the visible queue at 80 rows and
  *removes* rows beyond the limit (`downloads-view.js:61-68`), reuses row elements through
  a `Map` instead of rebuilding them, debounces refreshes at 180 ms
  (`downloads-view.js:122-128`), coalesces concurrent refreshes through
  `refreshPromise`/`refreshAgain` (`downloads-view.js:89-120`), and updates a single row
  in place for `download_progress` (`downloads-view.js:183-191`). The backend throttles
  progress events to 0.75 s per track (`core/downloader.py:162`), so the event rate is
  bounded. Bridge failures are surfaced in the UI (`downloads-view.js:103-109`).
- **`smart-playlists.js` is clean**: rule parsing is validated with real bounds
  (`smart-playlists.js:26-41`), all names are escaped, failures are shown inline
  (`smart-playlists.js:81-82`, `smart-playlists.js:128`, `smart-playlists.js:176`), the
  submit button is re-enabled in a `finally`, and the dialog focus trap is released on
  `close` (`smart-playlists.js:151`).
- **`profile.js` and `profile-comparison.js` are clean**: every bridge call goes through
  `request()` (`profile.js:11-19`) with a 20 s timeout; `Promise.allSettled` is used so a
  single failing call does not blank the page (`profile.js:135`); a generation counter
  invalidates stale renders (`profile.js:59`, `profile.js:132`, `profile.js:186`); the
  30 s poll is gated on `document.hidden` and on the view being active
  (`profile.js:182-184`); the avatar URL is built with `encodeURIComponent` and the proxy
  restricts `/api/avatar` to `~/.nedotify/avatars` (`core/proxy.py:115-140`).
- **`onboarding.js` is clean**: the completion flag is written only after the backend
  acknowledges (`onboarding.js:176-191`), a storage failure cannot mark onboarding done
  (the `writeStorage` helper swallows and the backend stays authoritative —
  `onboarding.js:17-19`), the draft is size-capped (`onboarding.js:91-92`), the audio
  device list is re-validated against the current generation (`onboarding.js:145-159`),
  and all controls are disabled during the save and restored in a `finally`
  (`onboarding.js:164-165`, `onboarding.js:208`).
- **The lyrics auto-scroll is genuinely well optimised** and was checked specifically for
  forced layouts: `updateLyricsPosition` (`lyrics.js:1068-1133`) does a binary search over
  `parsedLyrics` and performs **zero** layout work on the steady path (the "same line"
  branch returns early for any already-measured sheet); the line-change path performs a
  bounded number of class writes (`updateLineClasses` only touches the delta between the
  old and new index, `lyrics.js:537-564`); the transform write is de-duplicated
  (`applyTransform`, `lyrics.js:488-497`); `offsetTop` is used instead of
  `getBoundingClientRect` to avoid a paint-time flush (`lyrics.js:474-479`); and the
  sheet is driven by a single `translate3d` with a CSS transition rather than by
  `scrollTo` (`lyrics.js:319-335`). The `request_id`/revision guard
  (`lyrics.js:895-899`, `lyrics.js:314`) correctly rejects out-of-order and stale
  `lyrics_ready` payloads.
- **Stale-response guards are present and correct** across the area:
  `library.js:377`/`library.js:483`/`library.js:505` (library generation),
  `library-view.js:8`/`library-view.js:135`/`library-view.js:140` (overview generation),
  `smart-playlists.js:11`/`smart-playlists.js:68`/`smart-playlists.js:74`
  (smart-playlist generation), `lyrics.js:17`/`lyrics.js:822`/`lyrics.js:864`
  (lyrics generation), `artist_profile.js:21`/`artist_profile.js:718`/`artist_profile.js:747`
  (artist generation), `profile.js:7`/`profile.js:59`/`profile.js:132`,
  `profile-comparison.js:3`/`profile-comparison.js:28`.

### 4. Coverage gaps

- **No DOM-level test exists for any WN-32 module.** The JS tests in the area are Node
  `vm` harnesses that either (a) extract pure functions and strip the `import`/`export`
  keywords (`tests/test_library_view_ui.py:20`, `tests/test_profile_view_ui.py:17`), or
  (b) substitute a hand-written fake `Element` class
  (`tests/test_smart_search_ui.py:48-60`). Concretely, `tests/test_smart_search_ui.py:130`
  stubs `createTrackElement:()=>new Element()`, `decorateLibraryRow:element=>element` and
  `renderIcons:()=>{}` — so the DOM cost of the library list (F-WN-32-2) is *structurally
  invisible* to the suite. **Nothing in the suite can catch an XSS regression, a DOM/listener
  leak, or a performance regression in this area.**
- **Static-grep tests, not behavioural tests.** `tests/test_frontend_js.py:264-320` asserts
  on the *source text* of `artist_profile.js` (`"window.pywebview.api.get_artist_profile(" in
  artist_src`, `"mock marker still present in artist_profile.js"`) — it cannot detect a
  behavioural regression. `tests/test_frontend_js.py:62` is a `node --check` syntax test.
- **There is no test file for `downloads-view.js` at all** (the `tests/test_downloads_view*`
  files named in the brief do not exist; only the Python-side `test_downloader*.py`,
  `test_api_download.py` exist) and **no test file for `artist_profile.js` rendering** (only
  the bridge-contract test at `tests/test_catalog_lyrics_ui.py:65-82`, which exercises
  `fetchArtistProfileFromBridge` in isolation and stubs `document`).
- **`tests/test_lyrics_performance.py` does not test the UI.** Despite the name it tests
  `services/lyrics_service.py` / `lyrics_lookup.py` / `lyrics_cache.py` (Python) — cache
  identity, timing bounds, provider fallbacks. There is **no** measurement of
  `lyrics.js::updateLyricsPosition` cost, `renderLyrics` cost, or layout thrash.
- **The three findings that need a live WebView to confirm end-to-end** — F-WN-32-1
  (three rebuilds per download), F-WN-32-2 (row/listener growth), F-WN-32-3 (stale rows
  after a failure) — were verified by code reading plus the reproduction scripts described
  in each finding. I did **not** launch the packaged app (AGENTS.md forbids running the real
  app: it would disturb the user's `~/.nedotify/` profile). A DOM-level harness
  (jsdom or a headless WebView2) would be needed to assert the DOM node counts and the
  listener counts directly.
- **I did not measure the actual `get_library()` payload size** for a realistic library;
  the "10 000-track library" figure in the brief is used as the scaling model, and the
  unbounded query is confirmed (`core/database.py::get_all_tracks` has no `LIMIT`), but the
  per-row JSON size was not measured.
- **The `_emit`-side of the `download_complete` event** (the emit path and its thread
  safety) belongs to WN-03 and was not re-reviewed; only the JS consumer side was in scope.
- **`core/proxy.py`'s `/api/cover` and `/api/avatar` handlers** were only skimmed for the
  path allow-list that `profile.js:127` and `utils.js:626-628` depend on; a full SSRF /
  path-traversal review of the proxy belongs to WN-11.

### 5. Architecture improvements (ARCH)

These are engineering improvements without a proven defect. They are reported separately
from the defect list above.

**ARCH-1 — There is no shared track-row component; seven independent render paths exist.**
The markup base *is* shared (`utils.js::createTrackElement`, `utils.js:688-890`), and it is
used by `library.js:409`, `library-view.js:147`, `profile.js:42`, `artist_profile.js:197`
and `:593`, `search.js:491/729/927` and `home-shell.js:56`. But everything *around* it is
re-implemented per module:

| Path | Row builder | Own keydown handler | Own aria-label pass | Own duration handling |
|---|---|---|---|---|
| Library | `library-view.js:111 decorateLibraryRow` | yes (`library-view.js:113`) | guarded (`library-view.js:121`) | `—` for invalid (`library-view.js:120`) |
| Profile | `profile.js:41 decorateRow` | yes (`profile.js:45`) | **unconditional overwrite** (`profile.js:46`) | replaced by `.profile-track-metric` (`profile.js:44`) |
| Artist profile | `artist_profile.js:582 renderBatch` | **none** | **none** | play count / year inserted (`artist_profile.js:629-645`) |
| Search | `search.js:485-495` (batch only) | none | none | none |
| Queue | `queue.js:142-170` — **its own markup**, does not use `createTrackElement` | none | none | own `.track-item-duration` |
| Overview "recent" | `library-view.js:147` (via `commands.row`) | (inherits library) | (inherits library) | — |
| Home dialogs | `home-shell.js:56` | none | none | none |

**Concrete drift, already visible today:** the *same* `createTrackElement` row is
keyboard-focusable and Enter/Space-activatable in the Library (`library-view.js:113`) and in
the Profile (`profile.js:45`), but in the Artist Profile it is neither focusable nor
activatable — `ArtistTracksComponent` never sets `tabIndex` and never adds a `keydown`
handler, so `createTrackElement`'s row is mouse-only there. A fix "make track rows
keyboard-activatable" applied inside `createTrackElement` would land in the Library and the
Profile but **silently miss the Artist Profile**, because the two decorators add the
handler themselves instead of the shared factory doing it.

**Second concrete drift:** the aria-label pass. `library-view.js:121` only fills in a
*missing* label (`if(!button.getAttribute('aria-label'))`), whereas `profile.js:46`
**overwrites** whatever label exists (`button.setAttribute('aria-label', button.title || …)`).
Today the shared factory (`utils.js:732-745`) emits only `title` and no `aria-label`, so the
two happen to agree. The moment anyone adds a descriptive `aria-label` to a button in
`utils.js::createTrackElement` (e.g. `"Скачать трек «${title}»"`), the Library view will
keep the good label and the **Profile view will silently destroy it**.

**Third concrete drift:** the duration cell. `profile.js:44` *renames the class* of the
shared `.track-duration` node (`duration.className='profile-track-metric'`) and overwrites
its text, while `artist_profile.js:635` *inserts siblings before* the same node
(`durationEl.parentNode.insertBefore(metaText, durationEl)`) and `library-view.js:120`
*writes into* it. Three modules mutate the same shared markup in three incompatible ways.

*Direction:* introduce a single `TrackRow` component (factory + decorator pipeline) in a
shared module — e.g. `createTrackElement(track, index, tracks, current, {variant})` — with
one place that owns `tabIndex`, the keydown handler, the aria-label pass and the duration
cell, and with the per-view differences expressed as declarative options. Move the queue
view onto it too.

**ARCH-2 — Two incompatible strategies for the same problem (rendering a long track list).**
`search.js:470-502` chunks with `requestAnimationFrame` (`SEARCH_BATCH_SIZE = 30`) and
scopes the icon pass to the list (`renderIcons(list)`). `library.js:394-454` chunks on
scroll with a 50-row batch and calls the **document-wide** `renderIcons()`
(`library.js:413`). `artist_profile.js:582-652` chunks on scroll with a 20-row batch and
also calls the document-wide `renderIcons()` (`artist_profile.js:651`). Three modules, two
strategies, and the *correct* icon-scoping exists only in `search.js` — so a fix applied
there silently misses the two heaviest lists in the app.

**ARCH-3 — The library and the download manager have two independent refresh paths over
the same data.** `library.js` re-reads the library through `refreshActiveLibraryView()`
while `downloads-view.js` maintains its own 80-row window over the same underlying queue
(`downloads-view.js:58-87`). They are refreshed by different triggers (a `download_complete`
event vs. `download_progress` / `download_queue_updated`), so the "Загрузки" panel and the
Library view can show different states at the same moment. A single subscription that owns
"download state changed" and fans out to both views would remove the triple-refresh of
F-WN-32-1 at the same time.

**ARCH-4 — The bridge returns unbounded collections and the UI is left to cope.**
`get_library` (whole table), `get_playlist_tracks` on the `local` path (whole playlist,
the `limit` argument is ignored), `get_smart_playlist_tracks` (bounded only because the JS
chose `201`), `get_favorites`, `get_downloaded_tracks`. The area map places `get_library`
in WN-06, but the *contract* between the bridge and this area is "return everything and
let the UI batch it", which is what produces F-WN-32-1 and F-WN-32-2. A paged contract
(`get_library(offset, limit)` returning `{tracks, total}`) would let the UI keep a bounded
window, would cut the bridge payload by orders of magnitude, and would make the smart
playlist's hand-rolled "Показать ещё" (`library.js:521-540`) unnecessary.

**ARCH-5 — `library.js` mixes navigation, data loading, DOM rendering and drag-and-drop
in one module.** `library.js` contains the sidebar rendering (`loadPlaylists`), the
collection renderer (`selectSection`), the batch renderer, the playlist drag-and-drop
(`setupPlaylistDrag`/`startDrag`/`moveDrag`/`endDrag`, `library.js:701-833`), the context
menu (`openPlaylistMenu`), the playlist CRUD modals, the import dialog and the
batch-download progress UI. `library-view.js` already demonstrates the better split
(pure view functions + a `commands` callback object, `library-view.js:169-215`), but
`library.js` keeps a second, parallel implementation of the same responsibilities. The
drag-and-drop block in particular is ~130 lines of pointer maths with module-level mutable
state (`_dragGhost`, `_placeholder`, `_dragOffsetY`, `library.js:743-745`) that is
completely independent of the view layer and is not covered by any test.

**ARCH-6 — The test suite for this area tests the wrong things.** There are 11 test files
that touch WN-32 JS, and the bulk of them assert on *pure helper functions* through a
`node:vm` sandbox that strips the module graph. There is no DOM harness, so the three
highest-risk properties of this area — escaping at the `innerHTML` sinks, the DOM/listener
budget of the library list, and the teardown of listeners between views — are structurally
untestable today. A single `jsdom`-based fixture that mounts `#view-library` and asserts
"a track title containing `<img src=x onerror=…>` is rendered as text, not as an element",
"the number of `.track-item` nodes stays bounded", and "switching sections removes the
previous scroll listener" would cover all three.
