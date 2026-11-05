# NeDotify Linux

This checkout is the Linux desktop port. The reference Windows working tree is
`../NeDotify_Windows`; treat it as read-only. Android and archives are outside
the desktop task. Both appearances share `ui/web_new_v2/`; `ui/MACos_ui/` is its
scoped presentation pack.

- Read [CODING_STANDARDS.md](CODING_STANDARDS.md) before bridge, proxy, filename,
  threading or keybind changes. Its Windows installer/runtime sections describe
  the reference; Linux build and runtime behavior live in [README.md](README.md).
- Use `.venv/bin/python` on Linux. The existing `.venv/` is host-specific and
  must not be copied between systems. Windows checks may use the sibling
  Windows venv with `cwd` set to this checkout; record that host explicitly.
- Before claiming a feature works, run its corresponding pytest suite. Tests
  redirect the profile at collection and fixture boundaries; preserve that
  isolation for subprocesses and migrations. See
  [docs/LINUX_VALIDATION.md](docs/LINUX_VALIDATION.md) for native acceptance.
- `~/.nedotify/` belongs to the user: database, settings, downloads and secrets
  survive upgrades/uninstall. Use temporary copies for migration checks.
- Keep `BridgeApi.PUBLIC_METHODS`, frontend calls, event payloads, and mirrored
  hotkey tables consistent. `_emit` stays off the GUI thread. Add shared state
  under the owning class's existing lock; keep SQLite WAL and parameterized SQL.
- Qt operations must reach Qt's main thread; use `core/linux_integration.py`.
  Media transport commands must reach the HTML audio player, which owns sound.
- Source and frozen mode resolve assets via `sys._MEIPASS`; package both UI
  trees. Build with native Linux tools using `build_linux.sh`.
- Update [docs/WINDOWS_PARITY.md](docs/WINDOWS_PARITY.md) when parity or evidence
  changes. Distinguish source transfer, mocked tests, live provider checks and
  real Linux verification; old screenshots do not verify a new port.

Historical `.claude/skills/aura-*` documents describe a retired Windows/GTK
workflow. Current commands and safe process handling are in the linked Linux
README/validation guide.
