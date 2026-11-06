#!/usr/bin/env python3
"""
Music Player Desktop Widget with Animated Gradient Waveform
Modern, transparent, interactive desktop music player for audio files in ~/SE/toolbox/downloads and ~/SE/toolbox/music.
Location: /home/dev/SE/toolbox/widgets/music/music_widget.py
"""

import sys
import os
import re
import json
import math
import subprocess
import socket
import fcntl
from pathlib import Path

_lock_file = None
def _acquire_single_instance_lock():
    global _lock_file
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        lock_path = Path(runtime_dir) / "music_widget.lock"
    else:
        lock_path = Path.home() / ".config" / "music-widget" / "music_widget.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_file = open(lock_path, "a+")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        print("Another instance of music_widget is already running. Exiting.")
        sys.exit(0)
    except Exception as e:
        print(f"Warning: Could not acquire lock at {lock_path}: {e}")

# Ensure GTK 3, GStreamer 1.0, Pango & Cairo are loaded
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Gst', '1.0')
gi.require_version('Pango', '1.0')
try:
    gi.require_foreign('cairo')
except Exception:
    pass
import cairo
from gi.repository import Gtk, Gdk, GLib, Gst, Pango
import warnings

# Suppress GObject ValueArray deprecation warning in spectrum callback
warnings.filterwarnings('ignore', category=DeprecationWarning)

Gst.init(None)

SCRIPT_DIR = Path(__file__).parent.resolve()
MUSIC_DIR = Path.home() / "SE" / "toolbox" / "downloads"
ALT_MUSIC_DIR = Path.home() / "SE" / "toolbox" / "music"
CONFIG_DIR = Path.home() / ".config" / "music-widget"
CONFIG_FILE = CONFIG_DIR / "config.json"
LIKED_SONGS_FILE = CONFIG_DIR / "liked_songs.json"

DEFAULT_CONFIG = {
    "x": 3738,
    "y": 811,
    "width": 360,
    "height": 210,
    "always_on_top": False,
    "volume": 0.85,
    "muted": False
}

IPC_SOCKET_NAME = "\0music_widget_ipc"

NUM_FFT_BANDS = 48
NUM_VISUAL_BANDS = 24
SPECTRUM_THRESHOLD = -75.0


class AnimatedWaveform(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(-1, 38)
        self.phase = 0.0
        self.current_levels = [0.0] * NUM_VISUAL_BANDS
        self.target_levels = [0.0] * NUM_VISUAL_BANDS
        self.bass_avg = 0.2
        self.beat_impulse = 0.0
        self.loudness = 0.0
        self.is_playing = False

        # Precompute logarithmic bin edges mapping visual bands to FFT bands
        edges = [0]
        for i in range(1, NUM_VISUAL_BANDS + 1):
            edge = int(round(math.pow(NUM_FFT_BANDS, i / NUM_VISUAL_BANDS)))
            edge = max(edges[-1] + 1, min(NUM_FFT_BANDS, edge))
            edges.append(edge)
        self.bin_ranges = [(edges[i], edges[i + 1]) for i in range(NUM_VISUAL_BANDS)]

        self.connect("draw", self._on_draw)

    def set_playing(self, playing: bool):
        self.is_playing = playing
        if not playing:
            self.target_levels = [0.0] * NUM_VISUAL_BANDS
            self.beat_impulse = 0.0

    def push_spectrum(self, magnitudes: list):
        """Processes real-time dB magnitude spectrum from GStreamer."""
        try:
            if not magnitudes:
                return
            norm = [
                max(0.0, min(1.0, (val - SPECTRUM_THRESHOLD) / (-SPECTRUM_THRESHOLD)))
                for val in magnitudes
            ]
            for k, (start, end) in enumerate(self.bin_ranges):
                chunk = norm[start:end]
                self.target_levels[k] = sum(chunk) / len(chunk) if chunk else 0.0

            # Beat & kick drum detection from lowest bass frequencies
            bass_val = (norm[0] * 1.5 + norm[1] * 1.0) / 2.5 if len(norm) >= 2 else (norm[0] if norm else 0.0)
            if bass_val > self.bass_avg * 1.25 and bass_val > 0.22:
                diff = bass_val - self.bass_avg
                impulse = min(1.0, diff * 3.5 + 0.3)
                self.beat_impulse = max(self.beat_impulse, impulse)
            self.bass_avg = self.bass_avg * 0.90 + bass_val * 0.10
        except Exception:
            pass

    def update_frame(self):
        """Smooth interpolation and animation tick at 30 FPS."""
        try:
            for i in range(NUM_VISUAL_BANDS):
                target = self.target_levels[i] if self.is_playing else 0.0
                if target > self.current_levels[i]:
                    self.current_levels[i] += (target - self.current_levels[i]) * 0.55
                else:
                    self.current_levels[i] += (target - self.current_levels[i]) * 0.18

            self.beat_impulse *= 0.85
            if self.beat_impulse < 0.01:
                self.beat_impulse = 0.0

            target_loudness = sum(self.current_levels) / len(self.current_levels) if self.current_levels else 0.0
            self.loudness += (target_loudness - self.loudness) * 0.2

            speed = (
                0.035 + self.loudness * 0.06 + self.beat_impulse * 0.04
                if self.is_playing
                else 0.018
            )
            self.phase += speed
            if self.phase > 1000.0:
                self.phase = 0.0

            self.queue_draw()
        except Exception:
            pass

    def _draw_rounded_rect(self, cr: cairo.Context, x: float, y: float, w: float, h: float, r: float):
        r = max(0.0, min(r, w / 2.0, h / 2.0))
        if r <= 0.0:
            cr.rectangle(x, y, w, h)
            return
        cr.new_sub_path()
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.arc(x + w - r, y + r, r, 1.5 * math.pi, 2.0 * math.pi)
        cr.arc(x + w - r, y + h - r, r, 0.0, 0.5 * math.pi)
        cr.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
        cr.close_path()

    def _on_draw(self, widget, cr: cairo.Context):
        try:
            width = widget.get_allocated_width()
            height = widget.get_allocated_height()
            if width <= 0 or height <= 0:
                return False

            mid_y = height / 2.0
            cr.save()
            try:
                # --- BEAT PULSE GLOW ---
                if self.beat_impulse > 0.05 and self.is_playing:
                    glow_radius = max(1.0, width * 0.45)
                    rad_pat = cairo.RadialGradient(
                        width / 2.0, mid_y, 0, width / 2.0, mid_y, glow_radius
                    )
                    rad_pat.add_color_stop_rgba(0.0, 0.75, 0.45, 0.98, 0.15 * min(1.0, self.beat_impulse))
                    rad_pat.add_color_stop_rgba(1.0, 0.06, 0.73, 0.85, 0.0)
                    cr.set_source(rad_pat)
                    cr.paint()

                # --- LAYER 1: EQUALIZER FREQUENCY BARS ---
                bar_slot = width / NUM_VISUAL_BANDS
                bar_w = max(2.0, min(bar_slot * 0.48, bar_slot - 1.0))
                for i in range(min(NUM_VISUAL_BANDS, len(self.current_levels))):
                    lvl = self.current_levels[i]
                    if lvl <= 0.03 and not self.is_playing:
                        continue
                    bx = i * bar_slot + (bar_slot - bar_w) / 2.0
                    bh = max(3.0, min(height, lvl * (height * 0.78)))
                    by = mid_y - bh / 2.0

                    t = i / max(1, NUM_VISUAL_BANDS - 1)
                    r = 0.65 * (1.0 - t) + 0.10 * t
                    g = 0.35 * (1.0 - t) + 0.75 * t
                    b = 0.95 * (1.0 - t) + 0.95 * t
                    alpha = (
                        (0.18 + 0.48 * lvl + 0.20 * self.beat_impulse)
                        if self.is_playing
                        else 0.0
                    )

                    if alpha > 0.01:
                        cr.set_source_rgba(r, g, b, min(0.80, alpha))
                        self._draw_rounded_rect(
                            cr, bx, by, bar_w, bh, min(bar_w / 2.0, bh / 2.0, 3.0)
                        )
                        cr.fill()

                # --- LAYER 2: HARMONIC WAVE ---
                cr.new_path()
                step = max(2, int(width / 120))
                for x in range(0, width + step, step):
                    x_clamped = min(x, width)
                    t = x_clamped / max(1, width)
                    idx = t * (NUM_VISUAL_BANDS - 1)
                    i0 = int(idx)
                    i1 = min(i0 + 1, NUM_VISUAL_BANDS - 1)
                    frac = idx - i0
                    l0 = self.current_levels[i0] if i0 < len(self.current_levels) else 0.0
                    l1 = self.current_levels[i1] if i1 < len(self.current_levels) else 0.0
                    spec = l0 * (1.0 - frac) + l1 * frac
                    env = 0.35 + 0.65 * math.sin(math.pi * t)
                    amp = (spec * 8.5 + 1.8) * env if self.is_playing else 1.2 * env
                    y = mid_y + amp * math.sin(0.032 * x_clamped - self.phase * 1.1 + 0.8)
                    if x == 0:
                        cr.move_to(x_clamped, y)
                    else:
                        cr.line_to(x_clamped, y)
                cr.set_source_rgba(0.55, 0.35, 0.98, 0.35)
                cr.set_line_width(1.5)
                cr.stroke()

                # --- LAYER 3: PRIMARY NEON WAVE ---
                points = []
                step_neon = max(2, int(width / 180))
                for x in range(0, width + step_neon, step_neon):
                    x_clamped = min(x, width)
                    t = x_clamped / max(1, width)
                    idx = t * (NUM_VISUAL_BANDS - 1)
                    i0 = int(idx)
                    i1 = min(i0 + 1, NUM_VISUAL_BANDS - 1)
                    frac = idx - i0
                    l0 = self.current_levels[i0] if i0 < len(self.current_levels) else 0.0
                    l1 = self.current_levels[i1] if i1 < len(self.current_levels) else 0.0
                    spec = l0 * (1.0 - frac) + l1 * frac
                    env = 0.35 + 0.65 * math.sin(math.pi * t)
                    bass_boost = (1.0 - t * 0.65) * self.beat_impulse * 6.0
                    amp = (spec * 11.5 + bass_boost + (2.0 if self.is_playing else 1.4)) * env
                    osc = (
                        math.sin(0.038 * x_clamped + self.phase) * 0.72
                        + math.sin(0.076 * x_clamped - self.phase * 1.3) * 0.28
                    )
                    y = mid_y + amp * osc
                    points.append((x_clamped, y))

                cr.new_path()
                for i, (px, py) in enumerate(points):
                    if i == 0:
                        cr.move_to(px, py)
                    else:
                        cr.line_to(px, py)

                stroke_pat = cairo.LinearGradient(0, 0, max(1.0, float(width)), 0)
                stroke_pat.add_color_stop_rgba(0.0, 0.66, 0.33, 0.97, 0.95)   # Electric Violet
                stroke_pat.add_color_stop_rgba(0.35, 0.75, 0.45, 0.98, 0.95)  # Purple
                stroke_pat.add_color_stop_rgba(0.75, 0.22, 0.83, 0.93, 0.95)  # Sky Blue
                stroke_pat.add_color_stop_rgba(1.0, 0.06, 0.73, 0.85, 0.95)   # Cyan

                cr.set_source(stroke_pat)
                stroke_w = (2.2 + 0.8 * self.beat_impulse) if self.is_playing else 1.8
                cr.set_line_width(stroke_w)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.stroke()

            finally:
                cr.restore()
        except Exception:
            pass
        return False


class MusicPlayerWidget:
    def __init__(self):
        self.config = self._load_config()
        self.liked_data = self._load_liked_songs()
        self.target_x = self.config.get("x", 3738)
        self.target_y = self.config.get("y", 811)
        self._initial_positioned = False
        self._is_pinned_top = self.config.get("always_on_top", False)

        self.playlist = []
        self.current_index = 0
        self.is_playing = False
        self.duration_seconds = 0
        self.position_seconds = 0
        self._consecutive_eos_count = 0
        self._save_timer_id = None
        self._updating_vol_slider = False

        self.volume = max(0.0, min(1.0, float(self.config.get("volume", 0.85))))
        self.is_muted = bool(self.config.get("muted", False))

        # Initialize GStreamer playbin
        self.player = Gst.ElementFactory.make("playbin", "music-player")
        if not self.player:
            raise RuntimeError("GStreamer 'playbin' element could not be created")
        self.player.set_property("volume", 0.0 if self.is_muted else self.volume)

        # Attach real-time audio spectrum analyzer
        self.spectrum = Gst.ElementFactory.make("spectrum", "spectrum")
        if self.spectrum:
            self.spectrum.set_property("bands", NUM_FFT_BANDS)
            self.spectrum.set_property("threshold", int(SPECTRUM_THRESHOLD))
            self.spectrum.set_property("interval", int(1e9 / 30))  # 30 fps
            self.player.set_property("audio-filter", self.spectrum)

        self.bus = self.player.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self._on_bus_message)

        self._scan_music()
        self._init_window()
        self._load_css()
        self._build_ui()
        self._update_display()
        self._update_vol_button()
        self._update_like_button()
        self._init_ipc()

        # Animation loop: 30 FPS (~33ms)
        GLib.timeout_add(33, self._on_anim_tick)

        # Update playback position every 500ms
        GLib.timeout_add(500, self._on_tick)

    def _load_config(self) -> dict:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    merged = DEFAULT_CONFIG.copy()
                    merged.update(cfg)
                    return merged
            except Exception as e:
                print(f"Error loading config: {e}")
        return DEFAULT_CONFIG.copy()

    def _save_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = CONFIG_FILE.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            tmp_file.replace(CONFIG_FILE)
        except Exception as e:
            print(f"Error saving music widget config: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def _debounced_save_config(self):
        if self._save_timer_id:
            GLib.source_remove(self._save_timer_id)
            self._save_timer_id = None
        self._save_timer_id = GLib.timeout_add(300, self._do_debounced_save)

    def _do_debounced_save(self):
        self._save_config()
        self._save_timer_id = None
        return False

    def _load_liked_songs(self) -> dict:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if LIKED_SONGS_FILE.exists():
            try:
                with open(LIKED_SONGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {"liked_tracks": data}
                    elif isinstance(data, dict):
                        if "liked_tracks" not in data:
                            data["liked_tracks"] = []
                        return data
            except Exception as e:
                print(f"Error loading liked songs: {e}")
        return {"liked_tracks": []}

    def _save_liked_songs(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = LIKED_SONGS_FILE.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.liked_data, f, indent=2)
            tmp_file.replace(LIKED_SONGS_FILE)
        except Exception as e:
            print(f"Error saving liked songs: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def _is_current_track_liked(self) -> bool:
        if not self.playlist or self.current_index >= len(self.playlist):
            return False
        track_path = str(self.playlist[self.current_index].resolve())
        for item in self.liked_data.get("liked_tracks", []):
            if isinstance(item, dict) and item.get("path") == track_path:
                return True
            elif isinstance(item, str) and item == track_path:
                return True
        return False

    def _toggle_like(self) -> bool:
        if not self.playlist or self.current_index >= len(self.playlist):
            return False
        track_path = str(self.playlist[self.current_index].resolve())
        clean_title = self._clean_track_title(self.playlist[self.current_index].stem)

        tracks = self.liked_data.setdefault("liked_tracks", [])
        found_idx = -1
        for i, item in enumerate(tracks):
            p = item.get("path") if isinstance(item, dict) else item
            if p == track_path:
                found_idx = i
                break

        if found_idx >= 0:
            tracks.pop(found_idx)
            is_now_liked = False
        else:
            tracks.append({
                "path": track_path,
                "title": clean_title,
                "added_at": int(GLib.get_real_time() / 1e6)
            })
            is_now_liked = True

        self._save_liked_songs()
        self._update_like_button()
        return is_now_liked

    def _update_like_button(self):
        if not hasattr(self, "btn_like") or not self.btn_like:
            return
        liked = self._is_current_track_liked()
        self.btn_like.set_label("❤️" if liked else "🤍")
        if not self.playlist:
            self.btn_like.set_sensitive(False)
            self.btn_like.set_tooltip_text("No track loaded")
        else:
            self.btn_like.set_sensitive(True)
            self.btn_like.set_tooltip_text("Unlike song" if liked else "Like song")

    def _scan_music(self):
        try:
            MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not create {MUSIC_DIR}: {e}")
        try:
            ALT_MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not create {ALT_MUSIC_DIR}: {e}")

        audio_extensions = (
            "*.mp3", "*.MP3", "*.flac", "*.FLAC", "*.m4a", "*.M4A",
            "*.wav", "*.WAV", "*.ogg", "*.OGG", "*.opus", "*.OPUS",
            "*.aac", "*.AAC", "*.wma", "*.WMA"
        )
        found = []
        for folder in (MUSIC_DIR, ALT_MUSIC_DIR):
            if folder.is_dir():
                for ext in audio_extensions:
                    try:
                        found.extend(folder.rglob(ext))
                    except Exception:
                        pass

        # Deduplicate by resolved canonical path and filter valid existing files
        valid_files = []
        seen_paths = set()
        for p in found:
            try:
                resolved = p.resolve()
                if resolved.is_file() and resolved not in seen_paths:
                    seen_paths.add(resolved)
                    valid_files.append(resolved)
            except Exception:
                continue

        valid_files.sort(key=lambda p: p.name.lower())

        # Preserve currently active track if still in playlist
        current_track_path = None
        if self.playlist and 0 <= self.current_index < len(self.playlist):
            current_track_path = self.playlist[self.current_index]

        self.playlist = valid_files

        if current_track_path and current_track_path in self.playlist:
            self.current_index = self.playlist.index(current_track_path)
        elif self.current_index >= len(self.playlist):
            self.current_index = 0

    def _clean_track_title(self, raw_stem: str) -> str:
        s = raw_stem.replace("_", " ")
        patterns = [
            r'[\(\[\{][^\)\]\}]*(?:lyrics?|official|video|audio|extended|slowed|reverb|remix|hd|4k|instrumental|visualizer|mv|feat\.?|ft\.?|eng⧸jpn)[^\)\]\}]*[\)\]\}]',
            r'[｜|]\s*.*$',
            r'[–-]\s*(?:instrumental|slowed|reverb|official\s*video|visualizer).*$',
        ]
        cleaned = s
        for p in patterns:
            cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -–|')
        return cleaned if cleaned else s

    def _init_window(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Music Player Widget")
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

        self.window.set_default_size(self.config.get("width", 360), self.config.get("height", 210))
        self.window.move(self.target_x, self.target_y)

        self.window.connect("map-event", self._on_map)
        self.window.connect("configure-event", self._on_configure)
        self.window.connect("destroy", self._on_destroy)

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
        .music-card {
            background-color: rgba(18, 20, 26, 0.84);
            border: 1px solid rgba(255, 255, 255, 0.13);
            border-radius: 20px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6);
            padding: 12px 16px 14px 16px;
        }
        .music-header {
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 6px;
            margin-bottom: 6px;
        }
        .music-title {
            font-size: 12px;
            font-weight: bold;
            color: #d1d5db;
        }
        .badge-count {
            background-color: rgba(168, 85, 247, 0.22);
            color: #d8b4fe;
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
            border: 1px solid rgba(168, 85, 247, 0.4);
        }
        .track-title {
            font-size: 13px;
            font-weight: bold;
            color: #ffffff;
            margin-bottom: 2px;
        }
        .time-label {
            font-size: 11px;
            color: #9ca3af;
            font-family: monospace;
        }
        progressbar.progress-bar-fill-music,
        progressbar.progress-bar-fill-music trough {
            background-color: rgba(255, 255, 255, 0.08);
            background-image: none;
            border-radius: 4px;
            min-height: 5px;
            border: none;
        }
        progressbar.progress-bar-fill-music progress {
            background-color: #a855f7;
            background-image: none;
            border-radius: 4px;
            min-height: 5px;
            border: none;
        }
        button.btn-ctrl, .btn-ctrl {
            background-color: rgba(255, 255, 255, 0.08);
            background-image: none;
            color: #e5e7eb;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 10px;
            padding: 6px 16px;
            font-size: 14px;
            font-weight: bold;
            outline: none;
            box-shadow: none;
        }
        button.btn-ctrl:hover, .btn-ctrl:hover {
            background-color: rgba(255, 255, 255, 0.16);
            background-image: none;
            color: #ffffff;
            border-color: rgba(255, 255, 255, 0.25);
        }
        button.btn-ctrl:active, .btn-ctrl:active {
            background-color: rgba(255, 255, 255, 0.22);
            background-image: none;
        }
        button.btn-ctrl:focus, .btn-ctrl:focus {
            outline: none;
            box-shadow: none;
        }
        button.btn-play, .btn-play {
            background-color: #a855f7;
            background-image: none;
            color: #ffffff;
            border: 1px solid rgba(168, 85, 247, 0.6);
            border-radius: 12px;
            padding: 6px 24px;
            outline: none;
            box-shadow: 0 4px 14px rgba(168, 85, 247, 0.35);
        }
        button.btn-play:hover, .btn-play:hover {
            background-color: #9333ea;
            background-image: none;
            border-color: rgba(168, 85, 247, 0.9);
            box-shadow: 0 6px 18px rgba(168, 85, 247, 0.55);
        }
        button.btn-play:active, .btn-play:active {
            background-color: #7e22ce;
            background-image: none;
        }
        button.btn-play:focus, .btn-play:focus {
            outline: none;
            box-shadow: 0 0 0 2px rgba(168, 85, 247, 0.5);
        }
        .btn-play-label {
            font-size: 15px;
            font-weight: bold;
            color: #ffffff;
        }
        button.btn-icon, .btn-icon {
            background: transparent;
            background-color: transparent;
            background-image: none;
            border: none;
            outline: none;
            box-shadow: none;
            color: #9ca3af;
            padding: 3px 6px;
            border-radius: 6px;
            font-size: 13px;
        }
        button.btn-icon:hover, .btn-icon:hover {
            background-color: rgba(255, 255, 255, 0.1);
            background-image: none;
            color: #ffffff;
        }
        button.btn-icon:focus, .btn-icon:focus {
            outline: none;
            box-shadow: none;
        }
        scale.volume-slider {
            margin: 0;
            padding: 0;
        }
        scale.volume-slider trough {
            background-color: rgba(255, 255, 255, 0.12);
            background-image: none;
            border-radius: 4px;
            min-height: 4px;
            min-width: 58px;
            border: none;
        }
        scale.volume-slider highlight {
            background-color: #a855f7;
            background-image: none;
            border-radius: 4px;
            min-height: 4px;
            border: none;
        }
        scale.volume-slider slider {
            background-color: #ffffff;
            background-image: none;
            border-radius: 50%;
            min-width: 10px;
            min-height: 10px;
            border: none;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
            margin: -3px;
        }
        scale.volume-slider slider:hover {
            background-color: #d8b4fe;
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
        self.card.get_style_context().add_class("music-card")
        self.card.add_events(Gdk.EventMask.SCROLL_MASK)
        self.card.connect("scroll-event", self._on_scroll)

        # --- HEADER (Draggable) ---
        self.header_event_box = Gtk.EventBox()
        self.header_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.header_event_box.connect("button-press-event", self._on_header_press)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.get_style_context().add_class("music-header")

        lbl_icon = Gtk.Label(label="🎵")
        header_box.pack_start(lbl_icon, False, False, 0)

        lbl_title = Gtk.Label(label="Music Player")
        lbl_title.get_style_context().add_class("music-title")
        header_box.pack_start(lbl_title, False, False, 0)

        # Expanding Spacer
        header_spacer = Gtk.Box()
        header_box.pack_start(header_spacer, True, True, 0)

        # Track Counter Badge
        self.lbl_count = Gtk.Label(label="0/0")
        self.lbl_count.get_style_context().add_class("badge-count")
        self.lbl_count.set_halign(Gtk.Align.END)
        header_box.pack_start(self.lbl_count, False, False, 2)

        # Folder Button
        btn_folder = Gtk.Button(label="📂")
        btn_folder.set_tooltip_text("Open ~/SE/toolbox/downloads")
        btn_folder.get_style_context().add_class("btn-icon")
        btn_folder.connect("clicked", self._on_open_folder)
        header_box.pack_start(btn_folder, False, False, 0)

        # Pin Button
        self.btn_pin = Gtk.Button(label="📌" if self._is_pinned_top else "📍")
        self.btn_pin.set_tooltip_text("Toggle Always On Top vs Desktop Pinned")
        self.btn_pin.get_style_context().add_class("btn-icon")
        self.btn_pin.connect("clicked", self._on_toggle_pin)
        header_box.pack_start(self.btn_pin, False, False, 0)

        self.header_event_box.add(header_box)
        self.card.pack_start(self.header_event_box, False, False, 0)

        # --- TRACK TITLE ---
        self.lbl_track = Gtk.Label(label="No music found")
        self.lbl_track.set_xalign(0.0)
        self.lbl_track.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_track.get_style_context().add_class("track-title")
        self.card.pack_start(self.lbl_track, False, False, 2)

        # --- ANIMATED GRADIENT WAVEFORM ---
        self.waveform = AnimatedWaveform()
        self.card.pack_start(self.waveform, False, False, 2)

        # --- TIME ROW ---
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        self.lbl_time_pos = Gtk.Label(label="00:00")
        self.lbl_time_pos.set_xalign(0.0)
        self.lbl_time_pos.get_style_context().add_class("time-label")
        time_box.pack_start(self.lbl_time_pos, False, False, 0)

        time_spacer = Gtk.Box()
        time_box.pack_start(time_spacer, True, True, 0)

        self.lbl_time_dur = Gtk.Label(label="00:00")
        self.lbl_time_dur.set_xalign(1.0)
        self.lbl_time_dur.get_style_context().add_class("time-label")
        time_box.pack_start(self.lbl_time_dur, False, False, 0)

        self.card.pack_start(time_box, False, False, 1)

        # --- PROGRESS BAR (Click to Seek) ---
        self.progress_event_box = Gtk.EventBox()
        self.progress_event_box.set_visible_window(False)
        self.progress_event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.progress_event_box.connect("button-press-event", self._on_progress_click)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.get_style_context().add_class("progress-bar-fill-music")
        self.progress_event_box.add(self.progress_bar)

        self.card.pack_start(self.progress_event_box, False, False, 2)

        # --- BOTTOM CONTROLS BAR (Like, Prev, Play/Pause, Next, Volume/Mute, Slider) ---
        controls_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        controls_bar.set_margin_top(4)

        # 1. Like Button (🤍 / ❤️)
        self.btn_like = Gtk.Button(label="🤍")
        self.btn_like.set_tooltip_text("Like / Favorite this track")
        self.btn_like.get_style_context().add_class("btn-icon")
        self.btn_like.connect("clicked", lambda b: self._toggle_like())
        controls_bar.pack_start(self.btn_like, False, False, 0)

        # Spacer
        sp_left = Gtk.Box()
        controls_bar.pack_start(sp_left, True, True, 0)

        # 2. Playback Control Buttons (Prev, Play, Next)
        playback_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        btn_prev = Gtk.Button(label="⏮")
        btn_prev.set_tooltip_text("Previous Track")
        btn_prev.get_style_context().add_class("btn-ctrl")
        btn_prev.connect("clicked", self._on_prev)
        playback_box.pack_start(btn_prev, False, False, 0)

        self.btn_play = Gtk.Button()
        self.btn_play.set_tooltip_text("Play / Pause")
        self.btn_play.get_style_context().add_class("btn-play")
        self.btn_play.connect("clicked", self._on_play_pause)
        self.lbl_play_icon = Gtk.Label(label="▶")
        self.lbl_play_icon.get_style_context().add_class("btn-play-label")
        self.btn_play.add(self.lbl_play_icon)
        playback_box.pack_start(self.btn_play, False, False, 0)

        btn_next = Gtk.Button(label="⏭")
        btn_next.set_tooltip_text("Next Track")
        btn_next.get_style_context().add_class("btn-ctrl")
        btn_next.connect("clicked", self._on_next)
        playback_box.pack_start(btn_next, False, False, 0)

        controls_bar.pack_start(playback_box, False, False, 0)

        # Spacer
        sp_right = Gtk.Box()
        controls_bar.pack_start(sp_right, True, True, 0)

        # 3. Volume Section (Mute Button + Smooth Volume Slider)
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

        self.btn_vol = Gtk.Button(label="🔊")
        self.btn_vol.set_tooltip_text("Mute / Unmute")
        self.btn_vol.get_style_context().add_class("btn-icon")
        self.btn_vol.connect("clicked", self._on_toggle_mute)
        vol_box.pack_start(self.btn_vol, False, False, 0)

        self.vol_adj = Gtk.Adjustment(
            value=self.volume * 100.0,
            lower=0.0,
            upper=100.0,
            step_increment=1.0,
            page_increment=5.0,
            page_size=0.0
        )
        self.vol_slider = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=self.vol_adj
        )
        self.vol_slider.set_draw_value(False)
        self.vol_slider.set_size_request(60, -1)
        self.vol_slider.get_style_context().add_class("volume-slider")
        self.vol_slider.set_tooltip_text(f"Volume: {int(self.volume * 100)}%")
        self.vol_slider.connect("value-changed", self._on_vol_slider_changed)
        vol_box.pack_start(self.vol_slider, False, False, 0)

        controls_bar.pack_start(vol_box, False, False, 0)

        self.card.pack_start(controls_bar, False, False, 0)
        self.window.add(self.card)

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
        if x > -10000 and y > -10000 and w > 100 and h > 100:
            self.config["x"] = x
            self.config["y"] = y
            self.config["width"] = w
            self.config["height"] = h
            self.target_x = x
            self.target_y = y
            self._debounced_save_config()

    def _on_toggle_pin(self, button):
        self._is_pinned_top = not self._is_pinned_top
        self.config["always_on_top"] = self._is_pinned_top
        self.btn_pin.set_label("📌" if self._is_pinned_top else "📍")
        self._apply_layer()
        self._debounced_save_config()

    def _on_scroll(self, widget, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self._adjust_volume(0.05)
            return True
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self._adjust_volume(-0.05)
            return True
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            ok, dx, dy = event.get_scroll_deltas()
            if ok:
                if dy < 0:
                    self._adjust_volume(0.05)
                elif dy > 0:
                    self._adjust_volume(-0.05)
                return True
        return False

    def _on_vol_slider_changed(self, scale):
        if self._updating_vol_slider:
            return
        val = scale.get_value() / 100.0
        self.volume = max(0.0, min(1.0, round(val, 2)))
        if self.volume > 0:
            self.is_muted = False
        self.player.set_property("volume", 0.0 if self.is_muted else self.volume)
        self.config["volume"] = self.volume
        self.config["muted"] = self.is_muted
        self._update_vol_button()
        self._debounced_save_config()

    def _adjust_volume(self, delta: float):
        self.volume = max(0.0, min(1.0, round(self.volume + delta, 2)))
        if self.volume > 0:
            self.is_muted = False
        self.player.set_property("volume", 0.0 if self.is_muted else self.volume)
        self.config["volume"] = self.volume
        self.config["muted"] = self.is_muted
        self._updating_vol_slider = True
        try:
            self.vol_slider.set_value(self.volume * 100.0)
        finally:
            self._updating_vol_slider = False
        self._update_vol_button()
        self._debounced_save_config()

    def _on_toggle_mute(self, button):
        self.is_muted = not self.is_muted
        self.player.set_property("volume", 0.0 if self.is_muted else self.volume)
        self.config["muted"] = self.is_muted
        self._update_vol_button()
        self._debounced_save_config()

    def _update_vol_button(self):
        if not hasattr(self, "btn_vol") or not self.btn_vol:
            return
        pct = int(self.volume * 100)
        if hasattr(self, "vol_slider") and self.vol_slider:
            self.vol_slider.set_tooltip_text(f"Volume: {pct}%")
        if self.is_muted or self.volume <= 0.01:
            self.btn_vol.set_label("🔇")
            self.btn_vol.set_tooltip_text("Unmute")
        elif self.volume < 0.5:
            self.btn_vol.set_label("🔉")
            self.btn_vol.set_tooltip_text(f"Mute (Volume: {pct}%)")
        else:
            self.btn_vol.set_label("🔊")
            self.btn_vol.set_tooltip_text(f"Mute (Volume: {pct}%)")

    def _on_progress_click(self, widget, event):
        if event.button == 1 and self.duration_seconds > 0 and self.playlist:
            alloc = self.progress_bar.get_allocation()
            if alloc.width > 0:
                fraction = max(0.0, min(1.0, event.x / alloc.width))
                seek_time_ns = int(fraction * self.duration_seconds * Gst.SECOND)
                try:
                    self.player.seek_simple(
                        Gst.Format.TIME,
                        Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                        seek_time_ns
                    )
                    self.position_seconds = int(fraction * self.duration_seconds)
                    self.progress_bar.set_fraction(fraction)
                    self._update_time_label()
                except Exception as e:
                    print(f"Seek error: {e}")
                return True
        return False

    def _on_open_folder(self, button):
        try:
            target = MUSIC_DIR if MUSIC_DIR.exists() else ALT_MUSIC_DIR
            target.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["xdg-open", str(target)])
            GLib.timeout_add(1500, self._refresh_playlist)
        except Exception as e:
            print(f"Error opening music folder: {e}")

    def _refresh_playlist(self):
        self._scan_music()
        self._update_display()
        return False

    def _update_time_label(self):
        pos_m, pos_s = divmod(self.position_seconds, 60)
        dur_m, dur_s = divmod(self.duration_seconds, 60)
        self.lbl_time_pos.set_text(f"{pos_m:02d}:{pos_s:02d}")
        self.lbl_time_dur.set_text(f"{dur_m:02d}:{dur_s:02d}")

    def _update_display(self):
        total = len(self.playlist)
        if total > 0:
            cur_track = self.playlist[self.current_index]
            raw_title = cur_track.stem.replace("_", " ")
            clean_title = self._clean_track_title(cur_track.stem)
            self.lbl_track.set_text(clean_title)
            self.lbl_track.set_tooltip_text(raw_title)
            self.lbl_count.set_text(f"{self.current_index + 1}/{total}")
            if (not self.is_playing and self.position_seconds == 0) or (self.position_seconds == 0 and self.duration_seconds == 0):
                self._update_time_label()
                self.progress_bar.set_fraction(0.0)
        else:
            self.lbl_track.set_text("No music found in downloads or music")
            self.lbl_track.set_tooltip_text("Drop audio files into ~/SE/toolbox/downloads or ~/SE/toolbox/music")
            self.lbl_count.set_text("0/0")
            self.lbl_time_pos.set_text("00:00")
            self.lbl_time_dur.set_text("00:00")
            self.progress_bar.set_fraction(0.0)

        self.lbl_play_icon.set_text("⏸" if self.is_playing else "▶")
        self.waveform.set_playing(self.is_playing)
        self._update_like_button()

    def _play_track(self, index: int):
        self._scan_music()
        if not self.playlist:
            self.player.set_state(Gst.State.READY)
            self.is_playing = False
            self.current_index = 0
            self.position_seconds = 0
            self.duration_seconds = 0
            self._update_display()
            return

        self.current_index = index % len(self.playlist)
        track_path = self.playlist[self.current_index]
        if not track_path.is_file():
            print(f"File not found: {track_path}, advancing...")
            self.playlist.pop(self.current_index)
            if self.playlist:
                self._play_track(self.current_index % len(self.playlist))
            else:
                self.player.set_state(Gst.State.READY)
                self.is_playing = False
                self.current_index = 0
                self._update_display()
            return

        self.player.set_state(Gst.State.READY)
        self.player.set_property("uri", track_path.as_uri())
        self.player.set_property("volume", 0.0 if self.is_muted else self.volume)
        ret = self.player.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            print(f"Failed to play {track_path.name}")
            self._consecutive_eos_count += 1
            if self._consecutive_eos_count >= max(1, len(self.playlist)):
                self.player.set_state(Gst.State.NULL)
                self.is_playing = False
                self._update_display()
            else:
                self._on_next(None)
            return

        self.is_playing = True
        self.position_seconds = 0
        self.duration_seconds = 0
        self._update_display()

    def _on_play_pause(self, button):
        self._scan_music()
        if not self.playlist:
            self._on_open_folder(None)
            return

        if self.is_playing:
            self.player.set_state(Gst.State.PAUSED)
            self.is_playing = False
        else:
            state = self.player.get_state(0).state
            if state == Gst.State.PAUSED:
                self.player.set_state(Gst.State.PLAYING)
                self.is_playing = True
            else:
                self._play_track(self.current_index)

        self._update_display()

    def _on_prev(self, button):
        if not self.playlist:
            self.is_playing = False
            self.current_index = 0
            self._update_display()
            return
        new_idx = (self.current_index - 1) % len(self.playlist)
        self._play_track(new_idx)

    def _on_next(self, button):
        if not self.playlist:
            self.is_playing = False
            self.current_index = 0
            self._update_display()
            return
        new_idx = (self.current_index + 1) % len(self.playlist)
        self._play_track(new_idx)

    def _on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            # If track played through (> 1s), reset consecutive fail counter
            if self.position_seconds > 1:
                self._consecutive_eos_count = 0
            else:
                self._consecutive_eos_count += 1

            if self._consecutive_eos_count >= max(1, len(self.playlist)):
                print("All files unplayable or ended. Stopping playback.")
                self.player.set_state(Gst.State.READY)
                self.is_playing = False
                self.position_seconds = 0
                self.duration_seconds = 0
                self._consecutive_eos_count = 0
                self._update_display()
            else:
                self._on_next(None)
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer error: {err.message}")
            self.player.set_state(Gst.State.NULL)
            self._consecutive_eos_count += 1
            if self._consecutive_eos_count >= max(1, len(self.playlist)):
                print("All files unplayable or errored. Stopping playback.")
                self.is_playing = False
                self.position_seconds = 0
                self.duration_seconds = 0
                self._consecutive_eos_count = 0
                self._update_display()
            else:
                self._on_next(None)
        elif t == Gst.MessageType.ELEMENT:
            try:
                s = message.get_structure()
                if s and s.get_name() == "spectrum":
                    ok, arr = s.get_list("magnitude")
                    if ok and arr:
                        raw_vals = [arr.get_nth(i) for i in range(arr.n_values)]
                        self.waveform.push_spectrum(raw_vals)
            except Exception:
                pass

    def _on_anim_tick(self):
        try:
            self.waveform.update_frame()
        except Exception:
            pass
        return True

    def _on_tick(self):
        try:
            if self.is_playing:
                ok_dur, dur = self.player.query_duration(Gst.Format.TIME)
                if ok_dur and dur > 0:
                    self.duration_seconds = dur // Gst.SECOND

                ok_pos, pos = self.player.query_position(Gst.Format.TIME)
                if ok_pos and pos >= 0:
                    self.position_seconds = pos // Gst.SECOND
                    if self.position_seconds > 1:
                        self._consecutive_eos_count = 0

                if self.duration_seconds > 0:
                    fraction = min(1.0, max(0.0, self.position_seconds / self.duration_seconds))
                    self.progress_bar.set_fraction(fraction)
                    self._update_time_label()
        except Exception:
            pass
        return True

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
            conn.settimeout(2.0)
            data = conn.recv(1024).decode("utf-8").strip()
            cmd = data.lower().lstrip("-")
            parts = cmd.split()
            base_cmd = parts[0] if parts else ""

            if base_cmd == "toggle":
                self._on_play_pause(None)
                conn.sendall(f"is_playing: {self.is_playing}\n".encode("utf-8"))
            elif base_cmd == "next":
                self._on_next(None)
                conn.sendall(b"OK: next\n")
            elif base_cmd == "prev":
                self._on_prev(None)
                conn.sendall(b"OK: prev\n")
            elif base_cmd == "play":
                if not self.is_playing:
                    self._on_play_pause(None)
                conn.sendall(b"OK: playing\n")
            elif base_cmd == "pause":
                if self.is_playing:
                    self._on_play_pause(None)
                conn.sendall(b"OK: paused\n")
            elif base_cmd in ("quit", "exit", "stop"):
                conn.sendall(b"OK: quit\n")
                conn.close()
                self._save_config()
                self.player.set_state(Gst.State.NULL)
                GLib.idle_add(Gtk.main_quit)
                return True
            elif base_cmd in ("like", "toggle-like"):
                liked = self._toggle_like()
                conn.sendall(f"liked: {liked}\n".encode("utf-8"))
            elif base_cmd == "vol-up":
                self._adjust_volume(0.05)
                conn.sendall(f"volume: {self.volume}\n".encode("utf-8"))
            elif base_cmd == "vol-down":
                self._adjust_volume(-0.05)
                conn.sendall(f"volume: {self.volume}\n".encode("utf-8"))
            elif base_cmd == "volume" and len(parts) > 1:
                try:
                    v = float(parts[1])
                    if v > 1.0:
                        v /= 100.0
                    self.volume = max(0.0, min(1.0, round(v, 2)))
                    self.is_muted = False
                    self.player.set_property("volume", self.volume)
                    self.config["volume"] = self.volume
                    self.config["muted"] = self.is_muted
                    self._updating_vol_slider = True
                    try:
                        self.vol_slider.set_value(self.volume * 100.0)
                    finally:
                        self._updating_vol_slider = False
                    self._update_vol_button()
                    self._debounced_save_config()
                    conn.sendall(f"volume: {self.volume}\n".encode("utf-8"))
                except Exception as e:
                    conn.sendall(f"ERR: {e}\n".encode("utf-8"))
            elif base_cmd == "status":
                self._scan_music()
                if self.playlist and 0 <= self.current_index < len(self.playlist):
                    track_file = self.playlist[self.current_index]
                    track_name = track_file.name
                    track_clean = self._clean_track_title(track_file.stem)
                    track_num = self.current_index + 1
                    is_liked = self._is_current_track_liked()
                else:
                    track_name = "None"
                    track_clean = "No track loaded"
                    track_num = 0
                    is_liked = False

                info = {
                    "is_playing": self.is_playing,
                    "track": track_name,
                    "track_clean": track_clean,
                    "track_num": track_num,
                    "total_tracks": len(self.playlist),
                    "position": self.position_seconds,
                    "duration": self.duration_seconds,
                    "volume": self.volume,
                    "muted": self.is_muted,
                    "liked": is_liked
                }
                conn.sendall((json.dumps(info) + "\n").encode("utf-8"))
            else:
                conn.sendall(b"UNKNOWN_COMMAND\n")
            conn.close()
        except Exception as e:
            print(f"IPC connection error: {e}")
        return True

    def _on_destroy(self, widget):
        self._save_config()
        try:
            if hasattr(self, "ipc_sock") and self.ipc_sock:
                self.ipc_sock.close()
        except Exception:
            pass
        try:
            if hasattr(self, "player") and self.player:
                self.player.set_state(Gst.State.NULL)
        except Exception:
            pass
        Gtk.main_quit()

    def run(self):
        self.window.show_all()
        Gtk.main()


if __name__ == "__main__":
    valid_ipc_cmds = {
        "status", "toggle", "next", "prev", "play", "pause",
        "quit", "exit", "stop", "like", "toggle-like",
        "vol-up", "vol-down", "volume"
    }
    if len(sys.argv) > 1:
        first_arg = sys.argv[1].lstrip("-").lower()
        if sys.argv[1].startswith("-") or first_arg in valid_ipc_cmds:
            cmd = " ".join(sys.argv[1:]).lstrip("-")
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(3.0)
                s.connect(IPC_SOCKET_NAME)
                s.sendall(cmd.encode("utf-8"))
                resp = s.recv(4096)
                print(resp.decode("utf-8").strip())
                sys.exit(0)
            except (socket.error, ConnectionRefusedError, FileNotFoundError):
                print("Music widget is not currently running.")
                sys.exit(1)
            except Exception as e:
                print(f"Error communicating with music widget: {e}")
                sys.exit(1)

    _acquire_single_instance_lock()
    app = MusicPlayerWidget()
    app.run()
