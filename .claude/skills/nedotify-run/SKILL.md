---
name: nedotify-run
description: Launch the NeDotify desktop app to verify a change in the real UI. Use when asked to run/start/screenshot the app, reproduce a playback, search, download or tray bug, or confirm a fix works outside tests. Covers the venv, the WebView2 pin, log locations and clean shutdown.
---

# Running NeDotify

## Launch

Always use the project venv interpreter — the system Python lacks pywebview/yt-dlp:

```powershell
& ".venv_win\Scripts\python.exe" main.py
```

The app is a **blocking GUI process** (pywebview + WebView2). With a terminal
tool, use a background process/session and inspect the output without waiting
for the user to close the window. For a separate PowerShell launch:

```powershell
$appProcess = Start-Process -FilePath (Resolve-Path '.venv_win\Scripts\python.exe').Path -ArgumentList 'main.py' -WorkingDirectory (Get-Location).Path -WindowStyle Normal -PassThru
```

`main.py` is the entry point; `python -m app` does not exist in this project.
Do not launch another copy if NeDotify is already running; first check whether
its existing window is hidden or minimized.

## Verify the visible window

The log messages `window loaded` and `bridge initialized` confirm startup,
but do not prove that the user can see the window. A launch on 2026-10-15
completed both stages while the native `NeDotify` window was hidden
(`IsWindowVisible` was false); restoring that existing window made it visible.

Check the native window as well as the startup log. `Get-Process python,pythonw`
with `MainWindowTitle` / `MainWindowHandle` helps find a visible window; a zero
handle can also mean a hidden window, so it is not proof that startup failed.
Restore a minimized window or use the tray's **Открыть NeDotify** action. If
the window is hidden, restore/show the existing native window and bring it to
the foreground. Report visibility only after confirming it.

`main.py` self-restarts once on a fatal startup failure via
`NEDOTIFY_RESTART_COUNT`. Two "starting" banners in the log is expected
behaviour, not a duplicate launch.

## Environment facts that matter

- **WebView2 prefers** `151.0.4129.86` when that runtime folder exists; otherwise
  `main.py` uses the installed system runtime. Check the actual startup log's
  `WebView2 runtime setting` rather than assuming the pin is active. The old
  `151.0.4129.93` runtime hung bridge injection on this machine; if the UI renders
  but nothing responds, check the runtime and bridge initialization messages.
- pywebview serves the UI through **Bottle**, whose `run` is monkeypatched in
  `main.py` to install no-cache headers and asset fallback routes *before*
  serving starts. Do not move that registration into a thread — it loses the
  race and produces an `/assets/*.png` 404 storm.
- Static assets must resolve in both source and frozen mode (`sys._MEIPASS`).

## Logs and state

| What | Where |
|---|---|
| Runtime logs | `~/.nedotify/logs/app.log` (rotating 2 MB × 3) |
| Benchmark results | `tools/bench/results/` (see `nedotify-perf`) |
| Database | `~/.nedotify/nedotify_storage.db` (SQLite, WAL mode) |
| Stream cache | `~/.nedotify/streams/` |
| Downloads | `~/.nedotify/downloads/` |

## Shutdown

Closing the window may minimize it to the tray. For a full exit, use the tray
exit action or POST to the app's bridge-free route `/__aura_close` on its
pywebview HTTP server (this is separate from the audio proxy port). The old
route name is retained for compatibility. If a forced stop is necessary,
identify the exact app PID and terminate its process tree, including its own
WebView2 children:

```powershell
taskkill /PID <app-pid> /T /F
```

Do not stop every Python or WebView2 process: other applications use them too.
Do not delete `~/.nedotify/` to reset a launch; it contains the user's library.
