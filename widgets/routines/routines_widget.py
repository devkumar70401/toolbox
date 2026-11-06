#!/usr/bin/env python3
"""
Daily Routines Desktop Widget
Modern, transparent, interactive desktop checklist for daily routines.
Location: /home/dev/SE/Devendra/widgets/routines/routines_widget.py
"""

import sys
import os
import subprocess
import fcntl
from datetime import datetime
from pathlib import Path

_lock_file = None
def _acquire_single_instance_lock():
    global _lock_file
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        lock_path = Path(runtime_dir) / "routines_widget.lock"
    else:
        lock_path = Path.home() / ".config" / "routines-widget" / "routines_widget.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_file = open(lock_path, "a+")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        print("Another instance of routines_widget is already running. Exiting.")
        sys.exit(0)
    except Exception as e:
        print(f"Warning: Could not acquire lock at {lock_path}: {e}")

# Ensure GTK 3 is loaded
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from section_store import MultiSectionMarkdownStore, TaskItem


class RoutinesWidget:
    def __init__(self):
        self.store = MultiSectionMarkdownStore(section_type="routines")
        self.config = self.store.config
        self.tasks = []
        self._updating_ui = False
        self._is_pinned_top = self.config.get("always_on_top", False)
        self._save_timer_id = None

        self._init_window()
        self._load_css()
        self._build_ui()
        self._load_tasks()

        # Start periodic tick (every 1.5 seconds)
        GLib.timeout_add(1500, self._on_tick)

    def _init_window(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Daily Routines")
        self.window.set_decorated(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_app_paintable(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        self._apply_layer()
        self.window.stick()

        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.window.set_visual(visual)

        width = self.config.get("width", 360)
        height = self.config.get("height", 520)
        self.target_x = self.config.get("x", 3380)
        self.target_y = self.config.get("y", 503)
        self._initial_positioned = False

        self.window.set_default_size(width, height)
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
        if self._is_pinned_top:
            self.window.set_keep_above(True)
            self.window.set_keep_below(False)
        else:
            self.window.set_keep_above(False)
            self.window.set_keep_below(True)

    def _load_css(self):
        css = b"""
        window {
            background-color: transparent;
        }
        .main-card-routines {
            background-color: rgba(24, 20, 14, 0.82);
            border: 1px solid rgba(251, 191, 36, 0.22);
            border-radius: 20px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55);
            padding: 16px;
        }
        .header-box {
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 10px;
            margin-bottom: 10px;
        }
        .title-date {
            font-size: 15px;
            font-weight: bold;
            color: #f9fafb;
        }
        .title-day-routines {
            font-size: 11px;
            font-weight: bold;
            color: #fbbf24;
        }
        .progress-badge-routines {
            background-color: rgba(245, 158, 11, 0.22);
            color: #fde68a;
            border-radius: 12px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: bold;
            border: 1px solid rgba(245, 158, 11, 0.4);
        }
        .progress-bar-fill-routines {
            background-color: #f59e0b;
            border-radius: 4px;
            min-height: 4px;
        }
        .tasks-viewport {
            background-color: transparent;
        }
        .tasks-box {
            background-color: transparent;
        }
        .task-row {
            background-color: rgba(255, 255, 255, 0.035);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 12px;
            padding: 6px 10px;
            margin-bottom: 6px;
        }
        .task-row:hover {
            background-color: rgba(255, 255, 255, 0.07);
            border-color: rgba(251, 191, 36, 0.2);
        }
        .task-label {
            color: #f3f4f6;
            font-size: 13px;
            font-weight: normal;
        }
        .task-label-completed {
            color: #6b7280;
            font-size: 13px;
            text-decoration: line-through;
        }
        .btn-icon {
            background: transparent;
            border: none;
            color: #9ca3af;
            padding: 3px 6px;
            border-radius: 6px;
            font-size: 13px;
        }
        .btn-icon:hover {
            background-color: rgba(255, 255, 255, 0.1);
            color: #ffffff;
        }
        .btn-delete {
            background: transparent;
            border: none;
            color: #6b7280;
            padding: 2px 6px;
            border-radius: 6px;
            font-size: 14px;
            opacity: 0.6;
        }
        .btn-delete:hover {
            background-color: rgba(239, 68, 68, 0.2);
            color: #f87171;
            opacity: 1.0;
        }
        .entry-add-routines {
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(251, 191, 36, 0.2);
            border-radius: 10px;
            color: #f9fafb;
            padding: 7px 12px;
            font-size: 13px;
        }
        .entry-add-routines:focus {
            border-color: #f59e0b;
            background-color: rgba(255, 255, 255, 0.08);
        }
        .btn-add-routines {
            background-color: #f59e0b;
            color: white;
            border: none;
            border-radius: 10px;
            padding: 6px 12px;
            font-weight: bold;
            font-size: 13px;
        }
        .btn-add-routines:hover {
            background-color: #d97706;
        }
        checkbutton check {
            border-radius: 6px;
            border: 1.5px solid rgba(255, 255, 255, 0.35);
            background-color: rgba(255, 255, 255, 0.06);
            min-width: 17px;
            min-height: 17px;
        }
        checkbutton check:hover {
            border-color: #fbbf24;
        }
        checkbutton check:checked {
            background-color: #f59e0b;
            border-color: #f59e0b;
            color: white;
        }
        scrollbar slider {
            background-color: rgba(255, 255, 255, 0.15);
            border-radius: 4px;
            min-width: 4px;
        }
        scrollbar slider:hover {
            background-color: rgba(255, 255, 255, 0.3);
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
        self.card.get_style_context().add_class("main-card-routines")

        # --- HEADER (Draggable Area) ---
        self.header_event_box = Gtk.EventBox()
        self.header_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.header_event_box.connect("button-press-event", self._on_header_press)

        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_box.get_style_context().add_class("header-box")

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        titles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.lbl_day = Gtk.Label()
        self.lbl_day.set_xalign(0.0)
        self.lbl_day.get_style_context().add_class("title-day-routines")

        self.lbl_date = Gtk.Label()
        self.lbl_date.set_xalign(0.0)
        self.lbl_date.get_style_context().add_class("title-date")

        titles_box.pack_start(self.lbl_day, False, False, 0)
        titles_box.pack_start(self.lbl_date, False, False, 0)
        top_row.pack_start(titles_box, True, True, 0)

        # Progress badge
        self.lbl_progress = Gtk.Label(label="0/0")
        self.lbl_progress.get_style_context().add_class("progress-badge-routines")
        top_row.pack_start(self.lbl_progress, False, False, 0)

        # Pin / On-top toggle button
        self.btn_pin = Gtk.Button(label="📌" if self._is_pinned_top else "📍")
        self.btn_pin.set_tooltip_text("Toggle Always On Top vs Desktop Pinned")
        self.btn_pin.get_style_context().add_class("btn-icon")
        self.btn_pin.connect("clicked", self._on_toggle_pin)
        top_row.pack_start(self.btn_pin, False, False, 0)

        # Folder button
        btn_folder = Gtk.Button(label="📂")
        btn_folder.set_tooltip_text("Open Daily Markdown Folder")
        btn_folder.get_style_context().add_class("btn-icon")
        btn_folder.connect("clicked", self._on_open_folder)
        top_row.pack_start(btn_folder, False, False, 0)

        header_box.pack_start(top_row, False, False, 0)

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.get_style_context().add_class("progress-bar-fill-routines")
        header_box.pack_start(self.progress_bar, False, False, 2)

        self.header_event_box.add(header_box)
        self.card.pack_start(self.header_event_box, False, False, 0)

        # --- TASKS SCROLLABLE LIST ---
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.get_style_context().add_class("tasks-viewport")

        self.tasks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.tasks_box.get_style_context().add_class("tasks-box")
        self.scrolled_window.add(self.tasks_box)

        self.card.pack_start(self.scrolled_window, True, True, 6)

        # --- BOTTOM INPUT BOX ---
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bottom_box.set_margin_top(8)

        self.entry_task = Gtk.Entry()
        self.entry_task.set_placeholder_text("+ Add a routine...")
        self.entry_task.get_style_context().add_class("entry-add-routines")
        self.entry_task.connect("activate", self._on_add_task)
        bottom_box.pack_start(self.entry_task, True, True, 0)

        btn_add = Gtk.Button(label="Add")
        btn_add.get_style_context().add_class("btn-add-routines")
        btn_add.connect("clicked", self._on_add_task)
        bottom_box.pack_start(btn_add, False, False, 0)

        self.card.pack_start(bottom_box, False, False, 0)

        self.window.add(self.card)
        self._update_date_labels()

    def _update_date_labels(self):
        now = datetime.now()
        self.lbl_day.set_text(f"{now.strftime('%A').upper()} · 🔄 DAILY ROUTINES")
        self.lbl_date.set_text(now.strftime("%d %B %Y"))

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
        self.store.save_config(self.config)
        self._save_timer_id = None
        return False

    def _on_toggle_pin(self, button):
        self._is_pinned_top = not self._is_pinned_top
        self.config["always_on_top"] = self._is_pinned_top
        self.btn_pin.set_label("📌" if self._is_pinned_top else "📍")
        self._apply_layer()
        self.store.save_config(self.config)

    def _on_open_folder(self, button):
        try:
            subprocess.Popen(["xdg-open", str(self.store.daily_dir)])
        except Exception as e:
            print(f"Error opening daily folder: {e}")

    def _load_tasks(self):
        self._updating_ui = True
        self.tasks = self.store.load_tasks()

        for child in self.tasks_box.get_children():
            self.tasks_box.remove(child)

        completed_count = 0
        total_count = len(self.tasks)

        for i, task in enumerate(self.tasks):
            if task.completed:
                completed_count += 1
            row = self._create_task_row(i, task)
            self.tasks_box.pack_start(row, False, False, 0)

        if total_count > 0:
            fraction = completed_count / total_count
            pct = int(fraction * 100)
            self.lbl_progress.set_text(f"{completed_count}/{total_count} ({pct}%)")
            self.progress_bar.set_fraction(fraction)
        else:
            self.lbl_progress.set_text("0/0")
            self.progress_bar.set_fraction(0.0)

        self.tasks_box.show_all()
        self._updating_ui = False

    def _create_task_row(self, index: int, task: TaskItem) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.get_style_context().add_class("task-row")

        chk = Gtk.CheckButton()
        chk.set_active(task.completed)
        chk.connect("toggled", self._on_task_toggled, index)
        row.pack_start(chk, False, False, 0)

        lbl = Gtk.Label(label=task.text)
        lbl.set_xalign(0.0)
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        if task.completed:
            lbl.get_style_context().add_class("task-label-completed")
        else:
            lbl.get_style_context().add_class("task-label")
        row.pack_start(lbl, True, True, 0)

        btn_del = Gtk.Button(label="✕")
        btn_del.set_tooltip_text("Delete routine")
        btn_del.get_style_context().add_class("btn-delete")
        btn_del.connect("clicked", self._on_delete_task, index)
        row.pack_start(btn_del, False, False, 0)

        return row

    def _on_task_toggled(self, button, index: int):
        if self._updating_ui:
            return
        is_active = button.get_active()
        self.store.toggle_task(index, is_active)
        self._load_tasks()

    def _on_add_task(self, widget):
        text = self.entry_task.get_text().strip()
        if text:
            self.store.add_task(text)
            self.entry_task.set_text("")
            self._load_tasks()

    def _on_delete_task(self, button, index: int):
        self.store.delete_task(index)
        self._load_tasks()

    def _on_tick(self):
        if self.store.check_date_rollover():
            self._update_date_labels()
            self._load_tasks()
            return True

        if self.store.check_file_changed():
            self._load_tasks()

        return True

    def run(self):
        self.window.show_all()
        Gtk.main()


if __name__ == "__main__":
    _acquire_single_instance_lock()
    app = RoutinesWidget()
    app.run()
