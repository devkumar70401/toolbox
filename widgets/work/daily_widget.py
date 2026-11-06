#!/usr/bin/env python3
"""
Daily Desktop Widget Suite (Combined Work, Diet & Nutrition, Daily Routines)
Modern, transparent, interactive desktop widget with top tabs and dynamic theme colors.
Location: /home/dev/SE/Devendra/widgets/work/daily_widget.py
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
        lock_path = Path(runtime_dir) / "daily_widget.lock"
    else:
        lock_path = Path.home() / ".config" / "daily-todo-widget" / "daily_widget.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_file = open(lock_path, "a+")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        print("Another instance of daily_widget is already running. Exiting.")
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

# Tabs definition: (key, title, input_placeholder)
# Work is first and leftmost by default
TABS = [
    ("work", "💼 WORK", "+ Add a task for today..."),
    ("diet", "🥗 DIET & NUTRITION", "+ Add a meal / food item..."),
    ("routines", "🔄 ROUTINES", "+ Add a routine..."),
]


class DailyTodoWidget:
    def __init__(self):
        # Work is given first precedence and default on startup
        self.active_tab = "work"
        self.store = MultiSectionMarkdownStore(section_type=self.active_tab)
        self.config = self.store.config
        self.tasks = []
        self._updating_ui = False
        self._is_pinned_top = self.config.get("always_on_top", False)
        self._save_timer_id = None
        self.tab_buttons = {}
        self.tab_labels = {}

        self._init_window()
        self._load_css()
        self._build_ui()
        self._load_tasks()

        # Start periodic tick (every 1.5 seconds)
        GLib.timeout_add(1500, self._on_tick)

    def _init_window(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Daily Tasks")
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
        self.target_x = self.config.get("x", 4110)
        self.target_y = self.config.get("y", 505)
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
        css_path = SCRIPT_DIR / "widget.css"
        if css_path.exists():
            provider = Gtk.CssProvider()
            provider.load_from_path(str(css_path))
            screen = Gdk.Screen.get_default()
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _build_ui(self):
        # Outer Card Container with dynamic theme class
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.get_style_context().add_class("main-card")
        self.card.get_style_context().add_class(f"theme-{self.active_tab}")

        # 1. TOP TABS ROW (Clean text tabs, Work on the left, default precedence)
        # Kept outside header_event_box so clicking tabs never conflicts with window dragging
        tabs_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tabs_row.get_style_context().add_class("tabs-row")

        for sec_key, sec_label, _ in TABS:
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_can_focus(False)
            btn.get_style_context().add_class("tab-btn")
            if sec_key == self.active_tab:
                btn.get_style_context().add_class("active")

            lbl = Gtk.Label(label=sec_label)
            lbl.get_style_context().add_class("tab-label")
            btn.add(lbl)
            btn.connect("clicked", self._on_tab_clicked, sec_key)

            tabs_row.pack_start(btn, False, False, 0)
            self.tab_buttons[sec_key] = btn
            self.tab_labels[sec_key] = lbl

        self.card.pack_start(tabs_row, False, False, 0)

        # 2. DRAGGABLE HEADER BOX (Date + Progress Badge + Pin + Folder)
        self.header_event_box = Gtk.EventBox()
        self.header_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.header_event_box.connect("button-press-event", self._on_header_press)

        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        date_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        date_row.get_style_context().add_class("date-row")

        self.lbl_date = Gtk.Label()
        self.lbl_date.set_xalign(0.0)
        self.lbl_date.get_style_context().add_class("title-date")
        date_row.pack_start(self.lbl_date, True, True, 0)

        # Progress badge
        self.lbl_progress = Gtk.Label(label="0/0")
        self.lbl_progress.get_style_context().add_class("progress-badge")
        date_row.pack_start(self.lbl_progress, False, False, 0)

        # Pin / On-top toggle button
        self.btn_pin = Gtk.Button(label="📌" if self._is_pinned_top else "📍")
        self.btn_pin.set_tooltip_text("Toggle Always On Top vs Desktop Pinned")
        self.btn_pin.get_style_context().add_class("btn-icon")
        self.btn_pin.connect("clicked", self._on_toggle_pin)
        date_row.pack_start(self.btn_pin, False, False, 0)

        # Folder button
        btn_folder = Gtk.Button(label="📂")
        btn_folder.set_tooltip_text("Open Daily Markdown Folder")
        btn_folder.get_style_context().add_class("btn-icon")
        btn_folder.connect("clicked", self._on_open_folder)
        date_row.pack_start(btn_folder, False, False, 0)

        header_box.pack_start(date_row, False, False, 0)

        # 3. PROGRESS BAR (Shows active tab progress with dynamic theme color)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.get_style_context().add_class("progress-bar-fill")
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
        self.entry_task.set_placeholder_text(self._get_placeholder_text())
        self.entry_task.get_style_context().add_class("entry-add")
        self.entry_task.connect("activate", self._on_add_task)
        bottom_box.pack_start(self.entry_task, True, True, 0)

        self.btn_add = Gtk.Button(label="Add")
        self.btn_add.get_style_context().add_class("btn-add")
        self.btn_add.connect("clicked", self._on_add_task)
        bottom_box.pack_start(self.btn_add, False, False, 0)

        self.card.pack_start(bottom_box, False, False, 0)

        self.window.add(self.card)
        self._update_date_labels()

    def _get_placeholder_text(self) -> str:
        for key, _, placeholder in TABS:
            if key == self.active_tab:
                return placeholder
        return "+ Add..."

    def _update_date_labels(self):
        now = datetime.now()
        self.lbl_date.set_text(now.strftime("%A, %d %B %Y"))

    def _on_tab_clicked(self, button, section_key: str):
        if self.active_tab == section_key:
            return
        old_tab = self.active_tab
        self.active_tab = section_key

        # 1. Update tab button active classes
        for k, btn in self.tab_buttons.items():
            if k == section_key:
                btn.get_style_context().add_class("active")
            else:
                btn.get_style_context().remove_class("active")

        # 2. Switch theme styling on the entire widget card
        self.card.get_style_context().remove_class(f"theme-{old_tab}")
        self.card.get_style_context().add_class(f"theme-{self.active_tab}")

        # 3. Update entry placeholder
        self.entry_task.set_placeholder_text(self._get_placeholder_text())

        # 4. Load tasks for the newly selected tab
        self._load_tasks()

    def _on_header_press(self, widget, event):
        if event.button == 1:
            # Check if clicked inside a button (pin or folder)
            target = Gtk.get_event_widget(event)
            if isinstance(target, Gtk.Button) or (target and target.get_ancestor(Gtk.Button)):
                return False
            self.window.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )
            return True
        return False

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
        self.tasks = self.store.load_tasks(section=self.active_tab)

        # Clear existing rows
        for child in self.tasks_box.get_children():
            self.tasks_box.remove(child)

        completed_count = 0
        total_count = len(self.tasks)

        for i, task in enumerate(self.tasks):
            if task.completed:
                completed_count += 1
            row = self._create_task_row(i, task)
            self.tasks_box.pack_start(row, False, False, 0)

        # Update progress badge & bar for active section
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

        # Checkbox
        chk = Gtk.CheckButton()
        chk.set_active(task.completed)
        chk.connect("toggled", self._on_task_toggled, index)
        row.pack_start(chk, False, False, 0)

        # Label
        lbl = Gtk.Label(label=task.text)
        lbl.set_xalign(0.0)
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        if task.completed:
            lbl.get_style_context().add_class("task-label-completed")
        else:
            lbl.get_style_context().add_class("task-label")
        row.pack_start(lbl, True, True, 0)

        # Delete Button
        btn_del = Gtk.Button(label="✕")
        btn_del.set_tooltip_text("Delete task")
        btn_del.get_style_context().add_class("btn-delete")
        btn_del.connect("clicked", self._on_delete_task, index)
        row.pack_start(btn_del, False, False, 0)

        return row

    def _on_task_toggled(self, button, index: int):
        if self._updating_ui:
            return
        is_active = button.get_active()
        self.store.toggle_task(index, is_active, section=self.active_tab)
        self._load_tasks()

    def _on_add_task(self, widget):
        text = self.entry_task.get_text().strip()
        if text:
            self.store.add_task(text, section=self.active_tab)
            self.entry_task.set_text("")
            self._load_tasks()

    def _on_delete_task(self, button, index: int):
        self.store.delete_task(index, section=self.active_tab)
        self._load_tasks()

    def _on_tick(self):
        # 1. Check if date changed (midnight rollover)
        if self.store.check_date_rollover():
            self._update_date_labels()
            self._load_tasks()
            return True

        # 2. Check if markdown file was changed externally
        if self.store.check_file_changed():
            self._load_tasks()

        return True

    def run(self):
        self.window.show_all()
        Gtk.main()


if __name__ == "__main__":
    _acquire_single_instance_lock()
    app = DailyTodoWidget()
    app.run()
