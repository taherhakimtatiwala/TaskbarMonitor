#!/usr/bin/env python3
"""
TaskbarMonitor - Windows 11 Taskbar System Performance Overlay
A lightweight, borderless, always-on-top system monitor for Windows 11.
Displays live Upload/Download speeds, CPU usage %, and RAM usage %.

Compatible with PyInstaller:
    pyinstaller --onefile --noconsole taskbar_monitor.py
"""

import os
import sys
import json
import time
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, font as tkfont, colorchooser, messagebox
import psutil

# Optional Windows registry support for "Start with Windows"
try:
    import winreg
except ImportError:
    winreg = None


# =====================================================================
# DPI AWARENESS & WINDOWS API HELPERS
# =====================================================================

def enable_dpi_awareness() -> None:
    """Enable Per-Monitor DPI awareness on Windows 10/11 for crisp rendering."""
    if sys.platform == "win32":
        try:
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def get_work_area(root: tk.Tk) -> tuple[int, int, int, int, int, int]:
    """
    Retrieve the Windows usable work area (excluding taskbar) and full screen size.
    Returns (work_left, work_top, work_right, work_bottom, screen_w, screen_h).
    """
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    if sys.platform == "win32":
        try:
            rect = wintypes.RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
            ):
                return (
                    rect.left,
                    rect.top,
                    rect.right,
                    rect.bottom,
                    screen_w,
                    screen_h,
                )
        except Exception:
            pass

    # Fallback assuming standard 48px bottom taskbar on Windows 11
    return (0, 0, screen_w, max(0, screen_h - 48), screen_w, screen_h)


# =====================================================================
# PATH & STARTUP HELPER (PyInstaller & Script Compatible)
# =====================================================================

class PathHelper:
    """Handles application paths and Windows startup integration."""

    APP_NAME = "TaskbarMonitor"
    RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def is_frozen() -> bool:
        """Return True if running as a PyInstaller frozen executable."""
        return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

    @staticmethod
    def get_app_dir() -> str:
        """Return directory containing the executable or script."""
        if PathHelper.is_frozen():
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(__file__))

    @staticmethod
    def get_resource_path(relative_path: str) -> str:
        """Resolve resource path for both script execution and PyInstaller bundle."""
        if PathHelper.is_frozen():
            base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)

    @classmethod
    def get_config_dir(cls) -> str:
        """Return %APPDATA%\\TaskbarMonitor directory, creating it if missing."""
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = os.path.expanduser("~")
        config_dir = os.path.join(appdata, cls.APP_NAME)
        try:
            os.makedirs(config_dir, exist_ok=True)
        except OSError:
            config_dir = cls.get_app_dir()
        return config_dir

    @classmethod
    def get_settings_file(cls) -> str:
        """Return full path to settings.json in %APPDATA%\\TaskbarMonitor\\."""
        return os.path.join(cls.get_config_dir(), "settings.json")

    @classmethod
    def get_startup_command(cls) -> str:
        """Build the command string used to launch TaskbarMonitor at login."""
        if cls.is_frozen():
            return f'"{os.path.abspath(sys.executable)}"'
        python_exe = sys.executable
        # Prefer pythonw.exe when running as script so no console flashes on login
        if python_exe.lower().endswith("python.exe"):
            pythonw = python_exe[:-10] + "pythonw.exe"
            if os.path.exists(pythonw):
                python_exe = pythonw
        script_path = os.path.abspath(__file__)
        return f'"{python_exe}" "{script_path}"'

    @classmethod
    def get_startup_folder_vbs(cls) -> str:
        """Fallback path in Windows Startup folder."""
        appdata = os.environ.get("APPDATA", "")
        startup_dir = os.path.join(
            appdata,
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            "Startup",
        )
        return os.path.join(startup_dir, f"{cls.APP_NAME}.vbs")

    @classmethod
    def is_startup_enabled(cls) -> bool:
        """Check whether TaskbarMonitor is registered to start with Windows."""
        if sys.platform != "win32":
            return False

        # Check HKCU Run key first
        if winreg is not None:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, cls.RUN_KEY_PATH, 0, winreg.KEY_READ
                ) as key:
                    val, _ = winreg.QueryValueEx(key, cls.APP_NAME)
                    if val:
                        return True
            except FileNotFoundError:
                pass
            except OSError:
                pass

        # Check Startup folder fallback
        vbs_path = cls.get_startup_folder_vbs()
        return os.path.exists(vbs_path)

    @classmethod
    def set_startup_enabled(cls, enabled: bool) -> bool:
        """Enable or disable starting with Windows via HKCU Run key (or Startup folder fallback)."""
        if sys.platform != "win32":
            return False

        cmd = cls.get_startup_command()
        if winreg is not None:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    cls.RUN_KEY_PATH,
                    0,
                    winreg.KEY_SET_VALUE,
                ) as key:
                    if enabled:
                        winreg.SetValueEx(
                            key, cls.APP_NAME, 0, winreg.REG_SZ, cmd
                        )
                    else:
                        try:
                            winreg.DeleteValue(key, cls.APP_NAME)
                        except FileNotFoundError:
                            pass
                # Also clean up Startup folder script if disabling
                if not enabled:
                    vbs_path = cls.get_startup_folder_vbs()
                    if os.path.exists(vbs_path):
                        try:
                            os.remove(vbs_path)
                        except OSError:
                            pass
                return True
            except OSError:
                pass

        # Fallback to Startup folder .vbs launcher
        vbs_path = cls.get_startup_folder_vbs()
        try:
            if enabled:
                os.makedirs(os.path.dirname(vbs_path), exist_ok=True)
                escaped_cmd = cmd.replace('"', '""')
                vbs_content = (
                    'Set WshShell = CreateObject("WScript.Shell")\n'
                    f'WshShell.Run "{escaped_cmd}", 0, False\n'
                )
                with open(vbs_path, "w", encoding="utf-8") as f:
                    f.write(vbs_content)
            else:
                if os.path.exists(vbs_path):
                    os.remove(vbs_path)
            return True
        except OSError:
            return False


# =====================================================================
# SETTINGS MANAGER & PRESETS
# =====================================================================

class SettingsManager:
    """Manages configuration loading, validation, presets, and persistence."""

    PRESETS: dict[str, dict] = {
        "Dark": {
            "bg_color": "#1E1F22",
            "text_color": "#F3F4F6",
            "use_metric_colors": True,
            "upload_color": "#38BDF8",
            "download_color": "#34D399",
            "cpu_color": "#FBBF24",
            "ram_color": "#C084FC",
            "opacity": 0.92,
            "font_family": "Segoe UI",
            "font_size": 9,
            "font_bold": True,
            "font_italic": False,
            "corner_radius": 8,
            "padding_x": 10,
            "padding_y": 5,
            "display_mode": "labeled",
            "label_style": "symbols",
        },
        "Light": {
            "bg_color": "#F3F4F6",
            "text_color": "#111827",
            "use_metric_colors": True,
            "upload_color": "#0284C7",
            "download_color": "#059669",
            "cpu_color": "#D97706",
            "ram_color": "#7C3AED",
            "opacity": 0.94,
            "font_family": "Segoe UI",
            "font_size": 9,
            "font_bold": True,
            "font_italic": False,
            "corner_radius": 8,
            "padding_x": 10,
            "padding_y": 5,
            "display_mode": "labeled",
            "label_style": "symbols",
        },
        "Neon": {
            "bg_color": "#090A0F",
            "text_color": "#00F5D4",
            "use_metric_colors": True,
            "upload_color": "#00F5D4",
            "download_color": "#FF2A85",
            "cpu_color": "#FEE440",
            "ram_color": "#9B5DE5",
            "opacity": 0.90,
            "font_family": "Consolas",
            "font_size": 10,
            "font_bold": True,
            "font_italic": False,
            "corner_radius": 10,
            "padding_x": 12,
            "padding_y": 5,
            "display_mode": "labeled",
            "label_style": "symbols",
        },
        "Minimal": {
            "bg_color": "#18181B",
            "text_color": "#E4E4E7",
            "use_metric_colors": False,
            "upload_color": "#E4E4E7",
            "download_color": "#E4E4E7",
            "cpu_color": "#E4E4E7",
            "ram_color": "#E4E4E7",
            "opacity": 0.82,
            "font_family": "Segoe UI",
            "font_size": 9,
            "font_bold": False,
            "font_italic": False,
            "corner_radius": 4,
            "padding_x": 8,
            "padding_y": 3,
            "display_mode": "compact",
            "label_style": "symbols",
        },
    }

    DEFAULT_SETTINGS: dict = {
        "preset": "Dark",
        "font_family": "Segoe UI",
        "font_size": 9,
        "font_bold": True,
        "font_italic": False,
        "text_color": "#F3F4F6",
        "bg_color": "#1E1F22",
        "opacity": 0.92,
        "use_metric_colors": True,
        "upload_color": "#38BDF8",
        "download_color": "#34D399",
        "cpu_color": "#FBBF24",
        "ram_color": "#C084FC",
        "layout": "horizontal",          # "horizontal" or "vertical"
        "show_upload": True,
        "show_download": True,
        "show_cpu": True,
        "show_ram": True,
        "display_mode": "labeled",       # "labeled" or "compact"
        "label_style": "symbols",        # "symbols" (↑ ↓) or "text" (UP DN)
        "update_interval": 1.0,          # seconds
        "corner_radius": 8,              # pixels (0-20)
        "padding_x": 10,                 # pixels (2-30)
        "padding_y": 5,                  # pixels (2-20)
        "item_spacing": 12,              # pixels between metrics
        "locked": False,
        "pos_x": None,
        "pos_y": None,
        "start_with_windows": False,
    }

    def __init__(self) -> None:
        self.file_path = PathHelper.get_settings_file()
        self.data: dict = dict(self.DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        """Load settings from %APPDATA%\\TaskbarMonitor\\settings.json with safe fallback."""
        self.data = dict(self.DEFAULT_SETTINGS)
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    for key, default_val in self.DEFAULT_SETTINGS.items():
                        if key in loaded:
                            self.data[key] = loaded[key]
            except (json.JSONDecodeError, OSError, ValueError):
                # Corrupt or unreadable file: fall back to defaults and overwrite cleanly
                self.save()
        else:
            self.save()

        self._validate()

    def _validate(self) -> None:
        """Sanitize loaded settings so corrupt values never crash the UI."""
        try:
            self.data["font_size"] = max(6, min(32, int(self.data.get("font_size", 9))))
        except (ValueError, TypeError):
            self.data["font_size"] = 9

        try:
            self.data["opacity"] = max(
                0.20, min(1.0, float(self.data.get("opacity", 0.92)))
            )
        except (ValueError, TypeError):
            self.data["opacity"] = 0.92

        try:
            self.data["update_interval"] = max(
                0.25, min(10.0, float(self.data.get("update_interval", 1.0)))
            )
        except (ValueError, TypeError):
            self.data["update_interval"] = 1.0

        try:
            self.data["corner_radius"] = max(
                0, min(20, int(self.data.get("corner_radius", 8)))
            )
        except (ValueError, TypeError):
            self.data["corner_radius"] = 8

        try:
            self.data["padding_x"] = max(2, min(36, int(self.data.get("padding_x", 10))))
            self.data["padding_y"] = max(1, min(24, int(self.data.get("padding_y", 5))))
        except (ValueError, TypeError):
            self.data["padding_x"] = 10
            self.data["padding_y"] = 5

        if self.data.get("layout") not in ("horizontal", "vertical"):
            self.data["layout"] = "horizontal"
        if self.data.get("display_mode") not in ("labeled", "compact"):
            self.data["display_mode"] = "labeled"
        if self.data.get("label_style") not in ("symbols", "text"):
            self.data["label_style"] = "symbols"

        for color_key in (
            "text_color",
            "bg_color",
            "upload_color",
            "download_color",
            "cpu_color",
            "ram_color",
        ):
            val = str(self.data.get(color_key, ""))
            if not (val.startswith("#") and len(val) == 7):
                self.data[color_key] = self.DEFAULT_SETTINGS[color_key]

    def save(self) -> None:
        """Persist current settings to %APPDATA%\\TaskbarMonitor\\settings.json."""
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except OSError:
            pass

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value, save_now: bool = True) -> None:
        self.data[key] = value
        if save_now:
            self.save()

    def apply_preset(self, preset_name: str) -> None:
        """Apply a named visual preset and save."""
        if preset_name in self.PRESETS:
            self.data["preset"] = preset_name
            for k, v in self.PRESETS[preset_name].items():
                self.data[k] = v
            self.save()


# =====================================================================
# SYSTEM STATS COLLECTOR
# =====================================================================

class SystemMonitor:
    """Reads live network speeds, CPU %, and RAM % safely via psutil."""

    def __init__(self) -> None:
        self.last_time: float = time.monotonic()
        self.last_bytes_sent: int = 0
        self.last_bytes_recv: int = 0
        self._init_network_counters()
        # Prime psutil CPU measurement so first call is non-blocking
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    def _init_network_counters(self) -> None:
        """Initialize baseline byte counters safely."""
        try:
            net = psutil.net_io_counters()
            if net is not None:
                self.last_bytes_sent = net.bytes_sent
                self.last_bytes_recv = net.bytes_recv
            else:
                self.last_bytes_sent = 0
                self.last_bytes_recv = 0
        except Exception:
            self.last_bytes_sent = 0
            self.last_bytes_recv = 0
        self.last_time = time.monotonic()

    @staticmethod
    def format_speed(bytes_per_sec: float, compact: bool = False) -> str:
        """
        Format speed in bytes/sec to auto-switching KB/s or MB/s (or GB/s).
        Always uses KB/s as minimum unit for stable taskbar width.
        """
        kb_s = max(0.0, bytes_per_sec) / 1024.0
        unit_suffix = "" if compact else "/s"

        if kb_s < 1024.0:
            if kb_s < 100.0:
                return f"{kb_s:4.1f} KB{unit_suffix}"
            return f"{kb_s:4.0f} KB{unit_suffix}"

        mb_s = kb_s / 1024.0
        if mb_s < 1024.0:
            if mb_s < 100.0:
                return f"{mb_s:4.1f} MB{unit_suffix}"
            return f"{mb_s:4.0f} MB{unit_suffix}"

        gb_s = mb_s / 1024.0
        return f"{gb_s:4.2f} GB{unit_suffix}"

    def poll(self) -> dict[str, float]:
        """
        Return dictionary with:
            upload_bps, download_bps, cpu_percent, ram_percent
        Handles missing network adapters or counter resets gracefully.
        """
        now = time.monotonic()
        elapsed = max(0.001, now - self.last_time)
        self.last_time = now

        upload_bps = 0.0
        download_bps = 0.0

        try:
            net = psutil.net_io_counters()
            if net is not None:
                delta_sent = net.bytes_sent - self.last_bytes_sent
                delta_recv = net.bytes_recv - self.last_bytes_recv

                # Guard against adapter reset or counter wrap-around
                if delta_sent >= 0:
                    upload_bps = delta_sent / elapsed
                if delta_recv >= 0:
                    download_bps = delta_recv / elapsed

                self.last_bytes_sent = net.bytes_sent
                self.last_bytes_recv = net.bytes_recv
        except Exception:
            upload_bps = 0.0
            download_bps = 0.0

        try:
            cpu_pct = float(psutil.cpu_percent(interval=None))
        except Exception:
            cpu_pct = 0.0

        try:
            ram_pct = float(psutil.virtual_memory().percent)
        except Exception:
            ram_pct = 0.0

        return {
            "upload_bps": upload_bps,
            "download_bps": download_bps,
            "cpu_percent": cpu_pct,
            "ram_percent": ram_pct,
        }


# =====================================================================
# SETTINGS WINDOW (Live Customization)
# =====================================================================

class SettingsWindow:
    """Live customization dialog for TaskbarMonitor."""

    def __init__(self, app: "TaskbarMonitorApp") -> None:
        self.app = app
        self.settings = app.settings
        self.win: tk.Toplevel | None = None
        self.color_buttons: dict[str, tk.Button] = {}
        self._building_ui = False

    def show(self) -> None:
        """Open or focus the Settings window."""
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return

        self._building_ui = True
        self.win = tk.Toplevel(self.app.root)
        self.win.title("TaskbarMonitor Settings")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#18181B")

        # Build Tkinter variables bound to current settings
        self.var_preset = tk.StringVar(value=self.settings.get("preset", "Dark"))
        self.var_font_family = tk.StringVar(
            value=self.settings.get("font_family", "Segoe UI")
        )
        self.var_font_size = tk.IntVar(value=self.settings.get("font_size", 9))
        self.var_font_bold = tk.BooleanVar(value=self.settings.get("font_bold", True))
        self.var_font_italic = tk.BooleanVar(
            value=self.settings.get("font_italic", False)
        )
        self.var_opacity = tk.DoubleVar(value=self.settings.get("opacity", 0.92))
        self.var_use_metric_colors = tk.BooleanVar(
            value=self.settings.get("use_metric_colors", True)
        )

        self.var_layout = tk.StringVar(
            value=self.settings.get("layout", "horizontal")
        )
        self.var_display_mode = tk.StringVar(
            value=self.settings.get("display_mode", "labeled")
        )
        self.var_label_style = tk.StringVar(
            value=self.settings.get("label_style", "symbols")
        )

        self.var_show_upload = tk.BooleanVar(
            value=self.settings.get("show_upload", True)
        )
        self.var_show_download = tk.BooleanVar(
            value=self.settings.get("show_download", True)
        )
        self.var_show_cpu = tk.BooleanVar(value=self.settings.get("show_cpu", True))
        self.var_show_ram = tk.BooleanVar(value=self.settings.get("show_ram", True))

        self.var_update_interval = tk.DoubleVar(
            value=self.settings.get("update_interval", 1.0)
        )
        self.var_corner_radius = tk.IntVar(
            value=self.settings.get("corner_radius", 8)
        )
        self.var_padding_x = tk.IntVar(value=self.settings.get("padding_x", 10))
        self.var_padding_y = tk.IntVar(value=self.settings.get("padding_y", 5))
        self.var_locked = tk.BooleanVar(value=self.settings.get("locked", False))
        self.var_startup = tk.BooleanVar(value=PathHelper.is_startup_enabled())

        self._build_layout()
        self._building_ui = False

        # Center settings window on screen
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = max(20, (sw - w) // 2)
        y = max(20, (sh - h) // 2 - 40)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def _build_layout(self) -> None:
        assert self.win is not None

        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg_main = "#18181B"
        bg_card = "#27272A"
        fg_main = "#F4F4F5"
        fg_muted = "#A1A1AA"
        accent = "#38BDF8"

        style.configure("TNotebook", background=bg_main, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=bg_card,
            foreground=fg_muted,
            padding=(12, 6),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", accent)],
            foreground=[("selected", "#090D16")],
        )
        style.configure("Card.TFrame", background=bg_card)
        style.configure(
            "Card.TLabel",
            background=bg_card,
            foreground=fg_main,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Header.TLabel",
            background=bg_card,
            foreground=accent,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Card.TCheckbutton",
            background=bg_card,
            foreground=fg_main,
            font=("Segoe UI", 9),
        )
        style.map(
            "Card.TCheckbutton",
            background=[("active", bg_card)],
            foreground=[("active", fg_main)],
        )
        style.configure(
            "Card.TRadiobutton",
            background=bg_card,
            foreground=fg_main,
            font=("Segoe UI", 9),
        )
        style.map(
            "Card.TRadiobutton",
            background=[("active", bg_card)],
            foreground=[("active", fg_main)],
        )

        outer = tk.Frame(self.win, bg=bg_main, padx=14, pady=12)
        outer.pack(fill="both", expand=True)

        # Top Preset Bar
        preset_frame = tk.Frame(outer, bg=bg_card, padx=10, pady=8)
        preset_frame.pack(fill="x", pady=(0, 10))

        tk.Label(
            preset_frame,
            text="Theme Preset:",
            bg=bg_card,
            fg=fg_main,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(0, 8))

        for preset_name in ("Dark", "Light", "Neon", "Minimal"):
            btn = tk.Button(
                preset_frame,
                text=preset_name,
                bg="#3F3F46",
                fg=fg_main,
                activebackground=accent,
                activeforeground="#090D16",
                relief="flat",
                padx=10,
                pady=3,
                font=("Segoe UI", 9),
                cursor="hand2",
                command=lambda p=preset_name: self._on_preset_selected(p),
            )
            btn.pack(side="left", padx=3)

        # Notebook Tabs
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        tab_appearance = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        tab_colors = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        tab_layout = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        tab_behavior = ttk.Frame(notebook, style="Card.TFrame", padding=12)

        notebook.add(tab_appearance, text="Typography & Shape")
        notebook.add(tab_colors, text="Colors & Opacity")
        notebook.add(tab_layout, text="Layout & Metrics")
        notebook.add(tab_behavior, text="Behavior")

        # --- TAB 1: TYPOGRAPHY & SHAPE ---
        ttk.Label(tab_appearance, text="Font & Style", style="Header.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )

        ttk.Label(tab_appearance, text="Font Family:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=4
        )
        installed_fonts = sorted(set(tkfont.families()))
        font_combo = ttk.Combobox(
            tab_appearance,
            textvariable=self.var_font_family,
            values=installed_fonts,
            state="readonly",
            width=24,
        )
        font_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=4)
        font_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_live())

        ttk.Label(tab_appearance, text="Font Size:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=4
        )
        size_spin = tk.Spinbox(
            tab_appearance,
            from_=6,
            to=28,
            textvariable=self.var_font_size,
            width=8,
            bg="#3F3F46",
            fg=fg_main,
            buttonbackground="#52525B",
            relief="flat",
            command=self._apply_live,
        )
        size_spin.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=4)
        size_spin.bind("<Return>", lambda _e: self._apply_live())
        size_spin.bind("<FocusOut>", lambda _e: self._apply_live())

        style_box = ttk.Frame(tab_appearance, style="Card.TFrame")
        style_box.grid(row=3, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=4)
        ttk.Checkbutton(
            style_box,
            text="Bold",
            variable=self.var_font_bold,
            style="Card.TCheckbutton",
            command=self._apply_live,
        ).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(
            style_box,
            text="Italic",
            variable=self.var_font_italic,
            style="Card.TCheckbutton",
            command=self._apply_live,
        ).pack(side="left")

        ttk.Label(
            tab_appearance, text="Overlay Geometry", style="Header.TLabel"
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 6))

        ttk.Label(tab_appearance, text="Corner Roundness:", style="Card.TLabel").grid(
            row=5, column=0, sticky="w", pady=4
        )
        corner_scale = tk.Scale(
            tab_appearance,
            from_=0,
            to=20,
            orient="horizontal",
            variable=self.var_corner_radius,
            bg=bg_card,
            fg=fg_main,
            highlightthickness=0,
            troughcolor="#3F3F46",
            activebackground=accent,
            length=170,
            command=lambda _v: self._apply_live(),
        )
        corner_scale.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(8, 0))

        ttk.Label(tab_appearance, text="Horizontal Padding:", style="Card.TLabel").grid(
            row=6, column=0, sticky="w", pady=4
        )
        padx_scale = tk.Scale(
            tab_appearance,
            from_=2,
            to=28,
            orient="horizontal",
            variable=self.var_padding_x,
            bg=bg_card,
            fg=fg_main,
            highlightthickness=0,
            troughcolor="#3F3F46",
            activebackground=accent,
            length=170,
            command=lambda _v: self._apply_live(),
        )
        padx_scale.grid(row=6, column=1, columnspan=2, sticky="ew", padx=(8, 0))

        ttk.Label(tab_appearance, text="Vertical Padding:", style="Card.TLabel").grid(
            row=7, column=0, sticky="w", pady=4
        )
        pady_scale = tk.Scale(
            tab_appearance,
            from_=1,
            to=18,
            orient="horizontal",
            variable=self.var_padding_y,
            bg=bg_card,
            fg=fg_main,
            highlightthickness=0,
            troughcolor="#3F3F46",
            activebackground=accent,
            length=170,
            command=lambda _v: self._apply_live(),
        )
        pady_scale.grid(row=7, column=1, columnspan=2, sticky="ew", padx=(8, 0))

        # --- TAB 2: COLORS & OPACITY ---
        ttk.Label(tab_colors, text="Window Colors & Opacity", style="Header.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )

        self._add_color_row(tab_colors, 1, "Background Color:", "bg_color")
        self._add_color_row(tab_colors, 2, "Default Text Color:", "text_color")

        ttk.Label(tab_colors, text="Background Opacity:", style="Card.TLabel").grid(
            row=3, column=0, sticky="w", pady=4
        )
        opacity_scale = tk.Scale(
            tab_colors,
            from_=0.25,
            to=1.0,
            resolution=0.02,
            orient="horizontal",
            variable=self.var_opacity,
            bg=bg_card,
            fg=fg_main,
            highlightthickness=0,
            troughcolor="#3F3F46",
            activebackground=accent,
            length=170,
            command=lambda _v: self._apply_live(),
        )
        opacity_scale.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8, 0))

        ttk.Checkbutton(
            tab_colors,
            text="Use Separate Metric Colors",
            variable=self.var_use_metric_colors,
            style="Card.TCheckbutton",
            command=self._apply_live,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 6))

        self._add_color_row(tab_colors, 5, "Upload Color:", "upload_color")
        self._add_color_row(tab_colors, 6, "Download Color:", "download_color")
        self._add_color_row(tab_colors, 7, "CPU Usage Color:", "cpu_color")
        self._add_color_row(tab_colors, 8, "RAM Usage Color:", "ram_color")

        # --- TAB 3: LAYOUT & METRICS ---
        ttk.Label(tab_layout, text="Orientation", style="Header.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        orient_frame = ttk.Frame(tab_layout, style="Card.TFrame")
        orient_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Radiobutton(
            orient_frame,
            text="Horizontal (Taskbar Strip)",
            value="horizontal",
            variable=self.var_layout,
            style="Card.TRadiobutton",
            command=self._apply_live,
        ).pack(side="left", padx=(0, 14))
        ttk.Radiobutton(
            orient_frame,
            text="Vertical (Stacked)",
            value="vertical",
            variable=self.var_layout,
            style="Card.TRadiobutton",
            command=self._apply_live,
        ).pack(side="left")

        ttk.Label(tab_layout, text="Visible Metrics", style="Header.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 4)
        )
        metrics_frame = ttk.Frame(tab_layout, style="Card.TFrame")
        metrics_frame.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Checkbutton(
            metrics_frame,
            text="Upload Speed",
            variable=self.var_show_upload,
            style="Card.TCheckbutton",
            command=self._apply_live,
        ).grid(row=0, column=0, sticky="w", padx=(0, 18), pady=2)
        ttk.Checkbutton(
            metrics_frame,
            text="Download Speed",
            variable=self.var_show_download,
            style="Card.TCheckbutton",
            command=self._apply_live,
        ).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Checkbutton(
            metrics_frame,
            text="CPU Usage %",
            variable=self.var_show_cpu,
            style="Card.TCheckbutton",
            command=self._apply_live,
        ).grid(row=1, column=0, sticky="w", padx=(0, 18), pady=2)
        ttk.Checkbutton(
            metrics_frame,
            text="RAM Usage %",
            variable=self.var_show_ram,
            style="Card.TCheckbutton",
            command=self._apply_live,
        ).grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(tab_layout, text="Label Formatting", style="Header.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 4)
        )
        mode_frame = ttk.Frame(tab_layout, style="Card.TFrame")
        mode_frame.grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Radiobutton(
            mode_frame,
            text="Labeled Mode",
            value="labeled",
            variable=self.var_display_mode,
            style="Card.TRadiobutton",
            command=self._apply_live,
        ).pack(side="left", padx=(0, 14))
        ttk.Radiobutton(
            mode_frame,
            text="Compact Mode",
            value="compact",
            variable=self.var_display_mode,
            style="Card.TRadiobutton",
            command=self._apply_live,
        ).pack(side="left")

        sym_frame = ttk.Frame(tab_layout, style="Card.TFrame")
        sym_frame.grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(
            sym_frame,
            text="Symbols (↑ ↓ CPU RAM)",
            value="symbols",
            variable=self.var_label_style,
            style="Card.TRadiobutton",
            command=self._apply_live,
        ).pack(side="left", padx=(0, 14))
        ttk.Radiobutton(
            sym_frame,
            text="Text Labels (UP: DN: CPU: RAM:)",
            value="text",
            variable=self.var_label_style,
            style="Card.TRadiobutton",
            command=self._apply_live,
        ).pack(side="left")

        # --- TAB 4: BEHAVIOR ---
        ttk.Label(tab_behavior, text="Refresh & Window Controls", style="Header.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        ttk.Label(
            tab_behavior, text="Update Interval (seconds):", style="Card.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=4)
        interval_scale = tk.Scale(
            tab_behavior,
            from_=0.5,
            to=5.0,
            resolution=0.5,
            orient="horizontal",
            variable=self.var_update_interval,
            bg=bg_card,
            fg=fg_main,
            highlightthickness=0,
            troughcolor="#3F3F46",
            activebackground=accent,
            length=160,
            command=lambda _v: self._apply_live(),
        )
        interval_scale.grid(row=1, column=1, sticky="ew", padx=(8, 0))

        ttk.Checkbutton(
            tab_behavior,
            text="Lock Overlay Position (disable dragging)",
            variable=self.var_locked,
            style="Card.TCheckbutton",
            command=self._apply_live,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 4))

        ttk.Checkbutton(
            tab_behavior,
            text="Start TaskbarMonitor automatically with Windows",
            variable=self.var_startup,
            style="Card.TCheckbutton",
            command=self._on_toggle_startup,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

        btn_row = tk.Frame(tab_behavior, bg=bg_card)
        btn_row.grid(row=4, column=0, columnspan=2, sticky="w", pady=(14, 4))

        tk.Button(
            btn_row,
            text="Reset Overlay Position",
            bg="#3F3F46",
            fg=fg_main,
            activebackground=accent,
            activeforeground="#090D16",
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
            command=self.app.reset_position,
        ).pack(side="left", padx=(0, 8))

        tk.Label(
            tab_behavior,
            text=f"Config: {self.settings.file_path}",
            bg=bg_card,
            fg=fg_muted,
            font=("Segoe UI", 8),
            wraplength=330,
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

        # Bottom Close Button
        bottom_bar = tk.Frame(outer, bg=bg_main, pady=8)
        bottom_bar.pack(fill="x")
        tk.Button(
            bottom_bar,
            text="Done",
            bg=accent,
            fg="#090D16",
            activebackground="#7DD3FC",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            padx=18,
            pady=4,
            cursor="hand2",
            command=self.win.destroy,
        ).pack(side="right")

    def _add_color_row(
        self, parent: ttk.Frame, row: int, label_text: str, setting_key: str
    ) -> None:
        ttk.Label(parent, text=label_text, style="Card.TLabel").grid(
            row=row, column=0, sticky="w", pady=3
        )
        current_color = self.settings.get(setting_key, "#FFFFFF")
        btn = tk.Button(
            parent,
            text=current_color.upper(),
            bg=current_color,
            fg=self._contrasting_text(current_color),
            width=12,
            relief="flat",
            font=("Consolas", 9, "bold"),
            cursor="hand2",
            command=lambda k=setting_key: self._pick_color(k),
        )
        btn.grid(row=row, column=1, sticky="w", padx=(10, 0), pady=3)
        self.color_buttons[setting_key] = btn

    @staticmethod
    def _contrasting_text(hex_color: str) -> str:
        """Return black or white text color for legibility on a color swatch button."""
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            return "#090D16" if luminance > 0.55 else "#F9FAFB"
        except Exception:
            return "#FFFFFF"

    def _pick_color(self, key: str) -> None:
        initial = self.settings.get(key, "#FFFFFF")
        result = colorchooser.askcolor(
            color=initial, title="Select Color", parent=self.win
        )
        if result and result[1]:
            chosen = result[1].upper()
            self.settings.set(key, chosen)
            if key in self.color_buttons and self.color_buttons[key].winfo_exists():
                self.color_buttons[key].configure(
                    text=chosen,
                    bg=chosen,
                    fg=self._contrasting_text(chosen),
                )
            self.app.apply_settings_live()

    def _on_preset_selected(self, preset_name: str) -> None:
        self.settings.apply_preset(preset_name)
        self._building_ui = True
        try:
            self.var_preset.set(preset_name)
            self.var_font_family.set(self.settings.get("font_family", "Segoe UI"))
            self.var_font_size.set(self.settings.get("font_size", 9))
            self.var_font_bold.set(self.settings.get("font_bold", True))
            self.var_font_italic.set(self.settings.get("font_italic", False))
            self.var_opacity.set(self.settings.get("opacity", 0.92))
            self.var_use_metric_colors.set(
                self.settings.get("use_metric_colors", True)
            )
            self.var_corner_radius.set(self.settings.get("corner_radius", 8))
            self.var_padding_x.set(self.settings.get("padding_x", 10))
            self.var_padding_y.set(self.settings.get("padding_y", 5))
            self.var_display_mode.set(self.settings.get("display_mode", "labeled"))
            self.var_label_style.set(self.settings.get("label_style", "symbols"))

            for key, btn in self.color_buttons.items():
                if btn.winfo_exists():
                    c = self.settings.get(key, "#FFFFFF")
                    btn.configure(
                        text=c.upper(),
                        bg=c,
                        fg=self._contrasting_text(c),
                    )
        finally:
            self._building_ui = False
        self.app.apply_settings_live()

    def _on_toggle_startup(self) -> None:
        desired = bool(self.var_startup.get())
        ok = PathHelper.set_startup_enabled(desired)
        if ok:
            self.settings.set("start_with_windows", desired)
        else:
            if sys.platform != "win32":
                messagebox.showinfo(
                    "Windows Only",
                    "Start with Windows is only supported on Windows.",
                    parent=self.win,
                )
            self.var_startup.set(PathHelper.is_startup_enabled())

    def _apply_live(self) -> None:
        if self._building_ui:
            return
        # Ensure at least one metric stays visible
        if not any(
            [
                self.var_show_upload.get(),
                self.var_show_download.get(),
                self.var_show_cpu.get(),
                self.var_show_ram.get(),
            ]
        ):
            self.var_show_cpu.set(True)

        self.settings.data["font_family"] = self.var_font_family.get()
        self.settings.data["font_size"] = int(self.var_font_size.get())
        self.settings.data["font_bold"] = bool(self.var_font_bold.get())
        self.settings.data["font_italic"] = bool(self.var_font_italic.get())
        self.settings.data["opacity"] = float(self.var_opacity.get())
        self.settings.data["use_metric_colors"] = bool(
            self.var_use_metric_colors.get()
        )
        self.settings.data["layout"] = self.var_layout.get()
        self.settings.data["display_mode"] = self.var_display_mode.get()
        self.settings.data["label_style"] = self.var_label_style.get()
        self.settings.data["show_upload"] = bool(self.var_show_upload.get())
        self.settings.data["show_download"] = bool(self.var_show_download.get())
        self.settings.data["show_cpu"] = bool(self.var_show_cpu.get())
        self.settings.data["show_ram"] = bool(self.var_show_ram.get())
        self.settings.data["update_interval"] = float(self.var_update_interval.get())
        self.settings.data["corner_radius"] = int(self.var_corner_radius.get())
        self.settings.data["padding_x"] = int(self.var_padding_x.get())
        self.settings.data["padding_y"] = int(self.var_padding_y.get())
        self.settings.data["locked"] = bool(self.var_locked.get())
        self.settings.save()
        self.app.apply_settings_live()


# =====================================================================
# MAIN TASKBAR OVERLAY APPLICATION
# =====================================================================

class TaskbarMonitorApp:
    """Borderless, always-on-top Windows 11 taskbar system stats overlay."""

    CHROMA_KEY = "#010203"  # Unique color used for transparent rounded corners on Windows

    def __init__(self) -> None:
        enable_dpi_awareness()

        self.root = tk.Tk()
        self.root.title("TaskbarMonitor")
        self.root.withdraw()  # Hide briefly while configuring geometry

        self.settings = SettingsManager()
        self.monitor = SystemMonitor()
        self.settings_window = SettingsWindow(self)

        # Configure borderless, topmost overlay window
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        self._supports_transparent_color = False
        if sys.platform == "win32":
            try:
                self.root.attributes("-transparentcolor", self.CHROMA_KEY)
                self._supports_transparent_color = True
            except tk.TclError:
                self._supports_transparent_color = False

        # Drag state
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._is_dragging = False
        self._update_job: str | None = None
        self._topmost_job: str | None = None

        # Latest stats cache
        self.current_stats = {
            "upload_bps": 0.0,
            "download_bps": 0.0,
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
        }

        # Canvas for smooth rounded-rectangle rendering and crisp text
        self.canvas = tk.Canvas(
            self.root,
            bd=0,
            highlightthickness=0,
            bg=self.CHROMA_KEY
            if self._supports_transparent_color
            else self.settings.get("bg_color", "#1E1F22"),
        )
        self.canvas.pack(fill="both", expand=True)

        # Build right-click context menu
        self._build_context_menu()

        # Bind mouse interactions
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<Button-3>", self._show_context_menu)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.open_settings())

        # Initial render & position
        self.apply_settings_live(reposition_if_needed=True)
        self.root.deiconify()

        # Start loops
        self._tick_stats()
        self._enforce_topmost()

    def _build_context_menu(self) -> None:
        self.context_menu = tk.Menu(
            self.root,
            tearoff=0,
            bg="#1E1F22",
            fg="#F3F4F6",
            activebackground="#38BDF8",
            activeforeground="#090D16",
            font=("Segoe UI", 9),
            bd=1,
            relief="flat",
        )
        self.menu_locked_var = tk.BooleanVar(
            value=bool(self.settings.get("locked", False))
        )
        self.menu_startup_var = tk.BooleanVar(
            value=PathHelper.is_startup_enabled()
        )

        self.context_menu.add_command(
            label="Settings...", command=self.open_settings
        )
        self.context_menu.add_checkbutton(
            label="Lock position",
            variable=self.menu_locked_var,
            command=self._toggle_lock_from_menu,
        )
        self.context_menu.add_command(
            label="Reset position", command=self.reset_position
        )
        self.context_menu.add_separator()
        self.context_menu.add_checkbutton(
            label="Start with Windows",
            variable=self.menu_startup_var,
            command=self._toggle_startup_from_menu,
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Exit", command=self.exit_app)

    def _show_context_menu(self, event: tk.Event) -> None:
        self.menu_locked_var.set(bool(self.settings.get("locked", False)))
        self.menu_startup_var.set(PathHelper.is_startup_enabled())
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _toggle_lock_from_menu(self) -> None:
        locked = bool(self.menu_locked_var.get())
        self.settings.set("locked", locked)
        if (
            self.settings_window.win is not None
            and self.settings_window.win.winfo_exists()
        ):
            self.settings_window.var_locked.set(locked)

    def _toggle_startup_from_menu(self) -> None:
        desired = bool(self.menu_startup_var.get())
        if PathHelper.set_startup_enabled(desired):
            self.settings.set("start_with_windows", desired)
            if (
                self.settings_window.win is not None
                and self.settings_window.win.winfo_exists()
            ):
                self.settings_window.var_startup.set(desired)
        else:
            self.menu_startup_var.set(PathHelper.is_startup_enabled())

    def open_settings(self) -> None:
        self.settings_window.show()

    def _on_drag_start(self, event: tk.Event) -> None:
        if self.settings.get("locked", False):
            return
        self._is_dragging = True
        self._drag_offset_x = event.x
        self._drag_offset_y = event.y

    def _on_drag_motion(self, event: tk.Event) -> None:
        if not self._is_dragging or self.settings.get("locked", False):
            return
        new_x = self.root.winfo_x() + (event.x - self._drag_offset_x)
        new_y = self.root.winfo_y() + (event.y - self._drag_offset_y)
        self.root.geometry(f"+{new_x}+{new_y}")

    def _on_drag_end(self, _event: tk.Event) -> None:
        if not self._is_dragging:
            return
        self._is_dragging = False
        self.settings.set("pos_x", self.root.winfo_x(), save_now=False)
        self.settings.set("pos_y", self.root.winfo_y(), save_now=True)

    def compute_default_position(self, width: int, height: int) -> tuple[int, int]:
        """
        Calculate default bottom-right position just left of the Windows 11 system tray,
        vertically centered inside the taskbar.
        """
        work_left, work_top, work_right, work_bottom, screen_w, screen_h = (
            get_work_area(self.root)
        )

        # Estimate system tray width (~230px on Windows 11)
        tray_offset = 230
        taskbar_height = screen_h - work_bottom

        if taskbar_height >= 24:
            # Taskbar is at the bottom
            x = max(work_left + 8, work_right - width - tray_offset)
            y = work_bottom + max(0, (taskbar_height - height) // 2)
        else:
            # Fallback if taskbar is auto-hidden or non-bottom
            tb_h = 48
            x = max(8, screen_w - width - tray_offset)
            y = screen_h - tb_h + max(0, (tb_h - height) // 2)

        return int(x), int(y)

    def reset_position(self) -> None:
        """Reset overlay position to the default taskbar bottom-right slot."""
        self.root.update_idletasks()
        w = max(60, self.canvas.winfo_reqwidth())
        h = max(24, self.canvas.winfo_reqheight())
        x, y = self.compute_default_position(w, h)
        self.settings.set("pos_x", x, save_now=False)
        self.settings.set("pos_y", y, save_now=True)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def apply_settings_live(self, reposition_if_needed: bool = False) -> None:
        """Apply visual and layout settings immediately and redraw."""
        opacity = float(self.settings.get("opacity", 0.92))
        try:
            self.root.attributes("-alpha", opacity)
        except tk.TclError:
            pass

        self._render_overlay(reposition_if_needed=reposition_if_needed)

    def _build_metric_items(self) -> list[tuple[str, str]]:
        """
        Build list of (formatted_text, color_hex) tuples for enabled metrics.
        """
        s = self.settings
        compact = s.get("display_mode", "labeled") == "compact"
        symbols = s.get("label_style", "symbols") == "symbols"
        use_colors = bool(s.get("use_metric_colors", True))
        default_fg = s.get("text_color", "#F3F4F6")

        up_str = SystemMonitor.format_speed(
            self.current_stats["upload_bps"], compact=compact
        )
        dn_str = SystemMonitor.format_speed(
            self.current_stats["download_bps"], compact=compact
        )
        cpu_val = f"{self.current_stats['cpu_percent']:2.0f}%"
        ram_val = f"{self.current_stats['ram_percent']:2.0f}%"

        items: list[tuple[str, str]] = []

        if s.get("show_upload", True):
            prefix = "↑" if symbols else "UP:"
            sep = "" if compact else " "
            color = s.get("upload_color", default_fg) if use_colors else default_fg
            items.append((f"{prefix}{sep}{up_str}", color))

        if s.get("show_download", True):
            prefix = "↓" if symbols else "DN:"
            sep = "" if compact else " "
            color = s.get("download_color", default_fg) if use_colors else default_fg
            items.append((f"{prefix}{sep}{dn_str}", color))

        if s.get("show_cpu", True):
            if compact:
                text = f"C:{cpu_val}" if not symbols else f"CPU {cpu_val}"
            else:
                prefix = "CPU" if symbols else "CPU:"
                text = f"{prefix} {cpu_val}"
            color = s.get("cpu_color", default_fg) if use_colors else default_fg
            items.append((text, color))

        if s.get("show_ram", True):
            if compact:
                text = f"R:{ram_val}" if not symbols else f"RAM {ram_val}"
            else:
                prefix = "RAM" if symbols else "RAM:"
                text = f"{prefix} {ram_val}"
            color = s.get("ram_color", default_fg) if use_colors else default_fg
            items.append((text, color))

        if not items:
            items.append((f"CPU {cpu_val}", default_fg))

        return items

    @staticmethod
    def _draw_rounded_rect(
        canvas: tk.Canvas,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        fill: str,
        outline: str = "",
    ) -> None:
        """Draw a smooth rounded rectangle on a Tkinter Canvas."""
        r = max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
        if r <= 1:
            canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline)
            return

        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        canvas.create_polygon(points, smooth=True, fill=fill, outline=outline)

    def _render_overlay(self, reposition_if_needed: bool = False) -> None:
        """Measure text, resize canvas, draw rounded background and live stats."""
        s = self.settings
        bg_color = s.get("bg_color", "#1E1F22")
        # Avoid collision with transparent chroma key
        if bg_color.lower() == self.CHROMA_KEY.lower():
            bg_color = "#1E1F22"

        weight = "bold" if s.get("font_bold", True) else "normal"
        slant = "italic" if s.get("font_italic", False) else "roman"
        font_spec = tkfont.Font(
            family=s.get("font_family", "Segoe UI"),
            size=int(s.get("font_size", 9)),
            weight=weight,
            slant=slant,
        )

        items = self._build_metric_items()
        pad_x = int(s.get("padding_x", 10))
        pad_y = int(s.get("padding_y", 5))
        spacing = int(s.get("item_spacing", 12))
        layout = s.get("layout", "horizontal")
        radius = int(s.get("corner_radius", 8))

        line_height = font_spec.metrics("linespace")
        measured_widths = [font_spec.measure(text) for text, _ in items]

        if layout == "vertical":
            content_w = max(measured_widths) if measured_widths else 60
            content_h = line_height * len(items) + max(0, len(items) - 1) * 3
        else:
            content_w = sum(measured_widths) + max(0, len(items) - 1) * spacing
            content_h = line_height

        total_w = max(48, content_w + pad_x * 2)
        total_h = max(20, content_h + pad_y * 2)

        canvas_bg = (
            self.CHROMA_KEY
            if (self._supports_transparent_color and radius > 0)
            else bg_color
        )
        self.canvas.configure(
            width=total_w, height=total_h, bg=canvas_bg
        )
        self.canvas.delete("all")

        # Draw rounded pill/panel background
        self._draw_rounded_rect(
            self.canvas, 0, 0, total_w, total_h, radius=radius, fill=bg_color
        )

        # Draw each metric
        if layout == "vertical":
            curr_y = pad_y
            for text, color in items:
                self.canvas.create_text(
                    pad_x,
                    curr_y,
                    text=text,
                    fill=color,
                    font=font_spec,
                    anchor="nw",
                )
                curr_y += line_height + 3
        else:
            curr_x = pad_x
            center_y = total_h // 2
            for idx, (text, color) in enumerate(items):
                self.canvas.create_text(
                    curr_x,
                    center_y,
                    text=text,
                    fill=color,
                    font=font_spec,
                    anchor="w",
                )
                curr_x += measured_widths[idx] + spacing

        # Determine window position
        pos_x = s.get("pos_x")
        pos_y = s.get("pos_y")
        if pos_x is None or pos_y is None:
            pos_x, pos_y = self.compute_default_position(total_w, total_h)
            s.set("pos_x", pos_x, save_now=False)
            s.set("pos_y", pos_y, save_now=True)
        elif reposition_if_needed:
            # Keep within visible screen bounds on startup
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            pos_x = max(0, min(int(pos_x), sw - total_w))
            pos_y = max(0, min(int(pos_y), sh - total_h))

        self.root.geometry(f"{total_w}x{total_h}+{int(pos_x)}+{int(pos_y)}")

    def _tick_stats(self) -> None:
        """Poll system stats and schedule next update based on configurable interval."""
        if self._update_job is not None:
            try:
                self.root.after_cancel(self._update_job)
            except Exception:
                pass

        self.current_stats = self.monitor.poll()
        self._render_overlay(reposition_if_needed=False)

        interval_ms = max(
            250, int(float(self.settings.get("update_interval", 1.0)) * 1000)
        )
        self._update_job = self.root.after(interval_ms, self._tick_stats)

    def _enforce_topmost(self) -> None:
        """Periodically lift the overlay so the Windows 11 taskbar never obscures it."""
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except tk.TclError:
            pass
        self._topmost_job = self.root.after(1500, self._enforce_topmost)

    def exit_app(self) -> None:
        """Cleanly cancel timers, save settings, and exit."""
        for job in (self._update_job, self._topmost_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self.settings.save()
        self.root.destroy()
        sys.exit(0)

    def run(self) -> None:
        """Start the Tkinter main event loop."""
        self.root.mainloop()


if __name__ == "__main__":
    app = TaskbarMonitorApp()
    app.run()
