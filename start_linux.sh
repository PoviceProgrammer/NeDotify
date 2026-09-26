#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Clean up any stale single-instance lock if previous process died
if [ -f /tmp/nedotify_instance.lock ]; then
    PID=$(cat /tmp/nedotify_instance.lock 2>/dev/null || true)
    if [ -n "$PID" ] && ! kill -0 "$PID" 2>/dev/null; then
        rm -f /tmp/nedotify_instance.lock
    fi
fi

# Set Wayland / Display environment
if [ -z "$WAYLAND_DISPLAY" ] && [ -n "$XDG_RUNTIME_DIR" ] && [ -S "$XDG_RUNTIME_DIR/wayland-1" ]; then
    export WAYLAND_DISPLAY="wayland-1"
fi
if [ -z "$DISPLAY" ]; then
    export DISPLAY=":0"
fi

# Ensure user-level GStreamer plugins are in path
GST_USER="$HOME/.local/gstreamer-plugins/usr/lib/gstreamer-1.0"
if [ -d "$GST_USER" ]; then
    export GST_PLUGIN_PATH="$GST_USER:${GST_PLUGIN_PATH:-}"
    export GST_PLUGIN_SYSTEM_PATH_1_0="$GST_USER:/usr/lib/gstreamer-1.0"
fi

# Allow WebKitWebProcess access to audio sinks and plugins in Linux
export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1

exec "$DIR/.venv/bin/python" "$DIR/main.py" "$@"
