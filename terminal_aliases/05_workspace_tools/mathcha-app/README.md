# Mathcha Desktop Application

A lightweight, high-performance standalone desktop client for **Mathcha** (https://www.mathcha.io/editor), powered by the native Mozilla Firefox **Gecko** rendering engine in dedicated App Mode.

## ✨ Features

- **Native App Feel (Zero Browser Clutter)**:
  - Custom `userChrome.css` collapses Firefox tabs, navigation bar, URL address bar, bookmarks, and extra toolbars.
  - Presents a distraction-free application window matching Ubuntu GNOME's native dark styling.
  - Native window title and window buttons (minimize, maximize, close) managed directly by the system window manager.
- **Flawless Font Rendering & High-DPI Scaling**:
  - Powered by Mozilla Firefox's genuine Gecko engine with FreeType LCD subpixel antialiasing.
  - Perfect text layout and crisp math glyphs even at 400% zoom without damage-rectangle slicing or WebKitGTK canvas tearing.
- **Zero-Click Session Inheritance ("Already Login")**:
  - Automatically inherits the user's active Mathcha login credentials (`remember-me` authentication token) and offline IndexedDB/LocalStorage data from the primary Firefox profile.
  - Profile is isolated under `mathcha_app` to prevent interference with regular Firefox web browsing.
- **Instant Launching & Single-Instance Focus**:
  - Type `math` in terminal or search `math` / `Mathcha` in GNOME Shell overview (Super key).
  - Instantaneous background launching via systemd user slice (`mathcha-app.service`).
  - Subsequent invocations of `math` automatically bring the existing window to the front.
- **Dual-Instance Concurrency**:
  - Can run side-by-side with your everyday Firefox browser without locking profiles or conflicting sessions.

---

## 🚀 Usage

### Terminal Command:
```bash
# Launch Mathcha instantly in background
math

# Open specific document or URL
math https://www.mathcha.io/editor?id=...

# Check if Mathcha is running
math --status

# Stop running instance
math --stop

# Run in foreground (for debugging)
math --wait
```

### Desktop Application:
Press `Super` (Windows key), type **`math`** or **`Mathcha`**, and hit Enter.

---

## ⌨️ Shortcuts

| Shortcut | Action |
| :--- | :--- |
| **`F11`** | Toggle Fullscreen |
| **`Ctrl + +` / `Ctrl + -`** | Zoom in / Zoom out smoothly |
| **`Ctrl + 0`** | Reset Zoom |
| **`Ctrl + P`** | Export / Print to PDF |
| **`Ctrl + S`** | Save document (Mathcha native) |
| **`Ctrl + Z` / `Ctrl + Y`** | Undo / Redo |
