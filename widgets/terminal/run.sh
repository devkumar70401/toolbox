#!/bin/bash
# Launcher for Terminal Desktop Widget
# Uses X11 backend (XWayland) for absolute pixel positioning and desktop layer hints

export DISPLAY="${DISPLAY:-:0}"
export GDK_BACKEND=x11
unset WAYLAND_DISPLAY
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

# Clean Snap / VSCode inherited variables to ensure native system libraries are loaded
unset GTK_PATH
unset LOCPATH
unset LD_PRELOAD
unset GIO_MODULE_DIR
unset GTK_IM_MODULE_FILE
unset GSETTINGS_SCHEMA_DIR

# Ensure XAUTHORITY is available
if [ -z "$XAUTHORITY" ]; then
    for auth in "$XDG_RUNTIME_DIR"/.mutter-Xwaylandauth.* "$HOME"/.Xauthority; do
        if [ -r "$auth" ]; then
            export XAUTHORITY="$auth"
            break
        fi
    done
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$HOME/SE/toolbox/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="/usr/bin/python3"
fi

# Fast path: If CLI arguments are provided (e.g. --restart, --status, --reopen, --quit), execute directly
if [ "$#" -gt 0 ]; then
    cd "$SCRIPT_DIR"
    exec "$PYTHON_BIN" "$SCRIPT_DIR/terminal_widget.py" "$@"
fi

# Wait for X11 display / graphical session to become ready (up to 30 seconds on boot)
for i in {1..30}; do
    if "$PYTHON_BIN" -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; exit(0 if Gtk.init_check()[0] else 1)" 2>/dev/null; then
        break
    fi
    sleep 1
done

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" "$SCRIPT_DIR/terminal_widget.py" "$@"
