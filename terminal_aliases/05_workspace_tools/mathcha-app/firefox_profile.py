"""
Firefox Profile Manager and Synchronizer for Mathcha Desktop Application.
Ensures Mathcha runs as an independent, frameless, native-feeling app powered by Firefox Gecko.
Handles profile creation, userChrome.css styling, and seamless session/cookie inheritance.
"""

import os
import sys
import time
import shutil
import sqlite3
import configparser

DELETED_DIR = os.path.expanduser("~/deleted")


def find_firefox_base() -> str:
    candidates = [
        os.path.expanduser("~/snap/firefox/common/.mozilla/firefox"),
        os.path.expanduser("~/.mozilla/firefox"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


def find_default_profile(firefox_base: str) -> str:
    profiles_ini = os.path.join(firefox_base, "profiles.ini")
    if os.path.exists(profiles_ini):
        config = configparser.RawConfigParser()
        try:
            config.read(profiles_ini)
            for section in config.sections():
                if config.has_option(section, "Default") and config.get(section, "Default") == "1":
                    path = config.get(section, "Path", fallback="")
                    is_rel = config.get(section, "IsRelative", fallback="1") == "1"
                    full_path = os.path.join(firefox_base, path) if is_rel else path
                    if os.path.isdir(full_path):
                        return full_path
        except Exception:
            pass

    # Fallback scan for .default directory
    for item in os.listdir(firefox_base):
        if item.endswith(".default") and os.path.isdir(os.path.join(firefox_base, item)):
            return os.path.join(firefox_base, item)

    return ""


def ensure_profile_registered(firefox_base: str, profile_name: str = "mathcha_app") -> str:
    profile_dir = os.path.join(firefox_base, profile_name)
    os.makedirs(profile_dir, exist_ok=True)

    profiles_ini = os.path.join(firefox_base, "profiles.ini")
    config = configparser.RawConfigParser()
    if os.path.exists(profiles_ini):
        config.read(profiles_ini)

    registered = False
    for section in config.sections():
        if config.has_option(section, "Name") and config.get(section, "Name") == profile_name:
            registered = True
            break

    if not registered:
        num = 0
        while f"Profile{num}" in config.sections():
            num += 1
        new_sec = f"Profile{num}"
        config.add_section(new_sec)
        config.set(new_sec, "Name", profile_name)
        config.set(new_sec, "IsRelative", "1")
        config.set(new_sec, "Path", profile_name)
        config.set(new_sec, "Default", "0")
        with open(profiles_ini, "w") as f:
            config.write(f)

    return profile_dir


def write_app_preferences(profile_dir: str):
    user_js = """// Mathcha Standalone Desktop App Preferences
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.startup.page", 1);
user_pref("browser.startup.homepage", "https://www.mathcha.io/editor");
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.warnOnQuit", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("app.shield.optoutstudy.enabled", false);
user_pref("browser.aboutConfig.showWarning", false);
user_pref("browser.toolbars.bookmarks.visibility", "never");
user_pref("browser.tabs.inTitlebar", 0);
user_pref("browser.translations.enable", false);
user_pref("browser.download.panel.shown", false);
user_pref("browser.contextual-services.contextId", "mathcha");
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.link.open_newwindow", 2);
user_pref("browser.link.open_newwindow.restriction", 0);
user_pref("extensions.pocket.enabled", false);
user_pref("signon.rememberSignons", true);
user_pref("signon.autofillForms", true);
user_pref("privacy.trackingprotection.enabled", false);
user_pref("browser.cache.disk.enable", true);
user_pref("browser.cache.memory.enable", true);
"""
    with open(os.path.join(profile_dir, "user.js"), "w") as f:
        f.write(user_js)


def write_app_stylesheets(profile_dir: str):
    chrome_dir = os.path.join(profile_dir, "chrome")
    os.makedirs(chrome_dir, exist_ok=True)
    user_chrome_css = """@namespace url("http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul");

/* Hide all browser toolbars, tabs, address bar, bookmarks, and hamburger menus */
#navigator-toolbox,
#navigator-toolbox-background,
#titlebar,
#toolbar-menubar,
#TabsToolbar,
#nav-bar,
#PersonalToolbar,
#sidebar-box,
#sidebar-header,
#identity-box,
#urlbar-container {
    visibility: collapse !important;
    min-height: 0px !important;
    height: 0px !important;
    max-height: 0px !important;
    margin: 0px !important;
    padding: 0px !important;
    border: none !important;
    overflow: hidden !important;
}

#main-window {
    --tab-min-height: 0px !important;
}

#statuspanel,
#statuspanel-label {
    display: none !important;
}
"""
    with open(os.path.join(chrome_dir, "userChrome.css"), "w") as f:
        f.write(user_chrome_css)


def is_profile_running(profile_dir: str) -> bool:
    lock_path = os.path.join(profile_dir, "lock")
    if os.path.islink(lock_path):
        target = os.readlink(lock_path)
        if ":+" in target:
            try:
                pid = int(target.split(":+")[-1])
                os.kill(pid, 0)
                return True
            except OSError:
                pass
    return False


def sync_session_and_storage(profile_dir: str, default_profile: str):
    if not default_profile or not os.path.isdir(default_profile):
        return

    # If mathcha_app profile is already running, skip writing to active databases
    if is_profile_running(profile_dir):
        return

    # 1. Sync Cookies
    src_cookie_db = os.path.join(default_profile, "cookies.sqlite")
    dst_cookie_db = os.path.join(profile_dir, "cookies.sqlite")

    if os.path.exists(src_cookie_db):
        if not os.path.exists(dst_cookie_db):
            # Fresh copy
            try:
                src_conn = sqlite3.connect(f"file:{src_cookie_db}?immutable=1", uri=True)
                dst_conn = sqlite3.connect(dst_cookie_db, timeout=0.1)
                src_conn.backup(dst_conn)
                dst_conn.close()
                src_conn.close()
            except Exception as e:
                print(f"[FirefoxProfile] Initial cookie backup warning: {e}", file=sys.stderr)
        else:
            # Sync Mathcha cookie specifically
            try:
                src_conn = sqlite3.connect(f"file:{src_cookie_db}?immutable=1", uri=True)
                scur = src_conn.cursor()
                scur.execute("SELECT * FROM moz_cookies WHERE host LIKE '%mathcha%' AND name='remember-me'")
                row = scur.fetchone()
                src_conn.close()

                if row:
                    dst_conn = sqlite3.connect(dst_cookie_db, timeout=0.1)
                    dcur = dst_conn.cursor()
                    cols = [d[1] for d in dcur.execute("PRAGMA table_info(moz_cookies)").fetchall()]
                    placeholders = ",".join(["?"] * len(cols))
                    col_names = ",".join(cols)
                    dcur.execute(f"INSERT OR REPLACE INTO moz_cookies ({col_names}) VALUES ({placeholders})", row)
                    dst_conn.commit()
                    dst_conn.close()
            except Exception as e:
                print(f"[FirefoxProfile] Incremental cookie sync warning: {e}", file=sys.stderr)

    # 2. Sync Mathcha offline storage / IndexedDB
    src_storage = os.path.join(default_profile, "storage", "default")
    dst_storage = os.path.join(profile_dir, "storage", "default")

    if os.path.exists(src_storage):
        os.makedirs(dst_storage, exist_ok=True)
        for item in os.listdir(src_storage):
            if "mathcha" in item:
                s_path = os.path.join(src_storage, item)
                d_path = os.path.join(dst_storage, item)
                if os.path.isdir(s_path) and not os.path.exists(d_path):
                    try:
                        shutil.copytree(s_path, d_path, dirs_exist_ok=True)
                    except Exception as e:
                        print(f"[FirefoxProfile] Storage copy warning: {e}", file=sys.stderr)

    # 3. Copy TLS cert and key databases if not present
    for db_file in ["cert9.db", "key4.db"]:
        s = os.path.join(default_profile, db_file)
        d = os.path.join(profile_dir, db_file)
        if os.path.exists(s) and not os.path.exists(d):
            try:
                shutil.copy2(s, d)
            except Exception:
                pass


def clean_stale_lock(profile_dir: str):
    """
    Safely relocates stale Firefox lock file if the lock owner is dead.
    Complies with ZERO-DELETE MANDATE.
    """
    lock_path = os.path.join(profile_dir, "lock")
    if os.path.islink(lock_path):
        target = os.readlink(lock_path)
        # target format: 127.0.1.1:+<pid>
        if ":+" in target:
            try:
                pid = int(target.split(":+")[-1])
                # Check if process is still running
                os.kill(pid, 0)
                # Still running, leave lock intact
                return
            except OSError:
                # Dead PID: safely relocate lock symlink
                os.makedirs(DELETED_DIR, exist_ok=True)
                dest = os.path.join(DELETED_DIR, f"mathcha_lock_{int(time.time())}")
                try:
                    shutil.move(lock_path, dest)
                except Exception:
                    pass


def prepare_mathcha_profile() -> str:
    """Prepares and validates the dedicated profile, returning its absolute path."""
    firefox_base = find_firefox_base()
    default_profile = find_default_profile(firefox_base)
    profile_dir = ensure_profile_registered(firefox_base, "mathcha_app")
    write_app_preferences(profile_dir)
    write_app_stylesheets(profile_dir)
    sync_session_and_storage(profile_dir, default_profile)
    clean_stale_lock(profile_dir)
    return profile_dir


if __name__ == "__main__":
    prof = prepare_mathcha_profile()
    print(f"Mathcha profile ready at: {prof}")
