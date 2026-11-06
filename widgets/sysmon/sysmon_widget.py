#!/usr/bin/env python3
"""
System Vitals (SysMon) Desktop Widget
Minimal, transparent desktop widget displaying pure system vitals directly from root:
- Active physical sensors (Microphone, Audio Speaker, Camera, GPS, Bluetooth)
- Real-time Network upload / download speeds (/proc/net/dev)
- Total system memory load (/proc/meminfo)

Part of Devendra Desktop Widgets Suite
"""

import sys
import os
import time
import json
import glob
import subprocess
import threading
import re
import fcntl
from pathlib import Path

_lock_file = None
def _acquire_single_instance_lock():
    global _lock_file
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        lock_path = Path(runtime_dir) / "sysmon_widget.lock"
    else:
        lock_path = Path.home() / ".config" / "sysmon-widget" / "sysmon_widget.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_file = open(lock_path, "a+")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        print("Another instance of sysmon_widget is already running. Exiting.")
        sys.exit(0)
    except Exception as e:
        print(f"Warning: Could not acquire lock at {lock_path}: {e}")

# Ensure GTK 3 & Gdk are loaded
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_DIR = Path.home() / ".config" / "sysmon-widget"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "x": 3120,
    "y": 1285,
    "width": 360,
    "height": 115,
    "always_on_top": True,
    "opacity": 0.85
}


class SysMonWidget:
    def __init__(self):
        self.config = self._load_config()
        self.target_x = self.config.get("x", 3120)
        self.target_y = self.config.get("y", 1285)
        self._initial_positioned = False
        self._is_pinned_top = self.config.get("always_on_top", True)

        # Network measurement state
        self._last_net_time = 0.0
        self._last_rx = 0
        self._last_tx = 0
        self._primary_iface = ""

        # Background worker state
        self._is_scanning = False
        self._stop_thread = False
        self._save_timer_id = None

        self._init_window()
        self._load_css()
        self._build_ui()

        # Initialize network counters
        self._read_initial_net()

        # Start periodic tick (every 1.5 seconds)
        GLib.timeout_add(1500, self._on_timer_tick)
        # Immediate first scan
        self._trigger_background_scan()

    def _load_config(self) -> dict:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    merged = DEFAULT_CONFIG.copy()
                    merged.update(cfg)
                    return merged
            except Exception:
                pass
        local_cfg = SCRIPT_DIR / "config.json"
        if local_cfg.exists():
            try:
                with open(local_cfg, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    merged = DEFAULT_CONFIG.copy()
                    merged.update(cfg)
                    return merged
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def _save_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving sysmon config: {e}")
        try:
            local_cfg = SCRIPT_DIR / "config.json"
            with open(local_cfg, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass

    def _init_window(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("System Vitals")
        self.window.set_decorated(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_app_paintable(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.window.stick()

        self._apply_layer()

        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.window.set_visual(visual)

        self.window.set_default_size(
            self.config.get("width", 360),
            self.config.get("height", 115)
        )
        self.window.move(self.target_x, self.target_y)

        self.window.connect("map-event", self._on_map)
        self.window.connect("configure-event", self._on_configure)
        self.window.connect("destroy", self._on_destroy)

    def _on_map(self, widget, event):
        self.window.move(self.target_x, self.target_y)
        GLib.timeout_add(150, self._apply_initial_position)
        GLib.timeout_add(500, self._apply_initial_position)
        return False

    def _apply_initial_position(self):
        self.window.move(self.target_x, self.target_y)
        self._apply_layer()
        self._initial_positioned = True
        return False

    def _apply_layer(self):
        if self._is_pinned_top:
            self.window.set_keep_above(True)
            self.window.set_keep_below(False)
        else:
            self.window.set_keep_above(False)
            self.window.set_keep_below(True)

    def _load_css(self):
        css_file = SCRIPT_DIR / "sysmon.css"
        if css_file.exists():
            provider = Gtk.CssProvider()
            provider.load_from_path(str(css_file))
            screen = Gdk.Screen.get_default()
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _build_ui(self):
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.get_style_context().add_class("main-card")

        # --- HEADER (Draggable Area) ---
        self.header_event_box = Gtk.EventBox()
        self.header_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.header_event_box.connect("button-press-event", self._on_header_press)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.get_style_context().add_class("header-box")

        # Title and Subtitle
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        lbl_title = Gtk.Label(label="⚡ SYSTEM VITALS")
        lbl_title.set_xalign(0.0)
        lbl_title.get_style_context().add_class("title-main")

        lbl_sub = Gtk.Label(label="REAL-TIME HARDWARE")
        lbl_sub.set_xalign(0.0)
        lbl_sub.get_style_context().add_class("title-sub")

        title_box.pack_start(lbl_title, False, False, 0)
        title_box.pack_start(lbl_sub, False, False, 0)
        header_box.pack_start(title_box, True, True, 0)

        # Pin / On-top toggle button
        self.btn_pin = Gtk.Button(label="📌" if self._is_pinned_top else "📍")
        self.btn_pin.set_tooltip_text("Toggle Always On Top vs Desktop Pinned")
        self.btn_pin.get_style_context().add_class("btn-icon")
        self.btn_pin.connect("clicked", self._on_toggle_pin)
        header_box.pack_start(self.btn_pin, False, False, 0)

        self.header_event_box.add(header_box)
        self.card.pack_start(self.header_event_box, False, False, 0)

        # --- SECTION 1: NETWORK & OVERALL RAM CARD ---
        net_ram_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        net_ram_card.get_style_context().add_class("sub-card")

        # Net Speed Row
        net_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_net_icon = Gtk.Label(label="🌐")
        net_row.pack_start(lbl_net_icon, False, False, 0)

        self.lbl_net_down = Gtk.Label(label="↓ 0.0 KB/s")
        self.lbl_net_down.get_style_context().add_class("net-speed-down")
        net_row.pack_start(self.lbl_net_down, False, False, 0)

        self.lbl_net_up = Gtk.Label(label="↑ 0.0 KB/s")
        self.lbl_net_up.get_style_context().add_class("net-speed-up")
        net_row.pack_start(self.lbl_net_up, False, False, 0)

        self.lbl_iface_badge = Gtk.Label(label="NET")
        self.lbl_iface_badge.get_style_context().add_class("net-badge")
        self.lbl_iface_badge.set_xalign(1.0)
        net_row.pack_end(self.lbl_iface_badge, False, False, 0)

        net_ram_card.pack_start(net_row, False, False, 0)

        # System RAM Row
        ram_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.lbl_ram_summary = Gtk.Label(label="RAM: 0.0 / 0.0 GB (0%)")
        self.lbl_ram_summary.set_xalign(0.0)
        self.lbl_ram_summary.get_style_context().add_class("ram-label")
        ram_row.pack_start(self.lbl_ram_summary, True, True, 0)

        net_ram_card.pack_start(ram_row, False, False, 0)

        # RAM Progress Bar
        self.ram_bar = Gtk.ProgressBar()
        self.ram_bar.set_fraction(0.0)
        self.ram_bar.get_style_context().add_class("ram-bar-fill")
        net_ram_card.pack_start(self.ram_bar, False, False, 0)

        self.card.pack_start(net_ram_card, False, False, 0)
        self.window.add(self.card)

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

    def _on_destroy(self, widget):
        self._stop_thread = True
        Gtk.main_quit()

    # --- PURE ROOT NETWORK MEASUREMENT (/proc/net/dev) ---
    def _read_initial_net(self):
        rx, tx, iface = self._get_net_totals()
        self._last_rx = rx
        self._last_tx = tx
        self._primary_iface = iface
        self._last_net_time = time.time()

    def _get_net_totals(self):
        rx_total, tx_total = 0, 0
        primary_iface = ""
        active_count = 0
        max_bytes = -1
        try:
            with open("/proc/net/dev", "r") as f:
                for line in f:
                    if ":" in line:
                        iface, data = line.split(":", 1)
                        iface = iface.strip()
                        if iface == "lo" or iface.startswith("virbr") or iface.startswith("docker"):
                            continue
                        parts = data.split()
                        rx = int(parts[0])
                        tx = int(parts[8])
                        rx_total += rx
                        tx_total += tx
                        if (rx + tx) > 0:
                            active_count += 1
                        if (rx + tx) > max_bytes:
                            max_bytes = rx + tx
                            primary_iface = iface
        except Exception:
            pass
        iface_label = primary_iface if active_count <= 1 else "NET"
        return rx_total, tx_total, (iface_label or "NET")

    def _measure_net_speed(self):
        now = time.time()
        dt = now - self._last_net_time
        if dt <= 0.1:
            dt = 1.0

        rx, tx, iface = self._get_net_totals()
        down_speed = (rx - self._last_rx) / dt
        up_speed = (tx - self._last_tx) / dt

        self._last_rx = rx
        self._last_tx = tx
        self._primary_iface = iface
        self._last_net_time = now

        if down_speed < 0:
            down_speed = 0
        if up_speed < 0:
            up_speed = 0

        def fmt_speed(bps):
            if bps >= 1024 * 1024:
                return f"{bps / (1024 * 1024):.1f} MB/s"
            elif bps >= 1024:
                return f"{bps / 1024:.1f} KB/s"
            else:
                return f"{int(bps)} B/s"

        return fmt_speed(down_speed), fmt_speed(up_speed), iface

    # --- PURE ROOT MEMORY MEASUREMENT (/proc/meminfo) ---
    def _get_system_ram(self):
        total_kb = 0
        avail_kb = 0
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total_kb = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        avail_kb = int(line.split()[1])
        except Exception:
            pass

        used_kb = max(0, total_kb - avail_kb)
        pct = (used_kb / total_kb * 100.0) if total_kb > 0 else 0.0
        used_gb = used_kb / (1024 * 1024)
        total_gb = total_kb / (1024 * 1024)

        return used_gb, total_gb, pct

    # --- BACKGROUND WORKER SCAN ---
    def _trigger_background_scan(self):
        if self._is_scanning:
            return
        self._is_scanning = True
        threading.Thread(target=self._worker_scan, daemon=True).start()

    def _worker_scan(self):
        try:
            down_str, up_str, iface = self._measure_net_speed()
            ram_used_gb, ram_total_gb, ram_pct = self._get_system_ram()

            payload = {
                "down": down_str,
                "up": up_str,
                "iface": iface,
                "ram_used": ram_used_gb,
                "ram_total": ram_total_gb,
                "ram_pct": ram_pct,
            }

            GLib.idle_add(self._apply_ui_update, payload)
        except Exception as e:
            print(f"Error in SysMon worker: {e}")
        finally:
            self._is_scanning = False

    def _apply_ui_update(self, data):
        # Update Network & RAM
        self.lbl_net_down.set_text(f"↓ {data['down']}")
        self.lbl_net_up.set_text(f"↑ {data['up']}")
        self.lbl_iface_badge.set_text(data['iface'])

        pct_val = data['ram_pct']
        self.lbl_ram_summary.set_text(
            f"RAM: {data['ram_used']:.1f} / {data['ram_total']:.1f} GB ({pct_val:.0f}%)"
        )
        self.ram_bar.set_fraction(max(0.0, min(1.0, pct_val / 100.0)))
        return False

    def _on_timer_tick(self):
        if not self._stop_thread:
            self._trigger_background_scan()
        return True

    def run(self):
        self.window.show_all()
        Gtk.main()


if __name__ == "__main__":
    _acquire_single_instance_lock()
    # Wait for X11 / GTK initialization during early boot (up to 30 seconds)
    for _ in range(30):
        try:
            if Gtk.init_check()[0]:
                break
        except Exception:
            pass
        time.sleep(1)
    app = SysMonWidget()
    app.run()
