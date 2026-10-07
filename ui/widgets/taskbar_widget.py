"""
Taskbar Widget for GPU Sentry.
Sleek, lightweight, floating/dockable Windows taskbar widget positioned near the clock.
Provides real-time telemetry for CPU, GPU(s), RAM, and Power with customizable layouts.
"""

import sys
import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QMenu, QApplication
)
from PyQt6.QtCore import (
    Qt, QPoint, QRectF, pyqtSignal, QSettings, QTimer
)
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QCursor, QAction, QActionGroup, QLinearGradient
)

from core.gpu_types import GpuDevice, GpuMetrics, HostMetrics
from ui.theme import Theme


def apply_win32_tool_window_styles(hwnd: int):
    """
    Applies Windows extended window styles:
    - WS_EX_TOOLWINDOW (0x80): Hides window from taskbar icons and Alt+Tab.
    - WS_EX_NOACTIVATE (0x08000000): Clicking does not steal focus from active applications/games.
    """
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000

        get_fn = user32.GetWindowLongPtrW if hasattr(user32, "GetWindowLongPtrW") else user32.GetWindowLongW
        set_fn = user32.SetWindowLongPtrW if hasattr(user32, "SetWindowLongPtrW") else user32.SetWindowLongW

        current = get_fn(hwnd, GWL_EXSTYLE)
        set_fn(hwnd, GWL_EXSTYLE, current | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    except Exception:
        pass


class TaskbarWidget(QWidget):
    """
    Compact hardware monitor widget designed to sit on the Windows taskbar next to the clock.
    Supports auto-docking next to the notification area/clock, drag repositioning,
    multiple display layouts, and customizable metric columns.
    """
    visibility_changed = pyqtSignal(bool)
    request_show_dashboard = pyqtSignal()
    request_exit_app = pyqtSignal()

    # Layout modes
    MODE_COMPACT_2LINE = "compact_2line"
    MODE_SLIM_1LINE = "slim_1line"
    MODE_MULTI_GPU = "multi_gpu"
    MODE_MICRO_BARS = "micro_bars"

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        # Settings
        self.settings = QSettings("Antigravity", "GPUSentry")
        self.display_mode = self.settings.value("taskbar_mode", self.MODE_COMPACT_2LINE, type=str)
        self.selected_gpu_id = self.settings.value("taskbar_gpu", "auto", type=str)
        self.secondary_metric = self.settings.value("taskbar_sec_metric", "power", type=str)
        self.is_locked = self.settings.value("taskbar_locked", False, type=bool)
        self.always_on_top = self.settings.value("taskbar_topmost", True, type=bool)
        self.bg_opacity = self.settings.value("taskbar_opacity", 88, type=int)

        # Telemetry State
        self.devices: List[GpuDevice] = []
        self.metrics_by_id: Dict[str, GpuMetrics] = {}
        self.host_metrics: Optional[HostMetrics] = None
        self.summary: Dict = {}

        # Drag & interaction state
        self._dragging = False
        self._drag_start_pos = QPoint()
        self._hovered = False

        self._init_window()
        self._update_dimensions()

        # Restore position or dock to clock
        saved_x = self.settings.value("taskbar_x", None)
        saved_y = self.settings.value("taskbar_y", None)
        if saved_x is not None and saved_y is not None:
            self.move(int(saved_x), int(saved_y))
        else:
            QTimer.singleShot(200, self.dock_to_clock)

    def _init_window(self):
        # Window flags: Tool window, frameless, stay on top
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setWindowTitle("GPU Sentry - Taskbar Widget")

        # Win32 extended styles
        self.show()
        try:
            apply_win32_tool_window_styles(int(self.winId()))
        except Exception:
            pass

    def _update_dimensions(self):
        """Sets dimensions based on the active layout mode."""
        if self.display_mode == self.MODE_SLIM_1LINE:
            self.resize(300, 30)
        elif self.display_mode == self.MODE_MICRO_BARS:
            self.resize(248, 38)
        elif self.display_mode == self.MODE_MULTI_GPU:
            gpu_count = max(1, len(self.devices))
            w = max(260, 120 + gpu_count * 75)
            self.resize(w, 38)
        else:  # compact_2line
            self.resize(238, 38)
        self.update()

    def set_devices(self, devices: List[GpuDevice]):
        self.devices = devices
        if self.display_mode == self.MODE_MULTI_GPU:
            self._update_dimensions()
        self.update()

    def update_telemetry(self, host: Optional[HostMetrics], metrics: Dict[str, GpuMetrics], summary: Dict):
        self.host_metrics = host
        self.metrics_by_id = metrics
        self.summary = summary
        self._update_tooltip()
        self.update()

    def _update_tooltip(self):
        lines = ["<b>GPU Sentry Taskbar Widget</b>"]
        if self.host_metrics:
            c = self.host_metrics.cpu
            r = self.host_metrics.ram
            lines.append(f"CPU: {c.load_percent:.0f}% • {c.temp_core_c:.0f}°C ({c.freq_mhz:.0f} MHz)")
            lines.append(f"RAM: {r.load_percent:.0f}% • {r.used_gb:.1f} / {r.total_gb:.1f} GB")

        for dev in self.devices:
            m = self.metrics_by_id.get(dev.device_id)
            if m:
                used_gb = m.vram_used_mb / 1024.0
                tot_gb = (m.vram_total_mb if m.vram_total_mb > 0 else dev.vram_total_mb) / 1024.0
                lines.append(f"{dev.name}: {m.gpu_util_percent:.0f}% • {m.temp_core_c:.0f}°C • {m.power_draw_w:.0f}W • {used_gb:.1f}/{tot_gb:.1f}GB")

        lines.append("<hr>")
        lines.append("<small style='color:#8b949e;'>Double-click: Open Dashboard | Drag: Reposition | Right-click: Menu</small>")
        self.setToolTip("<br>".join(lines))

    def _get_active_gpu_data(self) -> tuple[str, float, float, float, float, str]:
        """
        Returns (short_name, util_pct, temp_c, power_w, vram_used_gb, vendor).
        Resolves 'auto' or specific GPU selection.
        """
        if not self.devices:
            return ("GPU", 0.0, 0.0, 0.0, 0.0, "NVIDIA")

        target_dev = None
        if self.selected_gpu_id != "auto":
            for d in self.devices:
                if d.device_id == self.selected_gpu_id:
                    target_dev = d
                    break

        # Auto selection: choose GPU with highest load or highest temperature
        if target_dev is None:
            best_score = -1.0
            target_dev = self.devices[0]
            for d in self.devices:
                m = self.metrics_by_id.get(d.device_id)
                if m:
                    score = m.gpu_util_percent * 1.5 + m.temp_core_c
                    if score > best_score:
                        best_score = score
                        target_dev = d

        m = self.metrics_by_id.get(target_dev.device_id, GpuMetrics())
        short_name = target_dev.name.replace("NVIDIA GeForce ", "").replace("AMD Radeon(TM) ", "").replace("Intel(R) ", "").strip()
        if len(short_name) > 12:
            short_name = short_name[:12]
        vram_gb = m.vram_used_mb / 1024.0
        return (short_name, m.gpu_util_percent, m.temp_core_c, m.power_draw_w, vram_gb, target_dev.vendor)

    def dock_to_clock(self):
        """
        Automatically docks the widget immediately to the left of the Windows Taskbar clock / notification area.
        Handles multi-monitor configurations, DPI scaling, and fallback geometries.
        """
        user32 = ctypes.windll.user32 if sys.platform == "win32" else None

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        dock_x, dock_y = None, None

        if user32:
            try:
                tray_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
                if tray_hwnd:
                    r_tray = RECT()
                    user32.GetWindowRect(tray_hwnd, ctypes.byref(r_tray))
                    tray_h = r_tray.bottom - r_tray.top
                    dock_y = r_tray.top + max(0, (tray_h - self.height()) // 2)

                    notify_hwnd = user32.FindWindowExW(tray_hwnd, None, "TrayNotifyWnd", None)
                    r_notify = RECT()
                    if notify_hwnd and user32.GetWindowRect(notify_hwnd, ctypes.byref(r_notify)):
                        # Place directly to the left of notification area
                        dock_x = r_notify.left - self.width() - 8
                    else:
                        dock_x = r_tray.right - 450 - self.width()
            except Exception:
                pass

        # Fallback to Qt Screen geometry
        if dock_x is None or dock_y is None:
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.geometry()
                ag = screen.availableGeometry()
                if ag.top() > sg.top():  # Top taskbar
                    taskbar_h = ag.top() - sg.top()
                    dock_y = sg.top() + max(0, (taskbar_h - self.height()) // 2)
                else:  # Bottom taskbar
                    taskbar_h = max(40, sg.bottom() - ag.bottom())
                    dock_y = ag.bottom() + max(0, (taskbar_h - self.height()) // 2)
                dock_x = ag.right() - 480 - self.width()

        if dock_x is not None and dock_y is not None:
            # Constrain to visible screen bounds
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.geometry()
                dock_x = max(sg.left() + 10, min(dock_x, sg.right() - self.width() - 10))
                dock_y = max(sg.top() + 5, min(dock_y, sg.bottom() - self.height() - 2))

            self.move(int(dock_x), int(dock_y))
            self.settings.setValue("taskbar_x", int(dock_x))
            self.settings.setValue("taskbar_y", int(dock_y))

    # Mouse & Drag Events
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.is_locked:
                self._dragging = True
                self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._drag_start_pos

            # Snap to taskbar bottom if close
            screen = QApplication.screenAt(event.globalPosition().toPoint()) or QApplication.primaryScreen()
            if screen:
                sg = screen.geometry()
                ag = screen.availableGeometry()
                ideal_y = ag.bottom() + max(0, (sg.height() - ag.height() - self.height()) // 2)
                if abs(new_pos.y() - ideal_y) < 18:
                    new_pos.setY(ideal_y)

            self.move(new_pos)
            self.settings.setValue("taskbar_x", new_pos.x())
            self.settings.setValue("taskbar_y", new_pos.y())
            event.accept()
        else:
            if not self.is_locked:
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            if not self.is_locked:
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_dashboard()
            event.accept()

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def _open_dashboard(self):
        self.request_show_dashboard.emit()
        if self.main_window:
            self.main_window.showNormal()
            self.main_window.activateWindow()

    # Context Menu
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {Theme.BG_CARD};
                color: {Theme.TEXT_PRIMARY};
                border: 1px solid {Theme.BORDER_ACCENT};
                border-radius: 8px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 6px 24px 6px 12px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {Theme.BG_SUBTLE};
                color: {Theme.NVIDIA_GREEN};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {Theme.BORDER_DEFAULT};
                margin: 4px 6px;
            }}
        """)

        # Action: Open Dashboard
        act_open = menu.addAction("🚀 Open GPU Sentry Dashboard")
        act_open.triggered.connect(self._open_dashboard)

        menu.addSeparator()

        # Action: Dock to Clock
        act_dock = menu.addAction("📌 Dock Next to Clock")
        act_dock.triggered.connect(self.dock_to_clock)

        # Action: Lock Position
        act_lock = menu.addAction("🔒 Lock Position")
        act_lock.setCheckable(True)
        act_lock.setChecked(self.is_locked)
        act_lock.triggered.connect(self._toggle_lock)

        menu.addSeparator()

        # Submenu: Layout Mode
        mode_menu = menu.addMenu("📐 Display Layout")
        mode_group = QActionGroup(self)

        modes = [
            ("Compact (2 Rows)", self.MODE_COMPACT_2LINE),
            ("Slim (1 Row)", self.MODE_SLIM_1LINE),
            ("Micro Load Bars", self.MODE_MICRO_BARS),
            ("Multi-GPU Strip", self.MODE_MULTI_GPU),
        ]
        for label, m_key in modes:
            act = mode_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.display_mode == m_key)
            mode_group.addAction(act)
            act.triggered.connect(lambda checked, k=m_key: self._set_layout_mode(k))

        # Submenu: Monitored GPU
        gpu_menu = menu.addMenu("⚡ Monitored GPU")
        gpu_group = QActionGroup(self)

        act_auto = gpu_menu.addAction("Auto (Highest Load/Temp)")
        act_auto.setCheckable(True)
        act_auto.setChecked(self.selected_gpu_id == "auto")
        gpu_group.addAction(act_auto)
        act_auto.triggered.connect(lambda: self._set_selected_gpu("auto"))

        for dev in self.devices:
            act_dev = gpu_menu.addAction(f"{dev.name}")
            act_dev.setCheckable(True)
            act_dev.setChecked(self.selected_gpu_id == dev.device_id)
            gpu_group.addAction(act_dev)
            act_dev.triggered.connect(lambda checked, d_id=dev.device_id: self._set_selected_gpu(d_id))

        # Submenu: Secondary Metric
        sec_menu = menu.addMenu("📊 Secondary Metric")
        sec_group = QActionGroup(self)
        sec_options = [
            ("GPU Power (Watts)", "power"),
            ("VRAM Used (GB)", "vram_gb"),
            ("VRAM Used (%)", "vram_pct"),
        ]
        for label, s_key in sec_options:
            act = sec_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.secondary_metric == s_key)
            sec_group.addAction(act)
            act.triggered.connect(lambda checked, k=s_key: self._set_secondary_metric(k))

        # Submenu: Opacity
        op_menu = menu.addMenu("🎨 Background Opacity")
        op_group = QActionGroup(self)
        op_options = [
            ("Glass (85% Dark Acrylic)", 88),
            ("Solid Dark (100%)", 100),
            ("Subtle Tint (60%)", 60),
            ("Transparent", 10),
        ]
        for label, val in op_options:
            act = op_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.bg_opacity == val)
            op_group.addAction(act)
            act.triggered.connect(lambda checked, v=val: self._set_opacity(v))

        # Always on top toggle
        act_top = menu.addAction("📌 Always on Top")
        act_top.setCheckable(True)
        act_top.setChecked(self.always_on_top)
        act_top.triggered.connect(self._toggle_always_on_top)

        menu.addSeparator()

        # Hide widget
        act_hide = menu.addAction("✖ Hide Widget")
        act_hide.triggered.connect(self.hide_widget)

        menu.addSeparator()

        # Exit application
        act_exit = menu.addAction("🚪 Exit GPU Sentry")
        act_exit.triggered.connect(self._exit_app)

        menu.exec(event.globalPos())

    def _exit_app(self):
        self.request_exit_app.emit()
        if self.main_window:
            self.main_window._quit_app()
        else:
            QApplication.quit()

    def _toggle_lock(self):
        self.is_locked = not self.is_locked
        self.settings.setValue("taskbar_locked", self.is_locked)
        if self.is_locked:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

    def _set_layout_mode(self, mode: str):
        self.display_mode = mode
        self.settings.setValue("taskbar_mode", mode)
        self._update_dimensions()

    def _set_selected_gpu(self, gpu_id: str):
        self.selected_gpu_id = gpu_id
        self.settings.setValue("taskbar_gpu", gpu_id)
        self.update()

    def _set_secondary_metric(self, metric: str):
        self.secondary_metric = metric
        self.settings.setValue("taskbar_sec_metric", metric)
        self.update()

    def _set_opacity(self, opacity: int):
        self.bg_opacity = opacity
        self.settings.setValue("taskbar_opacity", opacity)
        self.update()

    def _toggle_always_on_top(self):
        self.always_on_top = not self.always_on_top
        self.settings.setValue("taskbar_topmost", self.always_on_top)
        flags = self.windowFlags()
        if self.always_on_top:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()

    def hide_widget(self):
        self.hide()
        self.settings.setValue("taskbar_visible", False)
        self.visibility_changed.emit(False)

    def show_widget(self):
        self.show()
        self.settings.setValue("taskbar_visible", True)
        self.visibility_changed.emit(True)

    # Painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w, h = self.width(), self.height()

        # Background Pill
        alpha = int(255 * (self.bg_opacity / 100.0))
        bg_color = QColor(14, 17, 23, alpha)
        if self._hovered:
            border_pen = QPen(QColor(0, 230, 118, 140), 1)  # Soft green highlight
        else:
            border_pen = QPen(QColor(255, 255, 255, 30), 1)

        painter.setBrush(QBrush(bg_color))
        painter.setPen(border_pen)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)

        # Host values
        cpu_load = self.host_metrics.cpu.load_percent if self.host_metrics else 0.0
        cpu_temp = self.host_metrics.cpu.temp_core_c if self.host_metrics else 0.0
        ram_load = self.host_metrics.ram.load_percent if self.host_metrics else 0.0
        ram_used = self.host_metrics.ram.used_gb if self.host_metrics else 0.0

        # GPU values
        gpu_name, gpu_util, gpu_temp, gpu_pwr, vram_gb, vendor = self._get_active_gpu_data()

        if self.display_mode == self.MODE_SLIM_1LINE:
            self._paint_slim_1line(painter, w, h, cpu_load, cpu_temp, gpu_util, gpu_temp, ram_load, gpu_pwr)
        elif self.display_mode == self.MODE_MICRO_BARS:
            self._paint_micro_bars(painter, w, h, cpu_load, cpu_temp, gpu_util, gpu_temp, ram_load, ram_used, gpu_pwr, vram_gb, vendor)
        elif self.display_mode == self.MODE_MULTI_GPU:
            self._paint_multi_gpu(painter, w, h, cpu_load, cpu_temp, ram_load)
        else:
            self._paint_compact_2line(painter, w, h, cpu_load, cpu_temp, gpu_util, gpu_temp, ram_load, ram_used, gpu_pwr, vram_gb, vendor)

        painter.end()

    def _paint_compact_2line(self, p: QPainter, w: int, h: int, cpu_pct, cpu_t, gpu_pct, gpu_t, ram_pct, ram_gb, gpu_pwr, vram_gb, vendor):
        font_lbl = QFont("Segoe UI", 8)
        font_lbl.setBold(True)
        font_val = QFont("Segoe UI", 9)
        font_val.setBold(True)

        # ── Row 1: CPU & RAM ──
        y1 = 15
        p.setFont(font_lbl)
        p.setPen(QColor(Theme.CYBER_CYAN))
        p.drawText(8, y1, "CPU")

        p.setFont(font_val)
        p.setPen(QColor("#ffffff"))
        p.drawText(36, y1, f"{int(cpu_pct)}%")

        t_col = QColor(Theme.get_temp_color(cpu_t))
        p.setPen(t_col)
        p.drawText(66, y1, f"{int(cpu_t)}°C")

        # Vertical Divider
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(114, 5, 114, 33)

        # RAM
        p.setFont(font_lbl)
        p.setPen(QColor(Theme.TEXT_SECONDARY))
        p.drawText(122, y1, "RAM")

        p.setFont(font_val)
        p.setPen(QColor("#ffffff"))
        p.drawText(152, y1, f"{int(ram_pct)}%")

        p.setFont(font_lbl)
        p.setPen(QColor(Theme.TEXT_SECONDARY))
        p.drawText(184, y1, f"{ram_gb:.1f}G")

        # ── Row 2: GPU & Secondary ──
        y2 = 31
        v_col = QColor(Theme.get_vendor_color(vendor))
        p.setFont(font_lbl)
        p.setPen(v_col)
        p.drawText(8, y2, "GPU")

        p.setFont(font_val)
        p.setPen(QColor("#ffffff"))
        p.drawText(36, y2, f"{int(gpu_pct)}%")

        gt_col = QColor(Theme.get_temp_color(gpu_t))
        p.setPen(gt_col)
        p.drawText(66, y2, f"{int(gpu_t)}°C")

        # Secondary Metric
        if self.secondary_metric == "power":
            p.setFont(font_lbl)
            p.setPen(QColor(Theme.TEMP_WARM))
            p.drawText(122, y2, "PWR")
            p.setFont(font_val)
            p.setPen(QColor(Theme.TEXT_PRIMARY))
            p.drawText(152, y2, f"{int(gpu_pwr)} W")
        elif self.secondary_metric == "vram_gb":
            p.setFont(font_lbl)
            p.setPen(QColor(Theme.TEXT_ACCENT))
            p.drawText(122, y2, "VRAM")
            p.setFont(font_val)
            p.setPen(QColor(Theme.TEXT_PRIMARY))
            p.drawText(154, y2, f"{vram_gb:.1f} GB")
        else:  # vram_pct
            vram_tot = self.summary.get("total_vram_cap_gb", 16.0)
            v_pct = (vram_gb / max(1.0, vram_tot)) * 100.0
            p.setFont(font_lbl)
            p.setPen(QColor(Theme.TEXT_ACCENT))
            p.drawText(122, y2, "VRAM")
            p.setFont(font_val)
            p.setPen(QColor(Theme.TEXT_PRIMARY))
            p.drawText(154, y2, f"{int(v_pct)}%")

    def _paint_slim_1line(self, p: QPainter, w: int, h: int, cpu_pct, cpu_t, gpu_pct, gpu_t, ram_pct, gpu_pwr):
        font_lbl = QFont("Segoe UI", 8)
        font_lbl.setBold(True)
        font_val = QFont("Segoe UI", 9)
        font_val.setBold(True)

        y = 20
        # CPU
        p.setFont(font_lbl)
        p.setPen(QColor(Theme.CYBER_CYAN))
        p.drawText(8, y, "CPU")
        p.setFont(font_val)
        p.setPen(QColor("#ffffff"))
        p.drawText(36, y, f"{int(cpu_pct)}%")
        p.setPen(QColor(Theme.get_temp_color(cpu_t)))
        p.drawText(66, y, f"{int(cpu_t)}°C")

        # Bullet 1
        p.setPen(QColor(255, 255, 255, 60))
        p.drawText(100, y - 1, "•")

        # GPU
        p.setFont(font_lbl)
        p.setPen(QColor(Theme.NVIDIA_GREEN))
        p.drawText(112, y, "GPU")
        p.setFont(font_val)
        p.setPen(QColor("#ffffff"))
        p.drawText(140, y, f"{int(gpu_pct)}%")
        p.setPen(QColor(Theme.get_temp_color(gpu_t)))
        p.drawText(170, y, f"{int(gpu_t)}°C")

        # Bullet 2
        p.setPen(QColor(255, 255, 255, 60))
        p.drawText(204, y - 1, "•")

        # RAM
        p.setFont(font_lbl)
        p.setPen(QColor(Theme.TEXT_SECONDARY))
        p.drawText(216, y, "RAM")
        p.setFont(font_val)
        p.setPen(QColor("#ffffff"))
        p.drawText(246, y, f"{int(ram_pct)}%")

    def _paint_micro_bars(self, p: QPainter, w: int, h: int, cpu_pct, cpu_t, gpu_pct, gpu_t, ram_pct, ram_gb, gpu_pwr, vram_gb, vendor):
        # Draw standard compact top text
        self._paint_compact_2line(p, w, h, cpu_pct, cpu_t, gpu_pct, gpu_t, ram_pct, ram_gb, gpu_pwr, vram_gb, vendor)

        # Micro Load Bar 1: CPU (bottom of row 1 at y=17)
        bar_bg = QColor(255, 255, 255, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bar_bg))
        p.drawRoundedRect(QRectF(8, 17, 98, 2.5), 1.25, 1.25)

        cpu_fill_w = max(2.0, (cpu_pct / 100.0) * 98)
        p.setBrush(QBrush(QColor(Theme.CYBER_CYAN)))
        p.drawRoundedRect(QRectF(8, 17, cpu_fill_w, 2.5), 1.25, 1.25)

        # Micro Load Bar 2: GPU (bottom of row 2 at y=33)
        p.setBrush(QBrush(bar_bg))
        p.drawRoundedRect(QRectF(8, 33, 98, 2.5), 1.25, 1.25)

        v_col = QColor(Theme.get_vendor_color(vendor))
        gpu_fill_w = max(2.0, (gpu_pct / 100.0) * 98)
        p.setBrush(QBrush(v_col))
        p.drawRoundedRect(QRectF(8, 33, gpu_fill_w, 2.5), 1.25, 1.25)

    def _paint_multi_gpu(self, p: QPainter, w: int, h: int, cpu_pct, cpu_t, ram_pct):
        font_lbl = QFont("Segoe UI", 8)
        font_lbl.setBold(True)
        font_val = QFont("Segoe UI", 9)
        font_val.setBold(True)

        # Row 1: CPU and RAM
        y1 = 15
        p.setFont(font_lbl)
        p.setPen(QColor(Theme.CYBER_CYAN))
        p.drawText(8, y1, "CPU")
        p.setFont(font_val)
        p.setPen(QColor("#ffffff"))
        p.drawText(36, y1, f"{int(cpu_pct)}%")
        p.setPen(QColor(Theme.get_temp_color(cpu_t)))
        p.drawText(66, y1, f"{int(cpu_t)}°C")

        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(108, 5, 108, 17)

        p.setFont(font_lbl)
        p.setPen(QColor(Theme.TEXT_SECONDARY))
        p.drawText(116, y1, "RAM")
        p.setFont(font_val)
        p.setPen(QColor("#ffffff"))
        p.drawText(146, y1, f"{int(ram_pct)}%")

        # Row 2: Each GPU
        y2 = 31
        x = 8
        for i, dev in enumerate(self.devices):
            m = self.metrics_by_id.get(dev.device_id, GpuMetrics())
            s_name = f"G{i}"
            v_col = QColor(Theme.get_vendor_color(dev.vendor))

            p.setFont(font_lbl)
            p.setPen(v_col)
            p.drawText(x, y2, s_name)

            p.setFont(font_val)
            p.setPen(QColor("#ffffff"))
            p.drawText(x + 20, y2, f"{int(m.gpu_util_percent)}%")

            t_col = QColor(Theme.get_temp_color(m.temp_core_c))
            p.setPen(t_col)
            p.drawText(x + 48, y2, f"{int(m.temp_core_c)}°")

            x += 78
            if i < len(self.devices) - 1:
                p.setPen(QPen(QColor(255, 255, 255, 25), 1))
                p.drawLine(x - 5, 21, x - 5, 34)
