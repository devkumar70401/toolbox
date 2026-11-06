#!/usr/bin/env python3
"""
Mathcha Native App
A standalone, high-performance desktop application for Mathcha (https://www.mathcha.io/editor)
Powered by native WebKitGTK 2 / GTK 3 engine.
Features:
- Persistent sessions: Cookies (including session cookies), LocalStorage, and IndexedDB never expire.
- Credential management: Remembers email/password using GNOME Keyring and auto-fills login forms.
- OAuth popup window support for Google and third-party login.
- File export to ~/Downloads with native file picker.
"""

import sys
import os
import json
import subprocess
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('WebKit2', '4.1')
gi.require_version('Soup', '3.0')
gi.require_version('GdkPixbuf', '2.0')

from gi.repository import Gtk, Gdk, WebKit2, Soup, GLib, Gio, GdkPixbuf

# Import CredentialManager
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from credentials import CredentialManager

# Paths and configuration
APP_ID = "io.mathcha.App"
DEFAULT_URL = "https://www.mathcha.io/editor"
CONFIG_DIR = os.path.expanduser("~/.config/mathcha")
DATA_DIR = os.path.expanduser("~/.local/share/mathcha")
CACHE_DIR = os.path.expanduser("~/.cache/mathcha")
DOWNLOADS_DIR = os.path.expanduser("~/SE/toolbox/downloads")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PNG = os.path.join(APP_DIR, "assets", "mathcha.png")
ICON_SVG = os.path.join(APP_DIR, "assets", "mathcha.svg")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Standard browser user agent to ensure Google OAuth and modern web standards work seamlessly
STANDARD_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Injected JavaScript for automatic credential detection and autofill
AUTOFILL_SCRIPT = """
(function() {
    window.__MATHCHA_VAULT__ = window.__MATHCHA_VAULT__ || {};

    function triggerInput(el, val) {
        if (!el || !val) return;
        if (el.value === val) return;
        el.focus();
        try {
            var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
            if (nativeSetter && nativeSetter.set) {
                nativeSetter.set.call(el, val);
            } else {
                el.value = val;
            }
        } catch(e) {
            el.value = val;
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
    }

    function doAutofill() {
        var user = window.__MATHCHA_VAULT__.username;
        var pass = window.__MATHCHA_VAULT__.password;
        if (!user || !pass) return;

        var pwdInputs = document.querySelectorAll('input[type="password"]');
        pwdInputs.forEach(function(pwdInput) {
            if (pwdInput.value && pwdInput.value.length > 0) return;

            var userInput = null;
            var form = pwdInput.closest('form');
            if (form) {
                userInput = form.querySelector('input[type="email"], input[type="text"], input[name*="user"], input[name*="email"], input[name*="login"]');
            }
            if (!userInput) {
                var all = Array.from(document.querySelectorAll('input'));
                var idx = all.indexOf(pwdInput);
                for (var i = idx - 1; i >= 0; i--) {
                    if (all[i].type === 'text' || all[i].type === 'email') {
                        userInput = all[i];
                        break;
                    }
                }
            }

            if (userInput && (!userInput.value || userInput.value.length === 0)) {
                triggerInput(userInput, user);
            }
            triggerInput(pwdInput, pass);
        });
    }

    window.__doAutofill = doAutofill;

    function captureAndSend() {
        var pwdInput = document.querySelector('input[type="password"]');
        if (!pwdInput || !pwdInput.value) return;

        var userInput = null;
        var form = pwdInput.closest('form');
        if (form) {
            userInput = form.querySelector('input[type="email"], input[type="text"], input[name*="user"], input[name*="email"], input[name*="login"]');
        }
        if (!userInput) {
            var all = Array.from(document.querySelectorAll('input'));
            var idx = all.indexOf(pwdInput);
            for (var i = idx - 1; i >= 0; i--) {
                if (all[i].type === 'text' || all[i].type === 'email') {
                    userInput = all[i];
                    break;
                }
            }
        }

        var u = userInput ? userInput.value : (window.__MATHCHA_VAULT__.username || '');
        var p = pwdInput.value;
        if (u && p) {
            if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.credentialHandler) {
                window.webkit.messageHandlers.credentialHandler.postMessage({
                    action: 'save',
                    site: 'mathcha.io',
                    username: u,
                    password: p
                });
            }
        }
    }

    // Intercept form submission
    document.addEventListener('submit', function(e) {
        captureAndSend();
    }, true);

    // Intercept clicks on login buttons
    document.addEventListener('click', function(e) {
        var btn = e.target.closest('button, input[type="submit"], a, div[role="button"]');
        if (!btn) return;
        var text = (btn.innerText || btn.textContent || btn.value || '').toLowerCase();
        if (text.includes('sign in') || text.includes('log in') || text.includes('login') || text.includes('submit')) {
            setTimeout(captureAndSend, 100);
        }
    }, true);

    // DOM Observer to trigger autofill as soon as modal or form renders
    var observer = new MutationObserver(function() {
        doAutofill();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });

    // Initial and periodic check
    doAutofill();
    setInterval(doAutofill, 1000);
})();
"""


class MathchaWindow(Gtk.ApplicationWindow):
    def __init__(self, app, initial_url=None):
        super().__init__(application=app, title="Mathcha")
        self.app = app
        self.target_url = initial_url or DEFAULT_URL
        self.header_visible = True
        self.zoom_level = 1.0
        self.credential_manager = CredentialManager()

        self.setup_appearance()
        self.restore_window_state()
        self.setup_header_bar()
        self.setup_webview()
        self.setup_keyboard_shortcuts()

        # Connect window events
        self.connect("configure-event", self.on_configure_event)
        self.connect("window-state-event", self.on_window_state_event)
        self.connect("delete-event", self.on_delete_event)
        self.connect("destroy", self.on_window_destroy)

        # Periodic cookie persistence timer (every 20 seconds)
        GLib.timeout_add_seconds(20, self.sync_session_cookies)

        self.webview.load_uri(self.target_url)

    def setup_appearance(self):
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings:
            gtk_settings.set_property("gtk-application-prefer-dark-theme", True)
            try:
                gtk_settings.set_property("gtk-xft-antialias", 1)
                gtk_settings.set_property("gtk-xft-hinting", 1)
                gtk_settings.set_property("gtk-xft-hintstyle", "hintslight")
                gtk_settings.set_property("gtk-xft-rgba", "rgb")
            except Exception:
                pass

        if os.path.exists(ICON_PNG):
            try:
                self.set_icon_from_file(ICON_PNG)
            except Exception:
                pass
        elif Gtk.IconTheme.get_default().has_icon("mathcha"):
            self.set_icon_name("mathcha")

        css_provider = Gtk.CssProvider()
        css = b"""
        headerbar.mathcha-header {
            background: #18181b;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding: 3px 6px;
            min-height: 38px;
        }
        headerbar.mathcha-header button {
            border-radius: 6px;
            padding: 4px 8px;
            margin: 0 1px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: #e4e4e7;
        }
        headerbar.mathcha-header button:hover {
            background: rgba(255, 255, 255, 0.12);
            border-color: rgba(255, 255, 255, 0.2);
            color: #ffffff;
        }
        progressbar.mathcha-progress trough {
            background-color: transparent;
            border: none;
            min-height: 2px;
        }
        progressbar.mathcha-progress progress {
            background-color: #3b82f6;
            border: none;
            min-height: 2px;
        }
        """
        try:
            css_provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception:
            pass

    def restore_window_state(self):
        default_width, default_height = 1366, 850
        is_maximized = False
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    data = json.load(f)
                    default_width = data.get("width", default_width)
                    default_height = data.get("height", default_height)
                    is_maximized = data.get("maximized", False)
                    self.zoom_level = data.get("zoom", 1.0)
            except Exception:
                pass

        self.set_default_size(default_width, default_height)
        self.set_position(Gtk.WindowPosition.CENTER)
        if is_maximized:
            self.maximize()

    def save_window_state(self):
        try:
            alloc = self.get_allocation()
            is_max = bool(self.get_window() and (self.get_window().get_state() & Gdk.WindowState.MAXIMIZED))
            state = {
                "width": alloc.width if not is_max else 1366,
                "height": alloc.height if not is_max else 850,
                "maximized": is_max,
                "zoom": self.zoom_level
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def on_configure_event(self, widget, event):
        return False

    def on_window_state_event(self, widget, event):
        return False

    def on_delete_event(self, widget, event):
        self.save_window_state()
        self.sync_session_cookies()
        if self.app:
            self.app.window = None
        return False

    def on_window_destroy(self, widget):
        if self.app:
            self.app.window = None

    def setup_header_bar(self):
        self.header_bar = Gtk.HeaderBar()
        self.header_bar.get_style_context().add_class("mathcha-header")
        self.header_bar.set_show_close_button(True)
        self.header_bar.set_title("Mathcha")
        self.header_bar.set_subtitle("Mathematical Document & Diagram Editor")

        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

        self.btn_back = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        self.btn_back.set_tooltip_text("Go Back (Alt+Left)")
        self.btn_back.connect("clicked", lambda b: self.webview.go_back())
        left_box.pack_start(self.btn_back, False, False, 0)

        self.btn_forward = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        self.btn_forward.set_tooltip_text("Go Forward (Alt+Right)")
        self.btn_forward.connect("clicked", lambda b: self.webview.go_forward())
        left_box.pack_start(self.btn_forward, False, False, 0)

        self.btn_reload = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.btn_reload.set_tooltip_text("Reload (Ctrl+R / F5)")
        self.btn_reload.connect("clicked", lambda b: self.webview.reload())
        left_box.pack_start(self.btn_reload, False, False, 0)

        self.btn_home = Gtk.Button.new_from_icon_name("go-home-symbolic", Gtk.IconSize.BUTTON)
        self.btn_home.set_tooltip_text("Home (Open Editor)")
        self.btn_home.connect("clicked", lambda b: self.webview.load_uri(DEFAULT_URL))
        left_box.pack_start(self.btn_home, False, False, 0)

        self.header_bar.pack_start(left_box)

        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

        self.btn_zoom_out = Gtk.Button.new_from_icon_name("zoom-out-symbolic", Gtk.IconSize.BUTTON)
        self.btn_zoom_out.set_tooltip_text("Zoom Out (Ctrl+-)")
        self.btn_zoom_out.connect("clicked", lambda b: self.adjust_zoom(-0.1))
        right_box.pack_start(self.btn_zoom_out, False, False, 0)

        self.btn_zoom_reset = Gtk.Button(label="100%")
        self.btn_zoom_reset.set_tooltip_text("Reset Zoom (Ctrl+0)")
        self.btn_zoom_reset.connect("clicked", lambda b: self.set_zoom(1.0))
        right_box.pack_start(self.btn_zoom_reset, False, False, 0)

        self.btn_zoom_in = Gtk.Button.new_from_icon_name("zoom-in-symbolic", Gtk.IconSize.BUTTON)
        self.btn_zoom_in.set_tooltip_text("Zoom In (Ctrl++)")
        self.btn_zoom_in.connect("clicked", lambda b: self.adjust_zoom(0.1))
        right_box.pack_start(self.btn_zoom_in, False, False, 0)

        self.btn_zen = Gtk.Button.new_from_icon_name("view-fullscreen-symbolic", Gtk.IconSize.BUTTON)
        self.btn_zen.set_tooltip_text("Zen Mode: Hide Titlebar (F10 / Ctrl+H)")
        self.btn_zen.connect("clicked", lambda b: self.toggle_zen_mode())
        right_box.pack_start(self.btn_zen, False, False, 0)

        menu_button = Gtk.MenuButton()
        menu_button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_button.set_tooltip_text("App Options")
        menu = self.create_app_menu()
        menu_button.set_popup(menu)
        right_box.pack_start(menu_button, False, False, 0)

        self.header_bar.pack_end(right_box)
        self.set_titlebar(self.header_bar)

    def create_app_menu(self):
        menu = Gtk.Menu()

        item_print = Gtk.MenuItem(label="Print / Export PDF (Ctrl+P)")
        item_print.connect("activate", lambda i: self.print_page())
        menu.append(item_print)

        item_hard_reload = Gtk.MenuItem(label="Hard Reload (Ctrl+Shift+R)")
        item_hard_reload.connect("activate", lambda i: self.webview.reload_bypass_cache())
        menu.append(item_hard_reload)

        item_saved_creds = Gtk.MenuItem(label="Saved Credentials Status")
        item_saved_creds.connect("activate", lambda i: self.show_credentials_dialog())
        menu.append(item_saved_creds)

        item_sync_firefox = Gtk.MenuItem(label="Sync Login from Firefox")
        item_sync_firefox.connect("activate", lambda i: self.manual_sync_firefox())
        menu.append(item_sync_firefox)

        item_open_browser = Gtk.MenuItem(label="Open Current URL in System Browser")
        item_open_browser.connect("activate", lambda i: Gio.AppInfo.launch_default_for_uri(self.webview.get_uri(), None))
        menu.append(item_open_browser)

        menu.append(Gtk.SeparatorMenuItem())

        item_inspector = Gtk.MenuItem(label="Developer Tools (F12)")
        item_inspector.connect("activate", lambda i: self.webview.get_inspector().show())
        menu.append(item_inspector)

        menu.append(Gtk.SeparatorMenuItem())

        item_shortcuts = Gtk.MenuItem(label="Keyboard Shortcuts")
        item_shortcuts.connect("activate", lambda i: self.show_shortcuts_dialog())
        menu.append(item_shortcuts)

        item_about = Gtk.MenuItem(label="About Mathcha App")
        item_about.connect("activate", lambda i: self.show_about_dialog())
        menu.append(item_about)

        menu.show_all()
        return menu

    def setup_webview(self):
        # Configure Website Data Manager with isolated persistent storage
        data_manager = WebKit2.WebsiteDataManager(
            base_data_directory=DATA_DIR,
            base_cache_directory=CACHE_DIR,
            local_storage_directory=os.path.join(DATA_DIR, "localstorage"),
            indexeddb_directory=os.path.join(DATA_DIR, "indexeddb"),
            disk_cache_directory=os.path.join(CACHE_DIR, "diskcache")
        )

        self.web_context = WebKit2.WebContext.new_with_website_data_manager(data_manager)

        # Persistent Cookies
        self.cookie_manager = self.web_context.get_cookie_manager()
        cookie_db_path = os.path.join(DATA_DIR, "cookies.sqlite")
        self.cookie_manager.set_persistent_storage(cookie_db_path, WebKit2.CookiePersistentStorage.SQLITE)
        self.cookie_manager.set_accept_policy(WebKit2.CookieAcceptPolicy.ALWAYS)
        self.import_browser_cookies()

        # Downloads Handler
        self.web_context.connect("download-started", self.on_download_started)

        # User Content Manager with Script Message Handlers and Autofill UserScript
        self.user_content_manager = WebKit2.UserContentManager()
        self.user_content_manager.register_script_message_handler("credentialHandler")
        self.user_content_manager.connect("script-message-received::credentialHandler", self.on_credential_message)

        # Add Autofill UserScript
        user_script = WebKit2.UserScript.new(
            AUTOFILL_SCRIPT,
            WebKit2.UserContentInjectedFrames.ALL_FRAMES,
            WebKit2.UserScriptInjectionTime.END,
            [], []
        )
        self.user_content_manager.add_script(user_script)

        # Initialize WebView with Context and User Content Manager
        self.webview = WebKit2.WebView(
            web_context=self.web_context,
            user_content_manager=self.user_content_manager
        )

        # Configure WebKit Settings
        settings = self.webview.get_settings()
        settings.set_enable_javascript(True)
        settings.set_enable_webgl(True)
        settings.set_javascript_can_access_clipboard(True)
        settings.set_enable_developer_extras(True)
        settings.set_enable_smooth_scrolling(True)
        settings.set_enable_page_cache(True)
        settings.set_enable_resizable_text_areas(True)
        settings.set_enable_webaudio(True)
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ON_DEMAND)
        settings.set_user_agent(STANDARD_USER_AGENT)

        # High-Fidelity Font Rendering Configuration
        settings.set_sans_serif_font_family("Ubuntu")
        settings.set_default_font_family("Ubuntu")
        settings.set_serif_font_family("DejaVu Serif")
        settings.set_monospace_font_family("Ubuntu Mono")
        if hasattr(settings, "set_math_font_family"):
            settings.set_math_font_family("Asana Math")
        # Safe Font Smoothing without breaking Mathcha's font-metric calculations
        font_css = """
        html, body {
            -webkit-font-smoothing: antialiased;
        }
        """
        user_style = WebKit2.UserStyleSheet(
            font_css,
            WebKit2.UserContentInjectedFrames.ALL_FRAMES,
            WebKit2.UserStyleLevel.USER,
            [], []
        )
        self.user_content_manager.add_style_sheet(user_style)

        if self.zoom_level != 1.0:
            self.webview.set_zoom_level(self.zoom_level)
            self.btn_zoom_reset.set_label(f"{int(self.zoom_level * 100)}%")

        # Signals
        self.webview.connect("load-changed", self.on_load_changed)
        self.webview.connect("notify::estimated-load-progress", self.on_progress_changed)
        self.webview.connect("notify::title", self.on_title_changed)
        self.webview.connect("script-dialog", self.on_script_dialog)
        self.webview.connect("permission-request", self.on_permission_request)
        self.webview.connect("create", self.on_create_web_view)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.get_style_context().add_class("mathcha-progress")
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_no_show_all(True)
        vbox.pack_start(self.progress_bar, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.webview)
        vbox.pack_start(scrolled, True, True, 0)

        self.add(vbox)
        vbox.show_all()

    def import_browser_cookies(self):
        """
        Automatically imports existing Mathcha login sessions (remember-me tokens)
        from Firefox profiles so the user is immediately logged in without needing to enter anything.
        """
        import glob
        import sqlite3
        firefox_profiles = (
            glob.glob(os.path.expanduser("~/snap/firefox/common/.mozilla/firefox/*.default*")) +
            glob.glob(os.path.expanduser("~/.mozilla/firefox/*.default*"))
        )
        imported_count = 0
        for p in firefox_profiles:
            db_path = os.path.join(p, "cookies.sqlite")
            if not os.path.exists(db_path):
                continue
            try:
                conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
                c = conn.cursor()
                c.execute(
                    "SELECT name, value, host, path, expiry, isSecure, isHttpOnly "
                    "FROM moz_cookies WHERE host LIKE '%mathcha%'"
                )
                rows = c.fetchall()
                conn.close()
                for name, value, host, path, expiry, is_secure, is_http_only in rows:
                    if name == "remember-me":
                        expiry_sec = int(expiry // 1000) if expiry and expiry > 10000000000 else int(expiry or -1)
                        cookie = Soup.Cookie.new(name, value, host, path, -1)
                        if expiry_sec > 0:
                            cookie.set_expires(GLib.DateTime.new_from_unix_utc(expiry_sec))
                        cookie.set_secure(bool(is_secure))
                        cookie.set_http_only(bool(is_http_only))
                        if hasattr(cookie, "set_same_site_policy"):
                            cookie.set_same_site_policy(Soup.SameSitePolicy.LAX)
                        self.cookie_manager.add_cookie(cookie, None, None, None)

                        # Also sync directly to local SQLite
                        cookie_db_path = os.path.join(DATA_DIR, "cookies.sqlite")
                        try:
                            cconn = sqlite3.connect(cookie_db_path)
                            cc = cconn.cursor()
                            cc.execute('''
                            INSERT OR REPLACE INTO moz_cookies (name, value, host, path, expiry, lastAccessed, isSecure, isHttpOnly, sameSite)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (name, value, host, path, expiry_sec, 0, int(bool(is_secure)), int(bool(is_http_only)), 1))
                            cconn.commit()
                            cconn.close()
                        except Exception:
                            pass

                        imported_count += 1
            except Exception as e:
                print(f"[Mathcha] Browser cookie sync note: {e}", file=sys.stderr)

        # Clean any stale JSESSIONID or session affinity from SQLite to prevent session lockouts
        cookie_db_path = os.path.join(DATA_DIR, "cookies.sqlite")
        if os.path.exists(cookie_db_path):
            try:
                conn = sqlite3.connect(cookie_db_path)
                c = conn.cursor()
                c.execute("DELETE FROM moz_cookies WHERE name IN ('JSESSIONID', 'heroku-session-affinity')")
                conn.commit()
                conn.close()
            except Exception:
                pass
        return imported_count

    def manual_sync_firefox(self):
        count = self.import_browser_cookies()
        if count > 0:
            self.webview.reload()
            try:
                subprocess.run([
                    "notify-send",
                    "Mathcha Login Synced",
                    "Successfully imported active login session from Firefox.",
                    "-i", ICON_PNG
                ], check=False)
            except Exception:
                pass
        else:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Firefox Session Sync"
            )
            dialog.format_secondary_text(
                "No active Mathcha session found in Firefox.\n"
                "Log into mathcha.io in Firefox and click 'Sync Login from Firefox' again."
            )
            dialog.run()
            dialog.destroy()

    def sync_session_cookies(self):
        """
        Maintains long-term session persistence for remember-me tokens while
        leaving ephemeral session cookies untouched so Spring Security never rejects stale sessions.
        """
        def on_got_cookies(cm, res, data):
            try:
                cookies = cm.get_all_cookies_finish(res)
                for c in cookies:
                    if c.get_name() == "remember-me":
                        if c.get_expires() is None:
                            c.set_max_age(365 * 86400)
                            cm.add_cookie(c, None, None, None)
            except Exception:
                pass

        try:
            self.cookie_manager.get_all_cookies(None, on_got_cookies, None)
        except Exception:
            pass
        return True

    def on_credential_message(self, manager, js_result):
        """
        Receives submitted credentials from the webview and saves them in GNOME Keyring.
        """
        try:
            if hasattr(js_result, "get_js_value"):
                val = js_result.get_js_value()
                raw = val.to_json(0) if hasattr(val, "to_json") else val.to_string()
            elif hasattr(js_result, "to_json"):
                raw = js_result.to_json(0)
            else:
                raw = str(js_result)
            data = json.loads(raw)
            if data.get("action") == "save":
                site = data.get("site", "mathcha.io")
                username = data.get("username")
                password = data.get("password")
                if username and password:
                    self.credential_manager.save(site, username, password)
                    # Notify user
                    try:
                        subprocess.run([
                            "notify-send",
                            "Mathcha Password Remembered",
                            f"Account credentials for {username} saved securely.\nYou will remain signed in automatically.",
                            "-i", ICON_PNG
                        ], check=False)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Mathcha] Error processing credential message: {e}", file=sys.stderr)

    def inject_saved_credentials(self):
        """
        Injects saved credentials into the page so the autofill engine can populate forms immediately.
        """
        cred = self.credential_manager.get("mathcha.io")
        if cred and cred.get("username") and cred.get("password"):
            u_json = json.dumps(cred["username"])
            p_json = json.dumps(cred["password"])
            js = f"""
            window.__MATHCHA_VAULT__ = {{
                username: {u_json},
                password: {p_json}
            }};
            if (typeof window.__doAutofill === 'function') {{
                window.__doAutofill();
            }}
            """
            self.webview.run_javascript(js, None, None, None)

    def on_create_web_view(self, webview, navigation_action):
        """
        Handles OAuth login popups (e.g. 'Sign In with Google' or social login)
        in a dedicated popup window sharing the same WebContext so cookies & auth tokens persist.
        """
        popup = Gtk.Window(title="Authentication - Mathcha")
        popup.set_default_size(540, 700)
        popup.set_transient_for(self)
        popup.set_modal(True)
        popup.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)

        popup_webview = WebKit2.WebView.new_with_context(self.web_context)
        popup_settings = WebKit2.Settings()
        # Use Firefox user agent for OAuth popups so Google won't block embedded webview
        popup_settings.set_user_agent("Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0")
        popup_settings.set_enable_javascript(True)
        popup_settings.set_enable_webgl(True)
        popup_settings.set_javascript_can_access_clipboard(True)
        popup_webview.set_settings(popup_settings)

        def on_popup_close(w):
            self.sync_session_cookies()
            popup.destroy()
            self.webview.reload()

        popup_webview.connect("close", on_popup_close)

        def on_popup_load(w, event):
            if event == WebKit2.LoadEvent.FINISHED:
                uri = w.get_uri() or ""
                # If redirected back to mathcha editor, auth completed successfully
                if "mathcha.io" in uri and "oauth" not in uri and "login" not in uri:
                    self.sync_session_cookies()
                    GLib.timeout_add(1000, lambda: (popup.destroy(), None))
                    self.webview.reload()

        popup_webview.connect("load-changed", on_popup_load)
        popup.add(popup_webview)
        popup.show_all()
        return popup_webview

    def setup_keyboard_shortcuts(self):
        accel_group = Gtk.AccelGroup()
        self.add_accel_group(accel_group)

        shortcuts = [
            (Gdk.KEY_r, Gdk.ModifierType.CONTROL_MASK, lambda: self.webview.reload()),
            (Gdk.KEY_F5, 0, lambda: self.webview.reload()),
            (Gdk.KEY_r, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK, lambda: self.webview.reload_bypass_cache()),
            (Gdk.KEY_plus, Gdk.ModifierType.CONTROL_MASK, lambda: self.adjust_zoom(0.1)),
            (Gdk.KEY_equal, Gdk.ModifierType.CONTROL_MASK, lambda: self.adjust_zoom(0.1)),
            (Gdk.KEY_minus, Gdk.ModifierType.CONTROL_MASK, lambda: self.adjust_zoom(-0.1)),
            (Gdk.KEY_0, Gdk.ModifierType.CONTROL_MASK, lambda: self.set_zoom(1.0)),
            (Gdk.KEY_F11, 0, self.toggle_fullscreen),
            (Gdk.KEY_F10, 0, self.toggle_zen_mode),
            (Gdk.KEY_h, Gdk.ModifierType.CONTROL_MASK, self.toggle_zen_mode),
            (Gdk.KEY_F12, 0, lambda: self.webview.get_inspector().show()),
            (Gdk.KEY_p, Gdk.ModifierType.CONTROL_MASK, self.print_page),
            (Gdk.KEY_Left, Gdk.ModifierType.MOD1_MASK, lambda: self.webview.go_back()),
            (Gdk.KEY_Right, Gdk.ModifierType.MOD1_MASK, lambda: self.webview.go_forward()),
            (Gdk.KEY_q, Gdk.ModifierType.CONTROL_MASK, lambda: self.close()),
        ]

        def on_key_press(widget, event):
            state = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK)
            for keyval, mod, handler in shortcuts:
                if event.keyval == keyval and state == mod:
                    handler()
                    return True
            return False

        self.connect("key-press-event", on_key_press)

    def adjust_zoom(self, delta):
        self.set_zoom(round(self.zoom_level + delta, 2))

    def set_zoom(self, level):
        level = max(0.5, min(3.0, level))
        self.zoom_level = level
        self.webview.set_zoom_level(level)
        self.btn_zoom_reset.set_label(f"{int(level * 100)}%")

    def toggle_zen_mode(self):
        self.header_visible = not self.header_visible
        if self.header_visible:
            self.header_bar.show()
        else:
            self.header_bar.hide()

    def toggle_fullscreen(self):
        window = self.get_window()
        if window and (window.get_state() & Gdk.WindowState.FULLSCREEN):
            self.unfullscreen()
        else:
            self.fullscreen()

    def print_page(self):
        try:
            print_op = WebKit2.PrintOperation.new(self.webview)
            print_op.run_dialog(self)
        except Exception as e:
            print(f"[Mathcha] Print error: {e}", file=sys.stderr)

    def on_load_changed(self, webview, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.progress_bar.show()
        elif event == WebKit2.LoadEvent.FINISHED:
            self.progress_bar.hide()
            self.progress_bar.set_fraction(0.0)
            self.inject_saved_credentials()
            self.sync_session_cookies()
            # Post-load cookies often arrive via async requests
            GLib.timeout_add_seconds(2, self.sync_session_cookies)
            GLib.timeout_add_seconds(5, self.sync_session_cookies)

        self.btn_back.set_sensitive(webview.can_go_back())
        self.btn_forward.set_sensitive(webview.can_go_forward())

    def on_progress_changed(self, webview, param):
        progress = webview.get_estimated_load_progress()
        self.progress_bar.set_fraction(progress)
        if progress >= 1.0:
            self.progress_bar.hide()
        elif not self.progress_bar.get_visible():
            self.progress_bar.show()

    def on_title_changed(self, webview, param):
        title = webview.get_title()
        if title:
            self.set_title(f"Mathcha - {title}")
            self.header_bar.set_title(title)
        else:
            self.set_title("Mathcha")
            self.header_bar.set_title("Mathcha")

    def on_script_dialog(self, webview, dialog):
        dialog_type = dialog.get_dialog_type()
        text = dialog.get_message()

        if dialog_type == WebKit2.ScriptDialogType.ALERT:
            msg = Gtk.MessageDialog(
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=text
            )
            msg.run()
            msg.destroy()
            dialog.confirm()
            return True

        elif dialog_type in (WebKit2.ScriptDialogType.CONFIRM, WebKit2.ScriptDialogType.BEFORE_UNLOAD_CONFIRM):
            msg = Gtk.MessageDialog(
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text=text
            )
            res = msg.run()
            msg.destroy()
            if res == Gtk.ResponseType.YES:
                dialog.confirm()
            return True

        return False

    def on_permission_request(self, webview, request):
        request.allow()
        return True

    def on_download_started(self, context, download):
        def on_decide_destination(dl, suggested_filename):
            chooser = Gtk.FileChooserDialog(
                title="Save Export from Mathcha",
                transient_for=self,
                action=Gtk.FileChooserAction.SAVE
            )
            chooser.add_buttons(
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_SAVE, Gtk.ResponseType.ACCEPT
            )
            chooser.set_do_overwrite_confirmation(True)
            chooser.set_current_folder(DOWNLOADS_DIR)
            chooser.set_current_name(suggested_filename or "mathcha_export")

            response = chooser.run()
            if response == Gtk.ResponseType.ACCEPT:
                save_path = chooser.get_filename()
                chooser.destroy()
                dl.set_destination(GLib.filename_to_uri(save_path))
                dl.connect("finished", lambda d: self.notify_download_complete(save_path))
                return True
            else:
                chooser.destroy()
                dl.cancel()
                return False

        download.connect("decide-destination", on_decide_destination)

    def notify_download_complete(self, filepath):
        filename = os.path.basename(filepath)
        try:
            subprocess.run([
                "notify-send",
                "Mathcha Export Complete",
                f"Saved: {filename}\nPath: {filepath}",
                "-i", ICON_PNG
            ], check=False)
        except Exception:
            pass

    def show_credentials_dialog(self):
        cred = self.credential_manager.get("mathcha.io")
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Saved Login Credentials"
        )
        if cred and cred.get("username"):
            sec_text = (
                f"• Site: mathcha.io\n"
                f"• Account: {cred.get('username')}\n"
                f"• Password: Saved securely in GNOME Keyring\n"
                f"• Session Persistence: Active (Persistent SQLite + LocalStorage)\n\n"
                f"Once you log in, your session remains active indefinitely."
            )
        else:
            sec_text = (
                "No credentials saved yet for mathcha.io.\n\n"
                "When you log in or sign up in Mathcha, your login credentials\n"
                "and session cookies will automatically be saved and remembered."
            )
        dialog.format_secondary_text(sec_text)
        dialog.run()
        dialog.destroy()

    def show_shortcuts_dialog(self):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Mathcha Desktop Shortcuts"
        )
        shortcuts_text = (
            "• F10 / Ctrl+H : Toggle Zen Mode (Hide/Show HeaderBar)\n"
            "• F11 : Toggle Fullscreen\n"
            "• Ctrl+R / F5 : Reload Document\n"
            "• Ctrl+Shift+R : Hard Reload (Bypass Cache)\n"
            "• Ctrl + / Ctrl - : Zoom In / Out\n"
            "• Ctrl 0 : Reset Zoom to 100%\n"
            "• Ctrl+P : Print / Save to PDF\n"
            "• Alt+Left / Alt+Right : Navigate Back / Forward\n"
            "• F12 : Open Developer Tools / Inspector\n"
            "• Ctrl+Q : Close Mathcha\n"
        )
        dialog.format_secondary_text(shortcuts_text)
        dialog.run()
        dialog.destroy()

    def show_about_dialog(self):
        about = Gtk.AboutDialog(transient_for=self, modal=True)
        about.set_program_name("Mathcha Desktop")
        about.set_version("1.1.0")
        about.set_comments("Native desktop client for Mathcha with persistent sessions & credential autofill")
        about.set_website("https://www.mathcha.io")
        about.set_website_label("www.mathcha.io")
        if os.path.exists(ICON_PNG):
            try:
                about.set_logo(GdkPixbuf.Pixbuf.new_from_file(ICON_PNG))
            except Exception:
                pass
        about.run()
        about.destroy()


class MathchaApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = MathchaWindow(self)
        self.window.present()

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        url = None
        for arg in args:
            if not arg.startswith("-"):
                url = arg
                break

        if not self.window:
            self.window = MathchaWindow(self, initial_url=url)
            self.window.show_all()
        else:
            if url:
                self.window.webview.load_uri(url)
            self.window.present()

        return 0


def main():
    app = MathchaApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
