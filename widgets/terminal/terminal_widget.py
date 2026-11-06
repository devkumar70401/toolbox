#!/usr/bin/env python3
"""
Terminal Desktop Widget
Modern, transparent, interactive desktop terminal widget built with VTE and GTK3.
Location: /home/dev/SE/toolbox/widgets/terminal/terminal_widget.py
"""

import sys
import os
import time
import signal
import json
import socket
import subprocess
import fcntl
import atexit
from pathlib import Path

IPC_SOCKET_NAME = "\0terminal_widget_ipc"
CONFIG_DIR = Path.home() / ".config" / "terminal-widget"
CONFIG_FILE = CONFIG_DIR / "config.json"
REPO_CONFIG_FILE = Path(__file__).parent.resolve() / "config.json"
DEFAULT_CWD = Path.home() / "SE"

DEFAULT_CONFIG = {
    "x": 3882,
    "y": 1034,
    "width": 870,
    "height": 570,
    "always_on_top": False,
    "font": "Monospace 11"
}

# --- Fast-path CLI / IPC handling ---
# When invoked with CLI options (--status, --restart, etc.), communicate over IPC socket
# immediately without incurring the overhead of initializing GTK / VTE.
def _handle_cli_ipc():
    if len(sys.argv) <= 1:
        return

    raw_arg = sys.argv[1].lower()
    cmd = raw_arg.lstrip("-")

    if cmd in ("h", "help"):
        print("Terminal Desktop Widget")
        print("Usage: run.sh [OPTION] or python terminal_widget.py [OPTION]")
        print("")
        print("Options:")
        print("  --status     Print JSON status of running widget")
        print("  --restart    Restart and reset shell process")
        print("  --clear      Clear terminal scrollback buffer")
        print("  --toggle     Toggle widget visibility")
        print("  --reopen     Reopen and focus widget")
        print("  --quit       Shut down running widget")
        print("  --help       Show this help message")
        sys.exit(0)

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect(IPC_SOCKET_NAME)
        s.sendall((cmd + "\n").encode("utf-8"))
        resp = s.recv(2048).decode("utf-8").strip()
        print(f"Terminal Widget [running instance]: {resp}")
        s.close()
        sys.exit(0)
    except (ConnectionRefusedError, FileNotFoundError, OSError, socket.timeout):
        # No running instance or IPC server not active
        pass

    if cmd in ("status", "quit", "close", "stop", "restart", "clear", "toggle"):
        print("Terminal Widget is not currently running.")
        sys.exit(0)

_handle_cli_ipc()

# Clean inherited snap / VSCode variables to ensure system libraries are used
for var in [
    "GIO_MODULE_DIR",
    "GSETTINGS_SCHEMA_DIR",
    "GTK_PATH",
    "GTK_EXE_PREFIX",
    "GTK_MODULES",
    "GTK_IM_MODULE_FILE",
    "LOCPATH",
    "LD_PRELOAD"
]:
    os.environ.pop(var, None)

# Ensure GTK 3, VTE 2.91 & Pango are loaded
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Vte', '2.91')
gi.require_version('Pango', '1.0')
from gi.repository import Gtk, Gdk, GLib, Vte, Pango

_lock_file = None
def _acquire_single_instance_lock() -> bool:
    global _lock_file
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        lock_path = Path(runtime_dir) / "terminal_widget.lock"
    else:
        lock_path = CONFIG_DIR / "terminal_widget.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_file = open(lock_path, "a+")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (IOError, BlockingIOError):
        return False
    except Exception as e:
        print(f"Warning: Could not acquire lock at {lock_path}: {e}")
        return False


class TerminalWidget:
    def __init__(self):
        self.config = self._load_config()
        self.target_x = self.config.get("x", DEFAULT_CONFIG["x"])
        self.target_y = self.config.get("y", DEFAULT_CONFIG["y"])
        self._initial_positioned = False
        self._is_pinned_top = self.config.get("always_on_top", DEFAULT_CONFIG["always_on_top"])
        self.child_pid = None
        self._dying_pids = set()
        self._restart_timer_id = None
        self._save_timer_id = None
        self._last_spawn_time = 0.0
        self._is_restarting = False
        self.ipc_sock = None

        self._init_window()
        self._load_css()
        self._build_ui()
        self._init_ipc()
        self._init_signals()
        self._spawn_shell()
        atexit.register(self._cleanup_on_exit)

    def _load_config(self) -> dict:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        merged = DEFAULT_CONFIG.copy()
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    merged.update(cfg)
            except Exception:
                pass
        elif REPO_CONFIG_FILE.exists():
            try:
                with open(REPO_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    merged.update(cfg)
            except Exception:
                pass

        # Migrate legacy default dimensions (580x380) to 50% enlarged (870x570)
        if merged.get("width") == 580 and merged.get("height") == 380:
            merged["width"] = DEFAULT_CONFIG["width"]
            merged["height"] = DEFAULT_CONFIG["height"]
            self._save_config_data(merged)

        return merged

    def _save_config(self):
        self._save_config_data(self.config)

    def _save_config_data(self, data: dict):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving terminal widget config: {e}")

    def _clamp_to_screen(self):
        display = Gdk.Display.get_default()
        if not display:
            return
        n_mon = display.get_n_monitors()
        if n_mon == 0:
            return

        w = self.config.get("width", DEFAULT_CONFIG["width"])
        h = self.config.get("height", DEFAULT_CONFIG["height"])

        target_center_x = self.target_x + w // 2
        target_center_y = self.target_y + h // 2

        matched_mon = None
        for i in range(n_mon):
            mon = display.get_monitor(i)
            g = mon.get_geometry()
            if g.x <= target_center_x <= g.x + g.width and g.y <= target_center_y <= g.y + g.height:
                matched_mon = mon
                break

        if not matched_mon:
            matched_mon = display.get_primary_monitor() or display.get_monitor(0)

        geom = matched_mon.get_geometry()
        margin = 20

        max_x = geom.x + geom.width - w - margin
        min_x = geom.x + margin
        if max_x < min_x:
            self.target_x = geom.x
        else:
            self.target_x = max(min_x, min(self.target_x, max_x))

        max_y = geom.y + geom.height - h - margin
        min_y = geom.y + margin
        if max_y < min_y:
            self.target_y = geom.y
        else:
            self.target_y = max(min_y, min(self.target_y, max_y))

        self.config["x"] = self.target_x
        self.config["y"] = self.target_y

    def _init_window(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Terminal Widget")
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

        default_w = self.config.get("width", DEFAULT_CONFIG["width"])
        default_h = self.config.get("height", DEFAULT_CONFIG["height"])
        self.window.set_default_size(default_w, default_h)
        self.window.resize(default_w, default_h)
        self.window.set_size_request(400, 250)
        self.window.move(self.target_x, self.target_y)

        self.window.connect("map-event", self._on_map)
        self.window.connect("configure-event", self._on_configure)
        self.window.connect("destroy", self._on_destroy)

    def _init_signals(self):
        try:
            try:
                from gi.repository import GLibUnix
                signal_add = GLibUnix.signal_add
            except (ImportError, AttributeError):
                signal_add = GLib.unix_signal_add

            signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._on_signal_exit, signal.SIGTERM)
            signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self._on_signal_exit, signal.SIGINT)
            signal_add(GLib.PRIORITY_HIGH, signal.SIGHUP, self._on_signal_exit, signal.SIGHUP)
        except Exception as e:
            print(f"Signal handler init note: {e}")

    def _on_signal_exit(self, signum):
        self._on_destroy(None)
        return False

    def _on_map(self, widget, event):
        self.window.move(self.target_x, self.target_y)
        GLib.timeout_add(150, self._apply_initial_position)
        return False

    def _apply_initial_position(self):
        self._clamp_to_screen()
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

    def _init_ipc(self):
        try:
            self.ipc_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.ipc_sock.bind(IPC_SOCKET_NAME)
            self.ipc_sock.listen(5)
            self.ipc_sock.setblocking(False)
            GLib.io_add_watch(self.ipc_sock.fileno(), GLib.IO_IN, self._on_ipc_connection)
        except Exception as e:
            print(f"Terminal Widget IPC server init notice: {e}")

    def _on_ipc_connection(self, fd, condition):
        try:
            conn, _ = self.ipc_sock.accept()
            data = conn.recv(1024).decode("utf-8").strip()
            cmd = data.lower().lstrip("-")
            if cmd in ("reopen", "open", "present", "focus", "show"):
                self._reopen_and_focus()
                conn.sendall(b"OK: reopened and focused\n")
            elif cmd in ("restart", "refresh", "reload", "reset"):
                self._on_restart_shell()
                conn.sendall(b"OK: shell restarted and terminal reset\n")
            elif cmd in ("clear",):
                self.terminal.reset(True, True)
                conn.sendall(b"OK: terminal buffer cleared\n")
            elif cmd in ("toggle",):
                self._toggle_visibility()
                conn.sendall(b"OK: visibility toggled\n")
            elif cmd in ("status",):
                x, y = self.window.get_position()
                w, h = self.window.get_size()
                info = {
                    "running": True,
                    "pid": os.getpid(),
                    "child_pid": self.child_pid,
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                    "always_on_top": self._is_pinned_top
                }
                conn.sendall((json.dumps(info) + "\n").encode("utf-8"))
            elif cmd in ("quit", "close", "stop", "exit"):
                conn.sendall(b"OK: shutting down\n")
                conn.close()
                self.window.destroy()
                return False
            else:
                conn.sendall(b"UNKNOWN_COMMAND\n")
            conn.close()
        except Exception as e:
            print(f"IPC connection handling error: {e}")
        return True

    def _reopen_and_focus(self):
        self.window.deiconify()
        self.window.show_all()
        self._clamp_to_screen()
        self.window.move(self.target_x, self.target_y)
        self._apply_layer()
        self.window.present()
        self.terminal.grab_focus()

    def _toggle_visibility(self):
        if self.window.get_visible():
            self.window.hide()
        else:
            self._reopen_and_focus()

    def _load_css(self):
        css = b"""
        window {
            background-color: transparent;
        }
        .term-card {
            background-color: rgba(18, 20, 26, 0.88);
            border: 1px solid rgba(255, 255, 255, 0.13);
            border-radius: 20px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6);
            padding: 12px 14px;
        }
        .term-header {
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 8px;
            margin-bottom: 8px;
        }
        .term-title {
            font-size: 13px;
            font-weight: bold;
            color: #d1d5db;
        }
        .badge-shell {
            background-color: rgba(14, 165, 233, 0.22);
            color: #7dd3fc;
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
            border: 1px solid rgba(14, 165, 233, 0.4);
        }
        .btn-icon {
            background: transparent;
            border: none;
            color: #9ca3af;
            padding: 2px 6px;
            border-radius: 6px;
            font-size: 13px;
        }
        .btn-icon:hover {
            background-color: rgba(255, 255, 255, 0.1);
            color: #ffffff;
        }
        .btn-close:hover {
            background-color: rgba(239, 68, 68, 0.25);
            color: #ef4444;
        }
        .term-container {
            border-radius: 12px;
            background-color: rgba(10, 12, 16, 0.75);
            padding: 6px;
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
        self.card.get_style_context().add_class("term-card")
        self.card.set_hexpand(True)
        self.card.set_vexpand(True)

        # --- HEADER (Draggable Area) ---
        self.header_event_box = Gtk.EventBox()
        self.header_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK)
        self.header_event_box.connect("button-press-event", self._on_header_press)
        self.header_event_box.connect("realize", self._on_header_realize)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.get_style_context().add_class("term-header")

        lbl_icon = Gtk.Label(label="\U0001f4bb")
        header_box.pack_start(lbl_icon, False, False, 0)

        lbl_title = Gtk.Label(label="Terminal")
        lbl_title.get_style_context().add_class("term-title")
        header_box.pack_start(lbl_title, False, False, 0)

        # Shell badge
        lbl_badge = Gtk.Label(label="BASH")
        lbl_badge.get_style_context().add_class("badge-shell")
        header_box.pack_start(lbl_badge, True, True, 0)
        lbl_badge.set_xalign(1.0)

        # Clear / Restart button
        btn_restart = Gtk.Button(label="\U0001f504")
        btn_restart.set_tooltip_text("Restart / Reset Shell (Ctrl+Shift+R)")
        btn_restart.get_style_context().add_class("btn-icon")
        btn_restart.connect("clicked", self._on_restart_shell)
        header_box.pack_start(btn_restart, False, False, 0)

        # Open Directory Folder
        btn_folder = Gtk.Button(label="\U0001f4c2")
        btn_folder.set_tooltip_text("Open ~/SE in File Manager")
        btn_folder.get_style_context().add_class("btn-icon")
        btn_folder.connect("clicked", self._on_open_folder)
        header_box.pack_start(btn_folder, False, False, 0)

        # Pin Button
        self.btn_pin = Gtk.Button(label="\U0001f4cc" if self._is_pinned_top else "\U0001f4cd")
        self.btn_pin.set_tooltip_text("Toggle Always On Top vs Desktop Pinned")
        self.btn_pin.get_style_context().add_class("btn-icon")
        self.btn_pin.connect("clicked", self._on_toggle_pin)
        header_box.pack_start(self.btn_pin, False, False, 0)

        # Close Button
        btn_close = Gtk.Button(label="\u2715")
        btn_close.set_tooltip_text("Close Terminal Widget")
        btn_close.get_style_context().add_class("btn-icon")
        btn_close.get_style_context().add_class("btn-close")
        btn_close.connect("clicked", lambda _: self.window.destroy())
        header_box.pack_start(btn_close, False, False, 0)

        self.header_event_box.add(header_box)
        self.card.pack_start(self.header_event_box, False, False, 0)

        # --- VTE TERMINAL CONTAINER ---
        term_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        term_box.get_style_context().add_class("term-container")
        term_box.set_hexpand(True)
        term_box.set_vexpand(True)

        self.terminal = Vte.Terminal()
        self.terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)
        self.terminal.set_cursor_shape(Vte.CursorShape.IBEAM)
        self.terminal.set_scrollback_lines(2000)
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)

        # Font configuration (supports config override, defaults to Monospace 11)
        font_str = self.config.get("font", DEFAULT_CONFIG.get("font", "Monospace 11"))
        font_desc = Pango.FontDescription(font_str)
        self.terminal.set_font(font_desc)

        # Colors (Modern Obsidian Dark Theme)
        fg_color = Gdk.RGBA(0.90, 0.92, 0.95, 1.0)
        bg_color = Gdk.RGBA(0.06, 0.08, 0.11, 0.85)

        # 16-color ANSI Palette
        palette = [
            Gdk.RGBA(0.12, 0.14, 0.18, 1.0),  # Black
            Gdk.RGBA(0.94, 0.27, 0.27, 1.0),  # Red
            Gdk.RGBA(0.13, 0.77, 0.37, 1.0),  # Green
            Gdk.RGBA(0.96, 0.62, 0.04, 1.0),  # Yellow
            Gdk.RGBA(0.24, 0.51, 0.96, 1.0),  # Blue
            Gdk.RGBA(0.66, 0.33, 0.97, 1.0),  # Magenta
            Gdk.RGBA(0.06, 0.73, 0.85, 1.0),  # Cyan
            Gdk.RGBA(0.85, 0.87, 0.91, 1.0),  # White
            # Bright colors
            Gdk.RGBA(0.30, 0.33, 0.39, 1.0),
            Gdk.RGBA(0.97, 0.44, 0.44, 1.0),
            Gdk.RGBA(0.29, 0.87, 0.50, 1.0),
            Gdk.RGBA(0.98, 0.75, 0.18, 1.0),
            Gdk.RGBA(0.38, 0.65, 0.98, 1.0),
            Gdk.RGBA(0.75, 0.49, 0.98, 1.0),
            Gdk.RGBA(0.22, 0.83, 0.93, 1.0),
            Gdk.RGBA(1.00, 1.00, 1.00, 1.0)
        ]

        self.terminal.set_colors(fg_color, bg_color, palette)
        self.terminal.set_color_cursor(Gdk.RGBA(0.06, 0.73, 0.85, 1.0))
        self.terminal.set_color_cursor_foreground(Gdk.RGBA(0.06, 0.08, 0.11, 1.0))
        self.terminal.set_color_highlight(Gdk.RGBA(0.24, 0.51, 0.96, 0.5))
        self.terminal.set_color_highlight_foreground(Gdk.RGBA(1.0, 1.0, 1.0, 1.0))

        self.terminal.connect("child-exited", self._on_child_exited)
        self.terminal.connect("key-press-event", self._on_term_key_press)
        self.terminal.connect("button-press-event", self._on_term_button_press)

        term_box.pack_start(self.terminal, True, True, 0)
        self.card.pack_start(term_box, True, True, 0)

        self.window.add(self.card)

    def _on_header_realize(self, widget):
        win = widget.get_window()
        if win:
            display = Gdk.Display.get_default()
            cursor = Gdk.Cursor.new_from_name(display, "grab") or Gdk.Cursor.new_from_name(display, "move")
            if cursor:
                win.set_cursor(cursor)

    def _spawn_shell(self):
        shell = "/bin/bash" if Path("/bin/bash").exists() else os.environ.get("SHELL", "/bin/sh")
        cwd = str(DEFAULT_CWD) if DEFAULT_CWD.exists() else str(Path.home())
        self._last_spawn_time = time.time()

        def _on_spawned(terminal, pid, error, user_data=None):
            if error:
                print(f"Error spawning shell: {error}")
                self.child_pid = None
            else:
                self.child_pid = pid
                self._dying_pids.discard(pid)

        try:
            self.terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                cwd,
                [shell],
                [],
                GLib.SpawnFlags.DEFAULT,
                None, None,
                -1,
                None,
                _on_spawned
            )
        except Exception as e:
            print(f"Exception spawning shell: {e}")

    def _is_pid_alive(self, pid: int) -> bool:
        if not pid or pid <= 1:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _get_process_tree(self, root_pid: int):
        """Return (set of descendant pids including root, set of pgids)."""
        pids = {root_pid}
        pgrps = set()
        try:
            pgrps.add(os.getpgid(root_pid))
        except Exception:
            pgrps.add(root_pid)

        try:
            parent_map = {}
            for entry in os.scandir("/proc"):
                if entry.is_dir() and entry.name.isdigit():
                    try:
                        with open(f"/proc/{entry.name}/stat", "r") as f:
                            stat_str = f.read()
                        c_pid = int(entry.name)
                        post = stat_str.rsplit(")", 1)[1].split()
                        ppid = int(post[1])
                        pgrp = int(post[2])
                        parent_map.setdefault(ppid, []).append((c_pid, pgrp))
                    except Exception:
                        pass

            to_visit = [root_pid]
            while to_visit:
                curr = to_visit.pop()
                for c_pid, c_pgrp in parent_map.get(curr, []):
                    if c_pid not in pids:
                        pids.add(c_pid)
                        pgrps.add(c_pgrp)
                        to_visit.append(c_pid)
        except Exception as e:
            print(f"Error enumerating process tree for {root_pid}: {e}")

        return pids, pgrps

    def _kill_process_tree(self, pid: int, sync: bool = False):
        if not pid:
            return

        pids, pgrps = self._get_process_tree(pid)

        # 1. Send SIGHUP to process groups and pids
        for pg in pgrps:
            try:
                os.killpg(pg, signal.SIGHUP)
            except Exception:
                pass
        for p in pids:
            try:
                os.kill(p, signal.SIGHUP)
            except Exception:
                pass

        # 2. Also send SIGTERM
        for pg in pgrps:
            try:
                os.killpg(pg, signal.SIGTERM)
            except Exception:
                pass
        for p in pids:
            try:
                os.kill(p, signal.SIGTERM)
            except Exception:
                pass

        def _do_sigkill():
            for pg in pgrps:
                try:
                    os.killpg(pg, signal.SIGKILL)
                except Exception:
                    pass
            for p in pids:
                try:
                    os.kill(p, signal.SIGKILL)
                except Exception:
                    pass

        if sync:
            # Synchronous wait up to 150ms on shutdown/exit
            deadline = time.time() + 0.15
            while time.time() < deadline:
                alive = [p for p in pids if self._is_pid_alive(p)]
                if not alive:
                    return
                time.sleep(0.02)
            _do_sigkill()
        else:
            # Asynchronous watchdog for shell restart
            def _force_sigkill():
                _do_sigkill()
                return False
            GLib.timeout_add(150, _force_sigkill)

    def _kill_current_child(self, sync: bool = False):
        if self.child_pid:
            old_pid = self.child_pid
            self.child_pid = None
            self._dying_pids.add(old_pid)
            self._kill_process_tree(old_pid, sync=sync)

    def _on_child_exited(self, terminal, status):
        if self._restart_timer_id:
            GLib.source_remove(self._restart_timer_id)
            self._restart_timer_id = None

        if self._is_restarting:
            self._is_restarting = False
            self.terminal.reset(True, True)
            self._spawn_shell()
            return

        if self.child_pid is not None and self.child_pid not in self._dying_pids:
            self.child_pid = None
            elapsed = time.time() - self._last_spawn_time
            delay = 200 if elapsed > 1.0 else 1200
            GLib.timeout_add(delay, self._respawn)
        elif self.child_pid is None:
            GLib.timeout_add(500, self._respawn)

    def _respawn(self):
        if not self.child_pid and not self._is_restarting:
            self.terminal.reset(True, True)
            self._spawn_shell()
        return False

    def _on_restart_shell(self, button=None):
        if self._restart_timer_id:
            GLib.source_remove(self._restart_timer_id)
            self._restart_timer_id = None

        if self._is_restarting:
            self._is_restarting = False
            if self.child_pid:
                self._kill_current_child(sync=False)
            self.terminal.reset(True, True)
            self._spawn_shell()
            return

        self._is_restarting = True
        if self.child_pid:
            self._kill_current_child(sync=False)
            def _restart_watchdog():
                if self._is_restarting:
                    self._is_restarting = False
                    self.terminal.reset(True, True)
                    self._spawn_shell()
                self._restart_timer_id = None
                return False
            self._restart_timer_id = GLib.timeout_add(300, _restart_watchdog)
        else:
            self._is_restarting = False
            self.terminal.reset(True, True)
            self._spawn_shell()

    def _on_destroy(self, widget=None):
        if self._save_timer_id:
            GLib.source_remove(self._save_timer_id)
            self._save_timer_id = None
        if self._restart_timer_id:
            GLib.source_remove(self._restart_timer_id)
            self._restart_timer_id = None

        self._save_config()
        self._kill_current_child(sync=True)
        if self.ipc_sock:
            try:
                self.ipc_sock.close()
            except Exception:
                pass
            self.ipc_sock = None
        Gtk.main_quit()

    def _cleanup_on_exit(self):
        if self.child_pid:
            self._kill_process_tree(self.child_pid, sync=True)
            self.child_pid = None
        if self.ipc_sock:
            try:
                self.ipc_sock.close()
            except Exception:
                pass
            self.ipc_sock = None

    def _on_open_folder(self, button=None):
        try:
            cwd = str(DEFAULT_CWD) if DEFAULT_CWD.exists() else str(Path.home())
            subprocess.Popen(["xdg-open", cwd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Error opening folder: {e}")

    def _on_header_press(self, widget, event):
        if event.button == 1:
            self.window.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )
        elif event.button == 3:
            self._show_context_menu(event)
            return True

    def _on_configure(self, widget, event):
        if not self._initial_positioned:
            return
        x, y = self.window.get_position()
        w, h = self.window.get_size()
        if x > -10000 and y > -10000 and w > 50 and h > 50:
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

    def _on_toggle_pin(self, button=None):
        if isinstance(button, Gtk.CheckMenuItem):
            self._is_pinned_top = button.get_active()
        else:
            self._is_pinned_top = not self._is_pinned_top
        self.config["always_on_top"] = self._is_pinned_top
        if hasattr(self, "btn_pin") and self.btn_pin:
            self.btn_pin.set_label("\U0001f4cc" if self._is_pinned_top else "\U0001f4cd")
        self._apply_layer()
        self._save_config()

    def _on_term_key_press(self, widget, event):
        ctrl_shift = (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        ctrl_only = Gdk.ModifierType.CONTROL_MASK
        state = event.state

        # Ctrl + Shift + V -> Paste
        if (state & ctrl_shift) == ctrl_shift and event.keyval in (Gdk.KEY_V, Gdk.KEY_v):
            self.terminal.paste_clipboard()
            return True
        # Ctrl + Shift + C -> Copy
        elif (state & ctrl_shift) == ctrl_shift and event.keyval in (Gdk.KEY_C, Gdk.KEY_c):
            if hasattr(self.terminal, "copy_clipboard_format"):
                self.terminal.copy_clipboard_format(Vte.Format.TEXT)
            else:
                self.terminal.copy_clipboard()
            return True
        # Ctrl + Shift + R -> Restart / Reset Shell
        elif (state & ctrl_shift) == ctrl_shift and event.keyval in (Gdk.KEY_R, Gdk.KEY_r):
            self._on_restart_shell()
            return True
        # Ctrl + Shift + K -> Clear Scrollback Buffer
        elif (state & ctrl_shift) == ctrl_shift and event.keyval in (Gdk.KEY_K, Gdk.KEY_k):
            self.terminal.reset(True, True)
            return True
        # Shift + Insert -> Paste
        elif (state & Gdk.ModifierType.SHIFT_MASK) and event.keyval == Gdk.KEY_Insert:
            self.terminal.paste_clipboard()
            return True
        # Ctrl + '+' / Ctrl + '=' / Keypad Add -> Font Zoom In
        elif (state & ctrl_only) and event.keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            scale = self.terminal.get_font_scale()
            self.terminal.set_font_scale(min(scale + 0.1, 2.5))
            return True
        # Ctrl + '-' / Keypad Subtract -> Font Zoom Out
        elif (state & ctrl_only) and event.keyval in (Gdk.KEY_minus, Gdk.KEY_underscore, Gdk.KEY_KP_Subtract):
            scale = self.terminal.get_font_scale()
            self.terminal.set_font_scale(max(scale - 0.1, 0.6))
            return True
        # Ctrl + 0 / Keypad 0 -> Reset Zoom
        elif (state & ctrl_only) and event.keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.terminal.set_font_scale(1.0)
            return True

        return False

    def _show_context_menu(self, event):
        menu = Gtk.Menu()
        item_copy = Gtk.MenuItem(label="\U0001f4cb Copy (Ctrl+Shift+C)")
        item_copy.connect("activate", lambda _: self.terminal.copy_clipboard_format(Vte.Format.TEXT) if hasattr(self.terminal, "copy_clipboard_format") else self.terminal.copy_clipboard())
        menu.append(item_copy)

        item_paste = Gtk.MenuItem(label="\U0001f4e5 Paste (Ctrl+Shift+V)")
        item_paste.connect("activate", lambda _: self.terminal.paste_clipboard())
        menu.append(item_paste)

        sep1 = Gtk.SeparatorMenuItem()
        menu.append(sep1)

        item_restart = Gtk.MenuItem(label="\U0001f504 Restart / Reset Shell (Ctrl+Shift+R)")
        item_restart.connect("activate", lambda _: self._on_restart_shell())
        menu.append(item_restart)

        item_clear = Gtk.MenuItem(label="\U0001f9f9 Clear Scrollback (Ctrl+Shift+K)")
        item_clear.connect("activate", lambda _: self.terminal.reset(True, True))
        menu.append(item_clear)

        item_folder = Gtk.MenuItem(label="\U0001f4c2 Open ~/SE Folder")
        item_folder.connect("activate", self._on_open_folder)
        menu.append(item_folder)

        sep2 = Gtk.SeparatorMenuItem()
        menu.append(sep2)

        item_pin = Gtk.CheckMenuItem(label="\U0001f4cc Always On Top")
        item_pin.set_active(self._is_pinned_top)
        item_pin.connect("toggled", lambda m: self._on_toggle_pin(m))
        menu.append(item_pin)

        sep3 = Gtk.SeparatorMenuItem()
        menu.append(sep3)

        item_close = Gtk.MenuItem(label="\u274c Close Terminal Widget")
        item_close.connect("activate", lambda _: self.window.destroy())
        menu.append(item_close)

        menu.show_all()
        if event:
            menu.popup_at_pointer(event)
        else:
            menu.popup(None, None, None, None, 0, Gtk.get_current_event_time())

    def _on_term_button_press(self, widget, event):
        if event.button == 3:  # Right click context menu
            self._show_context_menu(event)
            return True
        return False

    def run(self):
        self.window.show_all()
        Gtk.main()


if __name__ == "__main__":
    # Acquire single-instance file lock
    if not _acquire_single_instance_lock():
        print("Another instance of terminal_widget is already running. Exiting.")
        sys.exit(0)

    app = TerminalWidget()
    app.run()
