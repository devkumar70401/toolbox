#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Start all core widgets
systemctl --user start daily-todo-widget.service pomodoro-widget.service music-widget.service terminal-widget.service youtube-widget.service sysmon-widget.service

# If explicitly requested with --standalone or --all, also launch individual diet and routines widgets
if [ "$1" = "--all" ] || [ "$1" = "--standalone" ]; then
    systemctl --user start diet-widget.service routines-widget.service
fi

echo "✔ Widgets suite active."
systemctl --user is-active daily-todo-widget.service pomodoro-widget.service music-widget.service terminal-widget.service youtube-widget.service sysmon-widget.service
