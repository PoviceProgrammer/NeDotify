#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(uname -s)" != Linux || "${EUID}" -eq 0 ]]; then
    echo 'Run this installer as your regular Linux desktop user.' >&2
    exit 1
fi
case "${1:---bundle}" in
    --source)
        PYTHON="${NEDOTIFY_SYSTEM_PYTHON:-python3}"
        "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
        "$PYTHON" -m venv "$TASK_DIR/.venv"
        "$TASK_DIR/.venv/bin/python" -m pip install --upgrade pip
        "$TASK_DIR/.venv/bin/python" -m pip install -r "$TASK_DIR/requirements.txt"
        "$TASK_DIR/.venv/bin/python" "$TASK_DIR/packaging/linux_support.py" --check-tools
        "$TASK_DIR/.venv/bin/python" "$TASK_DIR/packaging/linux_support.py" --install-source
        ;;
    --bundle)
        BUNDLE="${2:-$TASK_DIR/dist/NeDotify}"
        if [[ -z "${2:-}" && -d "$TASK_DIR/_internal" ]]; then
            BUNDLE="$TASK_DIR"
        fi
        python3 "$TASK_DIR/packaging/linux_support.py" --install-bundle "$BUNDLE"
        ;;
    --uninstall)
        python3 "$TASK_DIR/packaging/linux_support.py" --uninstall
        ;;
    *)
        echo 'Usage: bash install_linux.sh [--source | --bundle DIRECTORY | --uninstall]' >&2
        exit 2
        ;;
esac
