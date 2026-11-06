# Devendra Desktop Widgets Suite (Portable & Disaster-Recovery)

A self-contained, 100% portable collection of transparent, modern desktop widgets for Ubuntu Linux.

Even if the entire workstation is wiped, having this folder (`~/SE/Devendra/widgets`) allows you to restore and run all widgets on any Linux machine with one command.

---

## 📦 What's Inside

| Directory | Widget | Features & Source |
| :--- | :--- | :--- |
| **`work/`** | 💼 Daily Tasks Suite | Combined Work, Diet & Nutrition, and Daily Routines interactive widget with top 3 tabs, dynamic theme colors, and markdown sync |
| **`pomodoro/`**| 🍅 Pomodoro Timer | 30m Focus / 10m Break enforced input-guard timer, live countdown, pause/resume, hardware lock integration |
| **`music/`** | 🎵 Music Player | MP3 player with native GStreamer engine, scans `~/SE/Devendra/Music`, 3 buttons + folder icon |
| **`youtube/`** | ▶️ YouTube Player | Isolated YouTube & YouTube Music player with strict domain lock, dark theme, search bar & size presets |
| **`terminal/`**| 💻 Terminal Widget | Native embedded VTE terminal emulator, full bash support, custom dark theme, interactive CLI tools |
| **`sysmon/`**  | ⚡ System Vitals   | Real-time open apps & RAM monitor, physical sensors tracker (mic, speaker, cam, GPS, BT), network speed |
| **`bin/`** | ⚙️ Pre-compiled Binaries| Pre-compiled standalone `pomodoro`, `pomodoro-cli`, `pomodoro-guard`, `pomodoro-ui` |

---

## 🚀 1-Command Restore & Installation

On any fresh or existing Linux machine, simply run:

```bash
cd ~/SE/Devendra/widgets
./install.sh
```

### What `install.sh` Does:
1. Creates all required folders (`~/SE/Devendra/Daily`, `~/SE/Devendra/Music`, `~/.config/...`).
2. Restores all pre-configured coordinate settings (`config.json` for each widget).
3. Installs all systemd user services (`~/.config/systemd/user/*.service`).
4. Installs all autostart desktop entries (`~/.config/autostart/*.desktop`).
5. Restores Pomodoro binaries to `~/.local/bin/`.
6. Enables and immediately launches all 6 widgets on your desktop.

---

## 🎮 Quick Controls

* **Start all widgets:**
  ```bash
  ~/SE/Devendra/widgets/start_all.sh
  ```
* **Stop all widgets:**
  ```bash
  ~/SE/Devendra/widgets/stop_all.sh
  ```
* **Check status:**
  ```bash
  ~/SE/Devendra/widgets/status.sh
  ```
* **Auto-arrange / Reset Layout:**
  ```bash
  ~/SE/Devendra/widgets/layout.sh desktop  # Arrange on Main Desktop (Laptop screen)
  ~/SE/Devendra/widgets/layout.sh monitor  # Arrange on External Monitor
  ~/SE/Devendra/widgets/layout.sh single   # Arrange on Single screen setup
  ~/SE/Devendra/widgets/layout.sh save     # Save current live window positions as official layout
  ```

---

## 🎨 Design & Behavior Standards

* **Frameless & Borderless:** Translucent dark glassmorphic cards (`rgba(18, 20, 26, 0.85)`), rounded corners (`20px`).
* **Hidden from Dock & Alt+Tab:** Runs on desktop layer, never clutters application switchers.
* **Persistent Coordinates:** Automatically restores exact `(x, y)` coordinates across reboots via `config.json`.
* **Pinned / Always on Top Toggle:** Click `📌` in the header of any widget to switch between Desktop-Pinned and Always-on-Top.
