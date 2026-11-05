#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$TASK_DIR"
if [[ "$(uname -s)" != Linux ]]; then
    echo 'Linux packages must be built natively on Linux.' >&2
    exit 1
fi
PYTHON="${NEDOTIFY_PYTHON:-$TASK_DIR/.venv/bin/python}"
export PATH="$(dirname -- "$PYTHON"):$PATH"
export QT_API=pyqt6 PYWEBVIEW_GUI=qt
"$PYTHON" -m pip check
"$PYTHON" packaging/linux_support.py --check-tools
"$PYTHON" -m PyInstaller --noconfirm --clean setup_pyinstaller.spec
"$PYTHON" -m pip freeze > dist/NeDotify/BUILD-REQUIREMENTS.txt
"$PYTHON" packaging/linux_support.py --package --version "${NEDOTIFY_VERSION:-2.5.1}"
