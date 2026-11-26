"""
Centralized persistent settings manager for GPU Sentry.
Stores typed user preferences in ~/.gpu_sentry_settings.json with automatic
migration of legacy QSettings taskbar keys.
"""

import json
import os
from dataclasses import dataclass, asdict, fields
from typing import Any, Callable, List, Optional


SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".gpu_sentry_settings.json")


@dataclass
class SettingsData:
    # General & Window
    start_minimized: bool = False
    autostart_minimized: bool = True
    close_to_tray: bool = True
    remember_window_geometry: bool = True
    window_x: Optional[int] = None
    window_y: Optional[int] = None
    window_width: Optional[int] = None
    window_height: Optional[int] = None
    window_maximized: bool = False
    ui_scale_percent: int = 100
    temp_unit: str = "C"  # "C" or "F"
    always_on_top: bool = False
    compact_mode: bool = False

    # Monitoring & Network
    poll_interval_ms: int = 1000
    local_agent_enabled: bool = True
    local_agent_port: int = 51920
    auto_scan_network: bool = False

    # Taskbar Widget
    taskbar_visible: bool = True
    taskbar_mode: str = "compact_2line"
    taskbar_gpu: str = "auto"
    taskbar_sec_metric: str = "power"
    taskbar_locked: bool = False
    taskbar_topmost: bool = True
    taskbar_opacity: int = 88
    taskbar_pin_all_desktops: bool = False
    taskbar_x: Optional[int] = None
    taskbar_y: Optional[int] = None

    # Auto-Update (GitHub Releases)
    auto_check_updates: bool = True
    auto_install_updates: bool = True
    skipped_version: str = ""
    last_update_check: float = 0.0


def format_temp(temp_c: float, unit: str = "C", show_unit: bool = True) -> str:
    """Formats a Celsius temperature into °C or °F."""
    if unit.upper() == "F":
        val = temp_c * 9.0 / 5.0 + 32.0
        return f"{int(round(val))}°F" if show_unit else f"{int(round(val))}°"
    return f"{int(round(temp_c))}°C" if show_unit else f"{int(round(temp_c))}°"


class AppSettings:
    """Singleton-friendly settings store with JSON persistence and change listeners."""

    def __init__(self, path: str = SETTINGS_PATH):
        self.path = path
        self.data = SettingsData()
        self._listeners: List[Callable[[], None]] = []
        self.load()

    def load(self):
        loaded_file = False
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    valid = {fld.name for fld in fields(SettingsData)}
                    for k, v in raw.items():
                        if k in valid:
                            setattr(self.data, k, v)
                    loaded_file = True
            except Exception:
                pass

        if not loaded_file:
            self._migrate_legacy_qsettings()
            self.save()

    def _migrate_legacy_qsettings(self):
        """One-time migration from legacy QSettings('Antigravity', 'GPUSentry') taskbar values."""
        try:
            from PyQt6.QtCore import QSettings

            qs = QSettings("Antigravity", "GPUSentry")
            if qs.contains("taskbar_mode"):
                self.data.taskbar_mode = str(qs.value("taskbar_mode", self.data.taskbar_mode))
            if qs.contains("taskbar_gpu"):
                self.data.taskbar_gpu = str(qs.value("taskbar_gpu", self.data.taskbar_gpu))
            if qs.contains("taskbar_sec_metric"):
                self.data.taskbar_sec_metric = str(qs.value("taskbar_sec_metric", self.data.taskbar_sec_metric))
            if qs.contains("taskbar_locked"):
                self.data.taskbar_locked = qs.value("taskbar_locked", False, type=bool)
            if qs.contains("taskbar_topmost"):
                self.data.taskbar_topmost = qs.value("taskbar_topmost", True, type=bool)
            if qs.contains("taskbar_opacity"):
                self.data.taskbar_opacity = qs.value("taskbar_opacity", 88, type=int)
            if qs.contains("taskbar_visible"):
                self.data.taskbar_visible = qs.value("taskbar_visible", True, type=bool)
            tx = qs.value("taskbar_x", None)
            ty = qs.value("taskbar_y", None)
            if tx is not None and ty is not None:
                self.data.taskbar_x = int(tx)
                self.data.taskbar_y = int(ty)
        except Exception:
            pass

    def save(self):
        try:
            parent = os.path.dirname(os.path.abspath(self.path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.data), f, indent=2)
            os.replace(tmp_path, self.path)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self.data, key, default)

    def set(self, key: str, value: Any, save: bool = True, notify: bool = False):
        if hasattr(self.data, key):
            setattr(self.data, key, value)
            if save:
                self.save()
            if notify:
                self.notify_changed()

    def update(self, save: bool = True, notify: bool = True, **kwargs):
        changed = False
        for k, v in kwargs.items():
            if hasattr(self.data, k) and getattr(self.data, k) != v:
                setattr(self.data, k, v)
                changed = True
        if changed:
            if save:
                self.save()
            if notify:
                self.notify_changed()

    def add_listener(self, cb: Callable[[], None]):
        if cb not in self._listeners:
            self._listeners.append(cb)

    def notify_changed(self):
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass


_global_settings: Optional[AppSettings] = None


def get_settings() -> AppSettings:
    global _global_settings
    if _global_settings is None:
        _global_settings = AppSettings()
    return _global_settings
