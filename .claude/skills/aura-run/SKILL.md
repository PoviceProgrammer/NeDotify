---
name: aura-run
description: Launch the AURA Music (NeDotify) desktop app to verify a change in the real UI. Use when asked to run/start/screenshot the app, reproduce a playback, search, download or tray bug, or confirm a fix works outside tests. Covers the venv, the WebView2 pin, log locations and clean shutdown.
---

# Running AURA Music

## Launch

Always use the project venv interpreter — the system Python lacks pywebview/yt-dlp:

```powershell
& ".venv\Scripts\python.exe" main.py
```

The app is a **blocking GUI process** (pywebview + WebView2). Run it with
`run_in_background: true` and read its output file, otherwise the tool call
hangs until the user closes the window.

`main.py` self-restarts once on a fatal startup failure via
`NEDOTIFY_RESTART_COUNT`. Two "starting" banners in the log is expected
behaviour, not a duplicate launch.

## Environment facts that matter

- **WebView2 is pinned** to `151.0.4129.86` in `main.py:18-24`. Evergreen
  `151.0.4129.93` hangs bridge injection on this machine — `loaded` /
  `_pywebviewready` never fire, so every `window.pywebview.api.*` call is dead.
  If the UI renders but nothing responds, check that the pinned runtime folder
  still exists before debugging JS.
- pywebview serves the UI through **Bottle**, whose `run` is monkeypatched in
  `main.py` to install no-cache headers and asset fallback routes *before*
  serving starts. Do not move that registration into a thread — it loses the
  race and produces an `/assets/*.png` 404 storm.
- Static assets must resolve in both source and frozen mode (`sys._MEIPASS`).

## Logs and state

| What | Where |
|---|---|
| Runtime logs | `~/.nedotify/logs/` |
| Perf events | `~/.nedotify/logs/perf.jsonl` |
| Database | `aura.db` (SQLite, WAL mode) |
| Stream cache | `.cache/streams/` |
| Downloads | `.cache/downloads/` |

## Shutdown

Prefer closing the window or the bridge-free route `/__aura_close`. If you
must kill it, stop **both** processes — an orphaned `msedgewebview2.exe`
keeps the audio proxy port busy:

```powershell
Get-Process python, msedgewebview2 -ErrorAction SilentlyContinue | Stop-Process -Force
```

Killing a stray process tree is fine; do not delete `aura.db` or `.cache/`
to "get a clean state" without asking — that discards the user's library.
