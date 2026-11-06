#!/bin/bash
# Launcher for YouTube Desktop Widget
# Uses X11 backend (XWayland) for absolute pixel positioning and desktop layer hints

export DISPLAY="${DISPLAY:-:0}"
export GDK_BACKEND=x11
unset WAYLAND_DISPLAY
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

# Clean Snap / VSCode inherited variables so WebKitNetworkProcess uses system libraries
unset GIO_MODULE_DIR
unset GSETTINGS_SCHEMA_DIR
unset GTK_PATH
unset GTK_EXE_PREFIX
unset GTK_MODULES
unset GTK_IM_MODULE_FILE
unset LOCPATH
unset LD_PRELOAD

# Restore standard system data dirs if corrupted by snap
if [[ "$XDG_DATA_DIRS" == *"/snap/"* ]]; then
    export XDG_DATA_DIRS="/usr/share/ubuntu:/usr/share/gnome:/usr/local/share/:/usr/share/"
fi

# Wait for X11 display / graphical session to become ready (up to 30 seconds on boot)
for i in {1..30}; do
    if /usr/bin/python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; exit(0 if Gtk.init_check()[0] else 1)" 2>/dev/null; then
        break
    fi
    sleep 1
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$HOME/SE/toolbox/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="/usr/bin/python3"
fi

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" "$SCRIPT_DIR/youtube_widget.py" "$@"
