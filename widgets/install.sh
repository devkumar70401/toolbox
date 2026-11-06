#!/usr/bin/env bash
# ==============================================================================
# Master Desktop Widgets Installer & Disaster Recovery Script
# Restores and launches Work, Diet, Pomodoro, Music, Terminal, Sysmon, Routines,
# and YouTube widgets on ANY Linux system at ANY time.
# ==============================================================================

set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_HOME="$HOME"

echo "🌟 Installing & Restoring Desktop Widgets from $BASE_DIR..."

# 1. Create necessary user directories
mkdir -p "$USER_HOME/.local/bin"
mkdir -p "$USER_HOME/.config/autostart"
mkdir -p "$USER_HOME/.config/systemd/user"
mkdir -p "$USER_HOME/.config/daily-todo-widget"
mkdir -p "$USER_HOME/.config/diet-widget"
mkdir -p "$USER_HOME/.config/pomodoro-widget"
mkdir -p "$USER_HOME/.config/music-widget"
mkdir -p "$USER_HOME/.config/terminal-widget"
mkdir -p "$USER_HOME/.config/sysmon-widget"
mkdir -p "$USER_HOME/.config/routines-widget"
mkdir -p "$USER_HOME/.config/youtube-widget"
mkdir -p "$USER_HOME/SE/toolbox/daily"
mkdir -p "$USER_HOME/SE/toolbox/downloads"
mkdir -p "$USER_HOME/SE/toolbox/music"

# 2. Restore Pomodoro Binaries to ~/.local/bin
if [ -d "$BASE_DIR/bin" ]; then
    cp -u "$BASE_DIR/bin/"* "$USER_HOME/.local/bin/" 2>/dev/null || true
    chmod +x "$USER_HOME/.local/bin/pomodoro"* 2>/dev/null || true
    echo "  ✔ Pomodoro binaries restored to ~/.local/bin"
fi

# 3. Restore Config Files if not already existing
[ -f "$USER_HOME/.config/daily-todo-widget/config.json" ] || cp "$BASE_DIR/work/config.json" "$USER_HOME/.config/daily-todo-widget/"
[ -f "$USER_HOME/.config/diet-widget/config.json" ] || cp "$BASE_DIR/diet/config.json" "$USER_HOME/.config/diet-widget/"
[ -f "$USER_HOME/.config/pomodoro-widget/config.json" ] || cp "$BASE_DIR/pomodoro/config.json" "$USER_HOME/.config/pomodoro-widget/"
[ -f "$USER_HOME/.config/music-widget/config.json" ] || cp "$BASE_DIR/music/config.json" "$USER_HOME/.config/music-widget/"
[ -f "$USER_HOME/.config/terminal-widget/config.json" ] || cp "$BASE_DIR/terminal/config.json" "$USER_HOME/.config/terminal-widget/" 2>/dev/null || true
[ -f "$USER_HOME/.config/sysmon-widget/config.json" ] || cp "$BASE_DIR/sysmon/config.json" "$USER_HOME/.config/sysmon-widget/" 2>/dev/null || true
[ -f "$USER_HOME/.config/routines-widget/config.json" ] || cp "$BASE_DIR/routines/config.json" "$USER_HOME/.config/routines-widget/" 2>/dev/null || true
[ -f "$USER_HOME/.config/youtube-widget/config.json" ] || cp "$BASE_DIR/youtube/config.json" "$USER_HOME/.config/youtube-widget/" 2>/dev/null || true
echo "  ✔ Configuration files restored"

chmod +x "$BASE_DIR"/*.sh "$BASE_DIR"/*.py 2>/dev/null || true
chmod +x "$BASE_DIR"/work/*.sh "$BASE_DIR"/work/*.py 2>/dev/null || true
chmod +x "$BASE_DIR"/diet/*.sh "$BASE_DIR"/diet/*.py 2>/dev/null || true
chmod +x "$BASE_DIR"/pomodoro/*.sh "$BASE_DIR"/pomodoro/*.py 2>/dev/null || true
chmod +x "$BASE_DIR"/music/*.sh "$BASE_DIR"/music/*.py 2>/dev/null || true
chmod +x "$BASE_DIR"/terminal/*.sh "$BASE_DIR"/terminal/*.py 2>/dev/null || true
chmod +x "$BASE_DIR"/sysmon/*.sh "$BASE_DIR"/sysmon/*.py 2>/dev/null || true
chmod +x "$BASE_DIR"/routines/*.sh "$BASE_DIR"/routines/*.py 2>/dev/null || true
chmod +x "$BASE_DIR"/youtube/*.sh "$BASE_DIR"/youtube/*.py 2>/dev/null || true

# 5. Install Systemd User Services
cp "$BASE_DIR/work/daily-todo-widget.service" "$USER_HOME/.config/systemd/user/"
cp "$BASE_DIR/diet/diet-widget.service" "$USER_HOME/.config/systemd/user/"
cp "$BASE_DIR/pomodoro/pomodoro-widget.service" "$USER_HOME/.config/systemd/user/"
cp "$BASE_DIR/music/music-widget.service" "$USER_HOME/.config/systemd/user/"
cp "$BASE_DIR/terminal/terminal-widget.service" "$USER_HOME/.config/systemd/user/"
cp "$BASE_DIR/sysmon/sysmon-widget.service" "$USER_HOME/.config/systemd/user/"
cp "$BASE_DIR/routines/routines-widget.service" "$USER_HOME/.config/systemd/user/"
cp "$BASE_DIR/youtube/youtube-widget.service" "$USER_HOME/.config/systemd/user/"
echo "  ✔ Systemd user services installed"

# 6. Install Autostart Desktop Entries
cp "$BASE_DIR/work/daily-todo-widget.desktop" "$USER_HOME/.config/autostart/"
cp "$BASE_DIR/pomodoro/pomodoro-widget.desktop" "$USER_HOME/.config/autostart/"
cp "$BASE_DIR/music/music-widget.desktop" "$USER_HOME/.config/autostart/"
cp "$BASE_DIR/terminal/terminal-widget.desktop" "$USER_HOME/.config/autostart/"
cp "$BASE_DIR/sysmon/sysmon-widget.desktop" "$USER_HOME/.config/autostart/"
cp "$BASE_DIR/youtube/youtube-widget.desktop" "$USER_HOME/.config/autostart/"
echo "  ✔ Autostart desktop entries installed"

# 7. Reload systemd and enable/start all services
systemctl --user daemon-reload
systemctl --user enable daily-todo-widget.service pomodoro-widget.service music-widget.service terminal-widget.service youtube-widget.service
systemctl --user restart daily-todo-widget.service pomodoro-widget.service music-widget.service terminal-widget.service youtube-widget.service

echo ""
echo "🎉 Desktop widgets suite successfully installed, enabled on boot, and running live!"
echo "   • Daily Tasks Suite (Work, Diet, Routines): daily-todo-widget.service"
echo "   • Pomodoro Timer:   pomodoro-widget.service"
echo "   • Music Player:     music-widget.service"
echo "   • Terminal:         terminal-widget.service"
echo "   • YouTube Player:   youtube-widget.service"
