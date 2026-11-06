#!/usr/bin/env bash
echo "=== Desktop Widgets Suite Status ==="
systemctl --user status daily-todo-widget.service pomodoro-widget.service music-widget.service terminal-widget.service youtube-widget.service sysmon-widget.service --no-pager
