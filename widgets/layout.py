#!/usr/bin/env python3
"""
Master Desktop Widgets Layout Manager
Intelligently positions and docks all 8 Devendra Desktop Widgets.

Presets:
  desktop : Layout on Main Desktop (Laptop Screen eDP-1: 1920x1200 at X: 2560..4480)
  monitor : Layout on External Monitor (HDMI-1: 2560x1440 at X: 0..2560)
  single  : Layout for single-screen setup (X: 0..1920)

Usage:
  ./layout.py [desktop|monitor|single]
"""

import sys
import os
import json
import re
import subprocess
from pathlib import Path

HOME = Path.home()
BASE_DIR = Path(__file__).parent.resolve()

# Pre-defined optimal layouts
LAYOUTS = {
    "desktop": {
        # Current Laptop screen layout (eDP-1: 1920x1200, offset X: 2560, Y: 240)
        "Pomodoro Widget":        {"x": 3737, "y": 590, "width": 360, "height": 215, "cfg": "pomodoro-widget", "src": "pomodoro"},
        "Daily Tasks":           {"x": 4110, "y": 505, "width": 360, "height": 520, "cfg": "daily-todo-widget", "src": "work"},
        "Music Player Widget":   {"x": 3738, "y": 811, "width": 360, "height": 210, "cfg": "music-widget", "src": "music"},
        "Daily Diet & Nutrition":{"x": 3746, "y": 503, "width": 360, "height": 520, "cfg": "diet-widget", "src": "diet"},
        "Daily Routines":        {"x": 3380, "y": 503, "width": 360, "height": 520, "cfg": "routines-widget", "src": "routines"},
        "Terminal Widget":       {"x": 3882, "y": 1034, "width": 870, "height": 570, "cfg": "terminal-widget", "src": "terminal"},
        "System Vitals":         {"x": 2996, "y": 1178, "width": 525, "height": 220, "cfg": "sysmon-widget", "src": "sysmon"},
        "YouTube Widget":        {"x": 3283, "y": 1026, "width": 594, "height": 390, "cfg": "youtube-widget", "src": "youtube"},
    },
    "monitor": {
        # External Monitor (HDMI-1: 2560x1440, offset X: 0, Y: 0)
        "Pomodoro Widget":        {"x": 2180, "y": 50, "width": 360, "height": 215, "cfg": "pomodoro-widget", "src": "pomodoro"},
        "Daily Tasks":           {"x": 2180, "y": 280, "width": 360, "height": 260, "cfg": "daily-todo-widget", "src": "work"},
        "Music Player Widget":   {"x": 2180, "y": 555, "width": 360, "height": 205, "cfg": "music-widget", "src": "music"},
        "System Vitals":         {"x": 1800, "y": 50, "width": 360, "height": 153, "cfg": "sysmon-widget", "src": "sysmon"},
        "Daily Diet & Nutrition":{"x": 1800, "y": 220, "width": 366, "height": 490, "cfg": "diet-widget", "src": "diet"},
        "Daily Routines":        {"x": 1420, "y": 220, "width": 360, "height": 370, "cfg": "routines-widget", "src": "routines"},
        "Terminal Widget":       {"x": 1960, "y": 800, "width": 870, "height": 570, "cfg": "terminal-widget", "src": "terminal"},
        "YouTube Widget":        {"x": 50, "y": 50, "width": 594, "height": 390, "cfg": "youtube-widget", "src": "youtube"},
    },
    "single": {
        # Single screen (1920x1080 or 1920x1200 at X: 0, Y: 0)
        "Pomodoro Widget":        {"x": 1540, "y": 45, "width": 360, "height": 215, "cfg": "pomodoro-widget", "src": "pomodoro"},
        "Daily Tasks":           {"x": 1540, "y": 270, "width": 360, "height": 260, "cfg": "daily-todo-widget", "src": "work"},
        "Music Player Widget":   {"x": 1540, "y": 545, "width": 360, "height": 205, "cfg": "music-widget", "src": "music"},
        "System Vitals":         {"x": 1160, "y": 45, "width": 360, "height": 153, "cfg": "sysmon-widget", "src": "sysmon"},
        "Daily Diet & Nutrition":{"x": 1160, "y": 210, "width": 366, "height": 490, "cfg": "diet-widget", "src": "diet"},
        "Daily Routines":        {"x": 780, "y": 210, "width": 360, "height": 370, "cfg": "routines-widget", "src": "routines"},
        "Terminal Widget":       {"x": 1320, "y": 765, "width": 870, "height": 570, "cfg": "terminal-widget", "src": "terminal"},
        "YouTube Widget":        {"x": 30, "y": 45, "width": 740, "height": 480, "cfg": "youtube-widget", "src": "youtube"},
    }
}


def get_running_windows():
    """Returns mapping of window title keyword to window id."""
    windows = {}
    try:
        out = subprocess.check_output(["wmctrl", "-l"], text=True)
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                wid = parts[0]
                title = parts[3]
                windows[title] = wid
    except Exception as e:
        print(f"Error querying wmctrl: {e}")
    return windows


def update_config_file(cfg_path: Path, x: int, y: int, w: int, h: int):
    """Updates coordinate fields in a json config file while preserving others."""
    try:
        data = {}
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["x"] = x
        data["y"] = y
        data["width"] = w
        data["height"] = h
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error updating config {cfg_path}: {e}")


def apply_layout(preset_name="desktop"):
    if preset_name not in LAYOUTS:
        print(f"Unknown preset: '{preset_name}'. Options are: desktop, monitor, single")
        sys.exit(1)

    preset = LAYOUTS[preset_name]
    windows = get_running_windows()

    print(f"🚀 Applying layout preset: [{preset_name.upper()}]")
    print(f"{'Widget':<26} | {'Status':<10} | {'Window ID':<10} | {'Geometry (X, Y, W, H)':<24}")
    print("-" * 78)

    for widget_name, info in preset.items():
        x, y, w, h = info["x"], info["y"], info["width"], info["height"]
        cfg_dir = HOME / ".config" / info["cfg"]
        cfg_file = cfg_dir / "config.json"
        src_file = BASE_DIR / info["src"] / "config.json"

        # 1. Update config files (user .config and git-tracked repo)
        update_config_file(cfg_file, x, y, w, h)
        if src_file.parent.exists():
            update_config_file(src_file, x, y, w, h)

        # 2. Find live window and reposition
        matched_wid = None
        for title, wid in windows.items():
            if widget_name in title:
                matched_wid = wid
                break

        if matched_wid:
            # wmctrl -i -r <WID> -e 0,x,y,w,h
            cmd = ["wmctrl", "-i", "-r", matched_wid, "-e", f"0,{x},{y},{w},{h}"]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            status = "Moved"
        else:
            status = "Saved (Idle)"

        print(f"{widget_name:<26} | {status:<10} | {str(matched_wid or '---'):<10} | {f'{x}, {y}, {w}x{h}':<24}")

    print("-" * 78)
    print("✔ All widget configurations updated and live windows repositioned successfully!\n")


def capture_current_layout(preset_name="desktop"):
    """Reads live window positions and updates preset configurations in user .config and repo."""
    clean_env = os.environ.copy()
    for var in ["LD_PRELOAD", "GTK_PATH", "LOCPATH"]:
        clean_env.pop(var, None)

    windows = get_running_windows()
    preset = LAYOUTS.get(preset_name, LAYOUTS["desktop"])

    print(f"📸 Capturing current widget positions into official preset: [{preset_name.upper()}]")
    print(f"{'Widget':<26} | {'Source':<15} | {'Window ID':<10} | {'Geometry (X, Y, W, H)':<24}")
    print("-" * 83)

    for widget_name, info in preset.items():
        matched_wid = None
        for title, wid in windows.items():
            if widget_name in title:
                matched_wid = wid
                break

        x, y, w, h = info["x"], info["y"], info["width"], info["height"]
        source = "Default"

        if matched_wid:
            try:
                out = subprocess.check_output(["xwininfo", "-id", matched_wid], text=True, env=clean_env)
                abs_x = re.search(r"Absolute upper-left X:\s+(-?\d+)", out)
                abs_y = re.search(r"Absolute upper-left Y:\s+(-?\d+)", out)
                width = re.search(r"Width:\s+(\d+)", out)
                height = re.search(r"Height:\s+(\d+)", out)
                if abs_x and abs_y and width and height:
                    x = int(abs_x.group(1))
                    y = int(abs_y.group(1))
                    w = int(width.group(1))
                    h = int(height.group(1))
                    source = "Live Window"
            except Exception:
                pass

        if source == "Default":
            cfg_file = HOME / ".config" / info["cfg"] / "config.json"
            if cfg_file.exists():
                try:
                    with open(cfg_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if "x" in data and "y" in data:
                        x = data["x"]
                        y = data["y"]
                        w = data.get("width", w)
                        h = data.get("height", h)
                        source = "User .config"
                except Exception:
                    pass

        # Update both repo and user config
        info["x"] = x
        info["y"] = y
        info["width"] = w
        info["height"] = h

        cfg_file = HOME / ".config" / info["cfg"] / "config.json"
        src_file = BASE_DIR / info["src"] / "config.json"
        update_config_file(cfg_file, x, y, w, h)
        if src_file.parent.exists():
            update_config_file(src_file, x, y, w, h)

        print(f"{widget_name:<26} | {source:<15} | {str(matched_wid or '---'):<10} | {f'{x}, {y}, {w}x{h}':<24}")

    print("-" * 83)
    print("✔ Official positions captured and saved to repo and ~/.config successfully!\n")


if __name__ == "__main__":
    for var in ["LD_PRELOAD", "GTK_PATH", "LOCPATH"]:
        os.environ.pop(var, None)

    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "desktop"
    if cmd in ["save", "record", "capture", "sync"]:
        preset = sys.argv[2].lower() if len(sys.argv) > 2 else "desktop"
        capture_current_layout(preset)
    else:
        apply_layout(cmd)
