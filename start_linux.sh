#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$TASK_DIR"
if [[ "$(uname -s)" != Linux ]]; then
    echo 'NeDotify Linux must run on Linux.' >&2
    exit 1
fi
if [[ "${EUID}" -eq 0 ]]; then
    echo 'Run NeDotify as your desktop user, not root.' >&2
    exit 1
fi
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo 'No graphical desktop session. Start from your X11/Wayland session.' >&2
    exit 1
fi
PYTHON="${NEDOTIFY_PYTHON:-$TASK_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    echo 'Missing Linux virtual environment. Run: bash install_linux.sh --source' >&2
    exit 1
fi
export PATH="$(dirname -- "$PYTHON"):$PATH"
export PYWEBVIEW_GUI=qt
export QT_API=pyqt6
# Respect the compositor, audio session and sandbox configured by the desktop.
# Do not guess DISPLAY or remove another process's instance lock here.
exec "$PYTHON" "$TASK_DIR/main.py" "$@"
