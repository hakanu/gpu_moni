"""
Settings Dialog for GPU Sentry.
Provides organized tabs for General, Monitoring & Network, Taskbar Widget, and Updates.
"""

import webbrowser
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
    QCheckBox, QComboBox, QSpinBox, QPushButton, QFormLayout, QFrame,
    QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt

from core.gpu_types import GpuDevice
from core.settings import get_settings
from core.shortcut import (
    is_autostart_enabled,
    set_autostart,
    is_start_menu_shortcut_installed,
    install_start_menu_shortcut,
    remove_start_menu_shortcut,
)
from core.updater import UpdateManager, get_install_mode
from core.version import APP_VERSION, GITHUB_RELEASES_URL
from ui.theme import Theme
from ui.widgets.wrap_button import WrapButton


class SettingsDialog(QDialog):
    def __init__(
        self,
        devices: List[GpuDevice],
        updater: UpdateManager,
        net_manager=None,
        taskbar_widget=None,
        parent=None,
    ):
        super().__init__(parent)
        self.devices = devices
        self.updater = updater
        self.net_manager = net_manager
        self.taskbar_widget = taskbar_widget
        self.settings = get_settings()
        self._initial_scale = self.settings.data.ui_scale_percent

        self.setWindowTitle("GPU Sentry — Settings")
        self.setMinimumSize(520, 440)
        self.resize(580, 500)
        self._setup_styles()
        self._setup_ui()
        self._connect_updater()

    def _setup_styles(self):
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Theme.BG_WINDOW};
                color: {Theme.TEXT_PRIMARY};
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }}
            QTabWidget::pane {{
                border: 1px solid {Theme.BORDER_DEFAULT};
                background-color: {Theme.BG_CARD};
                border-radius: 8px;
                padding: 8px;
            }}
            QTabBar::tab {{
                background-color: {Theme.BG_PANEL};
                color: {Theme.TEXT_SECONDARY};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 7px 14px;
                margin-right: 4px;
                font-size: 12px;
                font-weight: 600;
            }}
            QTabBar::tab:selected {{
                background-color: {Theme.BG_CARD};
                color: {Theme.NVIDIA_GREEN};
                border-color: {Theme.BORDER_ACCENT};
            }}
            QCheckBox {{
                color: {Theme.TEXT_PRIMARY};
                spacing: 8px;
                font-size: 12px;
            }}
            QSpinBox, QComboBox {{
                background-color: {Theme.BG_SUBTLE};
                color: {Theme.TEXT_PRIMARY};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QLabel {{
                color: {Theme.TEXT_PRIMARY};
                font-size: 12px;
            }}
        """)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_monitoring_tab(), "Monitoring")
        self.tabs.addTab(self._build_alerts_logs_tab(), "Alerts & Logs")
        self.tabs.addTab(self._build_taskbar_tab(), "Taskbar Widget")
        self.tabs.addTab(self._build_updates_tab(), "Updates")
        root.addWidget(self.tabs, stretch=1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = WrapButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_save = WrapButton("Save & Apply")
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.NVIDIA_GREEN}22;
                color: {Theme.NVIDIA_GREEN};
                border: 1px solid {Theme.NVIDIA_GREEN};
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {Theme.NVIDIA_GREEN}38;
            }}
        """)
        self.btn_save.clicked.connect(self._save_and_accept)
        btn_row.addWidget(self.btn_save)
        root.addLayout(btn_row)

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        form.setContentsMargins(12, 12, 12, 12)
        sd = self.settings.data

        self.chk_autostart = QCheckBox("Launch GPU Sentry on system login")
        self.chk_autostart.setChecked(is_autostart_enabled())
        form.addRow("Startup:", self.chk_autostart)

        self.chk_autostart_min = QCheckBox("Start minimized to tray on system login")
        self.chk_autostart_min.setChecked(sd.autostart_minimized)
        form.addRow("", self.chk_autostart_min)

        self.chk_start_min = QCheckBox("Always start minimized to tray")
        self.chk_start_min.setChecked(sd.start_minimized)
        form.addRow("", self.chk_start_min)

        self.chk_start_menu = QCheckBox("Install Start Menu / Applications shortcut")
        self.chk_start_menu.setChecked(is_start_menu_shortcut_installed())
        form.addRow("Shortcut:", self.chk_start_menu)

        self.chk_close_tray = QCheckBox("Minimize to system tray when closing window")
        self.chk_close_tray.setChecked(sd.close_to_tray)
        form.addRow("Close Button:", self.chk_close_tray)

        self.chk_remember_geo = QCheckBox("Remember window size & position across launches")
        self.chk_remember_geo.setChecked(sd.remember_window_geometry)
        form.addRow("Window:", self.chk_remember_geo)

        self.cb_scale = QComboBox()
        for pct in (85, 90, 100, 110, 125, 150):
            label = f"{pct}% (Default)" if pct == 100 else f"{pct}%"
            self.cb_scale.addItem(label, pct)
        idx = self.cb_scale.findData(sd.ui_scale_percent)
        self.cb_scale.setCurrentIndex(idx if idx >= 0 else 2)
        form.addRow("UI Scale:", self.cb_scale)

        lbl_scale_hint = QLabel("UI scale changes take effect after restarting GPU Sentry.")
        lbl_scale_hint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        form.addRow("", lbl_scale_hint)

        self.cb_temp_unit = QComboBox()
        self.cb_temp_unit.addItem("Celsius (°C)", "C")
        self.cb_temp_unit.addItem("Fahrenheit (°F)", "F")
        t_idx = self.cb_temp_unit.findData(sd.temp_unit)
        self.cb_temp_unit.setCurrentIndex(t_idx if t_idx >= 0 else 0)
        form.addRow("Temperature:", self.cb_temp_unit)

        return w

    def _build_monitoring_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        form.setContentsMargins(12, 12, 12, 12)
        sd = self.settings.data

        self.cb_interval = QComboBox()
        for label, ms in (("500 ms (Fast)", 500), ("1.0 s (Default)", 1000), ("2.0 s", 2000), ("3.0 s", 3000), ("5.0 s (Low CPU)", 5000)):
            self.cb_interval.addItem(label, ms)
        idx = self.cb_interval.findData(sd.poll_interval_ms)
        self.cb_interval.setCurrentIndex(idx if idx >= 0 else 1)
        form.addRow("Poll Interval:", self.cb_interval)

        self.chk_local_agent = QCheckBox("Enable local LAN telemetry HTTP server")
        self.chk_local_agent.setChecked(sd.local_agent_enabled)
        form.addRow("LAN Agent:", self.chk_local_agent)

        self.sp_agent_port = QSpinBox()
        self.sp_agent_port.setRange(1024, 65535)
        self.sp_agent_port.setValue(sd.local_agent_port)
        form.addRow("Agent Port:", self.sp_agent_port)

        self.chk_auto_scan = QCheckBox("Auto-scan LAN & Tailnet on startup")
        self.chk_auto_scan.setChecked(sd.auto_scan_network)
        form.addRow("Discovery:", self.chk_auto_scan)

        self.chk_pin_remote = QCheckBox("Show remote network GPUs as full dashboard cards")
        pin_val = self.net_manager.pin_remote_cards if self.net_manager else True
        self.chk_pin_remote.setChecked(pin_val)
        form.addRow("Remote GPUs:", self.chk_pin_remote)

        return w

    def _build_alerts_logs_tab(self) -> QWidget:
        import os
        from core.telemetry_logger import DEFAULT_LOG_DIR

        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        form.setContentsMargins(12, 12, 12, 12)
        sd = self.settings.data

        self.chk_alerts = QCheckBox("Enable desktop notifications for GPU alerts")
        self.chk_alerts.setChecked(sd.alerts_enabled)
        form.addRow("Alerts:", self.chk_alerts)

        self.sp_alert_temp = QSpinBox()
        self.sp_alert_temp.setRange(50, 110)
        self.sp_alert_temp.setSuffix(" °C")
        self.sp_alert_temp.setValue(int(sd.alert_temp_c))
        form.addRow("High Temp Alert:", self.sp_alert_temp)

        self.sp_alert_vram = QSpinBox()
        self.sp_alert_vram.setRange(50, 100)
        self.sp_alert_vram.setSuffix(" %")
        self.sp_alert_vram.setValue(int(sd.alert_vram_pct))
        form.addRow("High VRAM Alert:", self.sp_alert_vram)

        self.chk_alert_offline = QCheckBox("Notify when a remote Tailnet / LAN GPU node goes offline")
        self.chk_alert_offline.setChecked(sd.alert_node_offline)
        form.addRow("Node Offline:", self.chk_alert_offline)

        self.chk_logging = QCheckBox("Record live telemetry snapshots to disk")
        self.chk_logging.setChecked(sd.logging_enabled)
        form.addRow("Telemetry Log:", self.chk_logging)

        self.cb_log_fmt = QComboBox()
        self.cb_log_fmt.addItem("CSV (Excel / Pandas friendly)", "csv")
        self.cb_log_fmt.addItem("JSONL (Structured per-tick)", "jsonl")
        f_idx = self.cb_log_fmt.findData(sd.logging_format)
        self.cb_log_fmt.setCurrentIndex(f_idx if f_idx >= 0 else 0)
        form.addRow("Log Format:", self.cb_log_fmt)

        log_dir = (sd.logging_dir or "").strip() or DEFAULT_LOG_DIR
        btn_open_logs = WrapButton("📂 Open Logs Folder")
        btn_open_logs.setToolTip(log_dir)
        btn_open_logs.clicked.connect(lambda: (os.makedirs(log_dir, exist_ok=True), webbrowser.open(log_dir)))
        form.addRow("Log Folder:", btn_open_logs)

        return w

    def _build_taskbar_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        form.setContentsMargins(12, 12, 12, 12)
        sd = self.settings.data

        self.chk_tb_visible = QCheckBox("Show floating taskbar telemetry widget")
        self.chk_tb_visible.setChecked(sd.taskbar_visible)
        form.addRow("Visibility:", self.chk_tb_visible)

        self.cb_tb_mode = QComboBox()
        modes = [
            ("Compact (2 Rows)", "compact_2line"),
            ("Slim (1 Row)", "slim_1line"),
            ("Micro Load Bars", "micro_bars"),
            ("Multi-GPU Strip", "multi_gpu"),
        ]
        for label, key in modes:
            self.cb_tb_mode.addItem(label, key)
        idx = self.cb_tb_mode.findData(sd.taskbar_mode)
        self.cb_tb_mode.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Layout:", self.cb_tb_mode)

        self.cb_tb_gpu = QComboBox()
        self.cb_tb_gpu.addItem("Auto (Highest Load / Temp)", "auto")
        for dev in self.devices:
            self.cb_tb_gpu.addItem(dev.name, dev.device_id)
        g_idx = self.cb_tb_gpu.findData(sd.taskbar_gpu)
        self.cb_tb_gpu.setCurrentIndex(g_idx if g_idx >= 0 else 0)
        form.addRow("Monitored GPU:", self.cb_tb_gpu)

        self.cb_tb_sec = QComboBox()
        for label, key in (("GPU Power (Watts)", "power"), ("VRAM Used (GB)", "vram_gb"), ("VRAM Used (%)", "vram_pct")):
            self.cb_tb_sec.addItem(label, key)
        s_idx = self.cb_tb_sec.findData(sd.taskbar_sec_metric)
        self.cb_tb_sec.setCurrentIndex(s_idx if s_idx >= 0 else 0)
        form.addRow("Secondary Metric:", self.cb_tb_sec)

        self.cb_tb_opacity = QComboBox()
        for label, val in (("Glass (88% Dark Acrylic)", 88), ("Solid Dark (100%)", 100), ("Subtle Tint (60%)", 60), ("Transparent (10%)", 10)):
            self.cb_tb_opacity.addItem(label, val)
        o_idx = self.cb_tb_opacity.findData(sd.taskbar_opacity)
        self.cb_tb_opacity.setCurrentIndex(o_idx if o_idx >= 0 else 0)
        form.addRow("Opacity:", self.cb_tb_opacity)

        self.chk_tb_locked = QCheckBox("Lock widget position")
        self.chk_tb_locked.setChecked(sd.taskbar_locked)
        form.addRow("Position:", self.chk_tb_locked)

        self.chk_tb_topmost = QCheckBox("Keep taskbar widget always on top")
        self.chk_tb_topmost.setChecked(sd.taskbar_topmost)
        form.addRow("Z-Order:", self.chk_tb_topmost)

        if self.taskbar_widget:
            btn_dock = WrapButton("📌 Dock Next to Clock Now")
            btn_dock.clicked.connect(self.taskbar_widget.dock_to_clock)
            form.addRow("", btn_dock)

        return w

    def _build_updates_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        sd = self.settings.data

        mode_map = {
            "frozen_win": "Standalone Windows GUI App",
            "uv_tool": "uv Tool Package",
            "python": "Python Environment",
        }
        mode_lbl = mode_map.get(get_install_mode(), "Python Environment")

        info_box = QFrame()
        info_box.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.BG_PANEL};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        il = QVBoxLayout(info_box)
        il.setSpacing(4)
        lbl_ver = QLabel(f"Installed Version: <b>v{APP_VERSION}</b>")
        lbl_ver.setStyleSheet("font-size: 13px; border: none;")
        lbl_mode = QLabel(f"Install Type: {mode_lbl}")
        lbl_mode.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px; border: none;")
        il.addWidget(lbl_ver)
        il.addWidget(lbl_mode)
        layout.addWidget(info_box)

        self.chk_auto_check = QCheckBox("Automatically check GitHub Releases on startup")
        self.chk_auto_check.setChecked(sd.auto_check_updates)
        layout.addWidget(self.chk_auto_check)

        self.chk_auto_install = QCheckBox("Automatically download and install new releases")
        self.chk_auto_install.setChecked(sd.auto_install_updates)
        layout.addWidget(self.chk_auto_install)

        self.lbl_upd_status = QLabel("Ready to check for updates.")
        self.lbl_upd_status.setWordWrap(True)
        self.lbl_upd_status.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self.lbl_upd_status)

        self.pb_update = QProgressBar()
        self.pb_update.setRange(0, 100)
        self.pb_update.setFixedHeight(8)
        self.pb_update.setTextVisible(False)
        self.pb_update.setVisible(False)
        layout.addWidget(self.pb_update)

        act_row = QHBoxLayout()
        self.btn_check_now = WrapButton("🔄 Check for Updates Now")
        self.btn_check_now.clicked.connect(lambda: self.updater.check_for_updates(silent=False, auto_install=False))
        act_row.addWidget(self.btn_check_now)

        self.btn_install_now = WrapButton("⬇ Download & Install")
        self.btn_install_now.setVisible(self.updater.latest_release is not None)
        self.btn_install_now.clicked.connect(self._on_install_clicked)
        act_row.addWidget(self.btn_install_now)

        self.btn_open_releases = WrapButton("🌐 GitHub Releases")
        self.btn_open_releases.clicked.connect(lambda: webbrowser.open(GITHUB_RELEASES_URL))
        act_row.addWidget(self.btn_open_releases)
        layout.addLayout(act_row)

        layout.addStretch()
        return w

    def _connect_updater(self):
        self.updater.status_changed.connect(self._on_upd_status)
        self.updater.download_progress.connect(self._on_upd_progress)
        self.updater.update_available.connect(self._on_upd_available)
        self.updater.update_error.connect(self._on_upd_error)

    def _on_upd_status(self, msg: str):
        self.lbl_upd_status.setText(msg)

    def _on_upd_progress(self, pct: int):
        self.pb_update.setVisible(True)
        self.pb_update.setValue(pct)

    def _on_upd_available(self, rel):
        self.btn_install_now.setText(f"⬇ Install v{rel.version}")
        self.btn_install_now.setVisible(True)

    def _on_upd_error(self, err: str):
        self.lbl_upd_status.setText(err)
        self.pb_update.setVisible(False)

    def _on_install_clicked(self):
        self.btn_install_now.setEnabled(False)
        self.pb_update.setVisible(True)
        self.pb_update.setValue(5)
        self.updater.install_update()

    def _save_and_accept(self):
        new_scale = int(self.cb_scale.currentData())

        self.settings.update(
            start_minimized=self.chk_start_min.isChecked(),
            autostart_minimized=self.chk_autostart_min.isChecked(),
            close_to_tray=self.chk_close_tray.isChecked(),
            remember_window_geometry=self.chk_remember_geo.isChecked(),
            ui_scale_percent=new_scale,
            temp_unit=str(self.cb_temp_unit.currentData()),
            poll_interval_ms=int(self.cb_interval.currentData()),
            local_agent_enabled=self.chk_local_agent.isChecked(),
            local_agent_port=int(self.sp_agent_port.value()),
            auto_scan_network=self.chk_auto_scan.isChecked(),
            taskbar_visible=self.chk_tb_visible.isChecked(),
            taskbar_mode=str(self.cb_tb_mode.currentData()),
            taskbar_gpu=str(self.cb_tb_gpu.currentData()),
            taskbar_sec_metric=str(self.cb_tb_sec.currentData()),
            taskbar_opacity=int(self.cb_tb_opacity.currentData()),
            taskbar_locked=self.chk_tb_locked.isChecked(),
            taskbar_topmost=self.chk_tb_topmost.isChecked(),
            auto_check_updates=self.chk_auto_check.isChecked(),
            auto_install_updates=self.chk_auto_install.isChecked(),
            alerts_enabled=self.chk_alerts.isChecked(),
            alert_temp_c=int(self.sp_alert_temp.value()),
            alert_vram_pct=int(self.sp_alert_vram.value()),
            alert_node_offline=self.chk_alert_offline.isChecked(),
            logging_enabled=self.chk_logging.isChecked(),
            logging_format=str(self.cb_log_fmt.currentData()),
            notify=True,
        )

        # Apply OS-level startup & shortcut toggles
        set_autostart(self.chk_autostart.isChecked(), start_minimized=self.chk_autostart_min.isChecked())

        want_shortcut = self.chk_start_menu.isChecked()
        has_shortcut = is_start_menu_shortcut_installed()
        if want_shortcut and not has_shortcut:
            install_start_menu_shortcut()
        elif not want_shortcut and has_shortcut:
            remove_start_menu_shortcut()

        if self.net_manager is not None:
            self.net_manager.set_pin_remote_cards(self.chk_pin_remote.isChecked())

        if new_scale != self._initial_scale:
            QMessageBox.information(
                self,
                "Restart Required for UI Scale",
                f"UI scale was set to {new_scale}%. Please restart GPU Sentry for the new scale to take effect.",
            )

        self.accept()
