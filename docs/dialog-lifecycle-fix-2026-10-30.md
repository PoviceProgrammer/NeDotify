# Native dialog dismissal and positioning

The playlist action dialog reproduced both reported symptoms in Chromium with
the shipped DOM and handlers, in the current and macOS interfaces:

- Position: `(0, 0)` after the global margin reset replaced the native dialog's
  automatic margins.
- After an outside click and reopening: `open=true`, `display=none`,
  `.hidden=true`. The browser still owned a modal in its top layer, so the rest
  of the document was inert while playback and JavaScript could keep running.

`initLibraryView` registered a backdrop handler that called `dialog.close()`.
The shared focus helper handled the same event afterward, saw `open=false`,
and incorrectly used its div-overlay fallback to hide the native dialog.

The shared helper now distinguishes native dialogs, never hides them with CSS
to close them, ignores duplicate closes, and releases listeners on native
`close` and `cancel`. Backdrop detection checks the card bounds and pointer
origin: clicking card padding or dragging from inside does not dismiss it.
Independent backdrop handlers were removed from playlist, home, profile and
smart-playlist dialogs. All native dialogs explicitly restore automatic
centering, viewport bounds, a shared surface and keyboard focus treatment.
Playlist actions also have a compact icon header, a close button and grouped
actions. Div overlays retain their existing callbacks.

Read-only log review: `~/.nedotify/logs/app.log`, final launch beginning
07:45:16 and cleanup at 07:55:14, contains no renderer failure explaining this
incident. It contains repeated redacted proxy configuration warnings and
provider errors. The older rotated log contains WinForms window-move failures;
those are separate from the deterministic invisible-modal reproduction.
Native browser inertness does not stop the renderer heartbeat, so a heartbeat
watchdog would not detect this failure.

Regression: `tests/dialog_lifecycle_browser.cjs` first failed on position and
invisible reopening in both interfaces. It now covers current, macOS dark and
macOS light, four native dialog types, 1100px and 360px viewports, outside click,
Escape, close buttons, native cancellation, padding clicks, duplicate closers,
focus-trap cleanup and background interaction. The real library CRUD browser
scenario also passes in both interfaces at 600/900/1280px.
