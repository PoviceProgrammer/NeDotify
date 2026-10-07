# CLAUDE.md

The rules for this repo live in **`AGENTS.md`** — read it first. It is the single
source of truth for the agent contract, the interpreter path and the three rules
that cannot be automated.

- `AGENTS.md` — read on every task.
- `CODING_STANDARDS.md` — per-subsystem contracts: the pywebview bridge, event
  names, the mirrored keybind tables, filenames, the profile layout, and the
  table of retired folklore. Read before touching any of those.
- `STATUS.md` — what the code actually does.
- `docs/AUDIT.md` — what the 2026-10-03 audit changed.

This file used to duplicate rules already in `AGENTS.md` and was wrong about the
interpreter. Duplication is what made it stale, so it is now a pointer and
nothing else.
