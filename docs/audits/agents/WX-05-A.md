# WX-05 — Search fan-out — ROLE A (Correctness & Reliability)

## SCENARIO WX-05 — Search fan-out — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read | Role in the scenario |
|---|---|---|
| `ui/web_new_v2/js/search.js` | 1–1250 (whole file) | UI entry point: query input, `runSearchQuery`, `onSearchResults`, dedup, result rendering |
| `ui/web_new_v2/js/utils.js` | 1–109, 610–807, 955–994 | `createTrackElement`, `getCoverUrl`, `formatTime`, `isSameTrack`, `getSourceIcon`, `filterVisibleTracks` |
| `ui/web_new_v2/js/events.js` | 110–169 | `search_results` / `search_completed` → `onSearchResults` dispatch |
| `ui/web_new_v2/index.html` | 360–399 | platform dropdown (source labels), type-filter buttons |
| `core/api.py` | 1–120, 340–538, 1122–1201, 2050–2380, 2545–2584, 3490–3530, 3640–3699, 4125–4164 | `AppApi.search`, `_emit`, `_search_executor`, `_search_lock`, `get_playlist_tracks` |
| `core/database.py` | 120–310, 1340–1469 | `tracks` schema, `search_tracks`, `search_albums`, `search_playlists`, `_like_pattern` |
| `core/app.py` | 85–240 | provider construction, lazy `soundcloud`/`yandex` properties, `_service_lock` |
| `core/offline.py` | 1–60 | `is_offline`, `available_tracks` |
| `services/base_service.py` | 1–329 (whole file) | `BaseMusicService.submit`, `_search_cache`, `_cache_lock`, `_join_request` |
| `services/youtube_service.py` | 120–569 | `YouTubeService.search` + cache key + result shape |
| `services/soundcloud_service.py` | 290–419 | `SoundCloudService.search` + cache key + result shape + executor |
| `services/spotify_service.py` | 1–244 (whole file) | `SpotifyService.search` + endpoint + cache key + result shape |
| `services/itunes_gateway.py` | 1–93 (whole file) | shared iTunes request queue / rate limiter / in-memory cache |
| `services/yandex_service.py` | 80–129 | `reset_client` cache eviction (lock usage) |
| `services/recommendation_service.py` | 55–84 | `reset_service` cache eviction (lock usage) |
| `utils/search_query.py` | 1–101 | suggestion helper (not on the main query path) |
| `tests/test_api_search.py` | 1–75 | existing pins for the bridge search contract |

**Callees traced into other areas (not owned by this scenario)**

- `core/database.py` — WN-12 (SQLite persistence): the `local` provider + `_like_pattern` + FTS5 index.
- `services/base_service.py` — WN-18 (service base class): `_search_cache`, `_cache_lock`, `_join_request`, `submit`.
- `services/youtube_service.py` / `soundcloud_service.py` — WN-19 / WN-20.
- `services/yandex_service.py` / `vk_service.py` / `spotify_service.py` / `lastfm_service.py` / `itunes_gateway.py` — WN-21.
- `ui/web_new_v2/js/search.js` / `js/utils.js` — WN-31 / WN-28.
- `core/api.py` search surface — WN-06.

**Verification method.** Nothing was modified in the repo. Three throwaway harnesses under
`%TEMP%\opencode\` (a TEMP SQLite DB, never `~/.nedotify/`):

- `wx05_verify.py` — real `AppApi` + fake providers → measured fan-out parallelism, provider
  isolation, per-provider deadline, LIKE escaping, cache TTL/LRU.
- `wx05_timer.py` — timestamped log of the per-provider timer lifecycle.
- `wx05_fts.py` — FTS5 path vs LIKE path side by side on the same rows.
- `wx05_ui_sim.js` — Node re-execution of the *verbatim* `js/search.js` playlist branch and
  `trackDedupKey` against the *verbatim* provider payload shapes.

---

### 2. Findings

#### F-WX-05-1  [P1] — The "Плейлисты" search tab fabricates playlist cards out of track results (SoundCloud + Spotify)

- **File:** `ui/web_new_v2/js/search.js:406-434` (primary owner: WN-31)
  plus `core/api.py:2219-2223` (contributing: WN-06) and `services/soundcloud_service.py:295` / `services/spotify_service.py:110,124`
- **Confirmed:** yes (empirically reproduced with Node, `wx05_ui_sim.js`)
- **Description:** With the type filter "Плейлисты" (`currentType === 'playlists'`) and source
  "Все площадки", the backend fans out to four providers with `result_type='playlists'`.
  Only `local` and `youtube` actually answer with playlist objects. **SoundCloud has no
  `result_type` parameter at all**, so the bridge's `except TypeError` fallback re-invokes it
  as a plain *track* search; **Spotify accepts `result_type` but only distinguishes
  `"albums"/"album"`**, so for `"playlists"` it runs the *track* search. Both therefore return
  track objects with **no `type` key**. The UI's playlist branch then converts *every
  non-playlist track* into a synthetic playlist card.
- **Cause:** The UI treats "anything without `type === 'playlist'`" as a playlist and invents the
  missing fields (`title` from the track title, `author` from the track artist,
  `track_count: 10` hard-coded). The provider contract is not enforced anywhere: the bridge
  sends `result_type` to providers that ignore it and the UI has no way to tell "playlist
  search that found no playlists" from "this provider returned tracks instead".
- **Trigger conditions:** Type filter "Плейлисты" + source "Все площадки" (the default source)
  + any query. Source "SoundCloud" or "Spotify" alone with the "Плейлисты" filter does the same.
- **User impact:** Up to ~40 bogus "playlist" cards appear, each titled with a *track* name and
  each claiming **"10 треков"** (a fabricated number). Clicking one calls
  `get_playlist_tracks(<track id>, 'soundcloud'|'spotify')` — a track id used as a set/album id —
  which fails, and the UI then silently re-runs a *search* for the track title
  (`js/search.js:842-846`).
- **Evidence:**
  ```js
  // ui/web_new_v2/js/search.js:406-427
  if (currentType === 'playlists') {
      const playlistMap = new Map();
      tracks.forEach((t, idx) => {
          if (t.type === 'playlist') { ... }
          else {
              const key = String(t.source_id || t.id || idx);
              if (!playlistMap.has(key)) {
                  playlistMap.set(key, {
                      id: t.id || `playlist_${idx}`,
                      title: t.title || 'Плейлист',
                      author: t.artist || t.author || 'NeDotify',
                      cover_url: t.cover_url || t.cover_path || '',
                      source: t.source || 'youtube',
                      source_id: t.source_id || '',
                      type: 'playlist',
                      track_count: t.track_count || 10     // <-- fabricated
                  });
              }
          }
      });
  ```
  ```python
  # core/api.py:2219-2223
  elif result_type:
      try:
          srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error)
      except TypeError:
          srv.search(query, callback=_on_success, error_callback=_on_error)
  ```
  ```python
  # services/soundcloud_service.py:295 — no result_type parameter at all
  def search(self, query: str, max_results: int = 20, callback: Callable = None, error_callback: Callable = None):
  ```
  ```python
  # services/spotify_service.py:124 — only albums are distinguished
  is_album_search = result_type in ("albums", "album")
  ```
  Reproduction (`node wx05_ui_sim.js`):
  ```
  cards rendered: 4
    type=playlist source=local      | title="Мой плейлист" author="Local"    | 12 треков
    type=playlist source=youtube    | title="YT Playlist"   author="Some Artist" | 40 треков
    type=playlist source=soundcloud | title="SC Song"       author="SC User"  | 10 треков
    type=playlist source=spotify    | title="SP Song"       author="SP Artist" | 10 треков
  ```
- **Reproduction / verification:** Run the app, search any term with source "Все площадки",
  click the "Плейлисты" filter. SoundCloud/Spotify tracks appear as playlist cards labelled
  "10 треков". Node reproduction of the exact branch: `%TEMP%\opencode\wx05_ui_sim.js`.
- **Suggested fix:** Do not synthesise playlist cards from non-playlist items. Either (a) the
  bridge must report which provider produced which payload type (e.g. an explicit
  `type` per item and a `playlist` result set per provider) and the UI must drop items whose
  `type` is not `playlist`, or (b) the bridge must not dispatch `result_type='playlists'` to
  providers that do not implement it (a per-provider capability table), so SoundCloud/Spotify
  are excluded from the playlist fan-out instead of returning tracks.
- **Fix side effects:** (b) changes the "Все площадки" provider set per type, which changes the
  `search_completed` accounting (`pending_providers`) and the UI's "ничего не найдено"
  behaviour. (a) requires a payload change in the `search_results` event and touches
  `js/artist_profile.js` (which also listens to `app:search_results`).
- **Discovered by:** A

#### F-WX-05-2  [P1] — The "Spotify" source is the iTunes Search API; the UI labels it Spotify

- **File:** `services/spotify_service.py:27-56` (primary owner: WN-21);
  labels in `ui/web_new_v2/index.html:379-383`, `ui/web_new_v2/js/search.js:178,49` (WN-28/WN-31)
- **Confirmed:** yes (code read; endpoint literal)
- **Description:** `SpotifyService` never talks to Spotify. Every search goes to
  `https://itunes.apple.com/search?term=…&entity=song&limit=…` (and `entity=album` for
  albums), i.e. the **Apple iTunes Search API**. The returned `source` string is nevertheless
  `"spotify"`, the UI platform dropdown shows the **Spotify logo** with
  `title="Spotify"`, the input placeholder becomes **"Поиск в Spotify..."**, and the results
  carry Apple artwork (`artworkUrl100` → `600x600bb`) and an `open.spotify.com/search/…`
  `source_url`. The album grid even labels these results **"iTunes"** — the app contradicts
  itself two screens apart.
- **Cause:** `SpotifyService` is a thin adapter over the iTunes catalogue that re-labels the
  results as Spotify so the rest of the app (badge, dedup, `source_id` routing) can treat it
  as a "Spotify" source. Nothing in the code or in `docs/` records the substitution
  (`grep -r "itunes.apple.com" docs/` → no hits).
- **Trigger conditions:** Any search with source "Spotify" (or "Все площадки").
- **User impact:** The user asks for Spotify and gets the Apple iTunes store: a completely
  different catalogue, Apple-only pricing/publisher metadata, Apple artwork, and links that
  point at `open.spotify.com/search/<term>` (a Spotify *search page*, not the track) even
  though the row is an iTunes row. The album view labels the same provider's rows
  "iTunes", so the UI shows two different names for one source.
- **Evidence:**
  ```python
  # services/spotify_service.py:30-32
  url = f"https://itunes.apple.com/search?term={encoded_query}&entity=song&limit={limit}"
  data = ITunesGateway.get(url, session=_session, timeout=3.5, is_current=is_current)
  ```
  ```python
  # services/spotify_service.py:42-52  (the tuple is labelled "spotify")
  results.append((
      f"spotify_{item.get('trackId', idx)}",
      title, artist, album, duration, cover_url,
      "spotify",
      f"ytsearch1: {artist} - {title}",
      item.get("trackViewUrl", f"https://open.spotify.com/search/{encoded_query}")
  ))
  ```
  ```html
  <!-- ui/web_new_v2/index.html:379-383 -->
  <button class="platform-item" data-source="spotify" title="Spotify" aria-label="Источник поиска: Spotify">
      <svg class="platform-svg" ... fill="#1DB954"> <!-- Spotify logo --> </svg>
  </button>
  ```
  ```js
  // ui/web_new_v2/js/search.js:532 — the album grid contradicts the badge
  const sourceLabel = album.source === 'local' ? 'Из библиотеки' : (album.source === 'youtube' ? 'YouTube Music' : 'iTunes');
  ```
- **Reproduction / verification:** `services/spotify_service.py:31` — `url` is a literal
  `itunes.apple.com` URL. Node check of the album label:
  `album grid source label for source="spotify": iTunes`.
- **Suggested fix:** Either (a) make the UI honest (rename the source to "iTunes / Apple Music"
  in the dropdown, the placeholder, the badge and the album label), or (b) implement the real
  Spotify Web API (OAuth) so the label is true. Pick one and make `source`/labels/URLs agree.
- **Fix side effects:** (a) touches `index.html`, `js/search.js` (label + `PLATFORM_SVGS`),
  `js/utils.js::getSourceIcon` and the CSS `source-<name>` badge classes; the `source` string
  `"spotify"` is persisted in `tracks.source` in the DB and is used by
  `core/downloader.py:476-484` to route `ytsearch1:` ids, so renaming the `source` value
  would orphan existing rows. (b) needs a Spotify app registration and a token store.
- **Discovered by:** A

#### F-WX-05-3  [P2] — The Spotify `source_id` is not an identifier: distinct iTunes tracks collapse into one and match the wrong "now playing" row

- **File:** `services/spotify_service.py:50` (primary owner: WN-21);
  consumed by `ui/web_new_v2/js/search.js:320-328` and `ui/web_new_v2/js/utils.js:659-673` (WN-31/WN-28)
- **Confirmed:** yes (Node reproduction)
- **Description:** The Spotify `source_id` is the string `ytsearch1: {artist} - {title}` — a
  *YouTube search expression*, not a track id. Two different iTunes tracks by the same artist
  with the same title (a remix, a live version, the same song on two albums) therefore get the
  **same** `source_id`. The UI's dedup key is `source::source_id`, so one of them silently
  disappears from the result list, and `isSameTrack()` (used for the "now playing" highlight)
  matches the wrong row.
- **Cause:** `source_id` was chosen to make the *downloader* able to re-resolve the track on
  YouTube (`core/downloader.py:476-484` explicitly handles `source_id.startswith('ytsearch')`),
  but `source_id` is also used as the *primary identity* of a search result. The real iTunes
  id (`trackId`) is only stored in the separate `id` field (`spotify_<trackId>`), which the
  dedup key only uses as a *fallback* (`t.source_id || t.id`).
- **Trigger conditions:** Any Spotify/iTunes search that returns two rows with the same
  artist + title. Very common: "Intro", "Outro", "Theme", or a song released on several
  albums/EPs.
- **User impact:** A result disappears from the list without any indication; clicking the
  surviving row can highlight/download the wrong recording; the badge/downloaded state of the
  dropped row is lost.
- **Evidence:**
  ```python
  # services/spotify_service.py:43-51
  f"spotify_{item.get('trackId', idx)}",        # id  -> the real iTunes id
  ...
  f"ytsearch1: {artist} - {title}",             # source_id -> NOT an id
  ```
  ```js
  // ui/web_new_v2/js/search.js:320-328
  function trackDedupKey(t) {
      const src = String(t.source || '').toLowerCase().trim();
      const sid = String(t.source_id || t.id || '').trim();
      if (src && sid) return `${src}::${sid}`;     // source_id wins over the real id
      ...
  }
  ```
  Node reproduction:
  ```
  dedup key spA: spotify::ytsearch1: A - Intro
  dedup key spB: spotify::ytsearch1: A - Intro
  two DIFFERENT iTunes tracks collapse in the UI list: true
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx05_ui_sim.js`; or search a title that
  exists twice on iTunes (e.g. an "Intro") with source "Spotify".
- **Suggested fix:** Keep the resolvable expression in a *separate* field (e.g.
  `resolve_hint` / `ytsearch_query`) and let `source_id` carry the stable id
  (`spotify_<trackId>` / the iTunes `trackId`). If `source_id` must stay a `ytsearch` string
  for the downloader, the UI dedup key must use `id` first and `source_id` only as a fallback.
- **Fix side effects:** `source_id` is persisted in `tracks.source_id` by
  `core/api.py::download_track` and is the key the downloader routes on
  (`core/downloader.py:476-484`); changing it requires a matching change there and a
  migration or re-keying of already-downloaded rows. `services/catalog_service.py:208` builds
  the same `ytsearch1:` id and would have to change in lock-step.
- **Discovered by:** A

#### F-WX-05-4  [P3] — The UI dedups by `source::source_id`, so the same song is listed up to three times (once per source)

- **File:** `ui/web_new_v2/js/search.js:320-328,366-381` (owner: WN-31)
- **Confirmed:** yes (Node reproduction)
- **Description:** `trackDedupKey` only falls back to `title+artist+duration` when `source`
  **or** `source_id` is missing. All four providers always supply both, so the
  title/artist fallback is unreachable and the same recording found on YouTube, SoundCloud
  and iTunes yields three separate cards.
- **Cause:** The dedup key is provider-scoped by design (the source badge is part of the
  card), but the fallback branch is dead code, so there is no second line of defence.
- **Trigger conditions:** Any "Все площадки" search where the same song exists on more than
  one provider — the normal case.
- **User impact:** The result list is padded with duplicates of the same song under three
  different badges (YouTube / SoundCloud / a music-note icon for "Spotify"). Given
  F-WX-05-2 the third badge is iTunes data, so the user sees one song three times with two
  different cover artworks.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/search.js:320-328
  const src = String(t.source || '').toLowerCase().trim();
  const sid = String(t.source_id || t.id || '').trim();
  if (src && sid) return `${src}::${sid}`;
  const title = ...; const artist = ...; const dur = ...;
  return `fallback::${title}__${artist}__${dur}`;     // unreachable for the 4 providers
  ```
  Node reproduction:
  ```
  cross-provider dedup keys:
     youtube::vid1
     soundcloud::777
     spotify::ytsearch1: Artist - Song
    => same song shown 3 times
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx05_ui_sim.js`; or search a mainstream
  song with source "Все площадки" and count the repeated title.
- **Suggested fix:** If cross-source duplicates are unwanted, add a second pass that collapses
  `title+artist` (with a duration tolerance) across sources and keeps a "also on: …" marker.
  If they are wanted, the dead fallback branch should be removed or the key should be
  documented as provider-scoped.
- **Fix side effects:** Cross-source collapsing would hide the ability to pick a specific
  provider's copy (and would break `isSameTrack`'s currently-consistent behaviour of
  matching on `source_id`).
- **Discovered by:** A

#### F-WX-05-5  [P3] — The FTS5 prefix path runs first and defeats the wildcard escaping of `_like_pattern`

- **File:** `core/database.py:1366-1404` together with `core/database.py:1350-1364` (owner: WN-12)
- **Confirmed:** yes (reproduced side by side on the same rows, `wx05_fts.py`)
- **Description:** `_like_pattern` exists to stop the user from owning the LIKE wildcards —
  its own docstring says *"Without this … 'AC_DC' matched every 'AC/DC' row and '100%' matched
  the whole library"*. But `search_tracks` tries the FTS5 index **first** and returns its rows
  when there is at least one, so the escaped LIKE is never reached. FTS5 tokenises
  `AC_DC` into `AC`/`DC` and `100%` into `100`, and prefix-matches each token, so the
  wildcard is silently ignored and *more* rows come back than the LIKE path would return.
- **Cause:** Two search strategies with different semantics are chained with "FTS wins if it
  returns anything". The FTS path has no notion of "the user's `_` is a literal `_`".
- **Trigger conditions:** The shipped configuration (`_fts_available == True`). Any query
  containing a non-alphanumeric character that FTS splits on (`_`, `%`, `/`, `.`, `-`).
- **User impact:** Searching `100%` also returns "100x Pure"; searching `AC_DC` also returns
  "AC/DC Tribute" — a *different song*. The user gets false positives in the "Все площадки"
  list, mixed with the (correct) provider results.
- **Evidence:**
  ```python
  # core/database.py:1368-1391
  if getattr(self, "_fts_available", False) and query.strip():
      try:
          terms = " ".join('"' + w.replace('"', '""') + '"*' for w in query.split() if w)
          ...
          rows = cursor.fetchall()
          if rows:
              return [dict(row) for row in rows]     # <-- LIKE never runs
  ```
  ```python
  # core/database.py:1350-1364
  """Build a LIKE pattern whose wildcards are literal.
  Without this the user owns the wildcards: "AC_DC" matched every
  "AC/DC" row and "100%" matched the whole library."""
  ```
  Reproduction (same DB, same rows):
  ```
  FTS available: True
  query='AC_DC'  -> ['AC/DC Tribute', 'AC_DC Live']
  query='100%'   -> ['100% Pure', '100x Pure']
  --- LIKE path only (FTS disabled) ---
  query='AC_DC'  -> ['AC_DC Live']
  query='100%'   -> ['100% Pure']
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx05_fts.py` (FTS on vs FTS off).
- **Suggested fix:** Make the two paths agree — either escape/strip the non-token characters
  before building the FTS terms (or fall back to LIKE when the query contains a character
  FTS drops), or run LIKE for queries that contain LIKE/FTS metacharacters.
- **Fix side effects:** Falling back to LIKE for such queries loses the FTS speed-up exactly
  for the queries that are currently the most over-broad; FTS is the reason the local search
  is fast on a large library.
- **Discovered by:** A

#### F-WX-05-6  [P3] — `BaseMusicService.clear_search_cache()` is dead code: the 5-minute TTL is the only invalidation of the whole search cache

- **File:** `services/base_service.py:272-276` (owner: WN-18)
- **Confirmed:** yes (`grep -rn "clear_search_cache" --include=*.py` → only the definition)
- **Description:** The class offers one API to drop the whole search cache, and nothing in
  the app calls it. The only invalidation paths are the 300 s TTL
  (`_SEARCH_CACHE_TTL`) and the 300-entry LRU cap. The two partial eviction helpers
  (`YandexService.reset_client`, `RecommendationService.reset_service`) only remove their own
  key prefixes, and `reset_client` is reachable only from `core/api.py:1933`.
- **Cause:** No invalidation hook is wired to the events that would make the cache stale
  (proxy/cookie change, provider re-auth, offline-mode toggle, library edit).
- **Trigger conditions:** The user changes `auth.proxy_url`, the cookies file or the browser
  cookies in Settings, or the provider's credentials change, and then searches again inside
  the 5-minute window.
- **User impact:** Up to 5 minutes of search results produced under the *old* network
  configuration (e.g. results fetched through a proxy that has since been removed, or an
  empty result set cached while the provider was unreachable) are served to the user.
- **Evidence:**
  ```python
  # services/base_service.py:272-276
  @classmethod
  def clear_search_cache(cls) -> None:
      """Clear all search cache entries."""
      with cls._cache_lock:
          cls._search_cache.clear()
  ```
  ```
  grep -rn "clear_search_cache" --include=*.py .
  services/base_service.py:273:    def clear_search_cache(cls) -> None:
  (no call sites)
  ```
- **Reproduction / verification:** `grep -rn "clear_search_cache" --include=*.py` over the repo.
- **Suggested fix:** Call `clear_search_cache()` from the settings path that changes the
  network/auth configuration (and from `set_offline_mode`, which changes the provider set).
- **Fix side effects:** The cache is class-level and shared by YouTube/SoundCloud/Spotify/
  Yandex/VK/iTunes/Recommendation, so clearing it also drops the recommendations cache
  (`recommendation:*` keys) and the related-tracks cache; that is a latency cost, not a
  correctness one.
- **Discovered by:** A

#### F-WX-05-7  [P3] — `except TypeError` around the provider call turns an internal `TypeError` into a second, duplicate search

- **File:** `core/api.py:2219-2223` (owner: WN-06)
- **Confirmed:** yes (code read; not currently reachable with the shipped providers)
- **Description:** The `TypeError` handler exists to cope with providers whose `search()`
  does not accept `result_type` (this is what turns F-WX-05-1 on). But it also catches a
  `TypeError` raised *inside* the provider's own body, in which case the bridge **calls the
  provider a second time**, with `result_type` silently dropped.
- **Cause:** Signature mismatch and internal failure are signalled by the same exception type,
  and the fallback re-issues the request instead of distinguishing the two.
- **Trigger conditions:** A provider whose `search()` body raises `TypeError` before it
  installs its own `except Exception` handler. None of the three shipped providers does this
  today (YouTube wraps its body in `except Exception`, SoundCloud/Spotify submit to their own
  executors), so this is latent.
- **User impact:** A doubled network request for one keystroke, and the second request runs
  with a *different* (default) result type than the user asked for; the first attempt's error
  message is swallowed.
- **Evidence:**
  ```python
  # core/api.py:2219-2223
  elif result_type:
      try:
          srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error)
      except TypeError:
          srv.search(query, callback=_on_success, error_callback=_on_error)
  ```
  Compare with the correct pattern used two methods above for the artist profile:
  ```python
  # core/api.py:3509-3512
  try:
      svc.get_profile(name, callback=ok, error_callback=fail, artist_ref=artist_ref, is_current=current)
  except TypeError:
      svc.get_profile(name, callback=ok, error_callback=fail)
  ```
  (same weakness, but `get_profile` is not on the search hot path)
- **Reproduction / verification:** Static read of `core/api.py:2219-2223`; reachable only with
  a provider that raises `TypeError` internally.
- **Suggested fix:** Inspect the signature instead of catching the exception (e.g.
  `inspect.signature(srv.search).parameters`), or catch `TypeError` only around the *call
  binding* by using a keyword-argument dict built from the accepted parameters.
- **Fix side effects:** Signature inspection costs a little per search and needs a fallback
  for C/extension callables; a per-provider capability table (see F-WX-05-1) removes the need
  for the `except TypeError` entirely.
- **Discovered by:** A

#### F-WX-05-8  [P3] — `AppApi.search` has no total budget: the completion sentinel waits for the slowest provider's deadline (up to 8 s), and a timed-out provider keeps working

- **File:** `core/api.py:2119-2129,2197-2208,2226-2230` (owner: WN-06)
- **Confirmed:** yes (measured, `wx05_verify.py`)
- **Description:** There is a **per-provider** deadline (`PROVIDER_SEARCH_TIMEOUT = 6.0`,
  8.0 s for SoundCloud) but **no total budget** for the search. `search_completed` is emitted
  only when the last provider in `pending_providers` has reported, so the completion event —
  and therefore the UI's "Ничего не найдено" / spinner termination — waits for the slowest
  provider even when the other three answered in 200 ms. The per-provider timer also does
  **not** cancel the provider's own work: `timer.cancel()` only stops the timer; the provider
  thread, its HTTP request and its provider-local executor slot keep running until they
  finish, and the answer is then discarded.
- **Cause:** The deadline is modelled per provider instead of per search; the two are
  conflated because the fan-out happens to be parallel.
- **Trigger conditions:** SoundCloud is slow (its first query also scrapes a `client_id`) or
  simply unreachable: the "Ничего не найдено" state then appears ~8 s after the keystroke
  even if YouTube already answered. Also: a provider that never calls *either* callback is
  only stopped by this timer — which is the timer working as designed, but it also means the
  provider's thread leaks for the duration of the request.
- **User impact:** The empty state and the correction banner ("Ничего не найдено. Попробуйте
  другую раскладку…", `js/search.js:1046-1073`) are delayed by up to 8 s. The provider
  threads are not released on timeout.
- **Evidence:**
  ```python
  # core/api.py:2196-2208
  # SoundCloud's first query includes discovery of its public key.
  _timeout = 8.0 if name == "soundcloud" else PROVIDER_SEARCH_TIMEOUT
  def _on_timeout():
      with lock:
          if is_done[0]: return
      logger.warning("%s search timed out after %.1fs", name, _timeout)
      _finish([])
  timer = threading.Timer(_timeout, _on_timeout)
  timer.daemon = True
  timer.start()
  ```
  ```python
  # core/api.py:2123-2129 — completion waits for ALL providers
  def mark_done(provider_name):
      with pending_lock:
          pending_providers.discard(provider_name)
          if not pending_providers and not completion_emitted[0]:
              completion_emitted[0] = True
              if is_current(): self._emit("search_completed", {"query": query, "source": source})
  ```
  Measurement (one provider hanging, three answering in 0.2 s):
  ```
  C) PER-PROVIDER TIMEOUT (hanging provider)
    search_completed after     : 6.017 s
    chunks                     : [('local', 0), ('youtube', 1), ('soundcloud', 1), ('spotify', 0)]
  ```
  And with a provider that raises without calling any callback (the timer as the only
  backstop): `soundcloud search timed out after 8.0s`.
- **Reproduction / verification:** `%TEMP%\opencode\wx05_verify.py`, sections A–C.
- **Suggested fix:** Add a total search deadline (the fan-out is parallel, so it can be
  `max(provider deadlines)` or an explicit smaller value) and emit `search_completed` when
  it expires, marking the unfinished providers as timed out. A per-provider status in the
  `search_completed` payload would also let the UI say *which* source failed.
- **Fix side effects:** A total deadline shorter than SoundCloud's 8 s would cut SoundCloud
  results on a cold start (its `client_id` scrape is the documented reason for the 8 s
  budget — `STATUS.md:187`); the safe form is `max(per-provider)` plus an *early*
  completion when every provider has answered (which is what `mark_done` already does).
- **Discovered by:** A

#### F-WX-05-9  [P3] — `AppApi.search` returns a constant empty stub; there is no `results` key and no `sources` map

- **File:** `core/api.py:2087-2088,2135,2232` (owner: WN-06); consumed by
  `ui/web_new_v2/js/search.js:1083`, `js/search.js:845`, `js/artist_profile.js:118` (WN-31/WN-32)
- **Confirmed:** yes
- **Description:** The bridge method returns `{"query": <q>, "tracks": []}` — the `tracks`
  list is **always empty**, on every path (empty query, disabled providers, normal fan-out).
  The results are delivered exclusively through the `search_results` event, one chunk per
  provider. There is no `results` key and no per-source map in the return value.
- **Cause:** The method was converted to the asynchronous event protocol but the return value
  was left as a placeholder instead of being removed or made meaningful.
- **Trigger conditions:** Any caller that awaits the promise and reads the result. All three
  current JS callers ignore the value, so there is no user-visible symptom today.
- **User impact:** None today; the risk is that any future caller (a plugin, a new UI view, an
  automation script) reads `tracks` and silently gets an empty result set — the exact
  "silent failure" class the project explicitly warns about in `AGENTS.md`.
- **Evidence:**
  ```python
  # core/api.py:2232
  return {"query": query, "tracks": []}
  # core/api.py:2087-2088
  if not query:
      return {"query": query, "tracks": []}
  # core/api.py:2131-2135 (disabled providers)
  self._emit("search_completed", {"query": query, "source": source})
  return {"query": query, "tracks": []}
  ```
  ```js
  // ui/web_new_v2/js/search.js:1083 — the value is discarded
  Promise.resolve().then(()=>api('search',query,source,type==='all'?null:type)).catch(()=>{...});
  ```
  Existing pin: `tests/test_api_search.py:19` asserts `res == {"query": "hello", "tracks": []}`.
- **Reproduction / verification:** `wx05_verify.py` prints the return value of two searches:
  `bridge return value : {'query': 'q2', 'tracks': []}`.
- **Suggested fix:** Either return the accepted/rejected status (e.g.
  `{"query": q, "accepted": True, "generation": n}`) or drop the method's result and make the
  event the only channel (documented). Do not leave a `tracks` key that is always empty.
- **Fix side effects:** `tests/test_api_search.py:19,32` assert the current shape and would
  have to be updated.
- **Discovered by:** A

---

### 3. Clean areas

- **The fan-out is genuinely PARALLEL** — this corrects/confirm the previous reviewer's
  measurement. Measured (`wx05_verify.py` section A, three providers each sleeping 1.0 s):
  the bridge returned after **0.001 s**, all three providers started at `t=0.001` and
  finished at `t=1.002`, and `search_completed` was emitted at **1.021 s** — i.e. *max* of
  the provider latencies, not the sum. The mechanism is
  `self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")`
  (`core/api.py:363`) with one `submit` per provider (`core/api.py:2161,2230`). Because the
  provider services' own `search()` methods are themselves asynchronous (they submit to their
  own pools), the six `SearchWorker` slots are held only briefly, so pool contention between
  concurrent searches is negligible (YouTube 10 workers, SoundCloud 10, Spotify 5).
- **Exception isolation works.** A provider that raises is contained: the other providers'
  results are still delivered, `search_completed` is still emitted exactly once, and the user
  sees a **partial result set with no error message** (measured: chunks
  `[('local',0),('youtube',1),('spotify',1),('soundcloud',0)]`, `search_completed` count = 1).
  The bridge's per-provider timer is also a correct backstop for a provider that calls
  *neither* callback — it fires and emits an empty chunk for that provider
  (`soundcloud search timed out after 8.0s`).
- **Stale-result suppression works.** `self._search_generation` + `is_current()` drops the
  results of a superseded search; `tests/test_api_search.py:46-75` pins that only the newest
  query reaches the providers and that only one `search_completed` is emitted.
- **The search cache lock is NOT held across the network call.** `get_search_cache` /
  `set_search_cache` (`services/base_service.py:243-270`) open `cls._cache_lock` only around
  the dict operations; the provider's HTTP call happens in the provider's own executor
  thread, outside every `BaseMusicService` lock. `_join_request`
  (`services/base_service.py:140-161`) pops the listener list under the lock and then invokes
  the callbacks **outside** it. The class-level `_cache_lock` is an `RLock` shared by all
  services, and every critical section is a pure dict operation, so it does **not** serialise
  provider requests. `ITunesGateway` builds its `Condition` on the same lock
  (`services/itunes_gateway.py:15`) and also performs its HTTP request outside it
  (`services/itunes_gateway.py:64`).
- **The cache key is complete for each provider's own parameters**, the TTL is applied and
  the expired entry is purged, and the LRU eviction is real:
  - YouTube `f'yt_search:{query}:{yt_filter}:{max_results}'` (`services/youtube_service.py:382`)
  - SoundCloud `f'sc_search:{query}:{max_results}'` (`services/soundcloud_service.py:298`)
  - Spotify `f'spotify_search:{query}:{result_type}:{limit}'` (`services/spotify_service.py:111`)
  Measured: TTL 300 s honoured (an entry stamped 400 s ago reads back as `None` and is
  removed), `_SEARCH_CACHE_MAX_SIZE = 300`, `_cache_recent` keeps insertion order == LRU
  order (`services/base_service.py:223-241`).
- **Query boundaries.** An empty/whitespace-only query is short-circuited in the bridge
  (`core/api.py:2084-2088`, `tests/test_api_search.py:31-33`); a single character works
  (FTS prefix match); Cyrillic works (UTF-8 `quote()` in the providers, FTS/LIKE in SQLite);
  a 500-character query is accepted and simply matches nothing; a quote-only query (`"""`)
  makes FTS5 throw and the `except Exception: pass` at `core/database.py:1390-1391` falls
  back to LIKE — no crash. `%` and `_` are escaped by `_like_pattern`
  (`core/database.py:1358-1363`: `'100%' -> '%100\\%%'`, `'AC_DC' -> '%AC\\_DC%'`) and the
  LIKE clauses all declare `ESCAPE '\'`, so there is no wildcard injection and no SQL
  injection (the FTS path builds a quoted, escaped token list).
- **The result payloads are normalised to one *enough* shape.** Every provider supplies
  `title`, `artist`, `source`, `source_id` and `duration`; every provider supplies a cover
  (`cover_url`, and `cover_path` for local rows). The UI reads exactly these plus
  `is_favorite`, `is_downloaded`, `id` and `type`, and every one of those is either supplied
  or safely defaulted (`formatTime(undefined) -> "0:00"`, `track.title || 'Unknown'`,
  `track.artist || 'Unknown'`, `track.is_downloaded || track.source === 'local'`). **No card
  renders the literal text "undefined"** — I found no field the UI renders unguarded that a
  provider can leave `undefined`. The two *missing* fields (`is_favorite` for YouTube /
  SoundCloud, `is_downloaded` for all three remote providers) are used only as booleans, so
  they degrade to "not liked" / "not downloaded", which is correct for a remote result.
- **`_emit` never runs on the UI thread**: `core/api.py:1147-1154` detects the main thread
  and hands the `evaluate_js` to an `EmitWorker` thread. The search fan-out emits from
  `SearchWorker` threads anyway.
- **The lazy-provider construction is off the bridge thread** — `srv = getattr(self._core, name, None)`
  is executed inside `_run_provider` (a pool worker), so `AppCore.soundcloud`'s lazy
  `SoundCloudService` construction (and its `client_id` warm-up) never blocks the JS promise.
  `tests/test_api_search.py:46-75` pins this.
- **The offline path is coherent**: offline mode forces `source='local'`
  (`core/api.py:2085-2086`) and the local results are filtered by
  `available_tracks` so only playable rows are returned.

### 3.1 Reference tables (measured / read from source)

**Provider list and order** (`core/api.py:2098-2106`)

| `source` argument | `requested_providers` | providers actually reachable | per-provider deadline |
|---|---|---|---|
| `"all"` (default) | `["local","youtube","soundcloud","spotify"]` | local (SQLite), YouTube (ytmusicapi), SoundCloud (api-v2 / yt-dlp), "Spotify" (= iTunes) | local: none (SQLite), YouTube 6.0 s, SoundCloud 8.0 s, Spotify 6.0 s |
| `"local"` | `["local"]` | SQLite only; run **synchronously on the bridge thread** | none |
| `"yandex"`, `"vk"`, `"vkontakte"`, `"zeno"` | `[]` | none — `search_completed` is emitted immediately | — |
| anything else | `[source]` | that one provider | 6.0 s (8.0 s for `soundcloud`) |

The list order is the *submission* order only; the fan-out is parallel, so the **result order
in the UI is the provider arrival order**, not the list order (the local rows usually land
first because SQLite is instantaneous).

**Result cap per provider**

| provider | cap | where |
|---|---|---|
| local | 50 | `db.search_tracks(query)` → `limit: int = 50` (`core/database.py:1366`) |
| YouTube | 20 | `max_results=20` default → `self._ytmusic.search(..., limit=max_results)` (`services/youtube_service.py:370,403`) |
| SoundCloud | 20 | `max_results=20` default → `…&limit={max_results}` (`services/soundcloud_service.py:295,321`) |
| Spotify (iTunes) | 20 | `limit: int = 20` default → `…&limit={limit}` (`services/spotify_service.py:110,31`) |

Worst case per search: 50 + 20 + 20 + 20 = **110 rows** before the UI dedups.

**Field matrix — provider payload vs. what the UI reads**

| field the UI reads (`js/utils.js:createTrackElement`, `js/search.js:renderResults`) | local (`SELECT * FROM tracks`) | YouTube | SoundCloud | "Spotify" (iTunes) |
|---|---|---|---|---|
| `title` | ✔ | ✔ | ✔ | ✔ |
| `artist` | ✔ | ✔ | ✔ | ✔ |
| `duration` | ✔ (REAL s) | ✔ (parsed `m:ss`) | ✔ (ms/1000) | ✔ (`trackTimeMillis/1000`) |
| `source` | ✔ | ✔ `"youtube"` | ✔ `"soundcloud"` | ✔ `"spotify"` |
| `source_id` | ✔ | ✔ (videoId) | ✔ (track id) | ⚠ `ytsearch1: A - T` (F-WX-05-3) |
| `id` | ✔ (int rowid) | ✖ | ✖ | ✔ `spotify_<trackId>` |
| `cover_url` | ✔ | ✔ | ✔ | ✔ (Apple artwork) |
| `cover_path` | ✔ | ✖ | ✖ | ✖ |
| `album` | ✔ | ✔ | ✖ | ✔ |
| `is_favorite` | ✔ | ✖ | ✖ | ✔ (`False`) |
| `is_downloaded` | ✔ (ALTER column) | ✖ | ✖ | ✖ |
| `type` | ✔ albums/playlists | ✔ albums/playlists | ✖ | ✔ albums only |
| `track_count` | ✔ albums/playlists | ✔ albums/playlists | ✖ | ✔ albums only |
| `year` | ✔ albums | ✔ albums | ✖ | ✔ albums |
| `source_url` | ✔ | ✖ | ✔ | ✔ |
| `waveform_url` | ✖ | ✖ | ✔ (never read by the UI) | ✖ |
| `og_image` / `artwork_url` (UI fallbacks in `getCoverUrl`) | ✖ | ✖ | ✖ | ✖ |

`source`-specific extras: `local` albums → `type:'album'`, `source:'local'`;
`local` playlists → `type:'playlist'`, `author:'Local'`;
YouTube playlists → `type:'playlist'`, `author`, `track_count` but **no `id`**
(`js/search.js:761` writes `card.dataset.id = pl.id || ''` → empty).

**Cache key analysis**

| provider | key | query | result type | limit | TTL | invalidation |
|---|---|---|---|---|---|---|
| YouTube | `yt_search:{query}:{yt_filter}:{max_results}` | ✔ | ✔ (`playlists`/`albums`/`None`) | ✔ | 300 s | TTL + LRU(300) only |
| SoundCloud | `sc_search:{query}:{max_results}` | ✔ | n/a (provider has no result type) | ✔ | 300 s | TTL + LRU(300) only |
| Spotify | `spotify_search:{query}:{result_type}:{limit}` | ✔ | ✔ (verbatim `result_type`) | ✔ | 300 s | TTL + LRU(300) only |
| local | *not cached* — the SQLite query runs on every search | — | — | — | — | — |

The keys are complete for their own parameter set. Two blemishes: (i) the Spotify key uses
`result_type` *verbatim* while the payload is decided by
`result_type in ("albums","album")`, so `"album"` and `"albums"` — and `None`/`"tracks"`/
`"playlists"` — occupy distinct keys for identical content (up to 4× cache dilution of a
300-entry budget); (ii) the whole cache is only invalidated by the TTL, because
`clear_search_cache()` has no call site (F-WX-05-6).

**Return shape comparison**

| producer | value |
|---|---|
| `core/api.py::search` returns | `{"query": <q>, "tracks": []}` — `tracks` **always empty**; no `results` key, no `sources` map |
| `search_results` event payload | `{"query", "source" (provider name), "type" (result_type or null), "tracks": [...], "offline": bool}` — one chunk per provider |
| `search_completed` event payload | `{"query", "source" (the requested source, e.g. "all")}` — no per-provider status |
| `js/search.js::onSearchResults` consumes | the two events only; the bridge's return value is discarded (`js/search.js:1083`) |

---

### 4. Coverage gaps

- **No live network run.** The provider endpoints were read, not executed — the repository's
  `pytest.ini` deselects the `network` marker and the audit rules forbid running the real app.
  The claims about *which* endpoint is called are literal-code facts; the claims about
  *latency* are from a fake-provider harness, not from real YouTube/SoundCloud/iTunes
  round-trips. What would confirm the production latency: a real search with a provider log.
- **`ytmusicapi` internals were not audited.** `self._ytmusic.search(query, filter=yt_filter, limit=20)`
  is called through a `TimeoutSession` that forces `timeout=6`
  (`services/youtube_service.py:201-205`); whether ytmusicapi retries internally inside that
  budget (and therefore whether the 6 s bridge deadline is realistic) was not verified.
- **`services/track_resolver.py` was not traced.** The WX-05 row of the area map names it,
  but in the shipped code the resolution of a search hit to a playable stream happens later
  (in `core/api.py::play_track` → `core/resolver.py`), not inside the search fan-out; the
  track resolver is reached from the *download* path (`core/downloader.py:476-558`). The
  `ytsearch1:` contract was therefore checked at the downloader, not in the resolver.
- **The `lastfm_service.py`, `vk_service.py` and `yandex_service.py` providers were not
  audited** — they are excluded from the UI fan-out
  (`DISABLED_UI_PROVIDERS = {"yandex","vk","vkontakte","zeno"}`, `core/api.py:2098`) and
  `lastfm` is not reachable from `AppApi.search` at all.
- **The `get_search_suggestions` / `utils/search_query.py` path** (the "другая раскладка"
  banner shown on an empty result) was read but not audited for correctness; it is a separate
  bridge method, not part of the fan-out.
- **The UI rendering of the album grid was only partially modelled.** `renderAlbumGrid`
  (`js/search.js:508-593`) was read, but the album **modal** path
  (`fetchAlbumDetails` → `CatalogService.album_details`) was not traced end to end, so the
  behaviour of a "Spotify"-sourced album inside the modal is only partially characterised
  (the catalogue *does* handle `source in ('spotify','itunes')`,
  `services/catalog_service.py:192-211`, but the tracks it returns carry the same
  non-unique `ytsearch1:` id as F-WX-05-3).
- **Race conditions on the shared class-level `_search_cache`** were checked by reading the
  two eviction helpers (`services/yandex_service.py:93-99`,
  `services/recommendation_service.py:65-68`) — both hold `_cache_lock` while iterating, so
  the classic "dict changed size during iteration" race does **not** exist there. A
  stress test of concurrent `set_search_cache` from five providers was not run.
- **The `ITunesGateway` global rate limiter** (`INTERVAL = 3.5 s`, `PER_MINUTE = 18`,
  `services/itunes_gateway.py:21-22`) can delay a Spotify search behind an unrelated iTunes
  call (album details, artist lookup) by up to 3.5 s of the 6 s budget. This interaction was
  derived from the code and not reproduced.
