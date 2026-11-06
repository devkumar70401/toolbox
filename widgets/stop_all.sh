#!/usr/bin/env bash
systemctl --user stop daily-todo-widget.service diet-widget.service pomodoro-widget.service music-widget.service terminal-widget.service sysmon-widget.service routines-widget.service youtube-widget.service

# Terminate any autostart scope or standalone widget instances
pkill -f 'terminal_widget.py' 2>/dev/null || true
pkill -f 'daily_widget.py' 2>/dev/null || true
pkill -f 'music_widget.py' 2>/dev/null || true
pkill -f 'youtube_widget.py' 2>/dev/null || true
pkill -f 'sysmon_widget.py' 2>/dev/null || true
pkill -f 'diet_widget.py' 2>/dev/null || true
pkill -f 'routines_widget.py' 2>/dev/null || true

echo "Stopped all widgets."
