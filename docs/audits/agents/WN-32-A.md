## AREA WN-32 — UI library, downloads, smart playlists, lyrics, artist profile, profile, onboarding — ROLE A

### 1. Scope reviewed

**Files opened (path: physical line ranges actually read)**

| File | Lines read | Notes |
|---|---|---|
| `ui/web_new_v2/js/library.js` | 1–967 (whole file) | 967 physical lines (area map says 854 — the file grew; reviewed all of it) |
| `ui/web_new_v2/js/library-view.js` | 1–215 (whole file) | 215 physical lines (area map says 201) |
| `ui/web_new_v2/js/downloads-view.js` | 1–193 (whole file) | 193 physical lines (area map says 182) |
| `ui/web_new_v2/js/smart-playlists.js` | 1–185 (whole file) | 185 physical lines (area map says 174) |
| `ui/web_new_v2/js/lyrics.js` | 1–1262 (whole file) | 1262 physical lines (area map says 1144) |
| `ui/web_new_v2/js/artist_profile.js` | 1–811 (whole file) | 811 physical lines (area map says 743) |
| `ui/web_new_v2/js/profile.js` | 1–188 (whole file) | 188 physical lines (area map says 187) |
| `ui/web_new_v2/js/profile-comparison.js` | 1–56 (whole file) | 56 physical lines (area map says 51) |
| `ui/web_new_v2/js/onboarding.js` | 1–238 (whole file) | 238 physical lines (area map says 232) |

**Callees traced into other areas (read for verification only, not reviewed)**

- `core/api.py` — `get_library` (2267), `get_favorites`/`get_favorite_tracks` (2273, 2727), `get_downloaded_tracks` (2277), `get_playlists` (2513), `get_playlist_tracks` (2545), `create_playlist` (2498), `delete_playlist` (2504), `add_to_playlist` (2517), `export_playlist` (2416), `import_external_playlist` (2362), `toggle_favorite` (2615), `get_wrapped_stats` (3156), `get_lyrics` (3192), `get_lyrics_translation` (3286), `get_profile_stats` (3388), `select_avatar` (3399), `create_local_playlist` (3420), `open_local_file` (3436), `get_artist_profile` (3477), `get_artists_avatars` (3515), `get_settings` (2922), `save_setting` (2940), `complete_onboarding` (2756), `get_downloads`/`pause_download`/`resume_download`/`retry_failed_downloads` (4176–4190), `get_smart_playlists`/`create_smart_playlist`/`update_smart_playlist`/`delete_smart_playlist`/`get_smart_playlist_tracks` (4192–4217), `get_listening_comparison` (4223), `report_position` (1407), `play_track`/`_resolve_track` (1437, 1608)
- `core/downloader.py` (60–209, 239–284, 563–600, 660–881) — status transitions, `_record_progress`, `get_downloads`, pause/resume/retry
- `core/download_store.py` (whole file, 71 L) — `rows()` shape, `percent` computation
- `core/database.py` — `get_favorite_tracks`, `get_most_played`, `get_history`, `get_wrapped_stats` (1723–1802), `get_playlists` (1931), `add_to_playlist` (1950), `get_playlist_tracks` (2004), `delete_playlist` (2018)
- `core/settings.py` — `set` (401), `sync_flush_now` (420)
- `core/user_errors.py` (whole file, 24 L) — `describe_error` shape
- `services/smart_playlists.py` (whole file, 177 L) — `normalize_rule`, `tracks`, `SORTS`, `MAX_TRACKS`
- `services/lyrics_service.py` (240–299) — `translate_lyrics`, `get_lyrics`
- `services/lyrics_lookup.py` (237–316) — revision/phase protocol
- `services/artist_identity.py` (whole file, 63 L) — `name_key`, `canonical_artist`
- `services/artist_service.py` (105–139, 248–287, 340–390) — profile/album/track payload shapes
- `services/listening_comparison.py` (whole file, 84 L) — comparison payload, `utc_offset_minutes` semantics
- `services/youtube_service.py` (483–512) — search-result track dict (no `id` field)
- `ui/web_new_v2/js/utils.js` — `createTrackElement` (688–890), like handler (815–858), `add_to_playlist` button (860–870)
- `ui/web_new_v2/js/events.js` (1–304) — bridge-event → custom-event mapping
- `ui/web_new_v2/js/feature-controls.js` (85–134) — `handleFeatureEvent` → downloads view
- `ui/web_new_v2/js/player.js` — `listAudioOutputs` (183–201), the `timeupdate` handler that dispatches `nedotify:position_changed` (580–618), `report_position` (615)
- `ui/web_new_v2/js/search.js` (270–329) — `searchArtistProfile` context plumbing
- `ui/web_new_v2/js/main.js` (398–437) — `nedotifySettingsReady`, `initOnboarding` ordering
- `ui/web_new_v2/index.html` — library view DOM (462–503), profile DOM (640–652), onboarding wizard (2181–2250)
- `ui/web_new_v2/css/components/library-refresh.css` (1–140) — `#lib-active-tracks { overflow: visible !important }`, `.lib-right-content { overflow-y: auto }`

---

### 2. Findings

#### F-WN-32-1  [P2] — Favourites counter double-counts every track liked from search (two different ID namespaces)

- **File:** `ui/web_new_v2/js/library.js:344-358` (and the same defect at `library.js:513-515`); enabling code in `ui/web_new_v2/js/utils.js:837`; backend key in `core/api.py:2615-2626`
- **Confirmed:** yes
- **Description:** The library's favourite counter adds "local-only" favourites on top of the backend list, assuming the localStorage key and the backend key identify the same track. They do not. `utils.js` stores `String(track.id || track.source_id)`. Provider search results have **no `id` field** (`services/youtube_service.py:490-498` returns only `source`/`source_id`/`title`/`artist`/`duration`/`cover_url`/`album`), so the localStorage entry is the **source_id** (e.g. `"dQw4w9WgXcQ"`). The backend, however, materialises a **numeric DB id** for the same track (`core/api.py:2617-2625`: `track_id = track_data.get("id")` → falsy → `db.add_track(...)`), and `get_favorites()` returns rows keyed by that numeric id. `library.js` then compares `String(bt.id || bt.source_id)` against the stored source_id — they never match.
- **Cause:** Two different primary keys for the same entity (`source_id` in localStorage vs. `id` in the DB) are compared for equality.
- **Trigger conditions:** The user likes a track from the search results (or any track object without a DB `id`), then opens the Library. The track is now a backend favourite **and** a localStorage entry that the backend set never "contains".
- **User impact:** The library shows "2 треков" (and the "Любимые" collection card shows 2) for a single favourite; the favourites section subtitle reads "2 треков" while only one row is rendered. The count grows with every track liked outside the library.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/utils.js:837  (what gets stored)
  const tId = String(track.id || track.source_id || '');
  ```
  ```js
  // ui/web_new_v2/js/library.js:350-352  (what gets compared)
  const backendIds = new Set(backendFavs.map(bt => String(bt.id || bt.source_id || '')));
  // M-2/M-3: count = unique backend + local-only IDs (legacy sync may lag)
  const favCount = backendFavs.length + [...localIds].filter(id => id && !backendIds.has(id)).length;
  ```
  ```js
  // ui/web_new_v2/js/library.js:513-515  (the section subtitle, same defect)
  if(type==='favorites') {
      try {const localIds=JSON.parse(localStorage.getItem('nedotify_favorites') || '[]').map(value=>String(typeof value==='string'?value:value?.id || value?.source_id || '')).filter(Boolean);count+=new Set(localIds.filter(id=>!seen.has(id))).size;}catch{}
  }
  ```
  ```python
  # core/api.py:2617-2626
  track_id = track_data.get("id")
  if not track_id:
      track_id = self._core.db.add_track(...)     # -> numeric id, source_id kept separately
  status = self._core.db.toggle_favorite(track_id)
  ```
- **Reproduction / verification:** Search for any track, click the ♥ on a search result (the row has no `id`), then open Library. `localStorage.getItem('nedotify_favorites')` contains the `source_id`; `pywebview.api.get_favorites()` returns the same track with a numeric `id`. `library.js` computes `backendFavs.length (1) + local-only (1) = 2`. Deterministic.
- **Suggested fix:** Key both sides by a stable identity (e.g. `source + ':' + source_id`) instead of `id || source_id`, or make the backend return the same composite key.
- **Fix side effects:** Changing the localStorage key format invalidates existing `nedotify_favorites` entries; a migration (or a re-derivation from the backend list) is needed, otherwise existing users lose their local fallback entries.
- **Discovered by:** A

#### F-WN-32-2  [P2] — "Add to playlist" failures are reported to the user as success

- **File:** `ui/web_new_v2/js/library.js:864-878` (context menu) and `ui/web_new_v2/js/library.js:931-945` (create-and-add); backend at `core/api.py:2517-2530` and `core/database.py:1950-1970`
- **Confirmed:** yes
- **Description:** `api.add_to_playlist` returns `db.add_to_playlist(...)`, which is a **plain bool** (`True` on success, `False` on any DB exception — `core/database.py:1967-1970`). The library's context menu checks `if (res && res.success === false)` — but a `false` return is falsy, so the `&&` short-circuits and the **success** branch runs. The user is told "Трек добавлен в …" for a track that was never added.
- **Cause:** The error test assumes a dict-shaped result (`res.success === false`), but the bridge returns a boolean.
- **Trigger conditions:** Any DB error during the insert (e.g. the playlist row was deleted concurrently — a foreign-key violation — or the DB is busy/locked). Also reachable through `createPlaylist()`: `await window.pywebview.api.add_to_playlist(plId, contextTrack)` at `library.js:937` ignores the return value entirely, so that path never reports anything at all.
- **User impact:** The track is silently missing from the playlist while the UI says it was added. The user has to reopen the playlist to notice.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/library.js:867-872
  const res = await window.pywebview.api.add_to_playlist(plId, currentContextTrack);
  if (res && res.success === false) {
      window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: res.error || 'Не удалось добавить трек', type: 'error' } }));
  } else {
      window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Трек добавлен в "${pl.name}"`, type: 'success' } }));
  }
  ```
  ```python
  # core/database.py:1950-1970
  def add_to_playlist(self, playlist_id: int, track_id: int) -> bool:
      ...
      try:
          with conn:
              ...
          return True
      except Exception as e:
          logger.error(f"Failed to add to playlist: {e}")
          return False
  ```
  ```python
  # core/api.py:2517-2530
  def add_to_playlist(self, playlist_id: int, track_data: dict):
      ...
      res = self._core.db.add_to_playlist(playlist_id, track_id)
      self._emit("playlist_changed", {"playlist_id": playlist_id})
      return res          # <- a bool, not a dict
  ```
- **Reproduction / verification:** Delete the playlist from another surface (or otherwise force the `playlist_tracks` insert to fail), then use the row's "+" → playlist button. The bridge resolves with `false`; the toast says "Трек добавлен". Alternatively, unit-level: `db.add_to_playlist(999999, 1)` returns `False`, and `AppApi.add_to_playlist` returns `False`.
- **Suggested fix:** Treat a falsy/`false` return as a failure (`if (res === false || res?.success === false) …`), and surface the failure in `createPlaylist()` too.
- **Fix side effects:** None — the current success path is only reachable when the insert actually succeeded or when it silently failed.
- **Discovered by:** A

#### F-WN-32-3  [P2] — The library scroll-loader is not detached when the newly selected collection is empty → stale rows from the previous collection can be appended

- **File:** `ui/web_new_v2/js/library.js:420-454` (`attachLibraryScrollLoader` / `renderLibraryList`), `ui/web_new_v2/js/library.js:519` (the empty-collection early return)
- **Confirmed:** yes (code path is deterministic); the *visible* glitch is timing-dependent
- **Description:** `renderLibraryList()` owns the teardown of the previous scroll listener (`if (libraryScrollCleanup) { libraryScrollCleanup(); … }`), but it is only reached on the **non-empty** path. When `selectSection()` renders an empty collection it calls `renderLibraryEmpty(container, …)` and returns at line 519, leaving the previous section's `scroll` listener attached to `.lib-right-content` together with a closure over the **previous** track array and its `renderNext`.
- **Cause:** Listener ownership is bound to "a non-empty render happened" rather than to "a new collection was selected".
- **Trigger conditions:** (a) The listener is never detached → it is retained for the lifetime of the page (one stale listener at a time, re-armed on the next non-empty render). (b) The stale `renderNext()` appends **the previous collection's** rows into `#lib-active-tracks` — the same container the new, empty collection is rendering into — whenever a `scroll` event reaches `.lib-right-content` while the content is short (which is always true for an empty collection, since `scrollHeight - 200 <= scrollTop + clientHeight`).
- **User impact:** The empty collection can show the message "В этом плейлисте пока нет треков" *together with* a stale list of up to 50 tracks from the previously viewed collection. The user may believe those tracks belong to the new playlist (and "Play all" would then play them — `currentActiveTracks` is the stale array until the next `selectSection`).
- **Evidence:**
  ```js
  // ui/web_new_v2/js/library.js:447-454
  function renderLibraryList(tracksContainer, tracks) {
      if (libraryScrollCleanup) { libraryScrollCleanup(); libraryScrollCleanup = null; }
      tracksContainer.innerHTML = '';
      ...
      libraryScrollCleanup = attachLibraryScrollLoader(tracksContainer, renderer.renderNext, renderer.getRendered, renderer.getTotal);
      return renderer;
  }
  ```
  ```js
  // ui/web_new_v2/js/library.js:519  (empty path — no cleanup, no new loader)
  if(!tracks.length){renderLibraryEmpty(container,type==='smart'?'По этим правилам пока нет треков':type==='playlist'?'В этом плейлисте пока нет треков':type==='favorites'?'Добавьте любимые треки':type==='offline'?'Музыка для прослушивания без сети':'Начните свою коллекцию');return;}
  ```
  ```js
  // ui/web_new_v2/js/library.js:437-442  (the stale closure that keeps firing)
  const onScroll = () => {
      const sc = scrollParent.scrollTop + scrollParent.clientHeight;
      if (sc >= scrollParent.scrollHeight - 200 && getRendered() < getTotal()) {
          renderNext();
      }
  };
  scrollParent.addEventListener('scroll', onScroll, { passive: true });
  ```
- **Reproduction / verification:** Open Library → "Вся музыка" (enough tracks to make the drain loop stop early, i.e. > 50) → click a playlist with 0 tracks → scroll the library list (or simply wait for the scroll event caused by the container shrinking). Inspect `#lib-active-tracks`: it contains `.lib-collection-empty` **and** `.track-item` rows from "Вся музыка".
- **Suggested fix:** Detach the previous loader at the top of `selectSection()` (or inside `renderLibraryEmpty`), not only inside `renderLibraryList()`.
- **Fix side effects:** None — the loader is re-created by the next `renderLibraryList()` call.
- **Discovered by:** A

#### F-WN-32-4  [P2] — A failed lyrics translation silently renders the original text as the "translation"

- **File:** `ui/web_new_v2/js/lyrics.js:57-92` (toggle + alignment), `ui/web_new_v2/js/lyrics.js:956-960` / `1010-1015` (rendering); backend at `core/api.py:3286-3291` and `services/lyrics_service.py:243-272`
- **Confirmed:** yes
- **Description:** Two independent failure modes are swallowed:
  1. `services/lyrics_service.py::translate_lyrics` catches every exception and returns the **input text unchanged** (`except Exception as e: logger.debug(...); return lyrics`, lines 270-272). The JS then treats that string as a translation. The alignment loop maps each line to a line that is *identical* to it, so `currentTranslationMap[line] === line`.
  2. `core/api.py::get_lyrics_translation` catches exceptions and returns `{"error": str(e)}`. The JS's `else` branch then does `currentTranslationMap = res || {}` → `{"error": "…"}` → no line ever matches → nothing is displayed and no error is shown.
  In both cases the user got the toast "Переводим текст песни..." and then, in case (1), every line is duplicated below itself in the `.lyric-translation` slot (original text shown as the translation); in case (2), the toggle silently does nothing.
- **Cause:** The bridge contract has no error/failure signal for a translation (the service returns the input as a fallback, the API returns an error *dict* instead of raising), and the JS cannot distinguish "translated" from "unchanged".
- **Trigger conditions:** Any network failure to `translate.googleapis.com`, or an exception inside `translate_lyrics`.
- **User impact:** The user believes the song has been translated into Russian and reads the original (English) text under every line, or sees the toggle do nothing at all. There is no error message in either case.
- **Evidence:**
  ```python
  # services/lyrics_service.py:266-272
  with self._open_url(req, timeout=HTTP_TIMEOUT) as resp:
      data = json.loads(resp.read().decode('utf-8', errors='ignore'))
      out.append("".join([x[0] for x in data[0] if x[0]]))
  return "\n".join(out) if out else lyrics
  except Exception as e:
      logger.debug(f"Translation error: {e}")
      return lyrics          # <- original text returned as if it were a translation
  ```
  ```python
  # core/api.py:3286-3291
  def get_lyrics_translation(self, lyrics_text: str, target_lang: str = "ru"):
      try:
          return self._core.lyrics.translate_lyrics(lyrics_text, target_lang=target_lang)
      except Exception as e:
          return {"error": str(e)}     # <- a dict, not an exception
  ```
  ```js
  // ui/web_new_v2/js/lyrics.js:65-83
  if (typeof res === 'string') {
      const transLines = res.split(/\r?\n/).map(s => s.trim());
      const origLines = cleanText.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
      const map = {};
      const keys = parsedLyrics.length > 0 ? parsedLyrics.map(l => l.text) : origLines;
      keys.forEach((k, i) => {
          if (k && transLines[i] && transLines[i] !== k) map[k] = transLines[i];
          else if (k && origLines[i] && transLines[i]) map[origLines[i]] = transLines[i];   // <- identity map on failure
      });
      ...
      currentTranslationMap = map;
  } else {
      currentTranslationMap = res || {};      // <- {"error": "..."} becomes the map
  }
  ```
  ```js
  // ui/web_new_v2/js/lyrics.js:956-960
  if (isTranslationEnabled && currentTranslationMap[line.text]) {
      const subEl = document.createElement('div');
      subEl.className = 'lyric-translation';
      subEl.textContent = currentTranslationMap[line.text];
      el.appendChild(subEl);
  }
  ```
- **Reproduction / verification:** Block `translate.googleapis.com` (or set the app offline), open the lyrics overlay for any track and click the RU toggle. The sheet shows each line twice (identical text) and no error toast. With `translate_lyrics` raising instead, `currentTranslationMap` becomes `{"error": …}` and the sheet is unchanged.
- **Suggested fix:** Make the bridge signal failure explicitly (raise / return `{"ok": false}`) and, on the JS side, detect "the returned text equals the input" and show an error toast instead of rendering an identity translation.
- **Fix side effects:** `translate_lyrics` returning the input as a fallback is also relied on elsewhere? (grep shows only `get_lyrics_translation` calls it) — changing the contract is contained, but the API shape is used by any other caller of `get_lyrics_translation` (none in this repo besides `lyrics.js`).
- **Discovered by:** A

#### F-WN-32-5  [P2] — The artist key is re-implemented in the UI and diverges from `services/artist_identity.py`

- **File:** `ui/web_new_v2/js/artist_profile.js:51-58` (`isTrackByArtist`); canonical implementation at `services/artist_identity.py:9-10` (`name_key`) and `:48-54` (`canonical_artist`)
- **Confirmed:** yes
- **Description:** The artist-profile view filters library tracks with its own normalisation (`normalize('NFKC').toLowerCase().replaceAll('ё','е')` + a hard-coded `фараон → pharaoh` mapping), while the rest of the app (lyrics lookup, taste profile, recommendations, artist bindings) uses `services/artist_identity.py::name_key` (`unicodedata.normalize('NFKC').casefold().replace('ё','е')` + the configurable alias table). The two agree on the happy path but diverge in three concrete ways.
- **Cause:** A duplicated normalisation rule that was not updated when the backend gained `casefold` semantics and a user-configurable alias table (`personalization.artist_aliases`, `personalization.artist_bindings`).
- **Trigger conditions:**
  - Artist names containing characters where `casefold` ≠ `toLowerCase` (ß/ẞ, ﬁ ligatures after NFKC, final sigma ς vs σ). The backend sees them as the same artist; the UI does not.
  - The user configured an alias in settings (`set_artist_alias`, `core/api.py:3002`). The backend honours it; the UI ignores it.
  - Multi-artist strings: the backend normalises the **whole** `artist` field, the UI splits on `,|&| feat.|ft.` and requires an exact per-part match.
- **User impact:** The "Треки из вашей библиотеки" fallback block (shown when the catalog lookup fails, `artist_profile.js:190-200`) can omit tracks that the app elsewhere considers the same artist, and can include tracks that the backend considers a *different* artist (the UI's per-part match accepts "Artist feat. X" for the artist "Artist", the backend does not).
- **Evidence:**
  ```js
  // ui/web_new_v2/js/artist_profile.js:51-58
  function isTrackByArtist(track, targetArtist) {
      const key = value => {
          const name = String(value || '').normalize('NFKC').toLowerCase().replaceAll('ё', 'е').trim().replace(/\s+/g, ' ');
          return name === 'фараон' ? 'pharaoh' : name;
      };
      const target = key(targetArtist);
      return Boolean(target) && String(track?.artist || '').split(/,|&| feat\.? | ft\.? /i).some(person => key(person) === target);
  }
  ```
  ```python
  # services/artist_identity.py:9-10, 48-54
  def name_key(value):
      return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().replace('ё', 'е').split())
  def canonical_artist(value, aliases=None):
      key, visited = name_key(value), set()
      aliases = DEFAULT_ALIASES if aliases is None else aliases
      while key in aliases and key not in visited:
          visited.add(key); key = name_key(aliases[key])
      return key
  ```
  Note `DEFAULT_ALIASES = {'фараон': 'PHARAOH'}` is applied by the backend but is **hard-coded** in the JS, and the user-configured `personalization.artist_aliases` / `artist_bindings` are not visible to the JS at all.
- **Reproduction / verification:** Set an artist alias in settings (`set_artist_alias('artist a', 'Artist B')`), then open the artist profile of "Artist B" while the catalog is unreachable. The backend's canonical key maps both names together; `isTrackByArtist` does not, so the "Треки из вашей библиотеки" list is empty. Same for a `ß`/`SS` pair.
- **Suggested fix:** Expose the canonical artist key to the frontend (e.g. a small `canonical_artist(name)` bridge method) or normalise through a shared helper; do not keep a second copy of the rule in JS.
- **Fix side effects:** Adding a bridge method touches `core/api.py` (WN-03/WN-09 area). A pure-JS fix (mirroring `casefold` + fetching the alias table) would still duplicate the rule.
- **Discovered by:** A

#### F-WN-32-6  [P2] — The artist profile's "Популярные треки" list is never sorted by popularity and its play-count / year badges are dead code

- **File:** `ui/web_new_v2/js/artist_profile.js:551-555` (sort), `:614-645` (badges), `:565` (header); payload produced at `services/artist_service.py:261-272`
- **Confirmed:** yes
- **Description:** `ArtistTracksComponent` sorts by `b.playCount || b.views || b.play_count || 0` and renders a "N прослушиваний" badge and a release-year badge. The backend's artist tracks (`services/artist_service.py:261-272`) contain only `artists, id, source, source_id, source_url, title, artist, album, duration, cover_url` — no `playCount`, no `views`, no `play_count`, no `release_date`, no `year`.
- **Cause:** The UI was written against a richer track shape than the one the artist service produces.
- **Trigger conditions:** Every artist profile that resolves through `get_artist_profile`.
- **User impact:** The block is titled "Популярные треки (N)" but the order is the backend's arbitrary collection order, not popularity; the "N прослушиваний" and year badges never appear. The header over-promises what the list delivers.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/artist_profile.js:553
  this.tracks = [...tracks].sort((a, b) => (b.playCount || b.views || b.play_count || 0) - (a.playCount || b.views || b.play_count || 0));
  ```
  ```js
  // ui/web_new_v2/js/artist_profile.js:618-628
  const pc = track.playCount || track.views || track.play_count || 0;
  if (pc >= 1000000) { … } else if (pc >= 1000) { … } else if (pc > 0) { … }   // never true
  const year = track.release_date ? new Date(track.release_date).getFullYear() : (track.year || null);
  ```
  ```python
  # services/artist_service.py:261-272
  tracks.append({
      "artists": item.get("artists") or [], "id": "yt_" + str(video_id),
      "source": "youtube", "source_id": video_id,
      "source_url": "https://www.youtube.com/watch?v=" + str(video_id),
      "title": title, "artist": self._artists_label(item, artist_name),
      "album": album_name, "duration": dur or 0, "cover_url": cover,
  })
  ```
- **Reproduction / verification:** Open any artist profile in the app (search → artist). Inspect the "Популярные треки" block: no play count, no year, and the order matches the backend payload order rather than any popularity metric.
- **Suggested fix:** Either populate popularity data server-side (the DB has `tracks.play_count` for library tracks) or rename the block and drop the dead badges/sort.
- **Fix side effects:** If the sort is driven from the DB, the artist track ids (`"yt_<videoId>"`) are not DB ids — a DB join would need `source`+`source_id` matching.
- **Discovered by:** A

#### F-WN-32-7  [P2] — The smart-playlist editor's preset dropdown is not synced with the rule being edited, and switching presets silently discards the user's rule

- **File:** `ui/web_new_v2/js/smart-playlists.js:90-95` (`populateEditor`), `:97-108` (`openSmartPlaylistEditor`), `:155-159` (preset `onchange`), `:160-180` (submit)
- **Confirmed:** yes
- **Description:** `openSmartPlaylistEditor()` calls `form.reset()` (which resets the `<select name="preset">` to its first option, "Добавлено за месяц") and then `populateEditor(playlist?.rule)` fills only the six rule fields. The preset dropdown therefore always reads "Добавлено за месяц", regardless of the rule actually loaded. Choosing a different preset then overwrites every rule field with the preset's rule — with no warning and no way to get the edited rule back.
- **Cause:** `populateEditor` writes the rule fields but not the preset; the preset is a second, parallel source of truth for the same rule set.
- **Trigger conditions:** Editing any existing smart playlist whose rule is not the "recent" preset (e.g. `Скачанное без прослушиваний`); or selecting a preset after hand-editing the fields.
- **User impact:** The dropdown misrepresents the current rule (the user cannot tell which preset they are editing), and a single mis-click on the preset discards all hand-edited conditions with no undo.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/smart-playlists.js:90-95
  function populateEditor(rule) {
      const form = dialog.querySelector('form');
      for (const field of ['favorite', 'downloaded', 'unplayed']) form.elements[field].value = rule[field] == null ? '' : String(rule[field]);
      for (const field of ['added_within_days', 'not_played_days', 'artist']) form.elements[field].value = rule[field] ?? '';
      form.elements.sort.value = rule.sort || 'newest';
      // form.elements.preset is never written
  }
  ```
  ```js
  // ui/web_new_v2/js/smart-playlists.js:97-108
  export function openSmartPlaylistEditor(playlist = null) {
      if (!dialog) return;
      editing = playlist;
      const form = dialog.querySelector('form');
      form.reset();                                   // <- preset select -> "recent"
      ...
      populateEditor(playlist?.rule || SMART_PRESETS.recent.rule);
  ```
  ```js
  // ui/web_new_v2/js/smart-playlists.js:155-159
  form.elements.preset.onchange = event => {
      const preset = SMART_PRESETS[event.target.value];
      form.elements.name.value = preset.name;
      populateEditor(preset.rule);       // <- silently overwrites the edited rule
  };
  ```
- **Reproduction / verification:** Create a smart playlist with the preset "Скачанное без прослушиваний", reopen it for editing: the preset dropdown still shows "Добавлено за месяц" while the fields show the "unplayed_downloads" rule. Change the preset to anything else and the edited fields are replaced.
- **Suggested fix:** Either drive the preset from the rule (mark "custom" when no preset matches) or drop the preset dropdown in favour of the explicit rule fields.
- **Fix side effects:** Marking "custom" requires a rule→preset matcher; the presets are simple enough to compare field-by-field.
- **Discovered by:** A

#### F-WN-32-8  [P3] — The onboarding "Настроить позже" (skip) button permanently completes the onboarding

- **File:** `ui/web_new_v2/js/onboarding.js:234-235` (the skip/close handlers), `:161-172` (`finish(skip)`); backend at `core/api.py:2756-2760` and `:2828-2829`
- **Confirmed:** yes
- **Description:** `finish(true)` sends an **empty** payload to `complete_onboarding`. The backend treats an empty payload as "skip: keep every existing preference unchanged" but still writes `general.first_launch_done = True` and `personalization.onboarding_completed = True`. There is no other entry point that re-opens the onboarding wizard.
- **Cause:** The button label promises "configure later", but the persisted state means "never configured, and will not be offered again".
- **Trigger conditions:** Clicking "Настроить позже" or the ✕ on the wizard at any point.
- **User impact:** The user who deferred the setup is locked out of the wizard permanently; the theme / performance preset / crossfade / normalisation / autostart / tray choices made in later steps are discarded (`payload = {}` keeps every existing preference) even if the user had already clicked through steps 1–2 before pressing "later".
- **Evidence:**
  ```js
  // ui/web_new_v2/js/onboarding.js:234-235
  $('ob-btn-skip').addEventListener('click',()=>finish(true));
  $('ob-btn-close').addEventListener('click',()=>finish(true));
  ```
  ```js
  // ui/web_new_v2/js/onboarding.js:167-172
  const payload = skip ? {} : { theme: …, theme_mode: …, performance_preset: …, particles_enabled: …, audio_device: …, crossfade_enabled: …, volume_normalization: …, autostart: …, minimize_to_tray: … };
  ```
  ```python
  # core/api.py:2756-2760, 2828-2829
  """An empty payload means skip: keep every existing preference unchanged."""
  ...
  settings.set("general", "first_launch_done", True)
  settings.set("personalization", "onboarding_completed", True)
  ```
- **Reproduction / verification:** First launch → step through the wizard → press "Настроить позже". Quit and relaunch: the wizard never appears again; `get_settings()` shows `general.first_launch_done == true`.
- **Suggested fix:** Distinguish "deferred" from "completed" (e.g. persist the draft and re-offer the wizard on the next launch), or rename the button to match what it does.
- **Fix side effects:** The backend contract (`complete_onboarding` always sets the flags) is shared with other callers; changing it needs a coordinated change in `core/api.py` (WN-08 area).
- **Discovered by:** A

#### F-WN-32-9  [P3] — The onboarding "done" state lives in three localStorage keys *and* the DB, and the localStorage copy wins over the backend

- **File:** `ui/web_new_v2/js/onboarding.js:20-34` (`isComplete` / `localComplete` / `rememberCompletion`), `:56-59` (`startOnboarding` ordering), `:181-191` (the post-save write)
- **Confirmed:** yes (the divergence is structural); the exact trigger below is a hypothesis
- **Description:** `startOnboarding()` checks `localComplete()` **before** `isComplete(window.settings)`:
  ```js
  if (!wizard || localComplete()) return;
  if (isComplete(window.settings)) { rememberCompletion(); return; }
  ```
  `localComplete()` reads three localStorage keys (`aura_onboarding_done`, `nedotify_general_first_launch_done`, `nedotify_personalization_onboarding_completed`). If the localStorage copy says "done" while the DB says otherwise, the wizard is skipped permanently and the backend is never asked. Additionally `isComplete()` tests `settings?.onboarding_done === true` — a key the backend **never writes** (`complete_onboarding` only writes `general.first_launch_done` and `personalization.onboarding_completed`), so that clause is dead.
- **Cause:** Two independent sources of truth with a fixed precedence (localStorage wins), plus a third, never-populated key.
- **Trigger conditions (hypothesis):** The WebView2 user-data folder keeps its localStorage while the app's SQLite settings are reset/restored (settings reset via `core/settings.py`, a DB restore, or a fresh profile pointing at an existing DB). The localStorage still says "done", so the onboarding never reappears although the backend has `first_launch_done == false`.
- **User impact:** The onboarding wizard cannot be re-opened even though the backend considers it not done; the dead `settings.onboarding_done` clause suggests the author expected a third location that does not exist.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/onboarding.js:20-34
  function isComplete(settings) {
      return settings?.general?.first_launch_done === true || settings?.personalization?.onboarding_completed === true || settings?.onboarding_done === true;
  }
  function localComplete() {
      let legacy = false;
      try { legacy = localStorage.getItem('aura_onboarding_done') === 'true'; } catch {}
      return legacy || readStorage('nedotify_general_first_launch_done') === 'true' || readStorage('nedotify_personalization_onboarding_completed') === 'true';
  }
  function rememberCompletion() {
      try { localStorage.setItem('aura_onboarding_done', 'true'); } catch {}
      writeStorage('nedotify_general_first_launch_done', 'true');
      writeStorage('nedotify_personalization_onboarding_completed', 'true');
      try { localStorage.removeItem('nedotify_onboarding_draft'); } catch {}
  }
  ```
  ```js
  // ui/web_new_v2/js/onboarding.js:56-59  (localStorage is consulted first)
  const wizard = document.getElementById('onboarding-wizard');
  if (!wizard || localComplete()) return;
  if (isComplete(window.settings)) { rememberCompletion(); return; }
  ```
  Grep across `core/` and `services/`: `onboarding_done` appears **only** in `ui/web_new_v2/js/onboarding.js` — no Python side ever writes it.
- **Reproduction / verification:** Set `localStorage['nedotify_general_first_launch_done'] = 'true'` (or complete the onboarding once), then clear the DB setting `general.first_launch_done` to `false` (settings reset) and relaunch: the wizard does not appear and `get_settings()` still reports `first_launch_done == false`. For the dead clause: `grep -rn "onboarding_done" core/ services/` returns nothing.
- **Suggested fix:** Make the backend authoritative (`isComplete(window.settings)` first, `localComplete()` only as a fallback for the very first launch before the settings arrive), and drop the `settings.onboarding_done` clause.
- **Fix side effects:** If the backend is consulted first, the wizard may appear briefly on a slow settings load; `startOnboarding` already awaits `window.nedotifySettingsReady` and polls for 2 s, so the ordering can be swapped safely.
- **Discovered by:** A

#### F-WN-32-10  [P3] — `profile-comparison.js` calls the bridge without waiting for it, and a failed call leaves a permanent error state

- **File:** `ui/web_new_v2/js/profile-comparison.js:25-42`
- **Confirmed:** yes
- **Description:** `loadComparison()` calls `window.pywebview.api.get_listening_comparison(period, …)` directly — no `await window.awaitBridge()`, no `window.pywebview?.api?.` guard. If the bridge is not ready (or the API is missing) the expression throws a `TypeError`, which is caught and turned into the permanent message "Не удалось сравнить периоды прослушивания. Нажмите «Обновить», чтобы повторить.". The `<details>` panel auto-loads on `toggle`, so the failure can happen on the first open before the bridge is up.
- **Cause:** Inconsistent with the rest of the WN-32 files: `profile.js:11-19` wraps every call in a `request()` helper that awaits `window.awaitBridge()` and throws a clear "Profile method unavailable" error; `library.js` and `smart-playlists.js` also await the bridge.
- **Trigger conditions:** Opening the "Сравнить периоды прослушивания" panel before `window.pywebview.api` is available.
- **User impact:** The comparison panel shows an error instead of the data, and only a manual "Обновить" click (which will work by then) recovers. The period `<select>` change handler has the same exposure.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/profile-comparison.js:31-38
  try {
      const period = document.getElementById('profile-comparison-period').value;
      const data = await window.pywebview.api.get_listening_comparison(period, -new Date().getTimezoneOffset());
      if (current !== generation) return;
      if (!data?.current || !data?.previous || !data.delta || !Array.isArray(data.new_artists)) throw new Error('Invalid comparison');
      renderComparison(host, data);
  } catch {
      if (current === generation) host.textContent = 'Не удалось сравнить периоды прослушивания. Нажмите «Обновить», чтобы повторить.';
  }
  ```
  ```js
  // ui/web_new_v2/js/profile.js:11-19  (the pattern the rest of the area uses)
  async function request(name,...args) {
      await window.awaitBridge();
      const method=window.pywebview?.api?.[name];if(typeof method!=='function')throw new Error('Profile method unavailable');
      …
  }
  ```
- **Reproduction / verification:** Open the profile page before the WebView bridge is ready (or evaluate `delete window.pywebview` in devtools) and open the comparison `<details>`.
- **Suggested fix:** Reuse the `request()`-style guard (`await window.awaitBridge()` + `window.pywebview?.api?.get_listening_comparison`) and retry once the bridge is available.
- **Fix side effects:** None.
- **Discovered by:** A

#### F-WN-32-11  [P3] — Every completed download refreshes the library twice

- **File:** `ui/web_new_v2/js/library.js:962-964` and `ui/web_new_v2/js/events.js:258-264`
- **Confirmed:** yes
- **Description:** `events.js` handles the `download_complete` event by calling `loadDownloaded(); loadPlaylists(); window.refreshActiveLibraryView();` **and** dispatching `nedotify:track_downloaded`. `library.js` listens to `nedotify:track_downloaded` and calls `loadDownloaded()` → `refreshActiveLibraryView()` → another full refresh.
- **Cause:** The same "download finished" signal is handled in two places, and both paths converge on `refreshActiveLibraryView()`.
- **Trigger conditions:** Every `download_complete` event — i.e. once per finished track, so N times for a batch of N.
- **User impact:** Each refresh issues `get_favorites` + `get_downloaded_tracks` + the active collection's tracks over the bridge and re-renders the library. During a batch download this is 2× the necessary bridge traffic and DOM rebuilds. No wrong data is shown, but the library flickers/rebuilds twice per track.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/events.js:258-264
  case 'download_complete':
  case 'track_downloaded':
      loadDownloaded();
      loadPlaylists();
      if (window.refreshActiveLibraryView) window.refreshActiveLibraryView();
      document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
      break;
  ```
  ```js
  // ui/web_new_v2/js/library.js:962-964
  document.addEventListener('nedotify:track_downloaded', () => {
      loadDownloaded();
  });
  ```
  ```js
  // ui/web_new_v2/js/library.js:548-550
  export async function loadDownloaded() {
      refreshActiveLibraryView();
  }
  ```
- **Reproduction / verification:** Start a batch download of N tracks and count the `get_favorites` / `get_downloaded_tracks` bridge calls per `download_complete` (pywebview debug console or `core/api.py` logging): 2× per track.
- **Suggested fix:** Drop one of the two handlers (keep the `nedotify:track_downloaded` listener and remove the direct `loadDownloaded()` from `events.js`, or vice versa).
- **Fix side effects:** `events.js` is shared with WN-28; the two paths are not exactly equivalent (`loadDownloaded()` from events.js is the library.js export, `refreshActiveLibraryView` is the global) — removing one must keep the library in sync.
- **Discovered by:** A

#### F-WN-32-12  [P3] — Dead exports in `artist_profile.js`: the avatar resolver and the search-based track fetcher are never called

- **File:** `ui/web_new_v2/js/artist_profile.js:60-131` (`fetchArtistTracks`), `ui/web_new_v2/js/artist_profile.js:203-252` (`fetchArtistAvatarFromApi`)
- **Confirmed:** yes
- **Description:** Both functions are exported but have no call site anywhere in `ui/web_new_v2/` (verified by grep over all JS modules and `index.html`). `fetchArtistAvatarFromApi` was written to resolve an artist photo through `core/api.py::get_artists_avatars` (the endpoint `home.js` uses) but the artist profile never calls it; the profile's avatar comes only from `bridgeProfile.avatar_url`. `fetchArtistTracks` (a search-based track collector with a 5 s timeout) is likewise unused — the profile uses `bridgeProfile.tracks`.
- **Cause:** The refactor that moved the profile onto the bridge (`get_artist_profile`) left the old helpers in place; the comment at `artist_profile.js:203-208` still describes `fetchArtistAvatarFromApi` as the mechanism in use.
- **Trigger conditions:** Always — there is no path that reaches either function.
- **User impact:** An artist whose catalogue record carries no `avatar_url` always shows the silhouette placeholder, even though the backend could resolve one through `get_artists_avatars`; the code that would do it is present but unreachable.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/artist_profile.js:203-213
  // H-4: this used to map a few artist names to hardcoded YouTube thumbnails and
  // fall back to a stock concert photo, so profiles showed other people's faces.
  // It now asks the backend (core/api.py::get_artists_avatars, the same endpoint
  // home.js uses) and resolves null when there is nothing to show, which lets
  // ArtistPhotoComponent draw its silhouette placeholder.
  export async function fetchArtistAvatarFromApi(artistName, timeoutMs = 5000) { … }
  ```
  Grep result across `ui/web_new_v2/js/*.js` + `index.html`: the only hits for `fetchArtistAvatarFromApi` / `fetchArtistTracks` are their own definitions in `artist_profile.js`.
  And the profile renders the avatar from the bridge payload only:
  ```js
  // ui/web_new_v2/js/artist_profile.js:756-764
  artistData = { …, avatarUrl: bridgeProfile.avatar_url || null, … };
  ```
- **Reproduction / verification:** Open an artist profile for an artist without a catalogue avatar: the silhouette is drawn and `get_artists_avatars` is never called (no `artists_avatars_ready` event for that name).
- **Suggested fix:** Either call `fetchArtistAvatarFromApi()` when `bridgeProfile.avatar_url` is empty, or delete both dead exports.
- **Fix side effects:** Calling the avatar resolver adds one bridge round-trip per artist profile (it is cached by the backend for a week).
- **Discovered by:** A

---

### 3. Clean areas

**Bridge-method cross-check (STEP 4) — every method called from the WN-32 files exists in `core/api.py`.** All static and dynamic calls were extracted mechanically and matched against `AppApi`'s method list:

| Called from | Method | `core/api.py` | Result |
|---|---|---|---|
| library.js | `get_favorites`, `get_downloaded_tracks`, `get_playlist_tracks`, `get_smart_playlist_tracks`, `get_library` (dynamic, `selectSection`) | 2273 / 2277 / 2545 / 4214 / 2267 | all exist |
| library.js | `get_playlists`, `create_playlist`, `delete_playlist`, `add_to_playlist`, `export_playlist` | 2513 / 2498 / 2504 / 2517 / 2416 | all exist |
| library.js | `import_external_playlist`, `open_local_file`, `get_storage_info`, `download_all_favorites`, `cancel_batch_download` | 2362 / 3436 / 3034 / 3685 / 3730 | all exist |
| library.js | `play_track`, `play_pause` | 1437 / 1746 | all exist |
| library-view.js | `get_library`, `get_playlist_tracks`, `export_playlist`, `play_track`, `toggle_shuffle` | 2267 / 2545 / 2416 / 1437 / 2004 | all exist |
| smart-playlists.js | `get_smart_playlists`, `create_smart_playlist`, `update_smart_playlist` (dynamic), `delete_smart_playlist` | 4196 / 4199 / 4204 / 4209 | all exist |
| downloads-view.js | `get_downloads`, `pause_download`, `resume_download`, `retry_failed_downloads` (dynamic map) | 4176 / 4183 / 4186 / 4189 | all exist |
| lyrics.js | `get_lyrics`, `get_lyrics_translation`, `save_setting` | 3192 / 3286 / 2940 | all exist |
| artist_profile.js | `get_artist_profile`, `get_artists_avatars`, `get_library`, `search`, `play_track` | 3477 / 3515 / 2267 / 2077 / 1437 | all exist |
| profile.js | `get_profile_stats`, `get_playlists`, `get_wrapped_stats`, `get_playlist_tracks`, `get_favorites`, `play_track`, `save_setting`, `select_avatar`, `create_local_playlist` | 3388 / 2513 / 3156 / 2545 / 2273 / 1437 / 2940 / 3399 / 3420 | all exist |
| profile-comparison.js | `get_listening_comparison` | 4223 | exists |
| onboarding.js | `complete_onboarding`, `get_settings`, `import_external_playlist` | 2756 / 2922 / 2362 | all exist |

**Fields read by the JS that the Python side never sends — checked and clean.** `get_profile_stats` (`total_tracks`, `favorite_count`, `playlist_count`, `total_listening_time_ms`, `most_played`, `recently_played`), `get_wrapped_stats` (`total_plays`, `top_tracks[].plays`), `get_listening_comparison` (`current.{plays,seconds,tracks,top_artists[]}`, `previous.*`, `delta.{plays,seconds,tracks}.{absolute,percent}`, `new_artists[]`, `returning_artists[]`, `days`), `get_smart_playlist_tracks` (`tracks[]`), `get_downloads` rows (`track_id`, `status`, `title`, `artist`, `source`, `percent`, `downloaded_bytes`, `total_bytes`, `user_error.message`), `get_lyrics` payload (`syncedLyrics`, `plainLyrics`, `instrumental`, `status`, `source`, `match_type`, `phase`, `revision`, `request_id`), `get_artist_profile` payload (`name`, `genres`, `subscribers`, `avatar_url`, `bio`, `bio_ru`, `bio_original`, `albums[]`, `tracks[]`, `candidates[]`, `context`, `status`, `request_id`), `export_playlist` (`success`, `file_path`, `exported_count`), `download_all_favorites` (`success`, `count`, `message`), `create_smart_playlist`/`update_smart_playlist` (`success`, `playlist`) — every field the JS reads is present. No JS reads a field the backend never sends.

**All named ES imports resolve.** A mechanical check of every `import { … } from './…'` in the nine WN-32 files against the exported names of the target modules found **zero** missing exports.

**Download status string diff — EMPTY (6/6 on both sides).**

| Backend status | Emitted / stored in | JS `statusLabels` (`downloads-view.js:9-12`) | UI behaviour |
|---|---|---|---|
| `pending` | `core/downloader.py:125,137,409`; `core/download_store.py:62`; `core/database.py` `download_queue` DEFAULT | `pending: 'В очереди'` | pausable ✓, progress bar shown ✓ |
| `downloading` | `core/downloader.py:776-777,787` | `downloading: 'Скачивается'` | pausable ✓, progress bar shown ✓ |
| `paused` | `core/downloader.py:111,381,598` | `paused: 'На паузе'` | resumable ✓, progress bar shown ✓ |
| `completed` | `core/downloader.py:829,836,838` | `completed: 'Готово'` | no action, bar hidden (backend `percent` = 100 is computed but not shown — cosmetic only) |
| `failed` | `core/downloader.py:850,855,869,876,881` | `failed: 'Ошибка'` | `user_error.message` shown ✓, "Повторить ошибки" toolbar ✓ |
| `cancelled` | `core/downloader.py:278,282,284,564,572` | `cancelled: 'Отменено'` | no action ✓ |

No backend status is missing from `statusLabels` and no JS label refers to a status the backend never produces.

**`download_complete` carries no `file_path` — no JS reads one.** `core/downloader.py:839` emits `self._emit('download_complete', {'track_id': track_id})`. Neither `downloads-view.js` nor `library.js` reads `file_path` from that event; `library.js` re-reads the tracks from the DB via `get_downloaded_tracks()` instead. No silent-`undefined` defect.

**`download_progress` payload shape matches.** `core/downloader.py:157-169` emits `{downloaded_bytes, total_bytes, track_id, percent}`; `downloads-view.js:183-191` matches on `payload.track_id` and merges the payload into the cached row item. `percent` may legitimately be `null` (unknown `total_bytes`) and `updateDownloadRow` handles that (`Number.isFinite(null) === false` → `progress.removeAttribute('value')` → indeterminate bar). ✓

**Pause / resume / retry send the right identifier.** `downloads-view.js:146` reads `button.closest('[data-track-id]')?.dataset.trackId`, and the row writes `row.dataset.trackId = String(item.track_id)` (line 29). The backend compares `str(row['track_id']) == str(track_id)` (`core/downloader.py:103,119`), so the string↔int conversion is safe. The per-row action is `pause_download`/`resume_download` with a track id; the toolbar buttons map to the same methods **without** an id, which the backend interprets as "all" ✓. `retry-failed` maps to `retry_failed_downloads()` with no id ✓.

**Playlist deletion removes rows only, never files.** `core/api.py:2504` → `core/database.py:2018-2026` deletes `playlist_tracks` rows and the `playlists` row; no `os.remove` and no file deletion. The library's delete flow *does* ask for confirmation (`library.js:639-698`, `showDeletePlaylistModal`, focus trap starting on **Cancel** so a stray Enter cannot delete). ✓ No data-loss risk.

**Smart-playlist rule serialisation matches the parser — quoted both sides.**

```js
// ui/web_new_v2/js/smart-playlists.js:26-41
export function readSmartRule(values) {
    const rule = { sort: values.sort || 'newest' };
    for (const field of ['favorite', 'downloaded', 'unplayed']) {
        if (values[field] !== '' && values[field] != null) rule[field] = values[field] === 'true';
    }
    for (const field of ['added_within_days', 'not_played_days']) {
        if (String(values[field] || '').trim()) {
            const days = Number(values[field]);
            if (!Number.isInteger(days) || days < 1 || days > 3650) throw new Error('Период должен быть от 1 до 3650 дней');
            rule[field] = days;
        }
    }
    if (values.artist?.trim()) rule.artist = values.artist.trim();
    if (Object.keys(rule).length === 1) throw new Error('Выберите хотя бы одно правило');
    return rule;
}
```
```python
# services/smart_playlists.py:21-51
allowed = {"added_within_days", "not_played_days", "favorite", "downloaded", "unplayed", "artist", "sort"}
…
for field in ("added_within_days", "not_played_days"):
    if field in rule:
        value = rule[field]
        if type(value) is not int or not 1 <= value <= 3650: raise ValueError("Период должен быть от 1 до 3650 дней")
for field in ("favorite", "downloaded", "unplayed"):
    if field in rule:
        if type(rule[field]) is not bool: raise ValueError("Фильтры должны быть логическими значениями")
if "artist" in rule:
    artist = rule["artist"]
    if not isinstance(artist, str) or len(artist) > 160: raise ValueError("Имя исполнителя слишком длинное")
    if artist.strip(): normalized["artist"] = artist.strip()
sort = rule.get("sort", "newest")
if not isinstance(sort, str) or sort not in cls.SORTS: raise ValueError("Неизвестный порядок сортировки")
if not normalized: raise ValueError("Выберите хотя бы одно правило")
```
Same key set, same types (bool / int / str), same ranges (1…3650), same "at least one rule" rule, and every `sort` option offered by the UI (`newest|oldest|most_played|least_played|title`) is in `SORTS`. ✓

**Smart-playlist pagination offset is wired correctly.** `library.js:503-504` calls `get_smart_playlist_tracks(id, 201, 0)`; the "Показать ещё" button calls `get_smart_playlist_tracks(data.id, 201, offset)` with `offset` advancing by exactly the number of rows consumed (`library.js:525-539`). The backend validates `1 <= limit <= 500` and `0 <= offset <= 100000` (`services/smart_playlists.py:130-133`), both satisfied. The 201st row of each page is discarded but re-fetched as the first row of the next page — no row is skipped and none is shown twice. ✓

**Lyrics `request_id` is used correctly on both sides.** The JS generates `lyrics-${Date.now()}-${loadGen}` (`lyrics.js:823`), passes it as the 6th argument of `get_lyrics` (`lyrics.js:854`), and the backend echoes it verbatim: `rid = str(request_id or uuid.uuid4().hex)` and `payload = dict(data or {}, request_id=rid, …)` (`core/api.py:3195, 3206`). The listener discards mismatching ids (`lyrics.js:313-316`, and the guard inside `renderLyrics` at `lyrics.js:895-898`). The backend additionally has its own cascade guard (`cascade_no == self._lyrics_cascade_count`), so a superseded request never even publishes. ✓

**Lyrics `revision` / `phase` protocol matches.** `services/lyrics_lookup.py:296-297` increments `flight['revision']` and stamps `phase='final'|'partial'`; `core/api.py:3219` stamps the terminal payload with `revision=1, phase='final'`. The JS's `Number(data.revision || 0) <= lastLyricsRevision` guard drops out-of-order updates. ✓

**The karaoke highlight is driven by the audio clock, not a separate timer.** `player.js:580-618` is the `<audio>` element's `timeupdate` handler; it dispatches `nedotify:position_changed` with `pos` in **milliseconds** (`currentPosMs = Math.round(audio.currentTime * 1000)`) and `duration` in ms (`audioDurMs = Math.round(audio.duration * 1000)`). `lyrics.js:304-311` reads `posMs` and calls `updateLyricsPosition(posMs)`, which binary-searches the parsed LRC timestamps (`lyrics.js:1075-1090`) and applies `currentOffsetMs` — so there is no drift between the highlight and the audio. The Python `position_changed` path (every 5 s, `player.js:613-615` → `core/api.py:1423`) carries the same millisecond units (`events.js:110-127` normalises `pos`/`position_ms` → ms). ✓

**Auto-scroll does not fight the user's manual scroll.** The sheet is transform-driven; a wheel/drag gesture sets `lastManualScrollAt` and suspends the follow (`lyrics.js:371-374, 574-577, 674-678`), and a timer-driven `resumeAutoFollow()` re-anchors the sheet 4 s after the last gesture (`lyrics.js:680-690`) — deliberately timer-based so the follow also resumes while playback is paused and no position ticks arrive. The `lastManualScrollAt !== 0` sentinel guard prevents the "never browsed" case from being read as "browsing" for the first 4 s of the app's life. ✓

**Lyrics empty / not-found / error states are all present.** `renderLyrics(null)` → "Текст песни не найден"; a payload with `status === 'unavailable'` → "Не удалось загрузить текст: источники временно недоступны" plus a working "Повторить" button; `instrumental` → "Инструментальная версия — без текста"; plain (unsynced) lyrics → an informational notice "Текст оригинальной версии — без таймкодов" / "Текст не синхронизирован с треком". The offset buttons are disabled (with an explanatory tooltip) when there are no timestamps. ✓

**The lyrics `get_lyrics` call signature matches the backend exactly.** `lyrics.js:854` → `get_lyrics(track.title, track.artist, durMs, track.file_path, track.album || '', activeLyricsRequestId)`; `core/api.py:3192` → `get_lyrics(self, track_name, artist_name, duration_ms=0, file_path=None, album_name='', request_id=None)`. ✓

**Artist-profile avatar fallback is handled.** `ArtistPhotoComponent.render()` installs `img.onerror = () => { img.style.display='none'; showSilhouette(); }`, and a missing `avatar_url` draws the silhouette immediately — no broken-image icon. ✓ (The *availability* of an avatar is limited by F-WN-32-12.)

**Profile period selector and timezone are correct.** `#profile-top-period` offers `all|week|month|year`; `core/database.py:1723-1733` handles exactly those (any other value means "no filter", i.e. `all`). The comparison panel offers `week|month|year`, which is exactly `_DAYS` in `services/listening_comparison.py:6` (the backend raises `ValueError` for anything else). The offset sign is right: `new Date().getTimezoneOffset()` is minutes *behind* UTC, so `-getTimezoneOffset()` is the east-positive value the backend expects (its default is `180`, i.e. UTC+3), and it is used as `f'{offset:+d} minutes'` for SQLite's `date(played_at, ?)` modifier. ✓

**Profile empty-history state is present.** `profile.js:78` → "Вы ещё ничего не слушали" + "Новые прослушивания появятся здесь"; the top-tracks panel shows "За этот период прослушиваний пока нет" for a non-`all` period; the comparison panel has explicit "пока нет" placeholders for each artist list. ✓

**Onboarding payload is complete and correctly typed.** The JS sends `{theme, theme_mode, performance_preset, particles_enabled, audio_device, crossfade_enabled, volume_normalization, autostart, minimize_to_tray}`; `core/api.py:2763-2781` validates exactly these (booleans must be booleans; `theme` ∈ {dark,midnight,mint,light}; `theme_mode` ∈ {dark,light,system}; `performance_preset` ∈ {high,balanced,low}; `audio_device` a non-empty string ≤ 512 chars) and `core/api.py:2791-2799` maps every one of them onto a settings category. The UI's theme values (`dark|midnight|mint|light`), profile values (`low|balanced|high`) and the `audio_device` string all satisfy those constraints. ✓ The skip payload `{}` is explicitly supported by the backend.

**Onboarding playlist-URL validation is stricter than the backend's SSRF guard and correctly ordered.** `validatePlaylistUrl` requires `https:`, no embedded credentials, a whitelisted host, and a playlist-shaped path; the wizard blocks step 3 until it passes, and the import itself is performed by `api.import_external_playlist` (which applies its own SSRF check at `core/api.py:2364-2367`). The step order in `index.html` (1 Оформление / 2 Звук / 3 Медиатека / 4 Готово) matches the hard-coded `3` in `validLibrary()` and in the "next" handler. ✓

**`delete_playlist` in the library has a confirmation and a destructive-safe default focus.** `library.js:639-698` — the focus trap starts on **Cancel** (`openModalFocusTrap(modal, { initialFocus: '#modal-dpl-cancel' })`) so a stray Enter/Space cannot delete a playlist. ✓

---

### 4. Coverage gaps

- **The `library.js` / `library-view.js` "delete track" and "delete duplicate track" flows are not in this area.** `delete_duplicate_track` is only called from `ui/web_new_v2/js/settings.js:3327-3331` (WN-30) and `toggle_favorite` only from `ui/web_new_v2/js/utils.js:852-856` and `js/player.js` (WN-28/WN-29). The optimistic favourite toggle **does not roll back** when the backend call fails (`utils.js:852-856`: `try { await …toggle_favorite(track); } catch (err) {}` — the UI keeps the new state and the localStorage entry). That is a real defect, but it belongs to WN-28 (utils.js) / WN-29 (player.js), not to WN-32; it is reported here only as a cross-area pointer. F-WN-32-1 is the WN-32-owned consequence of that same optimistic write.
- **The library rows themselves (cover, duration, source badge, download button, ⋯ context menu) are built by `utils.js::createTrackElement`, which is WN-28.** Only the WN-32-specific decoration (`decorateLibraryRow`) was reviewed here.
- **No runtime execution.** The app was not launched (per the ground rules) and no browser/WebView session was used; every finding is derived from reading the source and from the Python sources it calls. The P2 findings F-WN-32-1, -2, -4, -6, -7 are deterministic from the code; F-WN-32-3's visible glitch and F-WN-32-9's divergence are code-path confirmed but their user-visible trigger is a hypothesis.
- **No automated test was run** for the WN-32 area; the repo's pytest suite was not executed (read-only review only).
- **Features the brief asked about that do not exist in this code base** (not defects, scope notes): the lyrics view has **no copy/share action** (no `navigator.clipboard` usage in `lyrics.js`; the only clipboard use in the UI is `utils.js:1286-1287` for track sharing and `settings.js:1824` for config export), and the artist profile has **no "similar artists" section** (no `similar`/`related` identifier anywhere in `artist_profile.js`).
- **`services/artist_service.py`'s deeper matching behaviour** (`credited_to`, `artist_aliases` usage inside the service) was read only at the level of the emitted payload shape; the WN-18 area owns its correctness.
- **`core/api.py::play_track` / `_resolve_track`** were traced only far enough to confirm that the artist profile's track ids (`"yt_<videoId>"`, a non-numeric string) do not break the resolution path (`core/api.py:1650-1658` guards the `int(t_id)` conversion with try/except). The full playback contract is WN-05 / WX-01 territory.
- **`utils/cache_manager.py` / the lyrics disk cache** were not reviewed; the WN-32 lyrics work only depends on the `revision`/`phase`/`request_id` contract, which was verified end-to-end.
