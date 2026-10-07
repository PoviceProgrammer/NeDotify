# AURA Music — coding standards (disclosed reference)

Consulted on demand. `AGENTS.md` holds what every task needs; this file holds the
per-subsystem contracts behind it.

Citations are **symbol-first**: line numbers drift when a file grows, symbols do
not. If a change invalidates one, re-verify it or drop it.

---

## The pywebview bridge

Two channels, no third.

- **Python → JS** is `AppApi._emit(name, payload)` (`core/api.py`). It serialises
  with `json.dumps` *inside* the try, then evaluates
  `window.onPythonEvent(<name>, <payload>)` via `window.evaluate_js`. An
  unserialisable payload is logged and dropped rather than raised — that guard is
  the only reason a bad payload is visible at all. Do not hoist the `json.dumps`
  out of the try.
- **JS → Python** is `window.pywebview.api.<method>(...)`, against the `AppApi`
  instance handed to `create_window(js_api=...)`. There are ~200 such call sites
  in `ui/web_new_v2/js/`, so a thrown bridge call is a dead button, not an
  exception: wrap it, then fall back to a UI state that still renders.
- **There is no `EventSource`, no `text/event-stream` route and no WebSocket
  channel** anywhere in `ui/**` or in `core/`, `services/`, `audio/`,
  `main.py` (grep-verified). Frontend code that waits for a server push waits
  forever. The bridge callback is the only channel.

## Event names

The backend emits:

| event | payload | site |
|---|---|---|
| `download_complete` | `{"track_id": …}` | `core/downloader.py::download` |
| `download_failed` | `{"track_id": …, "error": str}` | `core/downloader.py` |

- `download_complete` carries **no** `file_path`. The path reaches the database
  only. Read it from `tracks.file_path` or `get_downloaded_tracks()` — reading it
  from the event yields `undefined`.
- `ui/web_new_v2/js/events.js` accepts `download_complete` **and** the long-dead
  `track_downloaded` as adjacent `case` arms, then re-dispatches its own
  `nedotify:track_downloaded` DOM event. That fallthrough is exactly why a backend
  rename is invisible: nothing errors, one branch simply stops firing. When you
  add an event, add it to both sides in the same change.

## The mirrored hotkey tables

Action ids live in two places that must stay identical:

- `DEFAULT_KEYBINDS` — `ui/web_new_v2/js/hotkeys.js`
- `DEFAULT_SETTINGS["hotkeys"]` — `core/settings.py`

`core/settings.py` says so in a comment at the definition: *MUST mirror
DEFAULT_KEYBINDS in ui/web_new_v2/js/hotkeys.js exactly*. The codebase already
documents this rule; the duplication is the hazard, not the prose.

- At startup the frontend builds `KNOWN_ACTIONS` from its own table
  (`ui/web_new_v2/js/hotkeys.js`) and applies backend settings **only** for ids in
  that set. An id present in one table and not the other is silently discarded —
  and dropped from persisted `localStorage` as a ghost entry — so the key simply
  stops working, with no error anywhere. This already happened once: the backend
  said `mute`, the frontend said `toggle_mute`.
- Values are `e.code` names joined with `+`, produced by `parseKeyEventCombo`.
  `formatKeyName` (`ui/web_new_v2/js/settings.js`) parses that back for display, so
  it splits on `+` and labels each part — a combo it cannot split renders as the
  literal text `Ctrl+ArrowRight`.
- There is exactly one dispatcher: `executeHotkeysAction` in `hotkeys.js`.
- **Done means `tests/test_keybind_contracts.py` passes** after you touch either
  table. It pins the mirror, the action set and the combo round-trip.

## Filenames and sanitisation

`utils/` holds `cache_manager.py`, `file_scanner.py` and `tag_parser.py`. There is
**no** `utils/path_utils.py` and no generic forbidden-character helper — sanitising
is inline at the point a name is constructed.

- **Stream-cache names** are reduced to `[A-Za-z0-9_-]` with
  `re.sub(r'[^a-zA-Z0-9_-]', '_', …)`, one call site each: `core/api.py` (two
  on-disk cache lookups), `core/proxy.py` (proxy side).
- **YouTube download names** are built by the same substitution into
  `yt_<safe_id>_<ts>.<ext>`, as a yt-dlp `outtmpl` in
  `services/youtube_service.py`. The *directory* is supplied separately by
  `core/downloader.py`.
- **Downloads** land in `~/.nedotify/downloads` (`core/downloader.py`) and are
  named by id and timestamp, not by title.
- `services/zapret_service.py: sanitize_zapret_args()` sanitises the *zapret
  command line*, not filenames. It is not a model for filename handling.

**If you introduce a human-readable `<artist> - <title>.mp3`, ship the
forbidden-character filter in the same commit.** Windows filenames reject
`< > : " / \ | ? *`, and nothing downstream will filter them for you.

> Not every provider holds this line. `services/yandex_service.py` still builds
> `ya_<raw_id>_<ts>.mp3` from an unsanitised id — the convention is documented,
> not enforced. See the audit note in `docs/AUDIT.md`.

## Profile layout — `~/.nedotify/`

| What | Where |
|---|---|
| Database | `~/.nedotify/nedotify_storage.db` (SQLite, WAL) — `core/database.py` |
| Downloads | `~/.nedotify/downloads/` — `core/downloader.py` |
| Stream cache | `~/.nedotify/streams/` — `utils/cache_manager.py` |
| Covers / temp | `~/.nedotify/covers/`, `~/.nedotify/temp/` — `utils/cache_manager.py` |
| Logs | `~/.nedotify/logs/app.log` (rotating 2 MB × 3) — `main.py` |

`tests/conftest.py: redirect_home` redirects `~` into `tmp_path`. It is
**opt-in, not autouse** (`@pytest.fixture`, no `autouse=True`), so nothing catches
a leak into the real profile. Any new test or code path that touches the profile
takes the fixture; `tests/test_conftest_home_isolation.py` guards the fixture
itself.

## SQLite

- **WAL is load-bearing.** `core/database.py` issues `PRAGMA journal_mode=WAL`;
  the loopback proxy serves reads while the UI writes, so without it concurrent
  reads meet `database is locked`.
- **`mark_track_downloaded` writes two columns** — `UPDATE tracks SET
  is_downloaded = 1, file_path = ? WHERE id = ?` (`core/database.py`), inside
  `with self._write_lock:` and `with self.conn:`. It leaves `source` and every
  metadata column untouched by construction. A row rewrite here silently
  re-labels the user's library, which is unrecoverable.
- Transactions go through `with self.conn:` — the attribute is `conn`, not a bare
  `conn`, and `core/database.py` uses it at every write site.

## Thread pools

Long work stays off the UI thread, on pools that already exist. Read the sizes;
do not trust a number written in a doc.

| Pool | Size / prefix | Site |
|---|---|---|
| Search | `max_workers=6`, `SearchWorker` | `core/api.py` |
| Downloads | `_MAX_INFLIGHT`, `download_worker` | `core/downloader.py` |
| Provider fan-out | `_SharedExecutor(max_workers=8)` | `services/base_service.py` |

Enter shared provider work through `BaseMusicService.submit()`. It is
shutdown-safe and returns `None` once the pool is gone — **that `None` is the
shutdown signal, not an error**; handle it and move on.

Locks: `BaseMusicService._search_cache` / `._stream_cache` share the class-level
`_cache_lock`, which is an **`RLock`** (`services/base_service.py`);
`StreamResolver._mem` / `._inflight` share `self._lock` (`core/resolver.py`).

## Player teardown

`ui/web_new_v2/js/player.js` holds two `Audio` elements for crossfade. Teardown
sets `src` empty and calls `load()` — on `audioEl` at construction, on the active
element at stop, and on the outgoing element at crossfade. Loading always routes
through `loadAudioSource`, never a raw `.src`; the `src = ""` inside that helper
is the error fallback. WebView2 otherwise keeps the socket alive and the next
track stalls on `waiting`.

## Frozen vs source assets

```python
base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
```

Canonical sites: `main.py`, `core/tray.py`, `core/proxy.py`. Any new asset
lookup needs both branches — a path that works under `python main.py` and breaks
in the exe is the most common packaging regression here.

`installer.iss` owns shortcuts, the HKCU autostart `Run` value, the registry and
the uninstaller. It is the **only** installer source: `build_installer.py`,
`installer_gui.py` and `uninstaller_gui.py` were deleted, and a test enforces
that no doc still points at them.

## Retired folklore — do not reintroduce

Each was believed at some point and is now false. All are grep-verified absent or
contradicted.

| Folklore | Reality | Verified at |
|---|---|---|
| `utils/path_utils.py` exists | `utils/` has no path module | `utils/` listing |
| `ThreadPoolExecutor(max_workers=5)` | 6, prefix `SearchWorker` | `core/api.py` |
| Search cache "must use `Lock()`" | it is a class-level `RLock` | `services/base_service.py` |
| 4.0 s per-provider search deadline | `PROVIDER_SEARCH_TIMEOUT = 6.0` | `core/api.py` |
| event `track_downloaded` | `download_complete` | `core/downloader.py` |
| downloads in `.cache/downloads/` | `~/.nedotify/downloads` | `core/downloader.py` |
| stream cache in `.cache/streams/` | `~/.nedotify/streams` | `utils/cache_manager.py` |
| database is `aura.db` | `nedotify_storage.db` | `core/database.py` |
| `.venv\Scripts\python.exe` | `.venv_win\Scripts\python.exe` is the only venv | `.venv\` does not exist |
| Nuitka is a build path | PyInstaller + Inno Setup only | no Nuitka in tree |
| `build_installer.py`, `installer_gui.py`, `uninstaller_gui.py` | none exist | repo-wide filename search |
| `ui/web_new/` is the UI | `ui/web_new_v2/` is the default | `main.py: NEDOTIFY_UI_DIR` |
| Playwright / Selenium E2E | opaque-box pytest against real `AppApi` | `tests/` |
