#!/usr/bin/env python3
"""
Pomodoro Modern Desktop Widget
Transparent, frameless, interactive desktop widget for the Pomodoro input-guard system.
Completely self-contained, robust 25m focus / 5m break loop with full-monitor break overlay.
"""

import sys
import os
import re
import json
import math
import subprocess
import threading
import fcntl
import time
import wave
import struct
import io
import socket
from pathlib import Path
from datetime import datetime

# Audio Synthesis for Clean Notification Beeps
def generate_beep_wav(freq: float = 880.0, duration: float = 0.14, volume: float = 0.5) -> bytes:
    """Synthesizes a clean sine wave beep PCM buffer with smooth envelope."""
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = []
        ramp_samples = max(1, int(sample_rate * 0.015))
        for i in range(n_samples):
            env = min(1.0, min(i / ramp_samples, (n_samples - i) / ramp_samples))
            val = int(32767 * volume * env * math.sin(2 * math.pi * freq * i / sample_rate))
            val = max(-32768, min(32767, val))
            frames.append(struct.pack("<h", val))
        wav.writeframes(b"".join(frames))
    return buf.getvalue()

BEEP_WAV_DATA = generate_beep_wav(880.0, 0.14, 0.5)

def play_single_beep():
    """Plays a single clean beep through pw-play, aplay, or canberra bell."""
    try:
        p = subprocess.Popen(["pw-play", "-"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.communicate(input=BEEP_WAV_DATA, timeout=1.0)
        if p.returncode == 0:
            return
    except Exception:
        pass
    try:
        p = subprocess.Popen(["aplay", "-q"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.communicate(input=BEEP_WAV_DATA, timeout=1.0)
        if p.returncode == 0:
            return
    except Exception:
        pass
    try:
        res = subprocess.run(["canberra-gtk-play", "-i", "bell"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
        if res.returncode == 0:
            return
    except Exception:
        pass
    print("\a", end="", flush=True)

def play_triple_beep():
    """Plays three distinct beeps asynchronously."""
    def _worker():
        for _ in range(3):
            play_single_beep()
            time.sleep(0.18)
    threading.Thread(target=_worker, daemon=True).start()

_lock_file = None
def _acquire_single_instance_lock():
    global _lock_file
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        lock_path = Path(runtime_dir) / "pomodoro_widget.lock"
    else:
        lock_path = Path.home() / ".config" / "pomodoro-widget" / "pomodoro_widget.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_file = open(lock_path, "a+")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        print("Another instance of pomodoro_widget is already running. Exiting.")
        sys.exit(0)
    except Exception as e:
        print(f"Warning: Could not acquire lock at {lock_path}: {e}")

# Ensure GTK 3 and Cairo are loaded
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Gio', '2.0')
try:
    gi.require_foreign('cairo')
except Exception:
    pass
from gi.repository import Gtk, Gdk, GLib, Gio, Pango
import cairo


class BreakPopupWindow(Gtk.Window):
    """
    Full-monitor break overlay displayed on each monitor during pomodoro breaks.
    Covers the entire monitor and all desktop widgets with a solid dark backdrop
    and displays a centered card with a live countdown and early dismiss option.
    """
    def __init__(self, target_x: int, target_y: int, target_w: int, target_h: int, on_dismiss=None, monitor_idx: int = 0):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.target_x = target_x
        self.target_y = target_y
        self.target_w = target_w
        self.target_h = target_h
        self.on_dismiss = on_dismiss
        self.monitor_idx = monitor_idx

        self.set_title("Take a break")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.stick()

        self.get_style_context().add_class("break-overlay-window")

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.set_default_size(self.target_w, self.target_h)
        self.move(self.target_x, self.target_y)
        if screen:
            self.fullscreen_on_monitor(screen, self.monitor_idx)
        else:
            self.fullscreen()

        self.connect("draw", self._on_draw)
        self.connect("map-event", self._on_map)
        self.connect("key-press-event", self._on_key_press)
        self.connect("button-press-event", self._on_button_press)

        self._build_ui()

    def _on_draw(self, widget, cr):
        # Draw solid opaque dark backdrop across entire screen covering all desktop widgets
        cr.set_source_rgb(0.04, 0.06, 0.10)
        cr.paint()
        return False

    def _on_map(self, widget, event):
        self.set_keep_above(True)
        screen = self.get_screen()
        if screen:
            self.fullscreen_on_monitor(screen, self.monitor_idx)
        else:
            self.fullscreen()
        return False

    def _on_key_press(self, widget, event):
        if event.keyval in [Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space]:
            if self.on_dismiss:
                self.on_dismiss()
            return True
        return False

    def _on_button_press(self, widget, event):
        return False

    def _build_ui(self):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        container.get_style_context().add_class("break-overlay-container")
        container.set_valign(Gtk.Align.FILL)
        container.set_halign(Gtk.Align.FILL)

        center_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        center_card.get_style_context().add_class("break-card")
        center_card.set_valign(Gtk.Align.CENTER)
        center_card.set_halign(Gtk.Align.CENTER)
        center_card.set_hexpand(True)
        center_card.set_vexpand(True)

        # Friendly break icon
        lbl_icon = Gtk.Label()
        lbl_icon.set_markup("<span font='64'>☕</span>")
        center_card.pack_start(lbl_icon, False, False, 0)

        # Main Title
        lbl_title = Gtk.Label()
        lbl_title.set_markup("<span font='42' weight='heavy' color='#10b981'>Take a break.</span>")
        lbl_title.get_style_context().add_class("break-title")
        center_card.pack_start(lbl_title, False, False, 0)

        # Subtitle
        lbl_sub = Gtk.Label()
        lbl_sub.set_markup("<span font='20' weight='medium' color='#f3f4f6'>Focus session complete! Time to relax :)</span>")
        lbl_sub.get_style_context().add_class("break-subtitle")
        center_card.pack_start(lbl_sub, False, False, 0)

        # Countdown pill
        self.lbl_countdown = Gtk.Label()
        self.lbl_countdown.set_markup("<span font='16' weight='bold' color='#a7f3d0'>Break ends in 05:00</span>")
        self.lbl_countdown.get_style_context().add_class("break-countdown-pill")
        center_card.pack_start(self.lbl_countdown, False, False, 8)

        # Early dismiss button
        btn_dismiss = Gtk.Button(label="Dismiss early (or press Esc / Space)")
        btn_dismiss.get_style_context().add_class("break-dismiss-btn")
        btn_dismiss.connect("clicked", lambda b: self.on_dismiss() if self.on_dismiss else None)
        center_card.pack_start(btn_dismiss, False, False, 0)

        container.pack_start(center_card, True, True, 0)
        self.add(container)

    def update_countdown(self, seconds_left: int):
        mins = max(0, seconds_left) // 60
        secs = max(0, seconds_left) % 60
        time_str = f"{mins:02d}:{secs:02d}"
        self.lbl_countdown.set_markup(f"<span font='16' weight='bold' color='#a7f3d0'>Break ends in {time_str}</span>")


import shutil

SCRIPT_DIR = Path(__file__).parent.resolve()
LOCAL_CONFIG = SCRIPT_DIR / "config.json"
CONFIG_DIR = Path.home() / ".config" / "pomodoro-widget"
CONFIG_FILE = CONFIG_DIR / "config.json"

candidate_daily = [
    Path.home() / "SE/toolbox/daily",
    SCRIPT_DIR.parent.parent / "daily",
    SCRIPT_DIR.parent / "daily",
    SCRIPT_DIR / "Daily"
]
DEFAULT_DAILY_DIR = next((d for d in candidate_daily if d.exists()), Path.home() / "SE/toolbox/daily")

def _resolve_bin(name: str) -> str:
    local_path = SCRIPT_DIR / "bin" / name
    parent_bin = SCRIPT_DIR.parent / "bin" / name
    if local_path.is_file() and os.access(local_path, os.X_OK):
        return str(local_path)
    if parent_bin.is_file() and os.access(parent_bin, os.X_OK):
        return str(parent_bin)
    system_path = shutil.which(name)
    if system_path:
        return system_path
    user_bin = Path.home() / ".local" / "bin" / name
    if user_bin.is_file() and os.access(user_bin, os.X_OK):
        return str(user_bin)
    return str(local_path)

CLI_BIN = _resolve_bin("pomodoro-cli")
GUARD_BIN = _resolve_bin("pomodoro-guard")
WRAPPER_BIN = _resolve_bin("pomodoro")

DEFAULT_CONFIG = {
    "x": 4104,
    "y": 155,
    "width": 360,
    "height": 223,
    "always_on_top": False,
    "auto_start_next": True,
    "idle_pause_enabled": True,
    "idle_threshold_seconds": 60,
    "restore_idle_seconds": False,
    "work_duration_minutes": 25,
    "break_duration_minutes": 5,
}

import traceback

def send_guard_ipc(action: str, payload: dict = None) -> dict:
    """Sends JSON-line IPC request directly to pomodoro-guard Unix domain socket."""
    req = {"action": action}
    if payload is not None:
        req["payload"] = payload
    for sock_path in ["/run/pomodoro-input-guard.sock", "/tmp/pomodoro-input-guard.sock"]:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.8)
            s.connect(sock_path)
            s.sendall(json.dumps(req).encode("utf-8") + b"\n")
            data = s.recv(4096)
            s.close()
            if data:
                return json.loads(data.decode("utf-8"))
        except Exception:
            continue
    return None


class ActivityMonitor:
    """Monitors system-wide user inactivity and activity via Mutter DBus interface."""
    def __init__(self, on_active_callback=None):
        self.on_active_callback = on_active_callback
        self._proxy = None
        self._bus = None
        self._active_watch_id = None
        self._sub_id = None
        self._init_dbus()

    def _init_dbus(self):
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._proxy = Gio.DBusProxy.new_sync(
                self._bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.gnome.Mutter.IdleMonitor",
                "/org/gnome/Mutter/IdleMonitor/Core",
                "org.gnome.Mutter.IdleMonitor",
                None,
            )
            self._sub_id = self._bus.signal_subscribe(
                "org.gnome.Mutter.IdleMonitor",
                "org.gnome.Mutter.IdleMonitor",
                "WatchFired",
                "/org/gnome/Mutter/IdleMonitor/Core",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_watch_fired,
                None,
            )
        except Exception as e:
            print(f"Warning: Could not initialize Mutter IdleMonitor: {e}")
            self._proxy = None

    def _on_watch_fired(self, connection, sender_name, object_path, interface_name, signal_name, parameters, user_data):
        if not parameters:
            return
        try:
            watch_id = parameters.unpack()[0]
            if self._active_watch_id is not None and watch_id == self._active_watch_id:
                self.remove_active_watch()
                if self.on_active_callback:
                    GLib.idle_add(self.on_active_callback)
        except Exception as e:
            print(f"Error handling IdleMonitor watch signal: {e}")

    def watch_for_user_active(self, callback=None):
        """Arm a watch that fires immediately when user touches keyboard or mouse."""
        if callback:
            self.on_active_callback = callback
        if self._proxy is None:
            self._init_dbus()
        if self._proxy is not None and self._active_watch_id is None:
            try:
                self._active_watch_id = self._proxy.AddUserActiveWatch()
            except Exception as e:
                print(f"Warning: AddUserActiveWatch failed: {e}")
                self._active_watch_id = None

    def remove_active_watch(self):
        """Disarm the active user watch."""
        if self._proxy is not None and self._active_watch_id is not None:
            try:
                self._proxy.RemoveWatch("(u)", self._active_watch_id)
            except Exception:
                pass
            self._active_watch_id = None

    def get_idle_seconds(self) -> float:
        """Returns number of seconds since last user input across all devices."""
        if self._proxy is None:
            self._init_dbus()
        if self._proxy is not None:
            try:
                idle_ms = self._proxy.GetIdletime()
                return idle_ms / 1000.0
            except Exception:
                self._proxy = None
                return 0.0
        return 0.0


class PomodoroStats:
    def __init__(self, work_sessions: int = 0, breaks_taken: int = 0, pauses: int = 0, restarts: int = 0, work_minutes: int = 25):
        self.work_sessions = work_sessions
        self.breaks_taken = breaks_taken
        self.pauses = pauses
        self.restarts = restarts
        self.work_minutes = work_minutes

    @property
    def total_focus_minutes(self) -> int:
        return self.work_sessions * self.work_minutes


class PomodoroDailyStore:
    """Manages reading and writing daily Pomodoro data in ~/SE/toolbox/daily/YYYY-MM-DD.md."""
    def __init__(self, daily_dir: Path = DEFAULT_DAILY_DIR, work_minutes: int = 25):
        self.daily_dir = Path(daily_dir)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.work_minutes = work_minutes
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.last_mtime = 0.0
        self.stats = PomodoroStats(work_minutes=self.work_minutes)
        self.load_today()

    def get_file_path(self, date_str: str = None) -> Path:
        if not date_str:
            date_str = self.current_date
        p = self.daily_dir / f"{date_str}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def load_today(self) -> PomodoroStats:
        target_path = self.get_file_path(self.current_date)
        if not target_path.exists():
            self._initialize_today_file(target_path)
        else:
            self._ensure_section_exists(target_path)

        try:
            self.last_mtime = target_path.stat().st_mtime
        except Exception:
            self.last_mtime = 0.0

        self.stats = self._read_stats_from_file(target_path)
        return self.stats

    def _find_incomplete_work_from_previous_day(self) -> list:
        md_files = sorted(
            [f for f in self.daily_dir.glob("*.md") if f.stem < self.current_date and re.match(r"^\d{4}-\d{2}-\d{2}$", f.stem)],
            key=lambda x: x.stem
        )
        if not md_files:
            return []

        last_file = md_files[-1]
        incomplete = []
        try:
            with open(last_file, "r", encoding="utf-8") as f:
                in_work_section = False
                task_regex = re.compile(r"^\s*-\s*\[([ ])\]\s*(.+)$")
                header_regex = re.compile(r"^##\s+(.+)$")

                for line in f:
                    hm = header_regex.match(line)
                    if hm:
                        header_text = hm.group(1).lower()
                        in_work_section = ("work" in header_text or "today" in header_text) and not ("diet" in header_text or "food" in header_text or "nutrition" in header_text)
                        continue

                    if in_work_section:
                        m = task_regex.match(line)
                        if m:
                            incomplete.append(m.group(2).strip())
        except Exception as e:
            print(f"Error reading previous day work tasks: {e}")
        return incomplete

    def _initialize_today_file(self, target_path: Path):
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "a+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0, os.SEEK_END)
                    if f.tell() > 0:
                        self.last_mtime = target_path.stat().st_mtime
                        return

                    date_obj = datetime.strptime(self.current_date, "%Y-%m-%d")
                    formatted_date = date_obj.strftime("%A, %d %B %Y")

                    carry_over = True
                    work_cfg_file = Path.home() / ".config" / "daily-todo-widget" / "config.json"
                    if work_cfg_file.exists():
                        try:
                            with open(work_cfg_file, "r", encoding="utf-8") as wf:
                                carry_over = json.load(wf).get("carry_over_incomplete", True)
                        except Exception:
                            pass

                    carried_work = []
                    if carry_over:
                        carried_work = self._find_incomplete_work_from_previous_day()

                    diet_lines = []
                    template_file = self.daily_dir / "templates" / "diet_template.json"
                    daily_items = [
                        "Pumpkin seeds", "Chia seeds", "Roasted chana",
                        "Almonds & Walnuts", "Monohydrate creatine",
                        "Moringa powder in dish", "Curd", "One glass of milk"
                    ]
                    sunday_items = ["D3 capsule on sunday"]
                    if template_file.exists():
                        try:
                            with open(template_file, "r", encoding="utf-8") as tf:
                                tdata = json.load(tf)
                                daily_items = tdata.get("daily_items", daily_items)
                                sunday_items = tdata.get("sunday_items", sunday_items)
                        except Exception:
                            pass

                    deduped_diet = []
                    for item in daily_items:
                        if item not in deduped_diet:
                            deduped_diet.append(item)
                    if date_obj.weekday() == 6:
                        for item in sunday_items:
                            if item not in deduped_diet:
                                deduped_diet.append(item)
                    diet_lines = [f"- [ ] {item}\n" for item in deduped_diet]

                    routines_lines = []
                    rt_template = self.daily_dir / "templates" / "routines_template.json"
                    rt_items = ["Check emails", "Bath & freshen up", "Check Instagram", "Brush teeth (night)"]
                    if rt_template.exists():
                        try:
                            with open(rt_template, "r", encoding="utf-8") as rf:
                                rt_data = json.load(rf)
                                rt_items = rt_data.get("daily_items", rt_items)
                        except Exception:
                            pass
                    routines_lines = [f"- [ ] {item}\n" for item in rt_items]

                    content = [
                        f"# Daily Tasks — {formatted_date}\n\n",
                        "## 💼 Work\n"
                    ]
                    for w in carried_work:
                        content.append(f"- [ ] {w}\n")
                    content.append("\n## 🥗 Diet & Nutrition\n")
                    content.extend(diet_lines)
                    content.append("\n## 🔄 Daily Routines\n")
                    content.extend(routines_lines)
                    content.extend([
                        "\n## 🍅 Pomodoro Data\n",
                        f"- Work Sessions ({self.work_minutes}m): 0\n",
                        "- Breaks Taken: 0\n",
                        "- Pauses: 0\n",
                        "- Restarts: 0\n"
                    ])

                    f.seek(0)
                    f.writelines(content)
                    f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            self.last_mtime = target_path.stat().st_mtime
        except Exception as e:
            print(f"Error initializing today's file: {e}")

    def _ensure_section_exists(self, target_path: Path):
        try:
            if not target_path.exists():
                self._initialize_today_file(target_path)
                return
            with open(target_path, "r+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    content = f.read()
                    if not re.search(r"^##\s+.*Pomodoro", content, re.MULTILINE | re.IGNORECASE):
                        if not content.endswith("\n\n"):
                            content += "\n" if content.endswith("\n") else "\n\n"
                        content += f"## 🍅 Pomodoro Data\n- Work Sessions ({self.work_minutes}m): 0\n- Breaks Taken: 0\n- Pauses: 0\n- Restarts: 0\n"
                        f.seek(0)
                        f.write(content)
                        f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            self.last_mtime = target_path.stat().st_mtime
        except Exception as e:
            print(f"Error ensuring pomodoro section: {e}")

    def _read_stats_from_file(self, file_path: Path) -> PomodoroStats:
        work_sessions = 0
        breaks_taken = 0
        pauses = 0
        restarts = 0

        header_regex = re.compile(r"^##\s+(.+)$")
        in_pomo = False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    for line in f:
                        hm = header_regex.match(line)
                        if hm:
                            in_pomo = "pomodoro" in hm.group(1).lower()
                            continue

                        if in_pomo:
                            m_work = re.search(r"(?:work|completed|focus)\s*sessions?(?:\s*\(.*?\))?:\s*(\d+)", line, re.IGNORECASE)
                            if m_work:
                                work_sessions = int(m_work.group(1))

                            m_break = re.search(r"breaks?(?:\s*taken)?:\s*(\d+)", line, re.IGNORECASE)
                            if m_break:
                                breaks_taken = int(m_break.group(1))

                            m_pause = re.search(r"pauses?(?:\s*count)?:\s*(\d+)", line, re.IGNORECASE)
                            if m_pause:
                                pauses = int(m_pause.group(1))

                            m_restart = re.search(r"restarts?(?:\s*count)?:\s*(\d+)", line, re.IGNORECASE)
                            if m_restart:
                                restarts = int(m_restart.group(1))
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as e:
            print(f"Error reading pomodoro stats: {e}")

        return PomodoroStats(work_sessions, breaks_taken, pauses, restarts, self.work_minutes)

    def save_stats(self):
        target_path = self.get_file_path(self.current_date)
        if not target_path.exists():
            self._initialize_today_file(target_path)
        else:
            self._ensure_section_exists(target_path)

        header_regex = re.compile(r"^##\s+(.+)$")
        new_lines = []
        in_pomo = False

        mins_str = f" ({self.stats.total_focus_minutes} mins)" if self.stats.total_focus_minutes > 0 else ""
        work_line = f"- Work Sessions ({self.work_minutes}m): {self.stats.work_sessions}{mins_str}\n"
        break_line = f"- Breaks Taken: {self.stats.breaks_taken}\n"
        pause_line = f"- Pauses: {self.stats.pauses}\n"
        restart_line = f"- Restarts: {self.stats.restarts}\n"

        seen_work = False
        seen_break = False
        seen_pause = False
        seen_restart = False

        try:
            with open(target_path, "r+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    lines = f.readlines()

                    for line in lines:
                        hm = header_regex.match(line)
                        if hm:
                            if in_pomo:
                                if not seen_work:
                                    new_lines.append(work_line)
                                if not seen_break:
                                    new_lines.append(break_line)
                                if not seen_pause:
                                    new_lines.append(pause_line)
                                if not seen_restart:
                                    new_lines.append(restart_line)
                                seen_work = seen_break = seen_pause = seen_restart = True
                            in_pomo = "pomodoro" in hm.group(1).lower()
                            new_lines.append(line)
                            continue

                        if in_pomo:
                            if re.search(r"^\s*-\s*(?:work|completed|focus)\s*sessions?", line, re.IGNORECASE):
                                new_lines.append(work_line)
                                seen_work = True
                                continue
                            elif re.search(r"^\s*-\s*breaks?(?:\s*taken)?", line, re.IGNORECASE):
                                new_lines.append(break_line)
                                seen_break = True
                                continue
                            elif re.search(r"^\s*-\s*pauses?", line, re.IGNORECASE):
                                new_lines.append(pause_line)
                                seen_pause = True
                                continue
                            elif re.search(r"^\s*-\s*restarts?", line, re.IGNORECASE):
                                new_lines.append(restart_line)
                                seen_restart = True
                                continue

                        new_lines.append(line)

                    if in_pomo:
                        if not seen_work:
                            new_lines.append(work_line)
                        if not seen_break:
                            new_lines.append(break_line)
                        if not seen_pause:
                            new_lines.append(pause_line)
                        if not seen_restart:
                            new_lines.append(restart_line)

                    f.seek(0)
                    f.writelines(new_lines)
                    f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

            self.last_mtime = target_path.stat().st_mtime
        except Exception as e:
            print(f"Error saving pomodoro stats: {e}")

    def record_work_session(self):
        self.stats.work_sessions += 1
        self.save_stats()

    def record_break(self):
        self.stats.breaks_taken += 1
        self.save_stats()

    def record_pause(self):
        self.stats.pauses += 1
        self.save_stats()

    def record_restart(self):
        self.stats.restarts += 1
        self.save_stats()

    def check_date_rollover(self) -> bool:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if today_str != self.current_date:
            self.current_date = today_str
            return True
        return False

    def check_file_changed(self) -> bool:
        target_path = self.get_file_path(self.current_date)
        if not target_path.exists():
            return False
        try:
            mtime = target_path.stat().st_mtime
            if mtime > self.last_mtime + 0.1:
                return True
        except Exception:
            pass
        return False


class PomodoroWidget:
    def __init__(self):
        self.config = self._load_config()
        self.work_minutes = int(self.config.get("work_duration_minutes", self.config.get("work_minutes", 25)))
        self.break_minutes = int(self.config.get("break_duration_minutes", self.config.get("break_minutes", 5)))

        self.work_seconds = self.work_minutes * 60
        self.break_seconds = self.break_minutes * 60
        self.work_str = f"{self.work_minutes:02d}:00"
        self.break_str = f"{self.break_minutes:02d}:00"

        self.target_x = self.config.get("x", 4104)
        self.target_y = self.config.get("y", 155)
        self._initial_positioned = False

        self.data_store = PomodoroDailyStore(work_minutes=self.work_minutes)
        self.prev_daemon_state = None
        self.prev_rem_sec = self.work_seconds
        self.break_popups = []
        self.break_popup_timer_id = None
        self.break_countdown_left = self.break_seconds

        self.state = "idle"  # "work", "break", "paused", "idle"
        self.paused_state = "work"
        self.paused_remaining_seconds = self.work_seconds
        self.paused_total_seconds = self.work_seconds
        self.remaining_str = self.work_str
        self.remaining_seconds = self.work_seconds
        self.total_seconds = self.work_seconds
        self.input_locked = False
        self.user_stopped = False
        self._is_pinned_top = self.config.get("always_on_top", False)
        self._save_timer_id = None
        self._is_querying = False
        self._ui_restarted = False
        self._consecutive_status_failures = 0

        # Automatic Inactivity (Idle) Pause & Resume Support
        self.idle_pause_enabled = self.config.get("idle_pause_enabled", True)
        self.idle_threshold_seconds = self.config.get("idle_threshold_seconds", 60)
        self.restore_idle_seconds = self.config.get("restore_idle_seconds", False)
        self.idle_paused = False
        self.activity_monitor = ActivityMonitor(on_active_callback=self._on_user_active)

        self._init_window()
        self._load_css()
        self._build_ui()

        # Start pomodoro automatically on launch if not user-stopped
        self._ensure_running_on_start()

        # Initial status query
        self._update_status()

        # Poll status every 1 second
        GLib.timeout_add_seconds(1, self._update_status)

    def _load_config(self) -> dict:
        target = None
        if CONFIG_FILE.exists():
            target = CONFIG_FILE
        elif LOCAL_CONFIG.exists():
            target = LOCAL_CONFIG

        if target:
            try:
                with open(target, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    merged = DEFAULT_CONFIG.copy()
                    merged.update(cfg)
                    return merged
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def _save_config(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            for path in [CONFIG_FILE, LOCAL_CONFIG]:
                try:
                    tmp_path = path.with_suffix(".tmp")
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump(self.config, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, path)
                except Exception:
                    pass
        except Exception:
            pass

    def _init_window(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Pomodoro Widget")
        self.window.set_decorated(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_app_paintable(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.window.stick()

        self._apply_layer()

        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.window.set_visual(visual)

        self.window.set_default_size(self.config.get("width", 360), self.config.get("height", 223))
        self.window.move(self.target_x, self.target_y)

        self.window.connect("map-event", self._on_map)
        self.window.connect("configure-event", self._on_configure)
        self.window.connect("destroy", Gtk.main_quit)

    def _on_map(self, widget, event):
        self.window.move(self.target_x, self.target_y)
        GLib.timeout_add(150, self._apply_initial_position)
        return False

    def _apply_initial_position(self):
        self.window.move(self.target_x, self.target_y)
        self._apply_layer()
        self._initial_positioned = True
        return False

    def _apply_layer(self):
        gdk_win = self.window.get_window()
        if self._is_pinned_top:
            self.window.set_keep_above(True)
            self.window.set_keep_below(False)
            if gdk_win:
                gdk_win.raise_()
        else:
            self.window.set_keep_above(False)
            self.window.set_keep_below(True)
            if gdk_win:
                gdk_win.lower()
            else:
                GLib.idle_add(lambda: self.window.get_window().lower() if self.window.get_window() else None)

    def _load_css(self):
        css = b"""
        window {
            background-color: transparent;
        }
        .pomo-card {
            background-color: rgba(18, 20, 26, 0.82);
            border: 1px solid rgba(255, 255, 255, 0.13);
            border-radius: 20px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55);
            padding: 14px 16px;
        }
        .pomo-header {
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 6px;
            margin-bottom: 6px;
        }
        .pomo-title {
            font-size: 12px;
            font-weight: bold;
            color: #d1d5db;
        }
        .badge-work {
            background-color: rgba(239, 68, 68, 0.22);
            color: #fca5a5;
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
            border: 1px solid rgba(239, 68, 68, 0.4);
        }
        .badge-break {
            background-color: rgba(16, 185, 129, 0.22);
            color: #6ee7b7;
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
            border: 1px solid rgba(16, 185, 129, 0.4);
        }
        .badge-paused {
            background-color: rgba(245, 158, 11, 0.22);
            color: #fcd34d;
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
            border: 1px solid rgba(245, 158, 11, 0.4);
        }
        .badge-idle {
            background-color: rgba(156, 163, 175, 0.18);
            color: #9ca3af;
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
            border: 1px solid rgba(156, 163, 175, 0.25);
        }
        .pomo-timer {
            font-size: 38px;
            font-weight: bold;
            color: #ffffff;
            margin-top: 2px;
            margin-bottom: 4px;
        }
        .progress-bar-fill {
            background-color: #ef4444;
            border-radius: 4px;
            min-height: 4px;
        }
        .progress-bar-break {
            background-color: #10b981;
            border-radius: 4px;
            min-height: 4px;
        }
        .progress-bar-paused {
            background-color: #f59e0b;
            border-radius: 4px;
            min-height: 4px;
        }
        .btn-work {
            background-color: #ef4444;
            color: white;
            border: none;
            border-radius: 9px;
            padding: 6px 10px;
            font-size: 11px;
            font-weight: bold;
        }
        .btn-work:hover {
            background-color: #dc2626;
        }
        .btn-pause {
            background-color: #f59e0b;
            color: #1f2937;
            border: none;
            border-radius: 9px;
            padding: 6px 10px;
            font-size: 11px;
            font-weight: bold;
        }
        .btn-pause:hover {
            background-color: #d97706;
        }
        .btn-break {
            background-color: #10b981;
            color: white;
            border: none;
            border-radius: 9px;
            padding: 6px 10px;
            font-size: 11px;
            font-weight: bold;
        }
        .btn-break:hover {
            background-color: #059669;
        }
        .btn-secondary {
            background-color: rgba(255, 255, 255, 0.08);
            color: #d1d5db;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 9px;
            padding: 6px 10px;
            font-size: 11px;
            font-weight: bold;
        }
        .btn-secondary:hover {
            background-color: rgba(255, 255, 255, 0.15);
        }
        .btn-icon {
            background: transparent;
            border: none;
            color: #9ca3af;
            padding: 2px 5px;
            border-radius: 6px;
            font-size: 12px;
        }
        .btn-icon:hover {
            background-color: rgba(255, 255, 255, 0.1);
            color: #ffffff;
        }
        .pomo-stats-box {
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 9px;
            padding: 4px 8px;
            margin-top: 5px;
            margin-bottom: 3px;
        }
        .pomo-stat-sep {
            color: rgba(255, 255, 255, 0.18);
            font-size: 10px;
        }

        /* --- Fullscreen Break Overlay Styling --- */
        window.break-overlay-window {
            background-color: #0b0f19;
        }
        .break-overlay-container {
            background-color: #0b0f19;
        }
        .break-card {
            background-color: #151a24;
            border: 2px solid #10b981;
            border-radius: 24px;
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.95);
            padding: 44px 64px;
        }
        .break-title {
            font-size: 42px;
            font-weight: 800;
            color: #10b981;
            letter-spacing: 0.5px;
        }
        .break-subtitle {
            font-size: 20px;
            font-weight: 500;
            color: #f3f4f6;
        }
        .break-countdown-pill {
            background-color: #202738;
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 16px;
            padding: 8px 24px;
            color: #a7f3d0;
            font-size: 17px;
            font-weight: 700;
        }
        .break-dismiss-btn {
            background-color: #262e3d;
            color: #e5e7eb;
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 12px;
            padding: 10px 28px;
            font-size: 14px;
            font-weight: 600;
        }
        .break-dismiss-btn:hover {
            background-color: rgba(16, 185, 129, 0.25);
            border-color: #10b981;
            color: #ffffff;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.get_style_context().add_class("pomo-card")

        # --- HEADER (Draggable) ---
        self.header_event_box = Gtk.EventBox()
        self.header_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.header_event_box.connect("button-press-event", self._on_header_press)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.get_style_context().add_class("pomo-header")

        lbl_icon = Gtk.Label(label="🍅")
        header_box.pack_start(lbl_icon, False, False, 0)

        lbl_title = Gtk.Label(label="Pomodoro")
        lbl_title.get_style_context().add_class("pomo-title")
        header_box.pack_start(lbl_title, False, False, 0)

        # Status Badge
        self.lbl_badge = Gtk.Label(label="IDLE")
        self.lbl_badge.get_style_context().add_class("badge-idle")
        header_box.pack_start(self.lbl_badge, True, True, 0)
        self.lbl_badge.set_xalign(1.0)

        # Pin Button
        self.btn_pin = Gtk.Button(label="📌" if self._is_pinned_top else "📍")
        self.btn_pin.set_tooltip_text("Toggle Always On Top vs Desktop Pinned")
        self.btn_pin.get_style_context().add_class("btn-icon")
        self.btn_pin.connect("clicked", self._on_toggle_pin)
        header_box.pack_start(self.btn_pin, False, False, 0)

        self.header_event_box.add(header_box)
        self.card.pack_start(self.header_event_box, False, False, 0)

        # --- COUNTDOWN DISPLAY ---
        self.lbl_timer = Gtk.Label(label=self.work_str)
        self.lbl_timer.get_style_context().add_class("pomo-timer")
        self.card.pack_start(self.lbl_timer, False, False, 0)

        # --- PROGRESS BAR ---
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(1.0)
        self.progress_bar.get_style_context().add_class("progress-bar-fill")
        self.card.pack_start(self.progress_bar, False, False, 4)

        # --- DAILY POMODORO STATS ---
        stats_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        stats_box.get_style_context().add_class("pomo-stats-box")
        stats_box.set_halign(Gtk.Align.CENTER)

        self.lbl_stat_work = Gtk.Label()
        self.lbl_stat_work.set_tooltip_text(f"Completed {self.work_minutes}m work sessions today")
        stats_box.pack_start(self.lbl_stat_work, False, False, 2)

        sep1 = Gtk.Label(label="•")
        sep1.get_style_context().add_class("pomo-stat-sep")
        stats_box.pack_start(sep1, False, False, 0)

        self.lbl_stat_break = Gtk.Label()
        self.lbl_stat_break.set_tooltip_text("Breaks taken today")
        stats_box.pack_start(self.lbl_stat_break, False, False, 2)

        sep2 = Gtk.Label(label="•")
        sep2.get_style_context().add_class("pomo-stat-sep")
        stats_box.pack_start(sep2, False, False, 0)

        self.lbl_stat_pause = Gtk.Label()
        self.lbl_stat_pause.set_tooltip_text("Times paused today")
        stats_box.pack_start(self.lbl_stat_pause, False, False, 2)

        sep3 = Gtk.Label(label="•")
        sep3.get_style_context().add_class("pomo-stat-sep")
        stats_box.pack_start(sep3, False, False, 0)

        self.lbl_stat_restart = Gtk.Label()
        self.lbl_stat_restart.set_tooltip_text("Times restarted today")
        stats_box.pack_start(self.lbl_stat_restart, False, False, 2)

        self.card.pack_start(stats_box, False, False, 0)
        self._update_stats_ui()

        # --- ACTION BUTTONS ---
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        btn_box.set_margin_top(6)

        # Work / Restart button
        self.btn_work = Gtk.Button(label="▶ Focus")
        self.btn_work.get_style_context().add_class("btn-work")
        self.btn_work.connect("clicked", self._on_work_clicked)
        btn_box.pack_start(self.btn_work, True, True, 0)

        # Pause / Resume Button
        self.btn_pause = Gtk.Button(label="⏸ Pause")
        self.btn_pause.get_style_context().add_class("btn-pause")
        self.btn_pause.connect("clicked", self._on_pause_clicked)
        btn_box.pack_start(self.btn_pause, True, True, 0)

        # Break button
        self.btn_break = Gtk.Button(label="☕ Break")
        self.btn_break.get_style_context().add_class("btn-break")
        self.btn_break.connect("clicked", self._on_break_clicked)
        btn_box.pack_start(self.btn_break, False, False, 0)

        # Stop button
        btn_stop = Gtk.Button(label="⏹")
        btn_stop.set_tooltip_text("Stop / Reset")
        btn_stop.get_style_context().add_class("btn-secondary")
        btn_stop.connect("clicked", self._on_stop_clicked)
        btn_box.pack_start(btn_stop, False, False, 0)

        self.card.pack_start(btn_box, False, False, 0)

        self.window.add(self.card)

    def _update_stats_ui(self):
        s = self.data_store.stats
        mins_str = f" ({s.total_focus_minutes}m)" if s.total_focus_minutes > 0 else ""
        self.lbl_stat_work.set_markup(f"<span color='#9ca3af'>🎯</span> <span color='#f3f4f6' weight='bold'>{s.work_sessions}</span><span size='smaller' color='#9ca3af'>{mins_str}</span>")
        self.lbl_stat_break.set_markup(f"<span color='#9ca3af'>☕</span> <span color='#f3f4f6' weight='bold'>{s.breaks_taken}</span>")
        self.lbl_stat_pause.set_markup(f"<span color='#9ca3af'>⏸</span> <span color='#f3f4f6' weight='bold'>{s.pauses}</span>")
        self.lbl_stat_restart.set_markup(f"<span color='#9ca3af'>🔄</span> <span color='#f3f4f6' weight='bold'>{s.restarts}</span>")

    def _on_header_press(self, widget, event):
        if event.button == 1:
            self.window.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )

    def _on_configure(self, widget, event):
        if not self._initial_positioned:
            return
        x, y = self.window.get_position()
        w, h = self.window.get_size()
        if x > -10000 and y > -10000:
            self.config["x"] = x
            self.config["y"] = y
            self.config["width"] = w
            self.config["height"] = h
            self.target_x = x
            self.target_y = y
            if self._save_timer_id:
                GLib.source_remove(self._save_timer_id)
            self._save_timer_id = GLib.timeout_add(500, self._debounced_save_config)

    def _debounced_save_config(self):
        self._save_config()
        self._save_timer_id = None
        return False

    def _on_toggle_pin(self, button):
        self._is_pinned_top = not self._is_pinned_top
        self.config["always_on_top"] = self._is_pinned_top
        self.btn_pin.set_label("📌" if self._is_pinned_top else "📍")
        self._apply_layer()
        self._save_config()

    def _ensure_guard(self):
        res = subprocess.run(["pgrep", "-f", "pomodoro-guard"], capture_output=True)
        if res.returncode != 0:
            subprocess.Popen([GUARD_BIN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(0.2)

    def _ensure_running_on_start(self):
        try:
            res = subprocess.run([CLI_BIN, "status"], capture_output=True, text=True, timeout=0.8)
            if res.returncode != 0 or "IDLE" in res.stdout:
                self._ensure_guard()
                subprocess.run([CLI_BIN, "start-work", str(self.work_minutes)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            self._ensure_guard()
            subprocess.run([CLI_BIN, "start-work", str(self.work_minutes)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _trigger_idle_pause(self):
        """Automatically pauses focus session when system has been inactive for >= 60 seconds."""
        if self.state != "work" or self.prev_daemon_state != "work" or self.idle_paused or self.remaining_seconds <= 5:
            return
        print(f"[Pomodoro] System inactive for >= {self.idle_threshold_seconds}s. Auto-pausing work session.")
        self.idle_paused = True
        self.paused_state = "work"
        if self.restore_idle_seconds:
            self.paused_remaining_seconds = min(self.total_seconds, self.remaining_seconds + self.idle_threshold_seconds)
        else:
            self.paused_remaining_seconds = self.remaining_seconds
        self.paused_total_seconds = self.total_seconds

        send_guard_ipc("EmergencyUnlock")
        subprocess.run([CLI_BIN, "emergency-unlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self.state = "paused"
        self.activity_monitor.watch_for_user_active(self._on_user_active)
        self._apply_state("paused", self.remaining_str, self.paused_remaining_seconds, self.total_seconds, False)

    def _on_user_active(self):
        """Called immediately when user input (keyboard or mouse) is detected while idle-paused."""
        if self.state == "paused" and self.idle_paused:
            print("[Pomodoro] System activity (keyboard/mouse) detected. Resuming focus session.")
            self.idle_paused = False
            self.user_stopped = False
            self.activity_monitor.remove_active_watch()
            self._ensure_guard()

            dur_secs = max(1, self.paused_remaining_seconds)
            self.total_seconds = self.paused_total_seconds

            res = send_guard_ipc("StartWork", {"duration_secs": dur_secs})
            if not res or res.get("response") != "Ok":
                subprocess.run([CLI_BIN, "start-work", f"{dur_secs}s"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            self.state = "work"
            self._update_status()

    def _on_work_clicked(self, button):
        self.user_stopped = False
        self.idle_paused = False
        self.activity_monitor.remove_active_watch()
        self._close_break_popups()
        self._ensure_guard()
        if self.state == "break" or self.btn_work.get_label() == "Restart":
            if self.state == "work":
                self._ui_restarted = True
                self.data_store.record_restart()
                self._update_stats_ui()
            send_guard_ipc("EmergencyUnlock")
            subprocess.run([CLI_BIN, "emergency-unlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        res = send_guard_ipc("StartWork", {"duration_secs": self.work_seconds})
        if not res or res.get("response") != "Ok":
            subprocess.run([CLI_BIN, "start-work", str(self.work_minutes)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state = "work"
        self.remaining_seconds = self.work_seconds
        self.total_seconds = self.work_seconds
        self.remaining_str = self.work_str
        self.prev_daemon_state = "work"
        self.prev_rem_sec = self.work_seconds
        self._update_status()

    def _on_break_clicked(self, button):
        self.user_stopped = False
        self.idle_paused = False
        self.activity_monitor.remove_active_watch()
        self._ensure_guard()
        send_guard_ipc("EmergencyUnlock")
        subprocess.run([CLI_BIN, "emergency-unlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        res = send_guard_ipc("StartBreak", {"duration_secs": self.break_seconds})
        if not res or res.get("response") != "Ok":
            subprocess.run([CLI_BIN, "start-break", str(self.break_minutes)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state = "break"
        self.remaining_seconds = self.break_seconds
        self.total_seconds = self.break_seconds
        self.remaining_str = self.break_str
        self.prev_daemon_state = "break"
        self.prev_rem_sec = self.break_seconds
        self.data_store.record_break()
        self._update_stats_ui()
        self._on_break_start()
        self._update_status()

    def _on_pause_clicked(self, button):
        if self.state == "paused":
            # Resume
            self.user_stopped = False
            self.idle_paused = False
            self.activity_monitor.remove_active_watch()
            self._ensure_guard()
            dur_secs = max(1, self.paused_remaining_seconds)
            self.total_seconds = self.paused_total_seconds
            if self.paused_state == "break":
                res = send_guard_ipc("StartBreak", {"duration_secs": dur_secs})
                if not res or res.get("response") != "Ok":
                    subprocess.run([CLI_BIN, "start-break", f"{dur_secs}s"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.state = "break"
                self.prev_daemon_state = "break"
                self._on_break_start()
            else:
                res = send_guard_ipc("StartWork", {"duration_secs": dur_secs})
                if not res or res.get("response") != "Ok":
                    subprocess.run([CLI_BIN, "start-work", f"{dur_secs}s"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.state = "work"
                self.prev_daemon_state = "work"
            self._update_status()
        else:
            # Manual Pause
            self.idle_paused = False
            self.activity_monitor.remove_active_watch()
            self.paused_state = self.state if self.state in ["work", "break"] else "work"
            self.paused_remaining_seconds = self.remaining_seconds
            self.paused_total_seconds = self.total_seconds
            self._close_break_popups()
            send_guard_ipc("EmergencyUnlock")
            subprocess.run([CLI_BIN, "emergency-unlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.state = "paused"
            self.data_store.record_pause()
            self._update_stats_ui()
            self._apply_state("paused", self.remaining_str, self.remaining_seconds, self.total_seconds, False)

    def _on_stop_clicked(self, button):
        self.user_stopped = True
        self.idle_paused = False
        self.activity_monitor.remove_active_watch()
        self._close_break_popups()
        send_guard_ipc("EmergencyUnlock")
        subprocess.run([WRAPPER_BIN, "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state = "idle"
        self.prev_daemon_state = "idle"
        self._apply_state("idle", self.work_str, self.work_seconds, self.work_seconds, False)

    def _dismiss_break(self):
        """Dismisses active break early, unlocks input, and returns immediately to 25m focus."""
        self._close_break_popups()
        send_guard_ipc("EmergencyUnlock")
        subprocess.run([CLI_BIN, "emergency-unlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not self.user_stopped:
            res = send_guard_ipc("StartWork", {"duration_secs": self.work_seconds})
            if not res or res.get("response") != "Ok":
                subprocess.run([CLI_BIN, "start-work", str(self.work_minutes)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.state = "work"
            self.remaining_seconds = self.work_seconds
            self.total_seconds = self.work_seconds
            self.remaining_str = self.work_str
            self.prev_daemon_state = "work"
            self.prev_rem_sec = self.work_seconds
        else:
            self.state = "idle"
            self.remaining_seconds = self.work_seconds
            self.total_seconds = self.work_seconds
            self.remaining_str = self.work_str
            self.prev_daemon_state = "idle"
            self.prev_rem_sec = self.work_seconds
        self._update_status()

    def _on_break_start(self):
        """Triggered when pomodoro break begins: plays triple beep and shows full-screen overlay on each monitor."""
        play_triple_beep()

        self._close_break_popups()
        display = Gdk.Display.get_default()
        if display:
            for i in range(display.get_n_monitors()):
                mon = display.get_monitor(i)
                geom = mon.get_geometry()
                popup = BreakPopupWindow(geom.x, geom.y, geom.width, geom.height, on_dismiss=self._dismiss_break, monitor_idx=i)
                self.break_popups.append(popup)
                popup.show_all()

        self.break_countdown_left = self.remaining_seconds if (self.state == "break" and self.remaining_seconds > 0) else self.break_seconds
        for popup in self.break_popups:
            try:
                popup.update_countdown(self.break_countdown_left)
            except Exception:
                pass
        self.break_popup_timer_id = GLib.timeout_add_seconds(1, self._on_break_popup_tick)

    def _on_break_popup_tick(self):
        self.break_countdown_left -= 1
        if self.break_countdown_left <= 0:
            self._close_break_popups()
            return False
        for popup in self.break_popups:
            try:
                popup.update_countdown(self.break_countdown_left)
            except Exception:
                pass
        return True

    def _close_break_popups(self):
        if self.break_popup_timer_id is not None:
            try:
                GLib.source_remove(self.break_popup_timer_id)
            except Exception:
                pass
            self.break_popup_timer_id = None
        for popup in list(self.break_popups):
            try:
                popup.destroy()
            except Exception:
                pass
        self.break_popups.clear()

    def _on_break_end(self):
        """Triggered when pomodoro break ends: plays triple beep and dismisses overlay."""
        play_triple_beep()
        self._close_break_popups()

    def _update_status(self):
        # Check date rollover or external file changes
        if self.data_store.check_date_rollover() or self.data_store.check_file_changed():
            self.data_store.load_today()
            self._update_stats_ui()

        if self.state == "paused":
            # If auto-paused due to inactivity, check if user activity resumed
            if self.idle_paused:
                idle_sec = self.activity_monitor.get_idle_seconds()
                if idle_sec < 1.5:
                    self._on_user_active()
                    return True
            self._apply_state("paused", self.remaining_str, self.paused_remaining_seconds, self.total_seconds, False)
            return True

        if self._is_querying:
            return True
        self._is_querying = True
        threading.Thread(target=self._query_daemon_worker, daemon=True).start()
        return True

    def _query_daemon_worker(self):
        payload = None
        try:
            status_ipc = send_guard_ipc("GetStatus")
            if status_ipc and status_ipc.get("response") == "Status" and "payload" in status_ipc:
                p = status_ipc["payload"]
                st_type = p.get("state", {}).get("type", "Idle").lower()
                state = "work" if "work" in st_type else ("break" if "break" in st_type else "idle")

                s_nanos = p.get("server_time", {}).get("nanos", 0)
                d_nanos = p.get("active_deadline", {}).get("nanos", 0)
                rem_sec = max(0, int((d_nanos - s_nanos) / 1_000_000_000)) if (d_nanos > s_nanos and state != "idle") else 0
                rem_str = f"{rem_sec // 60:02d}:{rem_sec % 60:02d}"
                locked = p.get("input_locked", False)

                payload = {
                    "ok": True,
                    "ipc": True,
                    "state": state,
                    "remaining": rem_str,
                    "rem_sec": rem_sec,
                    "locked": locked
                }
        except Exception:
            payload = None

        if payload is None:
            try:
                res = subprocess.run([CLI_BIN, "status"], capture_output=True, text=True, timeout=1.5)
                payload = {
                    "ok": (res.returncode == 0),
                    "ipc": False,
                    "stdout": res.stdout if res.returncode == 0 else ""
                }
            except Exception as e:
                payload = {
                    "ok": False,
                    "ipc": False,
                    "stdout": "",
                    "error": str(e)
                }

        GLib.idle_add(self._apply_daemon_status, payload)

    def _apply_daemon_status(self, payload):
        try:
            if not payload["ok"]:
                self._consecutive_status_failures += 1
                if self._consecutive_status_failures >= 3 and not self.user_stopped:
                    self._ensure_running_on_start()
                elif self.user_stopped:
                    self._apply_state("idle", self.work_str, self.work_seconds, self.work_seconds, False)
                return False

            self._consecutive_status_failures = 0

            if payload.get("ipc"):
                state = payload["state"]
                remaining = payload["remaining"]
                rem_sec = payload["rem_sec"]
                locked = payload["locked"]
            else:
                output = payload["stdout"]
                state = "idle"
                remaining = self.work_str
                locked = "YES" in output

                for line in output.splitlines():
                    if "Current State:" in line:
                        val = line.split("Current State:")[1].strip().upper()
                        if "WORKING" in val:
                            state = "work"
                        elif "BREAK" in val:
                            state = "break"
                        else:
                            state = "idle"
                    elif "Remaining Time:" in line:
                        remaining = line.split("Remaining Time:")[1].strip()

                rem_sec = self._parse_seconds(remaining)

            tot_sec = self.break_seconds if state == "break" else self.work_seconds
            if rem_sec > tot_sec:
                tot_sec = rem_sec

            # Initial status query handling
            if self.prev_daemon_state is None:
                self.prev_daemon_state = state
                self.prev_rem_sec = rem_sec
                if state == "break":
                    self._on_break_start()
                self._apply_state(state, remaining, rem_sec, tot_sec, locked)
                return False

            # State transition detection:
            # 1. Transition: WORK -> BREAK (natural completion of 25m focus or break clicked)
            if self.prev_daemon_state == "work" and state == "break":
                if self.prev_rem_sec <= 10:
                    self.data_store.record_work_session()
                self.data_store.record_break()
                self._update_stats_ui()
                self._on_break_start()

            # 2. Transition: BREAK -> WORK (natural completion of 5m break or focus clicked)
            elif self.prev_daemon_state == "break" and state == "work":
                self._on_break_end()

            # 3. Transition: IDLE -> BREAK
            elif self.prev_daemon_state == "idle" and state == "break":
                self.data_store.record_break()
                self._update_stats_ui()
                self._on_break_start()

            # 4. Transition: WORK -> IDLE (work ended)
            elif self.prev_daemon_state == "work" and state == "idle":
                if self.prev_rem_sec <= 5:
                    self.data_store.record_work_session()
                    self._update_stats_ui()
                if not self.user_stopped and self.config.get("auto_start_next", True):
                    # Automatic rollover to 5m break
                    res = send_guard_ipc("StartBreak", {"duration_secs": self.break_seconds})
                    if not res or res.get("response") != "Ok":
                        subprocess.run([CLI_BIN, "start-break", str(self.break_minutes)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    state = "break"
                    rem_sec = self.break_seconds
                    tot_sec = self.break_seconds
                    remaining = self.break_str
                    self.data_store.record_break()
                    self._update_stats_ui()
                    self._on_break_start()

            # 5. Transition: BREAK -> IDLE (5m break deadline arrived)
            elif self.prev_daemon_state == "break" and state == "idle":
                self._on_break_end()
                if not self.user_stopped and self.config.get("auto_start_next", True):
                    # Automatic rollover to 25m work
                    res = send_guard_ipc("StartWork", {"duration_secs": self.work_seconds})
                    if not res or res.get("response") != "Ok":
                        subprocess.run([CLI_BIN, "start-work", str(self.work_minutes)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    state = "work"
                    rem_sec = self.work_seconds
                    tot_sec = self.work_seconds
                    remaining = self.work_str

            # 6. Restart detected during work via CLI
            elif self.prev_daemon_state == "work" and state == "work" and self.prev_rem_sec < (self.work_seconds - 20) and rem_sec >= (self.work_seconds - 5):
                if not self._ui_restarted:
                    self.data_store.record_restart()
                    self._update_stats_ui()
                self._ui_restarted = False

            if state != "work":
                self._ui_restarted = False

            # Keep break popup countdown synchronized with daemon remaining time
            if self.break_popups and state == "break":
                self.break_countdown_left = rem_sec
                for popup in self.break_popups:
                    try:
                        popup.update_countdown(self.break_countdown_left)
                    except Exception:
                        pass
            elif self.break_popups and state != "break":
                self._close_break_popups()

            self.prev_daemon_state = state
            self.prev_rem_sec = rem_sec

            self._apply_state(state, remaining, rem_sec, tot_sec, locked)

            # Inactivity Auto-Pause: strictly during active focus session (never during break)
            if state == "work" and not self.user_stopped and self.idle_pause_enabled and rem_sec > 5:
                idle_sec = self.activity_monitor.get_idle_seconds()
                if idle_sec >= self.idle_threshold_seconds:
                    self._trigger_idle_pause()
        except Exception as e:
            print(f"Error applying pomodoro daemon status: {e}")
        finally:
            self._is_querying = False
        return False

    def _parse_seconds(self, time_str: str) -> int:
        try:
            parts = time_str.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            pass
        return 0

    def _apply_state(self, state: str, remaining_str: str, rem_sec: int, tot_sec: int, locked: bool):
        self.state = state
        self.remaining_str = remaining_str
        self.remaining_seconds = rem_sec
        self.total_seconds = tot_sec
        self.lbl_timer.set_text(remaining_str)

        ctx = self.lbl_badge.get_style_context()
        ctx.remove_class("badge-work")
        ctx.remove_class("badge-break")
        ctx.remove_class("badge-paused")
        ctx.remove_class("badge-idle")

        bar_ctx = self.progress_bar.get_style_context()
        bar_ctx.remove_class("progress-bar-fill")
        bar_ctx.remove_class("progress-bar-break")
        bar_ctx.remove_class("progress-bar-paused")

        fraction = max(0.0, min(1.0, rem_sec / max(1, tot_sec)))
        self.progress_bar.set_fraction(fraction)

        if state == "work":
            self.lbl_badge.set_text("● FOCUSING")
            ctx.add_class("badge-work")
            bar_ctx.add_class("progress-bar-fill")
            self.btn_work.set_label("Restart")
            self.btn_pause.set_label("⏸ Pause")
        elif state == "break":
            self.lbl_badge.set_text("☕ BREAK")
            ctx.add_class("badge-break")
            bar_ctx.add_class("progress-bar-break")
            self.btn_work.set_label("▶ Focus")
            self.btn_pause.set_label("⏸ Pause")
        elif state == "paused":
            if getattr(self, "idle_paused", False):
                self.lbl_badge.set_text("⏸ IDLE PAUSED")
            else:
                self.lbl_badge.set_text("⏸ PAUSED")
            ctx.add_class("badge-paused")
            bar_ctx.add_class("progress-bar-paused")
            self.btn_work.set_label("Restart")
            self.btn_pause.set_label("▶ Resume")
        else:
            self.lbl_badge.set_text("⏹ IDLE")
            ctx.add_class("badge-idle")
            bar_ctx.add_class("progress-bar-fill")
            self.btn_work.set_label("▶ Focus")
            self.btn_pause.set_label("⏸ Pause")

        self.window.show_all()

    def run(self):
        self.window.show_all()
        Gtk.main()


if __name__ == "__main__":
    _acquire_single_instance_lock()
    app = PomodoroWidget()
    app.run()
