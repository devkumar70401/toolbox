#!/usr/bin/env python3
"""
YouTube Desktop Widget (100% Pure Video Mode, No-Close, Standby Black Screen)
Isolated, frameless, transparent glassmorphic desktop widget for YouTube & YouTube Music.
Location: /home/dev/SE/Devendra/widgets/youtube/youtube_widget.py
"""

import sys
import os
import json
import re
import urllib.parse
from urllib.parse import urlparse
import socket
import fcntl
import warnings
from pathlib import Path

IPC_SOCKET_NAME = "\0youtube_widget_ipc"

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1].startswith("--"):
    cmd = sys.argv[1].lstrip("-")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(IPC_SOCKET_NAME)
        s.sendall(cmd.encode("utf-8"))
        resp = s.recv(1024)
        print(resp.decode("utf-8").strip())
        sys.exit(0)
    except Exception as e:
        print(f"Error communicating with youtube widget: {e}")
        sys.exit(1)

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

warnings.filterwarnings('ignore', category=DeprecationWarning)

# Single instance lock
_lock_file = None
def _acquire_single_instance_lock():
    global _lock_file
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        lock_path = Path(runtime_dir) / "youtube_widget.lock"
    else:
        lock_path = Path.home() / ".config" / "youtube-widget" / "youtube_widget.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_file = open(lock_path, "a+")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        print("Another instance of youtube_widget is already running. Exiting.")
        sys.exit(0)
    except Exception as e:
        print(f"Warning: Could not acquire lock at {lock_path}: {e}")

_acquire_single_instance_lock()

# Ensure GTK 3, GDK 3, and WebKit2 (4.1) are loaded
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, Gdk, GLib, WebKit2, Pango

CONFIG_DIR = Path.home() / ".config" / "youtube-widget"
CONFIG_FILE = CONFIG_DIR / "config.json"
REPO_CONFIG_FILE = Path(__file__).parent.resolve() / "config.json"

DATA_DIR = Path.home() / ".local" / "share" / "youtube-widget"
CACHE_DIR = Path.home() / ".cache" / "youtube-widget"

DEFAULT_CONFIG = {
    "x": 3283,
    "y": 1026,
    "width": 594,
    "height": 390,
    "always_on_top": True,
    "view_mode": "youtube",   # "youtube" or "music"
    "pure_video": True,       # 100% video coverage on watch pages
    "powered_on": True,       # True = normal display, False = standby / shrunk button
    "shrink_on_turn_off": True # True = shrink to button widget when turned off
}

ALLOWED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "googlevideo.com",
    "ytimg.com",
    "googleusercontent.com",
    "accounts.google.com",
    "apis.google.com",
    "gstatic.com",
    "googleapis.com"
)

PRESET_SIZES = [
    (594, 390, "Standard"),
    (624, 416, "Compact"),
    (832, 546, "Medium"),
    (1066, 676, "Theater"),
    (1248, 780, "Wide")
]

# Injected CSS for 100% edge-to-edge player and dark theme
PURE_VIDEO_INJECTED_CSS = """
html, body {
    background-color: #000000 !important;
    overflow-x: hidden !important;
}

/* Sleek dark scrollbars */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.22);
    border-radius: 4px;
}
::-webkit-scrollbar-track {
    background: transparent;
}

/* --- 100% PURE VIDEO MODE ON WATCH PAGES --- */
html.pure-video-mode ytd-masthead,
html.pure-video-mode #masthead-container,
html.pure-video-mode #secondary,
html.pure-video-mode #below,
html.pure-video-mode #comments,
html.pure-video-mode #chat,
html.pure-video-mode #actions,
html.pure-video-mode tp-yt-app-drawer,
html.pure-video-mode #guide,
html.pure-video-mode ytd-merch-shelf-renderer {
    display: none !important;
}

html.pure-video-mode #page-manager {
    margin-top: 0 !important;
    padding-top: 0 !important;
}

html.pure-video-mode ytd-watch-flexy {
    margin: 0 !important;
    padding: 0 !important;
    min-height: 100vh !important;
}

html.pure-video-mode #player-container-outer,
html.pure-video-mode #player-container-inner,
html.pure-video-mode #player-container,
html.pure-video-mode ytd-player,
html.pure-video-mode #movie_player {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    max-width: 100vw !important;
    max-height: 100vh !important;
    z-index: 999999 !important;
    margin: 0 !important;
    padding: 0 !important;
}

html.pure-video-mode video.video-stream.html5-main-video {
    width: 100vw !important;
    height: 100vh !important;
    max-width: 100vw !important;
    max-height: 100vh !important;
    object-fit: contain !important;
    top: 0 !important;
    left: 0 !important;
    margin: 0 !important;
}

html.pure-video-mode .ytp-chrome-bottom {
    width: calc(100vw - 24px) !important;
    left: 12px !important;
}
"""

# Injected JavaScript to detect watch pages, activate 100% video mode, and detect hover
PURE_VIDEO_INJECTED_JS = """
(function() {
    let lastWatchState = null;

    function setupPage() {
        document.documentElement.setAttribute('dark', 'true');
        document.documentElement.classList.add('dark');

        const path = window.location.pathname;
        const isWatch = path === '/watch' || path.startsWith('/shorts/');
        const purePref = document.documentElement.getAttribute('data-pure-video');
        const pureActive = purePref !== 'off' && isWatch;

        if (pureActive) {
            if (!document.documentElement.classList.contains('pure-video-mode')) {
                document.documentElement.classList.add('pure-video-mode');
                window.dispatchEvent(new Event('resize'));
            }
            var p = document.getElementById('movie_player');
            if (p && p.setInternalSize) {
                p.setInternalSize();
            }
        } else {
            if (document.documentElement.classList.contains('pure-video-mode')) {
                document.documentElement.classList.remove('pure-video-mode');
                window.dispatchEvent(new Event('resize'));
            }
        }

        // Only send message when watch state actually transitions (prevents title flipping)
        if (isWatch !== lastWatchState) {
            lastWatchState = isWatch;
            try {
                if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.widgetTrigger) {
                    window.webkit.messageHandlers.widgetTrigger.postMessage('page:' + (isWatch ? 'watch' : 'browse'));
                }
            } catch(e) {}
        }
    }

    setupPage();
    document.addEventListener('DOMContentLoaded', setupPage);
    window.addEventListener('yt-navigate-finish', setupPage);
    window.addEventListener('popstate', setupPage);
    setInterval(setupPage, 500);

    // Mouse hover detection to signal floating header reveal
    document.addEventListener('mousemove', function(e) {
        try {
            if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.widgetTrigger) {
                if (e.clientY < 60) {
                    window.webkit.messageHandlers.widgetTrigger.postMessage('mouse:top');
                } else if (e.clientY > 85) {
                    window.webkit.messageHandlers.widgetTrigger.postMessage('mouse:body');
                }
            }
        } catch(err) {}
    }, { passive: true });
})();
"""


def clean_youtube_title(raw_title: str, default_name: str = "YouTube") -> str:
    """Cleans notification counts, play symbols, and YouTube suffixes from page titles."""
    if not raw_title:
        return default_name
    title = raw_title.strip()
    # Strip notification badge prefix e.g. "(1) Video Title" or "(99+) Video Title"
    title = re.sub(r'^\(\d+\+?\)\s*', '', title)
    # Strip leading play symbols if YouTube added them
    title = re.sub(r'^[▶►]\s*', '', title)
    # Strip trailing YouTube suffix
    for suffix in [" - YouTube Music", " - YouTube", " – YouTube", " — YouTube"]:
        if title.endswith(suffix):
            title = title[:-len(suffix)]
            break
    title = title.strip()
    return title or default_name


def normalize_youtube_url(uri: str) -> str:
    """If an /embed/ URL is encountered, redirects it back to standard /watch?v= so it plays natively without Error 153."""
    try:
        parsed = urlparse(uri)
        host = (parsed.hostname or "").lower()
        if "youtube.com" in host or "youtube-nocookie.com" in host:
            if parsed.path.startswith("/embed/"):
                vid = parsed.path.split("/embed/")[1].split("?")[0].split("/")[0]
                if vid:
                    qs = urllib.parse.parse_qs(parsed.query)
                    extra = ""
                    if "list" in qs:
                        extra = f"&list={qs['list'][0]}"
                    return f"https://www.youtube.com/watch?v={vid}{extra}"
    except Exception:
        pass
    return uri


def is_allowed_url(uri: str) -> bool:
    try:
        parsed = urlparse(uri)
        if parsed.scheme in ("about", "data", "blob", "javascript"):
            return True
        host = (parsed.hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)
    except Exception:
        return False


class YouTubeWidget:
    def __init__(self):
        self.config = self._load_config()
        self.target_x = self.config.get("x", DEFAULT_CONFIG["x"])
        self.target_y = self.config.get("y", DEFAULT_CONFIG["y"])
        self.target_w = self.config.get("width", DEFAULT_CONFIG["width"])
        self.target_h = self.config.get("height", DEFAULT_CONFIG["height"])
        self._is_pinned_top = self.config.get("always_on_top", DEFAULT_CONFIG["always_on_top"])
        self._view_mode = self.config.get("view_mode", "youtube")
        self._pure_video_enabled = self.config.get("pure_video", True)
        self._is_powered_on = self.config.get("powered_on", True)

        self.normal_w = self.target_w if self.target_w > 150 else DEFAULT_CONFIG["width"]
        self.normal_h = self.target_h if self.target_h > 120 else DEFAULT_CONFIG["height"]
        self._standby_press_coord = None
        self._standby_is_dragging = False

        self._last_shrunk_offsets = None
        self._initial_positioned = False
        self._save_timer_id = None
        self._hide_header_timer_id = None
        self._is_fullscreen = False
        self._is_watch_page = False
        self._mouse_over_header = False
        self._search_active = False

        self._setup_window()
        self._load_css()
        self._build_ui()
        self._init_ipc()

        # Connect window events (intercept delete-event so widget NEVER closes)
        self.window.connect("delete-event", self._on_delete_event)
        self.window.connect("button-press-event", self._on_window_button_press)
        self.window.connect("key-press-event", self._on_key_press)
        self.window.connect("map-event", self._on_map)
        self.window.connect("configure-event", self._on_configure)

        self.window.show_all()

        # Apply power / standby state
        if not self._is_powered_on:
            if self.config.get("shrink_on_turn_off", True):
                self._apply_shrunk_ui()
            else:
                self._apply_full_standby_ui()
        else:
            self.frame_box.get_style_context().add_class("yt-window-frame")
            self.stack.set_visible_child_name("active")
            self._show_header()

        # Load initial URL
        if self._view_mode == "music":
            self.webview.load_uri("https://music.youtube.com")
        else:
            self.webview.load_uri("https://www.youtube.com")

    def _load_config(self) -> dict:
        cfg = DEFAULT_CONFIG.copy()
        for path in [CONFIG_FILE, REPO_CONFIG_FILE]:
            if path.is_file():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        cfg.update(data)
                        break
                except Exception as e:
                    print(f"Error loading config from {path}: {e}")
        return cfg

    def _save_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        for target in [CONFIG_FILE, REPO_CONFIG_FILE]:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2)
            except Exception as e:
                print(f"Error saving config to {target}: {e}")

    def _setup_window(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("YouTube Widget")
        self.window.set_decorated(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_resizable(True)
        self.window.stick()

        self._apply_layer()

        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.window.set_visual(visual)

        if not self._is_powered_on and self.config.get("shrink_on_turn_off", True):
            self.window.set_default_size(52, 52)
            ox, oy = self._calc_shrunk_offsets()
            self.window.move(self.target_x + ox, self.target_y + oy)
        else:
            self.window.set_default_size(self.target_w, self.target_h)
            self.window.move(self.target_x, self.target_y)

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
        .yt-window-frame {
            background-color: #000000;
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 18px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.7);
        }
        .yt-floating-header {
            background-color: rgba(18, 20, 26, 0.88);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 14px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.75);
            margin: 8px 12px;
            padding: 5px 10px;
        }
        .yt-title {
            font-size: 13px;
            font-weight: bold;
            color: #f3f4f6;
        }
        .btn-icon {
            background: transparent;
            border: 1px solid transparent;
            color: #9ca3af;
            padding: 3px 6px;
            border-radius: 8px;
            font-size: 13px;
        }
        .btn-icon:hover {
            background-color: rgba(255, 255, 255, 0.14);
            color: #ffffff;
            border-color: rgba(255, 255, 255, 0.18);
        }
        .btn-icon:disabled {
            color: #4b5563;
        }
        .btn-icon.active {
            background-color: rgba(16, 185, 129, 0.22);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.4);
        }
        .btn-home {
            background-color: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.22);
            color: #ffffff;
            padding: 4px 12px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
        }
        .btn-home:hover {
            background-color: rgba(255, 255, 255, 0.25);
            border-color: rgba(255, 255, 255, 0.45);
            color: #ffffff;
        }
        .btn-search {
            background-color: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.22);
            color: #ffffff;
            padding: 4px 12px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
        }
        .btn-search:hover {
            background-color: rgba(255, 255, 255, 0.25);
            border-color: rgba(255, 255, 255, 0.45);
            color: #ffffff;
        }
        .btn-search.active {
            background-color: rgba(59, 130, 246, 0.30);
            border-color: rgba(59, 130, 246, 0.65);
            color: #93c5fd;
        }
        .yt-search-entry {
            background-color: rgba(20, 24, 33, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 8px;
            color: #ffffff;
            padding: 3px 8px;
            font-size: 12px;
            min-height: 24px;
        }
        .yt-search-entry:focus {
            background-color: rgba(25, 30, 42, 1.0);
            border-color: rgba(59, 130, 246, 0.75);
            color: #ffffff;
        }
        .yt-search-entry placeholder {
            color: rgba(255, 255, 255, 0.45);
        }
        .btn-back {
            background-color: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.22);
            color: #ffffff;
            padding: 4px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
        }
        .btn-back:hover {
            background-color: rgba(255, 255, 255, 0.25);
            border-color: rgba(255, 255, 255, 0.45);
            color: #ffffff;
        }
        .btn-power {
            background-color: rgba(239, 68, 68, 0.18);
            border: 1px solid rgba(239, 68, 68, 0.35);
            color: #f87171;
            padding: 4px 10px;
            border-radius: 8px;
            font-size: 14px;
        }
        .btn-power:hover {
            background-color: rgba(239, 68, 68, 0.35);
            border-color: #ef4444;
            color: #fca5a5;
        }
        /* --- 100% BLACK SCREEN STANDBY STYLING --- */
        .standby-screen {
            background-color: #000000;
            border-radius: 18px;
        }
        .btn-standby-power {
            background-color: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 50%;
            color: #ef4444;
            font-size: 28px;
            padding: 16px 22px;
        }
        .btn-standby-power:hover {
            background-color: rgba(239, 68, 68, 0.25);
            border-color: #ef4444;
            color: #fca5a5;
        }
        .standby-text {
            color: #9ca3af;
            font-size: 12px;
            font-weight: 500;
            margin-top: 8px;
        }
        /* --- SHRUNK BUTTON-SIZED STANDBY STYLING --- */
        .shrunk-frame {
            background: radial-gradient(circle, #251212 0%, #0d0d10 100%);
            border: 2px solid rgba(239, 68, 68, 0.7);
            border-radius: 26px;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.85), 0 0 12px rgba(239, 68, 68, 0.35);
        }
        .shrunk-frame:hover {
            background: radial-gradient(circle, #381818 0%, #15151b 100%);
            border-color: #ff3b30;
            box-shadow: 0 6px 24px rgba(0, 0, 0, 0.95), 0 0 18px rgba(239, 68, 68, 0.6);
        }
        .shrunk-icon {
            color: #ef4444;
            font-size: 22px;
            font-weight: bold;
        }
        .shrunk-frame:hover .shrunk-icon {
            color: #ff6e65;
        }
        .btn-shrunk-power {
            background: radial-gradient(circle, #251212 0%, #0d0d10 100%);
            border: 2px solid rgba(239, 68, 68, 0.7);
            border-radius: 26px;
            color: #ef4444;
            font-size: 22px;
            font-weight: bold;
            padding: 0px;
            margin: 0px;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.85), 0 0 12px rgba(239, 68, 68, 0.35);
        }
        .btn-shrunk-power:hover {
            background: radial-gradient(circle, #381818 0%, #15151b 100%);
            border-color: #ff3b30;
            color: #ff6e65;
            box-shadow: 0 6px 24px rgba(0, 0, 0, 0.95), 0 0 18px rgba(239, 68, 68, 0.6);
        }
        .btn-shrunk-power:active {
            background: radial-gradient(circle, #4a1e1e 0%, #201515 100%);
            color: #ffffff;
            border-color: #ff5544;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        self.frame_box = Gtk.Box()
        self.frame_box.get_style_context().add_class("yt-window-frame")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(250)
        self.stack.set_homogeneous(False)

        # ==========================================
        # PAGE 1: "active" - LIVE WIDGET
        # ==========================================
        self.overlay = Gtk.Overlay()

        # 1. Base Layer: 100% Edge-to-Edge WebKit WebView
        self._setup_webview()
        self.overlay.add(self.webview)

        # 2. Floating Auto-Hiding Header Bar
        self.header_revealer = Gtk.Revealer()
        self.header_revealer.set_valign(Gtk.Align.START)
        self.header_revealer.set_halign(Gtk.Align.FILL)
        self.header_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.header_revealer.set_transition_duration(250)
        self.header_revealer.connect("notify::child-revealed", self._on_header_revealed_changed)

        self.header_event_box = Gtk.EventBox()
        self.header_event_box.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.header_event_box.connect("button-press-event", self._on_header_press)
        self.header_event_box.connect("enter-notify-event", self._on_header_enter)
        self.header_event_box.connect("leave-notify-event", self._on_header_leave)

        self.floating_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.floating_box.get_style_context().add_class("yt-floating-header")

        # Top row of header
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Left: YouTube Icon & Title
        lbl_icon = Gtk.Label(label="▶️")
        header_row.pack_start(lbl_icon, False, False, 0)

        self.lbl_title = Gtk.Label(label="YouTube")
        self.lbl_title.get_style_context().add_class("yt-title")
        self.lbl_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_title.set_max_width_chars(38)
        self.lbl_title.set_xalign(0.0)
        header_row.pack_start(self.lbl_title, False, False, 0)

        # Flexible spacer
        spacer = Gtk.Box()
        header_row.pack_start(spacer, True, True, 0)

        # OPTION 1: Home Option
        self.btn_home = Gtk.Button(label="🏠 Home")
        self.btn_home.set_tooltip_text("Go to Home (Alt+Home)")
        self.btn_home.get_style_context().add_class("btn-home")
        self.btn_home.connect("clicked", lambda b: self._on_go_home())
        header_row.pack_start(self.btn_home, False, False, 4)

        # OPTION 2: Search Option (Search button + expandable search bar)
        self.search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self.search_revealer = Gtk.Revealer()
        self.search_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.search_revealer.set_transition_duration(200)

        self.search_entry = Gtk.Entry()
        placeholder = "Search YouTube Music..." if self._view_mode == "music" else "Search YouTube..."
        self.search_entry.set_placeholder_text(placeholder)
        self.search_entry.get_style_context().add_class("yt-search-entry")
        self.search_entry.set_width_chars(22)
        self.search_entry.connect("activate", self._on_search_activate)
        self.search_entry.connect("key-press-event", self._on_search_entry_key_press)
        self.search_entry.connect("changed", self._on_search_changed)
        self.search_entry.connect("icon-press", self._on_search_icon_press)
        self.search_revealer.add(self.search_entry)

        self.btn_search = Gtk.Button(label="🔍 Search")
        self.btn_search.set_tooltip_text("Search YouTube (Ctrl+F or /)")
        self.btn_search.get_style_context().add_class("btn-search")
        self.btn_search.connect("clicked", self._on_search_button_clicked)

        self.search_box.pack_start(self.search_revealer, False, False, 0)
        self.search_box.pack_start(self.btn_search, False, False, 0)
        header_row.pack_start(self.search_box, False, False, 4)

        # OPTION 3: Back Option
        self.btn_back = Gtk.Button(label="‹ Back")
        self.btn_back.set_tooltip_text("Go Back (Alt+Left or Backspace)")
        self.btn_back.get_style_context().add_class("btn-back")
        self.btn_back.connect("clicked", lambda b: self._on_go_back())
        header_row.pack_start(self.btn_back, False, False, 4)

        # OPTION 4: Stand-by Option (Turn Off & Shrink to Button)
        self.btn_power = Gtk.Button(label="⏻")
        self._update_power_button_tooltip()
        self.btn_power.get_style_context().add_class("btn-icon")
        self.btn_power.get_style_context().add_class("btn-power")
        self.btn_power.connect("clicked", lambda b: self._turn_off())
        self.btn_power.connect("button-press-event", self._on_power_btn_press)
        header_row.pack_start(self.btn_power, False, False, 2)

        self.floating_box.pack_start(header_row, False, False, 0)

        self.header_event_box.add(self.floating_box)
        self.header_revealer.add(self.header_event_box)
        self.overlay.add_overlay(self.header_revealer)

        self.stack.add_named(self.overlay, "active")

        # ==========================================
        # PAGE 2: "standby" - BUTTON-SIZED OR FULL STANDBY
        # ==========================================
        self.standby_wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # 1. Shrunk Button-Sized Widget Container (52x52)
        self.shrunk_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.shrunk_container.set_valign(Gtk.Align.CENTER)
        self.shrunk_container.set_halign(Gtk.Align.CENTER)

        self.btn_shrunk = Gtk.Button(label="⏻")
        self.btn_shrunk.get_style_context().add_class("btn-shrunk-power")
        self.btn_shrunk.set_tooltip_text(
            "YouTube Widget (Turned Off) · Click to Turn On · Drag to Move"
        )
        self.btn_shrunk.set_size_request(48, 48)
        self.btn_shrunk.connect("clicked", lambda b: self._turn_on())
        self.btn_shrunk.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
        self.btn_shrunk.connect("button-press-event", self._on_shrunk_btn_press)
        self.btn_shrunk.connect("motion-notify-event", self._on_shrunk_btn_motion)
        self.shrunk_container.pack_start(self.btn_shrunk, True, True, 0)
        self.standby_wrapper.pack_start(self.shrunk_container, True, True, 0)

        # 2. Legacy Full Standby Container (Full-screen 100% black)
        self.full_standby_event_box = Gtk.EventBox()
        self.full_standby_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.full_standby_event_box.connect("button-press-event", self._on_full_standby_click)

        self.full_standby_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.full_standby_container.get_style_context().add_class("standby-screen")

        standby_center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        standby_center.set_valign(Gtk.Align.CENTER)
        standby_center.set_halign(Gtk.Align.CENTER)

        self.btn_wake_power = Gtk.Button(label="⏻")
        self.btn_wake_power.set_tooltip_text("Turn On YouTube Widget")
        self.btn_wake_power.get_style_context().add_class("btn-standby-power")
        self.btn_wake_power.connect("clicked", lambda b: self._turn_on())
        standby_center.pack_start(self.btn_wake_power, False, False, 0)

        lbl_standby = Gtk.Label(label="Widget Standby · Click to Turn On")
        lbl_standby.get_style_context().add_class("standby-text")
        standby_center.pack_start(lbl_standby, False, False, 0)

        self.full_standby_container.pack_start(standby_center, True, True, 0)
        self.full_standby_event_box.add(self.full_standby_container)
        self.standby_wrapper.pack_start(self.full_standby_event_box, True, True, 0)

        self.stack.add_named(self.standby_wrapper, "standby")

        self.frame_box.pack_start(self.stack, True, True, 0)
        self.window.add(self.frame_box)

    def _setup_webview(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        dm = WebKit2.WebsiteDataManager(
            base_data_directory=str(DATA_DIR),
            base_cache_directory=str(CACHE_DIR)
        )
        ctx = WebKit2.WebContext.new_with_website_data_manager(dm)

        # Persistent cookies
        cookie_file = str(DATA_DIR / "cookies.sqlite")
        cm = ctx.get_cookie_manager()
        cm.set_persistent_storage(cookie_file, WebKit2.CookiePersistentStorage.SQLITE)

        # User Content Manager
        self.ucm = WebKit2.UserContentManager()
        self.ucm.register_script_message_handler("widgetTrigger")
        self.ucm.connect("script-message-received::widgetTrigger", self._on_script_message)

        # User stylesheet
        user_css = WebKit2.UserStyleSheet(
            PURE_VIDEO_INJECTED_CSS,
            WebKit2.UserContentInjectedFrames.ALL_FRAMES,
            WebKit2.UserStyleLevel.USER,
            None,
            None
        )
        self.ucm.add_style_sheet(user_css)

        # User script
        user_script = WebKit2.UserScript(
            PURE_VIDEO_INJECTED_JS,
            WebKit2.UserContentInjectedFrames.ALL_FRAMES,
            WebKit2.UserScriptInjectionTime.START,
            None,
            None
        )
        self.ucm.add_script(user_script)

        self.webview = WebKit2.WebView(web_context=ctx, user_content_manager=self.ucm)

        bg = Gdk.RGBA(0.0, 0.0, 0.0, 1.0)
        self.webview.set_background_color(bg)

        settings = self.webview.get_settings()
        settings.set_user_agent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        settings.set_enable_media(True)
        settings.set_enable_mediasource(True)
        settings.set_enable_encrypted_media(True)
        settings.set_enable_webaudio(True)
        settings.set_enable_webgl(True)
        settings.set_media_playback_allows_inline(True)
        settings.set_media_playback_requires_user_gesture(False)
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
        settings.set_enable_smooth_scrolling(True)
        settings.set_javascript_can_open_windows_automatically(True)

        # Signals
        self.webview.connect("decide-policy", self._on_decide_policy)
        self.webview.connect("load-changed", self._on_load_changed)
        self.webview.connect("notify::title", self._on_title_changed)
        self.webview.connect("enter-fullscreen", self._on_enter_fullscreen)
        self.webview.connect("leave-fullscreen", self._on_leave_fullscreen)

    def _on_delete_event(self, widget, event):
        """Intercepts close signals. Instead of closing, enters standby / shrinks to button."""
        self._turn_off()
        return True  # Stop propagation so window is NEVER destroyed

    def _calc_shrunk_offsets(self):
        """Calculates (ox, oy) offset from the widget's top-left to align the shrunk button with btn_power."""
        BUTTON_SIZE = 52
        cur_w = getattr(self, "normal_w", self.config.get("width", DEFAULT_CONFIG["width"]))
        if hasattr(self, "btn_power") and self.btn_power.get_realized():
            try:
                coords = self.btn_power.translate_coordinates(self.window, 0, 0)
                alloc = self.btn_power.get_allocation()
                if coords and coords[0] > 0 and alloc.width > 0:
                    center_x = coords[0] + alloc.width // 2
                    center_y = coords[1] + alloc.height // 2
                    if 0 <= center_y <= 120:
                        ox = max(0, center_x - BUTTON_SIZE // 2)
                        oy = max(0, center_y - BUTTON_SIZE // 2)
                        self._last_shrunk_offsets = (ox, oy)
                        return ox, oy
            except Exception:
                pass
        if getattr(self, "_last_shrunk_offsets", None):
            return self._last_shrunk_offsets
        return max(0, cur_w - BUTTON_SIZE - 19), 6

    def _turn_off(self):
        """Turns off widget and shrinks it to a compact button-sized widget (or full standby)."""
        self._is_powered_on = False
        self.config["powered_on"] = False

        if getattr(self, "_is_fullscreen", False):
            self.window.unfullscreen()
            self._is_fullscreen = False

        # Pause any playing media immediately
        js = "document.querySelectorAll('video, audio').forEach(el => el.pause());"
        try:
            self.webview.evaluate_javascript(js, -1, None, None, None, None, None)
        except Exception:
            pass

        # Calculate shrunk target position BEFORE hiding header
        cur_x, cur_y = self.window.get_position()
        ox, oy = self._calc_shrunk_offsets()

        # Cache normal dimensions before shrinking
        cur_w, cur_h = self.window.get_size()
        if cur_w > 150 and cur_h > 120:
            self.normal_w = cur_w
            self.normal_h = cur_h
            self.config["width"] = cur_w
            self.config["height"] = cur_h
            self.config["x"] = cur_x
            self.config["y"] = cur_y
            self.target_x = cur_x
            self.target_y = cur_y

        # Hide floating header & close search
        self._close_search()
        if self._hide_header_timer_id:
            GLib.source_remove(self._hide_header_timer_id)
            self._hide_header_timer_id = None
        self.header_revealer.set_reveal_child(False)

        # Switch UI to shrunk button or full black standby
        if self.config.get("shrink_on_turn_off", True):
            target_shrunk_x = cur_x + ox
            target_shrunk_y = cur_y + oy
            self._apply_shrunk_ui(target_x=target_shrunk_x, target_y=target_shrunk_y)
        else:
            self._apply_full_standby_ui()

        self._save_config()

    def _apply_shrunk_ui(self, target_x=None, target_y=None):
        """Applies button-sized widget UI (52x52) and hides full webview."""
        if hasattr(self, "full_standby_event_box"):
            self.full_standby_event_box.hide()
        elif hasattr(self, "full_standby_container"):
            self.full_standby_container.hide()
        if hasattr(self, "shrunk_container"):
            self.shrunk_container.show_all()

        self.overlay.hide()
        self.stack.set_visible_child_name("standby")

        self.frame_box.get_style_context().remove_class("yt-window-frame")
        self.frame_box.get_style_context().add_class("shrunk-frame")

        BUTTON_SIZE = 52
        if target_x is not None and target_y is not None:
            self.window.move(target_x, target_y)

        gdk_win = self.window.get_window()
        if gdk_win:
            gdk_win.resize(BUTTON_SIZE, BUTTON_SIZE)
        self.window.resize(BUTTON_SIZE, BUTTON_SIZE)

        if target_x is not None and target_y is not None:
            self.window.move(target_x, target_y)

        if hasattr(self, "btn_shrunk"):
            self.btn_shrunk.grab_focus()

    def _apply_full_standby_ui(self):
        """Applies full-size 100% black screen standby mode."""
        if hasattr(self, "shrunk_container"):
            self.shrunk_container.hide()
        if hasattr(self, "full_standby_event_box"):
            self.full_standby_event_box.show_all()
        elif hasattr(self, "full_standby_container"):
            self.full_standby_container.show_all()

        self.frame_box.get_style_context().remove_class("shrunk-frame")
        self.frame_box.get_style_context().add_class("yt-window-frame")

        self.stack.set_visible_child_name("standby")

    def _turn_on(self):
        """Wakes up widget from standby mode and restores normal player size."""
        self._is_powered_on = True
        self.config["powered_on"] = True

        # Switch styling back to normal window frame
        self.frame_box.get_style_context().remove_class("shrunk-frame")
        self.frame_box.get_style_context().add_class("yt-window-frame")

        # Show active webview overlay & switch stack
        self.overlay.show_all()
        self.stack.set_visible_child_name("active")

        # Restore normal dimensions
        restore_w = getattr(self, "normal_w", self.config.get("width", DEFAULT_CONFIG["width"]))
        restore_h = getattr(self, "normal_h", self.config.get("height", DEFAULT_CONFIG["height"]))
        if restore_w < 200:
            restore_w = DEFAULT_CONFIG["width"]
        if restore_h < 150:
            restore_h = DEFAULT_CONFIG["height"]

        # Calculate position so that the off button stays right where the mini button was
        cur_x, cur_y = self.window.get_position()
        if self.config.get("shrink_on_turn_off", True):
            ox, oy = self._calc_shrunk_offsets()
            restore_x = cur_x - ox
            restore_y = cur_y - oy
        else:
            restore_x = cur_x
            restore_y = cur_y

        # Screen boundaries clamping using monitor geometry
        display = Gdk.Display.get_default()
        if display:
            monitor = display.get_monitor_at_point(cur_x, cur_y)
            if not monitor:
                monitor = display.get_primary_monitor() or display.get_monitor(0)
            if monitor:
                geom = monitor.get_geometry()
                mon_x, mon_y, mon_w, mon_h = geom.x, geom.y, geom.width, geom.height
                if restore_x + restore_w > mon_x + mon_w:
                    restore_x = max(mon_x, mon_x + mon_w - restore_w - 20)
                if restore_y + restore_h > mon_y + mon_h:
                    restore_y = max(mon_y, mon_y + mon_h - restore_h - 20)
                if restore_x < mon_x:
                    restore_x = mon_x
                if restore_y < mon_y:
                    restore_y = mon_y

        self.window.move(restore_x, restore_y)
        self.target_x = restore_x
        self.target_y = restore_y
        self.config["x"] = restore_x
        self.config["y"] = restore_y

        gdk_win = self.window.get_window()
        if gdk_win:
            gdk_win.resize(restore_w, restore_h)
        self.window.resize(restore_w, restore_h)

        # Show header & save config
        self._show_header()
        self._save_config()

    def _on_shrunk_btn_press(self, button, event):
        if event.button == 1:
            self._shrunk_drag_coord = (event.x_root, event.y_root, event.time)
            if event.state & Gdk.ModifierType.MOD1_MASK:
                self.window.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)
                return True
            return False  # Let GtkButton process standard click
        elif event.button == 2:
            self.window.begin_move_drag(2, int(event.x_root), int(event.y_root), event.time)
            return True
        elif event.button == 3:
            self._show_standby_context_menu(event)
            return True
        return False

    def _on_shrunk_btn_motion(self, button, event):
        if hasattr(self, "_shrunk_drag_coord") and self._shrunk_drag_coord and (event.state & Gdk.ModifierType.BUTTON1_MASK):
            dx = abs(event.x_root - self._shrunk_drag_coord[0])
            dy = abs(event.y_root - self._shrunk_drag_coord[1])
            if dx > 8 or dy > 8:
                self.window.begin_move_drag(1, int(event.x_root), int(event.y_root), int(event.time))
                self._shrunk_drag_coord = None
                return True
        return False

    def _on_full_standby_click(self, widget, event):
        if event.button == 1:
            self._turn_on()
            return True
        elif event.button == 3:
            self._show_standby_context_menu(event)
            return True
        return False

    def _on_power_btn_press(self, button, event):
        if event.button == 3:
            menu = Gtk.Menu()

            item_off = Gtk.MenuItem(label="⏻ Turn Off Widget")
            item_off.connect("activate", lambda m: self._turn_off())
            menu.append(item_off)

            sep1 = Gtk.SeparatorMenuItem()
            menu.append(sep1)

            shrink_active = self.config.get("shrink_on_turn_off", True)
            item_shrink = Gtk.CheckMenuItem(label="Shrink to Button on Turn Off")
            item_shrink.set_active(shrink_active)
            item_shrink.connect("toggled", self._on_toggle_shrink_config)
            menu.append(item_shrink)

            sep2 = Gtk.SeparatorMenuItem()
            menu.append(sep2)

            item_quit = Gtk.MenuItem(label="❌ Exit YouTube Widget")
            item_quit.connect("activate", lambda m: Gtk.main_quit())
            menu.append(item_quit)

            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        return False

    def _show_standby_context_menu(self, event):
        menu = Gtk.Menu()

        item_wake = Gtk.MenuItem(label="▶ Turn On YouTube Widget")
        item_wake.connect("activate", lambda m: self._turn_on())
        menu.append(item_wake)

        sep1 = Gtk.SeparatorMenuItem()
        menu.append(sep1)

        shrink_active = self.config.get("shrink_on_turn_off", True)
        item_shrink = Gtk.CheckMenuItem(label="Shrink to Button on Turn Off")
        item_shrink.set_active(shrink_active)
        item_shrink.connect("toggled", self._on_toggle_shrink_config)
        menu.append(item_shrink)

        item_pin = Gtk.CheckMenuItem(label="Always On Top")
        item_pin.set_active(self._is_pinned_top)
        item_pin.connect("toggled", lambda m: self._toggle_pin())
        menu.append(item_pin)

        sep2 = Gtk.SeparatorMenuItem()
        menu.append(sep2)

        item_quit = Gtk.MenuItem(label="❌ Exit YouTube Widget")
        item_quit.connect("activate", lambda m: Gtk.main_quit())
        menu.append(item_quit)

        menu.show_all()
        menu.popup_at_pointer(event)

    def _on_toggle_shrink_config(self, item):
        val = item.get_active()
        self.config["shrink_on_turn_off"] = val
        self._save_config()
        self._update_power_button_tooltip()
        if not self._is_powered_on:
            if val:
                cur_x, cur_y = self.window.get_position()
                ox, oy = self._calc_shrunk_offsets()
                self._apply_shrunk_ui(target_x=cur_x + ox, target_y=cur_y + oy)
            else:
                cur_x, cur_y = self.window.get_position()
                ox, oy = self._calc_shrunk_offsets()
                restore_w = getattr(self, "normal_w", self.config.get("width", DEFAULT_CONFIG["width"]))
                restore_h = getattr(self, "normal_h", self.config.get("height", DEFAULT_CONFIG["height"]))
                self.window.move(cur_x - ox, cur_y - oy)
                self.window.resize(restore_w, restore_h)
                self._apply_full_standby_ui()

    def _toggle_pin(self):
        self._is_pinned_top = not self._is_pinned_top
        self.config["always_on_top"] = self._is_pinned_top
        self._apply_layer()
        self._save_config()

    def _update_power_button_tooltip(self):
        if hasattr(self, "btn_power"):
            if self.config.get("shrink_on_turn_off", True):
                self.btn_power.set_tooltip_text("Turn Off & Shrink to Button (Ctrl+P)")
            else:
                self.btn_power.set_tooltip_text("Turn Off (100% Black Screen Standby) (Ctrl+P)")

    def _init_ipc(self):
        try:
            self.ipc_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.ipc_sock.bind(IPC_SOCKET_NAME)
            self.ipc_sock.listen(5)
            self.ipc_sock.setblocking(False)
            GLib.io_add_watch(self.ipc_sock.fileno(), GLib.IO_IN, self._on_ipc_connection)
        except Exception as e:
            print(f"IPC init note: {e}")

    def _on_ipc_connection(self, fd, condition):
        try:
            conn, _ = self.ipc_sock.accept()
            data = conn.recv(1024).decode("utf-8").strip()
            cmd = data.lower().lstrip("-")
            if cmd in ("toggle", "power"):
                if self._is_powered_on:
                    self._turn_off()
                    conn.sendall(b"OK: turned_off\n")
                else:
                    self._turn_on()
                    conn.sendall(b"OK: turned_on\n")
            elif cmd in ("off", "shrink"):
                self._turn_off()
                conn.sendall(b"OK: turned_off\n")
            elif cmd in ("on", "wake"):
                self._turn_on()
                conn.sendall(b"OK: turned_on\n")
            elif cmd == "status":
                w, h = self.window.get_size()
                x, y = self.window.get_position()
                ox, oy = self._calc_shrunk_offsets()
                info = {
                    "powered_on": self._is_powered_on,
                    "shrunk": not self._is_powered_on and self.config.get("shrink_on_turn_off", True),
                    "current_width": w,
                    "current_height": h,
                    "current_x": x,
                    "current_y": y,
                    "offset_x": ox,
                    "offset_y": oy,
                    "saved_width": self.config.get("width", DEFAULT_CONFIG["width"]),
                    "saved_height": self.config.get("height", DEFAULT_CONFIG["height"]),
                    "x": self.config.get("x", DEFAULT_CONFIG["x"]),
                    "y": self.config.get("y", DEFAULT_CONFIG["y"])
                }
                conn.sendall((json.dumps(info) + "\n").encode("utf-8"))
            elif cmd == "home":
                self._on_go_home()
                conn.sendall(b"OK: home\n")
            elif cmd == "reload":
                self.webview.reload()
                conn.sendall(b"OK: reloaded\n")
            elif cmd in ("quit", "exit"):
                conn.sendall(b"OK: quitting\n")
                conn.close()
                Gtk.main_quit()
                return False
            else:
                conn.sendall(b"UNKNOWN_COMMAND\n")
            conn.close()
        except Exception as e:
            print(f"IPC connection error: {e}")
        return True

    def _on_script_message(self, ucm, js_result):
        """Receives messages from the injected JavaScript."""
        if not self._is_powered_on:
            return

        try:
            val = js_result.get_js_value()
            msg = val.to_string()
        except Exception:
            return

        if msg == "page:watch":
            self._is_watch_page = True
            if self._pure_video_enabled:
                self._schedule_hide_header(delay_ms=2200)

        elif msg == "page:browse":
            self._is_watch_page = False
            self._show_header()

        elif msg == "mouse:top":
            self._show_header()

        elif msg == "mouse:body":
            if (
                self._is_watch_page
                and self._pure_video_enabled
                and not self._mouse_over_header
                and not getattr(self, "_search_active", False)
                and not (hasattr(self, "search_entry") and self.search_entry.is_focus())
            ):
                self._schedule_hide_header(delay_ms=1600)

    def _show_header(self):
        if not self._is_powered_on:
            return
        if self._hide_header_timer_id:
            GLib.source_remove(self._hide_header_timer_id)
            self._hide_header_timer_id = None
        self.overlay.set_overlay_pass_through(self.header_revealer, False)
        self.header_revealer.set_reveal_child(True)

    def _schedule_hide_header(self, delay_ms: int = 2000):
        if (
            self._mouse_over_header
            or getattr(self, "_search_active", False)
            or (hasattr(self, "search_entry") and self.search_entry.is_focus())
            or not self._is_watch_page
            or not self._pure_video_enabled
            or not self._is_powered_on
        ):
            return
        if self._hide_header_timer_id:
            GLib.source_remove(self._hide_header_timer_id)
        self._hide_header_timer_id = GLib.timeout_add(delay_ms, self._do_hide_header)

    def _do_hide_header(self):
        if (
            not self._mouse_over_header
            and not getattr(self, "_search_active", False)
            and not (hasattr(self, "search_entry") and self.search_entry.is_focus())
            and self._is_watch_page
            and self._pure_video_enabled
        ):
            self.header_revealer.set_reveal_child(False)
        self._hide_header_timer_id = None
        return False

    def _on_header_revealed_changed(self, revealer, pspec):
        is_revealed = revealer.get_child_revealed()
        self.overlay.set_overlay_pass_through(revealer, not is_revealed)

    def _on_header_enter(self, widget, event):
        self._mouse_over_header = True
        self._show_header()

    def _on_header_leave(self, widget, event):
        self._mouse_over_header = False
        if getattr(self, "_search_active", False) or (hasattr(self, "search_entry") and self.search_entry.is_focus()):
            return
        if self._is_watch_page and self._pure_video_enabled:
            self._schedule_hide_header(delay_ms=1800)

    def _on_search_button_clicked(self, button=None):
        if not self.search_revealer.get_reveal_child():
            self._open_search()
        else:
            query = self.search_entry.get_text().strip()
            if query:
                self._execute_search(query)
            else:
                self._close_search()

    def _on_search_activate(self, entry):
        query = entry.get_text().strip()
        if query:
            self._execute_search(query)

    def _on_search_entry_key_press(self, entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self._close_search()
            return True
        return False

    def _on_search_changed(self, entry):
        text = entry.get_text()
        if text:
            entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-clear-symbolic")
            entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Clear search")
        else:
            entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, None)

    def _on_search_icon_press(self, entry, icon_pos, event):
        if icon_pos == Gtk.EntryIconPosition.SECONDARY:
            entry.set_text("")
            entry.grab_focus()

    def _open_search(self):
        self._search_active = True
        self._show_header()
        self.search_revealer.set_reveal_child(True)
        self.btn_search.get_style_context().add_class("active")
        GLib.timeout_add(80, self._focus_search_entry)

    def _focus_search_entry(self):
        if hasattr(self, "search_entry"):
            self.search_entry.grab_focus()
            self.search_entry.select_region(0, -1)
        return False

    def _close_search(self):
        self._search_active = False
        if hasattr(self, "search_revealer"):
            self.search_revealer.set_reveal_child(False)
        if hasattr(self, "btn_search"):
            self.btn_search.get_style_context().remove_class("active")
        self.window.grab_focus()
        if self._is_watch_page and self._pure_video_enabled:
            self._schedule_hide_header(delay_ms=1800)

    def _toggle_search(self):
        if hasattr(self, "search_revealer") and self.search_revealer.get_reveal_child():
            self._close_search()
        else:
            self._open_search()

    def _execute_search(self, query: str):
        query = query.strip()
        if not query:
            return

        cur_uri = (self.webview.get_uri() or "").lower()
        is_music = self._view_mode == "music" or "music.youtube.com" in cur_uri

        if (
            query.startswith("http://")
            or query.startswith("https://")
            or "youtube.com" in query
            or "youtu.be" in query
        ):
            url = query if query.startswith("http") else f"https://{query}"
            normalized = normalize_youtube_url(url)
            self.webview.load_uri(normalized)
        else:
            encoded = urllib.parse.quote_plus(query)
            if is_music:
                search_url = f"https://music.youtube.com/search?q={encoded}"
            else:
                search_url = f"https://www.youtube.com/results?search_query={encoded}"
            self.webview.load_uri(search_url)

        self._close_search()

    def _on_go_home(self, button=None):
        """Navigates to YouTube Home page."""
        if getattr(self, "_search_active", False) or (
            hasattr(self, "search_revealer") and self.search_revealer.get_reveal_child()
        ):
            self._close_search()
        self._show_header()

        cur_uri = (self.webview.get_uri() or "").lower()
        is_music = "music.youtube.com" in cur_uri or self._view_mode == "music"
        home_url = "https://music.youtube.com" if is_music else "https://www.youtube.com"

        js = f"""
        (function() {{
            try {{
                const logo = document.querySelector('a#logo, a.ytd-topbar-logo-renderer, ytmusic-nav-bar #left-content a');
                if (logo && window.location.pathname !== '/' && window.location.pathname !== '') {{
                    logo.click();
                    return;
                }}
            }} catch (e) {{}}
            window.location.href = '{home_url}';
        }})();
        """
        try:
            self.webview.evaluate_javascript(js, -1, None, None, None, None, None)
        except Exception:
            self.webview.load_uri(home_url)

    def _on_go_back(self, button=None):
        """Goes back to previous video or Home page."""
        js = """
        (function() {
            if (window.location.pathname !== '/' && window.location.pathname !== '') {
                if (window.history.length > 1) {
                    window.history.back();
                } else {
                    window.location.href = 'https://www.youtube.com';
                }
            } else {
                if (window.history.length > 1) {
                    window.history.back();
                }
            }
        })();
        """
        try:
            self.webview.evaluate_javascript(js, -1, None, None, None, None, None)
        except Exception:
            if self.webview.can_go_back():
                self.webview.go_back()
            else:
                self.webview.load_uri("https://www.youtube.com")

    def _on_enter_fullscreen(self, webview):
        self._is_fullscreen = True
        self.header_revealer.set_reveal_child(False)
        self.window.fullscreen()
        return False

    def _on_leave_fullscreen(self, webview):
        self._is_fullscreen = False
        self.window.unfullscreen()
        self._show_header()
        return False

    def _on_decide_policy(self, web_view, decision, decision_type):
        """Strict domain filter & automatic normalization of embed URLs to watch URLs."""
        if decision_type in (
            WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
            WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION,
        ):
            nav_action = decision.get_navigation_action()
            req = nav_action.get_request()
            uri = req.get_uri() if req else ""

            if is_allowed_url(uri):
                # If an /embed/ URL is encountered, normalize to native /watch?v= to avoid Error 153
                normalized = normalize_youtube_url(uri)
                if normalized != uri:
                    decision.ignore()
                    self.webview.load_uri(normalized)
                    return True

                if decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                    decision.ignore()
                    self.webview.load_uri(uri)
                    return True

                decision.use()
                return True
            else:
                print(f"[YouTube Widget] Blocked external URL: {uri}")
                decision.ignore()
                return True

        return False

    def _on_load_changed(self, web_view, load_event):
        if load_event == WebKit2.LoadEvent.COMMITTED:
            cur_uri = self.webview.get_uri() or ""
            is_watch = "/watch" in cur_uri or "/shorts/" in cur_uri
            self._is_watch_page = is_watch

            # Update search placeholder if on YouTube Music vs regular YouTube
            if hasattr(self, "search_entry"):
                if "music.youtube.com" in cur_uri or self._view_mode == "music":
                    self.search_entry.set_placeholder_text("Search YouTube Music...")
                else:
                    self.search_entry.set_placeholder_text("Search YouTube...")

            # Synchronize pure video preference to document attribute
            pref = "on" if self._pure_video_enabled else "off"
            js = f"document.documentElement.setAttribute('data-pure-video', '{pref}');"
            try:
                self.webview.evaluate_javascript(js, -1, None, None, None, None, None)
            except Exception:
                pass

            if is_watch and self._pure_video_enabled:
                self._schedule_hide_header(delay_ms=2200)

    def _on_title_changed(self, web_view, pspec):
        raw = self.webview.get_title() or ""
        default_name = "YouTube Music" if self._view_mode == "music" else "YouTube"
        title = clean_youtube_title(raw, default_name=default_name)
        self.lbl_title.set_text(title)
        self.lbl_title.set_tooltip_text(title)

    def _on_header_press(self, widget, event):
        if event.button == 1:
            self.window.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )

    def _on_window_button_press(self, widget, event):
        # Alt + Left Click anywhere on the widget to drag
        if event.button == 1 and (event.state & Gdk.ModifierType.MOD1_MASK):
            self.window.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )
            return True
        return False

    def _on_key_press(self, widget, event):
        keyval = event.keyval
        state = event.state

        # Standby wake-up: if in standby, any of Escape, Enter, Space, or Ctrl+P wakes it up
        if not self._is_powered_on:
            if keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
                self._turn_on()
                return True
            if (state & Gdk.ModifierType.CONTROL_MASK) and keyval in (Gdk.KEY_p, Gdk.KEY_P):
                self._turn_on()
                return True

        # Escape: exit fullscreen or close search
        if keyval == Gdk.KEY_Escape:
            if getattr(self, "_search_active", False) or (hasattr(self, "search_revealer") and self.search_revealer.get_reveal_child()):
                self._close_search()
                return True
            if self._is_fullscreen:
                self.window.unfullscreen()
                self._is_fullscreen = False
                self._show_header()
                return True

        # Search shortcut: Ctrl+F, Ctrl+K
        if (state & Gdk.ModifierType.CONTROL_MASK) and keyval in (Gdk.KEY_f, Gdk.KEY_F, Gdk.KEY_k, Gdk.KEY_K):
            self._toggle_search()
            return True

        # Backspace or Alt+Left: Go Back (only if not focused in search entry)
        search_focused = hasattr(self, "search_entry") and self.search_entry.is_focus()
        if not search_focused:
            if keyval == Gdk.KEY_BackSpace or ((state & Gdk.ModifierType.MOD1_MASK) and keyval == Gdk.KEY_Left):
                self._on_go_back()
                return True
            if (state & Gdk.ModifierType.MOD1_MASK) and keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
                self._on_go_home()
                return True

        # Ctrl+P: Toggle Power / Turn Off
        if (state & Gdk.ModifierType.CONTROL_MASK) and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            if self._is_powered_on:
                self._turn_off()
            else:
                self._turn_on()
            return True

        # F5: reload
        if keyval == Gdk.KEY_F5:
            self.webview.reload()
            return True

        return False

    def _on_map(self, widget, event):
        if not self._is_powered_on and self.config.get("shrink_on_turn_off", True):
            ox, oy = self._calc_shrunk_offsets()
            self.window.move(self.target_x + ox, self.target_y + oy)
            gdk_win = self.window.get_window()
            if gdk_win:
                gdk_win.resize(52, 52)
            self.window.resize(52, 52)
        else:
            self.window.move(self.target_x, self.target_y)
        GLib.timeout_add(150, self._apply_initial_position)
        return False

    def _apply_initial_position(self):
        if not self._is_powered_on and self.config.get("shrink_on_turn_off", True):
            ox, oy = self._calc_shrunk_offsets()
            self.window.move(self.target_x + ox, self.target_y + oy)
            self._apply_layer()
            gdk_win = self.window.get_window()
            if gdk_win:
                gdk_win.resize(52, 52)
            self.window.resize(52, 52)
        else:
            self.window.move(self.target_x, self.target_y)
            self._apply_layer()
        self._initial_positioned = True
        return False

    def _on_configure(self, widget, event):
        if not self._initial_positioned or self._is_fullscreen:
            return
        x, y = self.window.get_position()
        w, h = self.window.get_size()
        if x > -10000 and y > -10000:
            if not self._is_powered_on and self.config.get("shrink_on_turn_off", True):
                ox, oy = self._calc_shrunk_offsets()
                expanded_x = x - ox
                expanded_y = y - oy
                self.config["x"] = expanded_x
                self.config["y"] = expanded_y
                self.target_x = expanded_x
                self.target_y = expanded_y
            else:
                self.config["x"] = x
                self.config["y"] = y
                self.target_x = x
                self.target_y = y
                if self._is_powered_on and w > 150 and h > 120:
                    self.config["width"] = w
                    self.config["height"] = h
                    self.normal_w = w
                    self.normal_h = h
                    self.target_w = w
                    self.target_h = h
            if self._save_timer_id:
                GLib.source_remove(self._save_timer_id)
            self._save_timer_id = GLib.timeout_add(500, self._debounced_save_config)

    def _debounced_save_config(self):
        self._save_config()
        self._save_timer_id = None
        return False


def main():
    app = YouTubeWidget()
    Gtk.main()


if __name__ == "__main__":
    main()
