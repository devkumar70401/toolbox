# SE Toolbox - Terminal Aliases & Utilities (`~/SE/toolbox/terminal_aliases`)

This directory houses self-contained shell utilities, scripts, binary dependencies, and alias configurations for the SE workspace.

> **Zero External Dependency:** This folder is completely independent of the `~/data` folder. If `~/data` is moved or deleted, all aliases and utilities in this directory remain 100% functional.

---

## Folder Organization

| Folder | Utility Group | Included Executables / Files | System Aliases |
| :--- | :--- | :--- | :--- |
| **`00_yt`** | YouTube & Audio/Video Media Tools | `yt`, `yt4`, `yt-gui`, `yt_downloader_cli.py`, `yt_downloader_gui.py`, `mp3` | `yt`, `yt4`, `ytg`, `yt-gui`, `mp3` |
| **`01_venv`** | Virtualenv Dynamic Switcher | `act.sh` | `act`, `activate`, `deact` |
| **`02_aria`** | Aria2 Turbo & Torrent Downloaders | `aria`, `aria_torr` | `aria`, `aria_torr` |
| **`03_notebooks`** | Jupyter Notebook & PDF Converters | `ipynb_to_md.py`, `convert_notebooks.sh`, `ipynbtomd` | `ipynbtomd`, `pdf`, `html`, `pdfs` |
| **`05_workspace_tools`** | Workspace & Desktop Shortcuts | `math`, `rewind-lecture`, `toggle-lecture`, `mathcha-app/` | `sec`, `math`, `rewind-lecture`, `toggle-lecture` |
| **`bin`** | Bundled Binaries & Wrappers | `ffmpeg`, `ffprobe`, `aria2c`, `aria2c.real` | Global PATH in `~/.local/bin` |
| **`lib`** | Bundled Shared Libraries | `libaria2.so*` | Internal LD_LIBRARY_PATH |

---

## Python Virtual Environment

Backed by: **`~/SE/toolbox/.venv`**  
Installed packages:
- `yt-dlp` (High-speed video & audio extraction)
- `ipython` (Interactive Python shell)
- `nbconvert` & `jupyter-core` (Notebook conversion to HTML/PDF/Markdown)

---

## System Aliases (`~/.bash_aliases`)

All aliases are hooked directly into `~/.bashrc` via `~/.bash_aliases`:

* `se`: Jump to `~/SE` and activate `~/SE/toolbox/.venv`
* `sec`: Open SE root in VS Code (`code ~/SE/SE.code-workspace`)
* `act` / `activate`: Dynamic virtualenv switcher (walks directory tree or activates toolbox)
* `deact`: Deactivate virtual environment
* `yt <url>`: Download audio directly as high-quality MP3
* `yt4 <url>`: Download video in highest quality MP4
* `ytg`: Launch graphical YouTube downloader
* `mp3`: Batch convert videos to MP3
* `aria <url>`: 16-connection accelerated downloader to `~/Downloads`
* `aria_torr <magnet/torrent>`: Optimized BitTorrent / magnet downloader
* `ipynbtomd <notebook.ipynb>`: Converts Jupyter notebook to formatted Markdown
* `pdf <notebook.ipynb>`: Converts notebook to PDF using nbconvert
* `html <notebook.ipynb>`: Converts notebook to HTML using nbconvert
* `pdfs <dir>`: Batch converts and merges notebooks in a directory into PDFs
* `math`: Launch Mathcha desktop editor
* `rewind-lecture`: Rewind active media player by 5 seconds over DBus/MPRIS
* `toggle-lecture`: Toggle Play/Pause on active media player
* `update`: `sudo apt update && sudo apt upgrade -y`
* `artifacts`: Navigate to or list Antigravity CLI artifacts
