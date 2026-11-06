"""
yt_downloader_gui.py - Standalone Graphical Interface for YouTube Media Downloader
Location: ~/SE/projects/01_alias/00_yt/yt_downloader_gui.py
"""

import os
import shutil
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import yt_dlp


def get_default_music_dir() -> Path:
    download_dir = Path(__file__).resolve().parent.parent.parent / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    return download_dir


def get_node_runtime() -> dict:
    """Finds the available Node.js binary to handle YouTube n-sig / cipher execution."""
    candidates = [
        shutil.which("node"),
        shutil.which("nodejs"),
        str(Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "node"),
    ]
    for candidate in candidates:
        if candidate and (os.path.exists(candidate) or shutil.which(candidate)):
            return {"node": {"path": candidate}}
    return {}


class YouTubeDownloaderGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("🎵 YouTube Media Downloader (Pro)")
        self.geometry("560x490")
        self.resizable(False, False)
        self.configure(bg="#181825")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.default_music_dir = str(get_default_music_dir())
        self.storage_path = tk.StringVar(value=self.default_music_dir)
        self.prompt_every_time = tk.BooleanVar(value=False)
        self.is_downloading = False

        self._setup_styles()
        self._build_interface()

    def _setup_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.bg_color = "#181825"
        self.card_color = "#1e1e2e"
        self.fg_color = "#cdd6f4"
        self.accent_color = "#89b4fa"
        self.accent_hover = "#b4befe"
        self.success_color = "#a6e3a1"
        self.error_color = "#f38ba8"

        self.style.configure(".", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 9))
        self.style.configure("Card.TFrame", background=self.card_color)
        self.style.configure("Card.TLabel", background=self.card_color, foreground=self.fg_color)
        self.style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"), foreground=self.accent_color)
        self.style.configure("Status.TLabel", font=("Segoe UI", 9), foreground="#a6adc8")
        self.style.configure("TCheckbutton", background=self.card_color, foreground=self.fg_color)
        self.style.map("TCheckbutton", background=[("active", self.card_color)])

        self.style.configure(
            "Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            background=self.accent_color,
            foreground="#11111b",
            padding=(10, 6),
            borderwidth=0
        )
        self.style.map("Primary.TButton", background=[("active", self.accent_hover)])

        self.style.configure(
            "Secondary.TButton",
            font=("Segoe UI", 8),
            background="#45475a",
            foreground=self.fg_color,
            padding=(6, 4),
            borderwidth=0
        )
        self.style.map("Secondary.TButton", background=[("active", "#585b70")])

        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#313244",
            background=self.accent_color,
            thickness=12
        )

    def _build_interface(self):
        container = ttk.Frame(self, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Label(container, text="YouTube Media Downloader", style="Header.TLabel")
        header.pack(anchor="w", pady=(0, 12))

        storage_card = ttk.Frame(container, style="Card.TFrame", padding=12)
        storage_card.pack(fill=tk.X, pady=(0, 12))

        lbl_storage = ttk.Label(storage_card, text="📁 Download Storage Location:", font=("Segoe UI", 10, "bold"), style="Card.TLabel")
        lbl_storage.pack(anchor="w", pady=(0, 6))

        path_row = ttk.Frame(storage_card, style="Card.TFrame")
        path_row.pack(fill=tk.X, pady=(0, 8))

        self.path_entry = tk.Entry(
            path_row,
            textvariable=self.storage_path,
            bg="#313244",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            relief="flat",
            font=("Consolas", 9)
        )
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 6))

        browse_btn = ttk.Button(path_row, text="Browse...", style="Secondary.TButton", command=self._browse_directory)
        browse_btn.pack(side=tk.RIGHT)

        options_row = ttk.Frame(storage_card, style="Card.TFrame")
        options_row.pack(fill=tk.X)

        ttk.Label(options_row, text="Presets:", style="Card.TLabel").pack(side=tk.LEFT, padx=(0, 5))
        self.preset_combo = ttk.Combobox(
            options_row,
            values=["Toolbox Downloads", "Custom Selection..."],
            state="readonly",
            width=18
        )
        self.preset_combo.current(0)
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_changed)
        self.preset_combo.pack(side=tk.LEFT, padx=(0, 10))

        prompt_chk = ttk.Checkbutton(
            options_row,
            text="Ask folder on every download",
            variable=self.prompt_every_time,
            style="TCheckbutton"
        )
        prompt_chk.pack(side=tk.LEFT)

        url_card = ttk.Frame(container, style="Card.TFrame", padding=12)
        url_card.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(url_card, text="🔗 Paste YouTube URL:", font=("Segoe UI", 10, "bold"), style="Card.TLabel").pack(anchor="w", pady=(0, 6))

        self.url_entry = tk.Entry(
            url_card,
            bg="#313244",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            relief="flat",
            font=("Segoe UI", 10)
        )
        self.url_entry.pack(fill=tk.X, ipady=6)

        self.progress_bar = ttk.Progressbar(container, style="Horizontal.TProgressbar", mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(0, 6))

        self.status_label = ttk.Label(container, text="Status: Idle", style="Status.TLabel")
        self.status_label.pack(anchor="w")

        self.speed_label = ttk.Label(container, text="Speed: -- | ETA: --", style="Status.TLabel")
        self.speed_label.pack(anchor="w", pady=(0, 12))

        self.download_btn = ttk.Button(
            container,
            text="⚡ Download in Original High Quality",
            style="Primary.TButton",
            command=self.start_download
        )
        self.download_btn.pack(fill=tk.X, ipady=4)

    def _browse_directory(self):
        chosen = filedialog.askdirectory(
            initialdir=self.storage_path.get(),
            title="Select Storage Folder"
        )
        if chosen:
            self.storage_path.set(chosen)

    def _on_preset_changed(self, event):
        choice = self.preset_combo.get()
        if choice == "Toolbox Downloads":
            self.storage_path.set(str(get_default_music_dir()))
        elif choice == "Custom Selection...":
            self._browse_directory()

    def start_download(self):
        if self.is_downloading:
            messagebox.showwarning("In Progress", "A download is currently running.")
            return

        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please paste a YouTube URL first.")
            return

        target_dir = self.storage_path.get().strip()
        if self.prompt_every_time.get():
            selected_dir = filedialog.askdirectory(
                initialdir=target_dir or self.default_music_dir,
                title="Select Storage Destination"
            )
            if not selected_dir:
                self.status_label.config(text="Download cancelled by user.", foreground="#f9e2af")
                return
            target_dir = selected_dir
            self.storage_path.set(target_dir)

        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Directory Error", f"Failed to access folder:\n{e}")
            return

        self.is_downloading = True
        self.download_btn.config(state="disabled")
        self.progress_bar["value"] = 0
        self.status_label.config(text="Status: Connecting to YouTube...", foreground=self.fg_color)
        self.speed_label.config(text="Speed: -- | ETA: --")

        worker = threading.Thread(target=self._download_worker, args=(url, target_dir), daemon=True)
        worker.start()

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            eta = d.get("eta")

            percent = (downloaded / total * 100) if total > 0 else 0
            speed_str = f"{speed / (1024 * 1024):.2f} MB/s" if speed > 1024 * 1024 else f"{speed / 1024:.2f} KB/s"
            eta_str = f"{eta}s" if eta is not None else "--"

            downloaded_mb = downloaded / (1024 * 1024)
            total_mb_str = f"{total / (1024 * 1024):.1f} MB" if total > 0 else "Unknown"

            status_text = f"Downloading: {percent:.1f}% ({downloaded_mb:.1f}MB / {total_mb_str})"
            speed_text = f"Speed: {speed_str} | ETA: {eta_str}"

            self.after(0, self._update_ui_progress, percent, status_text, speed_text)

        elif d["status"] == "finished":
            self.after(0, self._update_ui_progress, 100, "Processing & Finalizing...", "Finalizing...")

    def _update_ui_progress(self, percent, status_text, speed_text):
        self.progress_bar["value"] = percent
        self.status_label.config(text=f"Status: {status_text}")
        self.speed_label.config(text=speed_text)

    def _download_worker(self, url, output_dir):
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "writethumbnail": False,
            "progress_hooks": [self._progress_hook],
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                }
            ],
        }

        js_runtime = get_node_runtime()
        if js_runtime:
            ydl_opts["js_runtimes"] = js_runtime

        error_msg = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            error_msg = str(e)

        self.after(0, self._on_download_finished, error_msg, output_dir)

    def _on_download_finished(self, error, output_dir):
        self.is_downloading = False
        self.download_btn.config(state="normal")

        if error:
            self.status_label.config(text="Status: Download Failed!", foreground=self.error_color)
            messagebox.showerror("Download Error", f"An error occurred:\n{error}")
        else:
            self.status_label.config(text=f"Status: ✅ Saved to {output_dir}", foreground=self.success_color)
            self.speed_label.config(text="Complete!")
            self.url_entry.delete(0, tk.END)
            messagebox.showinfo("Success", f"Media downloaded successfully!\n\nFolder: {output_dir}")

    def _on_close(self):
        if self.is_downloading:
            if messagebox.askyesno("Exit Confirmation", "A download is currently running. Quitting now will abort the process. Exit anyway?"):
                self.destroy()
        else:
            self.destroy()


if __name__ == "__main__":
    app = YouTubeDownloaderGUI()
    app.mainloop()
