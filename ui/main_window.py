"""
Main Dashboard Window for multi-GPU monitoring.
Hosts global summary telemetry, responsive controls, GPU cards, network GPU nodes,
Tailscale ON/OFF toggle, Very Condensed View of Everything, deep hardware specs,
Settings dialog, GitHub Releases auto-updater, and system tray.
"""

import os
import sys
import webbrowser
import psutil
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QScrollArea, QFrame, QSystemTrayIcon,
    QMenu, QApplication, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QAction, QColor, QPainter, QPixmap, QFont

from core.gpu_types import GpuDevice, GpuMetrics, HostMetrics
from core.hardware_info import HardwareInfoCollector
from core.network_telemetry import NetworkTelemetryManager, RemoteNodeState
from core.monitor_worker import MonitorWorker
from core.settings import get_settings, format_temp
from core.alerts import AlertManager
from core.telemetry_logger import SessionPeakTracker, TelemetryLogger
from core.energy_tracker import EnergyTracker
from core.updater import UpdateManager, ReleaseInfo
from core.version import APP_VERSION
from ui.theme import Theme, GLOBAL_STYLESHEET
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.wrap_button import WrapButton
from ui.widgets.gpu_card import GpuCard
from ui.widgets.cpu_ram_card import CpuRamCard
from ui.widgets.hardware_specs_card import HardwareSpecsCard
from ui.widgets.network_nodes_card import NetworkNodesCard
from ui.widgets.condensed_dashboard import CondensedDashboardWidget
from ui.widgets.taskbar_widget import TaskbarWidget
from ui.widgets.settings_dialog import SettingsDialog
from core.shortcut import (
    is_start_menu_shortcut_installed,
    install_start_menu_shortcut,
    remove_start_menu_shortcut,
    is_autostart_enabled,
    set_autostart,
)


class MainWindow(QMainWindow):
    def __init__(self, start_condensed: Optional[bool] = None):
        super().__init__()
        self.app_settings = get_settings()
        sd = self.app_settings.data

        self.setWindowTitle(f"GPU Sentry v{APP_VERSION} - Multi-GPU & Network Hardware Dashboard")
        self.setMinimumSize(560, 380)
        self._restore_initial_geometry()

        # State
        self._is_quitting = False
        self.latest_summary: dict = {}
        self.local_devices: List[GpuDevice] = []
        self.remote_devices: List[GpuDevice] = []
        self.cards_metrics: Dict[str, GpuMetrics] = {}
        self.remote_metrics: Dict[str, GpuMetrics] = {}

        # Hardware Specifications & Cards state
        self.hw_specs = HardwareInfoCollector.collect_all()
        self.cards: Dict[str, GpuCard] = {}
        self.remote_cards: Dict[str, GpuCard] = {}
        self.cpu_ram_card = CpuRamCard()
        self.cpu_ram_card.set_hardware_specs(self.hw_specs)
        self.hw_specs_card = HardwareSpecsCard(specs=self.hw_specs)

        # Network Telemetry Manager & Cards
        self.net_manager = NetworkTelemetryManager(os_name=self.hw_specs.os_info.os_name, parent=self)
        self.net_manager.local_server.port = sd.local_agent_port
        self.net_manager.server_enabled = sd.local_agent_enabled
        self.net_manager.auto_scan_on_start = sd.auto_scan_network
        self.net_manager.nodes_updated.connect(self._on_network_nodes_updated)
        self.net_manager.tailscale_enabled_changed.connect(self._on_tailscale_enabled_changed)
        self.net_manager.tailnet_scan_status.connect(self._on_tailnet_scan_status)
        self.network_card = NetworkNodesCard(self.net_manager)

        # Very Condensed View of Everything Widget
        self.condensed_dashboard = CondensedDashboardWidget(
            hw_specs=self.hw_specs,
            net_manager=self.net_manager,
            parent=self,
        )
        self.condensed_dashboard.request_full_specs.connect(self._jump_to_hardware_specs)
        self.condensed_dashboard.request_manage_network.connect(self._jump_to_network_gpus)

        self.latest_host_metrics: Optional[HostMetrics] = None
        self.is_condensed = self.net_manager.condensed_view if start_condensed is None else bool(start_condensed)
        self.is_compact = bool(sd.compact_mode)
        self.is_paused = False
        self.always_on_top = bool(sd.always_on_top)

        # Alerts, Session Peaks, Energy Burn Tracker & CSV/JSONL Logger
        self.alert_manager = AlertManager()
        self.peak_tracker = SessionPeakTracker()
        self.telemetry_logger = TelemetryLogger()
        self.energy_tracker = EnergyTracker()

        # GitHub Releases Auto-Updater
        self.updater = UpdateManager(parent=self)
        self.updater.update_available.connect(self._on_update_available)
        self.updater.up_to_date.connect(self._on_up_to_date)
        self.updater.update_error.connect(self._on_update_error)
        self.updater.restart_requested.connect(self._quit_app)
        self._pending_release: Optional[ReleaseInfo] = None

        # Taskbar Widget (Docked near Windows Clock)
        self.taskbar_widget = TaskbarWidget(main_window=self)
        self.taskbar_widget.visibility_changed.connect(self._on_widget_visibility_changed)
        self.taskbar_widget.request_show_dashboard.connect(self._show_dashboard)
        self.taskbar_widget.request_exit_app.connect(self._quit_app)

        # Apply global styles
        self.setStyleSheet(GLOBAL_STYLESHEET)

        # Worker initialization
        self.worker = MonitorWorker(interval_ms=sd.poll_interval_ms)
        self.worker.devices_discovered.connect(self._on_devices_discovered)
        self.worker.metrics_updated.connect(self._on_metrics_updated)
        self.worker.host_updated.connect(self._on_host_updated)
        self.worker.summary_updated.connect(self._on_summary_updated)

        self._setup_ui()
        self._setup_tray()

        if self.always_on_top:
            self.btn_pin.setChecked(True)
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            self.btn_pin.setText("📌 Pinned")

        if self.is_condensed:
            self._apply_condensed_mode(True, initial=True)
        elif self.is_compact:
            self.btn_compact.setChecked(True)
            self._apply_compact_state()

        self.app_settings.add_listener(self._on_settings_changed)

        # Start worker and network manager
        self.worker.start()
        self.net_manager.start()

        # Schedule background GitHub Releases update check
        if sd.auto_check_updates:
            QTimer.singleShot(
                4000,
                lambda: self.updater.check_for_updates(
                    silent=True,
                    auto_install=self.app_settings.data.auto_install_updates,
                ),
            )

    def _restore_initial_geometry(self):
        sd = self.app_settings.data
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None

        if avail:
            default_w = min(1060, max(620, avail.width() - 60))
            default_h = min(720, max(440, avail.height() - 60))
        else:
            default_w, default_h = 1020, 680

        if sd.remember_window_geometry and sd.window_width and sd.window_height:
            w = max(560, int(sd.window_width))
            h = max(380, int(sd.window_height))
            if avail:
                w = min(w, avail.width())
                h = min(h, avail.height())
            self.resize(w, h)
            if sd.window_x is not None and sd.window_y is not None:
                x, y = int(sd.window_x), int(sd.window_y)
                visible_on_any = any(
                    scr.availableGeometry().contains(x + 40, y + 20)
                    for scr in QApplication.screens()
                )
                if visible_on_any:
                    self.move(x, y)
        else:
            self.resize(default_w, default_h)

    def _save_window_geometry(self):
        if not self.app_settings.data.remember_window_geometry:
            return
        if self.isMaximized():
            self.app_settings.update(window_maximized=True, notify=False)
        else:
            geo = self.geometry()
            self.app_settings.update(
                window_x=geo.x(),
                window_y=geo.y(),
                window_width=geo.width(),
                window_height=geo.height(),
                window_maximized=False,
                notify=False,
            )

    def _setup_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        self.root_layout = QVBoxLayout(central_widget)
        self.root_layout.setContentsMargins(14, 12, 14, 10)
        self.root_layout.setSpacing(10)

        # 1. Top Navigation Header (Brand Row + Wrapping Controls FlowLayout)
        header_box = QVBoxLayout()
        header_box.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(6)

        self.lbl_live_dot = QLabel("●")
        self.lbl_live_dot.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 14px; font-weight: bold;")
        brand_row.addWidget(self.lbl_live_dot)

        lbl_app_name = QLabel("GPU SENTRY")
        lbl_app_name.setStyleSheet("font-size: 17px; font-weight: 800; letter-spacing: 1px; color: #ffffff;")
        brand_row.addWidget(lbl_app_name)

        self.lbl_sub = QLabel("LOCAL & NETWORK TELEMETRY")
        self.lbl_sub.setStyleSheet(f"font-size: 9px; font-weight: 700; color: {Theme.TEXT_MUTED}; letter-spacing: 0.5px;")
        brand_row.addWidget(self.lbl_sub)

        brand_row.addStretch()

        lbl_refresh = QLabel("Interval:")
        lbl_refresh.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
        brand_row.addWidget(lbl_refresh)

        self.cb_interval = QComboBox()
        self.cb_interval.addItem("500 ms", 500)
        self.cb_interval.addItem("1.0 s", 1000)
        self.cb_interval.addItem("2.0 s", 2000)
        self.cb_interval.addItem("3.0 s", 3000)
        self.cb_interval.addItem("5.0 s", 5000)
        cur_idx = self.cb_interval.findData(self.app_settings.data.poll_interval_ms)
        self.cb_interval.setCurrentIndex(cur_idx if cur_idx >= 0 else 1)
        self.cb_interval.currentIndexChanged.connect(self._change_interval)
        brand_row.addWidget(self.cb_interval)

        header_box.addLayout(brand_row)

        # Wrapping Toolbar Controls (FlowLayout + WrapButton -> zero clipped labels!)
        controls_flow = FlowLayout(margin=0, h_spacing=6, v_spacing=6)

        # Master Tailscale ON / OFF Toggle Button
        self.btn_tailscale = WrapButton()
        self.btn_tailscale.setCheckable(True)
        self.btn_tailscale.setChecked(self.net_manager.tailscale_enabled)
        self.btn_tailscale.setToolTip("Turn Tailscale-based GPU discovery & monitoring ON or OFF")
        self.btn_tailscale.clicked.connect(self._on_toggle_tailscale)
        self._style_top_tailscale_btn(self.net_manager.tailscale_enabled)
        controls_flow.addWidget(self.btn_tailscale)

        # Refresh Tailnet Devices Button
        self.btn_rescan = WrapButton("🔄 Refresh Tailnet")
        self.btn_rescan.setToolTip("Refresh & re-scan all online Tailscale Tailnet peers (Linux, Windows, macOS) & local LAN for GPU machines")
        self.btn_rescan.clicked.connect(self._on_rescan_network)
        controls_flow.addWidget(self.btn_rescan)

        # Very Condensed View of Everything Toggle Button
        self.btn_condensed = WrapButton("⚡ Condensed")
        self.btn_condensed.setCheckable(True)
        self.btn_condensed.setChecked(self.is_condensed)
        self.btn_condensed.setToolTip("Switch to Very Condensed View of Everything (CPU, RAM, Local GPUs, Tailscale GPUs & Processes in one dense view)")
        self.btn_condensed.clicked.connect(self._toggle_condensed)
        controls_flow.addWidget(self.btn_condensed)

        # Compact Card View toggle
        self.btn_compact = WrapButton("🗗 Compact")
        self.btn_compact.setCheckable(True)
        self.btn_compact.setToolTip("Hide sparkline graphs and drawers on GPU/CPU cards")
        self.btn_compact.clicked.connect(self._toggle_compact)
        controls_flow.addWidget(self.btn_compact)

        # Network GPUs Jump button
        self.btn_net_gpus = WrapButton("🌐 Network GPUs")
        self.btn_net_gpus.setToolTip("Jump to LAN & Tailscale Network GPUs Manager")
        self.btn_net_gpus.clicked.connect(self._jump_to_network_gpus)
        controls_flow.addWidget(self.btn_net_gpus)

        # Hardware Specs Jump button
        self.btn_hw_specs = WrapButton("🧬 Specs")
        self.btn_hw_specs.setToolTip("Jump to Deep Hardware Specifications (RAM MHz, Channels, Motherboard, BIOS, CPU, PCIe, NVMe)")
        self.btn_hw_specs.clicked.connect(self._jump_to_hardware_specs)
        controls_flow.addWidget(self.btn_hw_specs)

        # Always On Top toggle
        self.btn_pin = WrapButton("📌 Pin")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip("Keep window always on top")
        self.btn_pin.clicked.connect(self._toggle_always_on_top)
        controls_flow.addWidget(self.btn_pin)

        # Taskbar Widget toggle
        self.btn_taskbar = WrapButton("📊 Widget")
        self.btn_taskbar.setCheckable(True)
        self.btn_taskbar.setChecked(self.taskbar_widget.isVisible())
        self.btn_taskbar.setToolTip("Show/Hide live telemetry widget on taskbar near clock")
        self.btn_taskbar.clicked.connect(self._toggle_taskbar_widget)
        controls_flow.addWidget(self.btn_taskbar)

        # Pause / Resume button
        self.btn_pause = WrapButton("⏸ Pause")
        self.btn_pause.clicked.connect(self._toggle_pause)
        controls_flow.addWidget(self.btn_pause)

        # Settings button
        self.btn_settings = WrapButton("⚙ Settings")
        self.btn_settings.setToolTip("Configure startup, scaling, taskbar widget, monitoring, and GitHub auto-updates")
        self.btn_settings.clicked.connect(self._open_settings)
        controls_flow.addWidget(self.btn_settings)

        header_box.addLayout(controls_flow)
        self.root_layout.addLayout(header_box)

        # 1b. Non-intrusive GitHub Release Update Banner
        self.update_banner = self._create_update_banner()
        self.update_banner.setVisible(False)
        self.root_layout.addWidget(self.update_banner)

        # 2. Global Telemetry Summary Ribbon (FlowLayout so pills wrap cleanly)
        self.summary_ribbon = self._create_summary_ribbon()
        self.root_layout.addWidget(self.summary_ribbon)

        # 3. Scrollable GPU & Hardware Cards Container
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 2, 0, 2)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        self.root_layout.addWidget(self.scroll_area, stretch=1)

        # 4. Footer Status Bar
        footer = QHBoxLayout()
        footer.setSpacing(12)

        self.lbl_footer_status = QLabel("Engine: Initializing...")
        self.lbl_footer_status.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self.lbl_footer_status, stretch=1)

        self.lbl_version = QLabel(f"v{APP_VERSION}")
        self.lbl_version.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        footer.addWidget(self.lbl_version)

        self.lbl_memory_footprint = QLabel("App RAM: -- MB")
        self.lbl_memory_footprint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self.lbl_memory_footprint)

        self.lbl_last_updated = QLabel("Last update: --")
        self.lbl_last_updated.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self.lbl_last_updated)

        self.root_layout.addLayout(footer)

    def _create_update_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("UpdateBanner")
        banner.setStyleSheet(f"""
            QFrame#UpdateBanner {{
                background-color: #10261e;
                border: 1px solid {Theme.NVIDIA_GREEN}88;
                border-radius: 8px;
            }}
        """)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 6, 10, 6)
        layout.setSpacing(10)

        self.lbl_update_msg = QLabel("A new version of GPU Sentry is available!")
        self.lbl_update_msg.setWordWrap(True)
        self.lbl_update_msg.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 12px; font-weight: 700; border: none;")
        layout.addWidget(self.lbl_update_msg, stretch=1)

        self.btn_update_now = WrapButton("⬇ Update & Restart")
        self.btn_update_now.clicked.connect(self._trigger_install_update)
        layout.addWidget(self.btn_update_now)

        self.btn_update_notes = WrapButton("Notes")
        self.btn_update_notes.clicked.connect(self._open_release_notes)
        layout.addWidget(self.btn_update_notes)

        btn_dismiss = WrapButton("✕")
        btn_dismiss.setToolTip("Dismiss update notification")
        btn_dismiss.clicked.connect(lambda: self.update_banner.setVisible(False))
        layout.addWidget(btn_dismiss)

        return banner

    def _style_top_tailscale_btn(self, enabled: bool):
        self.btn_tailscale.blockSignals(True)
        self.btn_tailscale.setChecked(enabled)
        self.btn_tailscale.blockSignals(False)
        if enabled:
            self.btn_tailscale.setText("🦊 Tailscale: ON")
            self.btn_tailscale.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.NVIDIA_GREEN}22;
                    color: {Theme.NVIDIA_GREEN};
                    border: 1px solid {Theme.NVIDIA_GREEN}88;
                    border-radius: 6px;
                    padding: 5px 11px;
                    font-size: 11px;
                    font-weight: 800;
                }}
                QPushButton:hover {{
                    background-color: {Theme.NVIDIA_GREEN}33;
                }}
            """)
        else:
            self.btn_tailscale.setText("🦊 Tailscale: OFF")
            self.btn_tailscale.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.BG_SUBTLE};
                    color: {Theme.TEXT_MUTED};
                    border: 1px solid {Theme.BORDER_DEFAULT};
                    border-radius: 6px;
                    padding: 5px 11px;
                    font-size: 11px;
                    font-weight: 700;
                }}
                QPushButton:hover {{
                    color: {Theme.TEXT_PRIMARY};
                    border: 1px solid {Theme.BORDER_ACCENT};
                }}
            """)

    def _on_toggle_tailscale(self, checked: bool):
        self.net_manager.set_tailscale_enabled(checked)

    def _on_rescan_network(self):
        if not self.net_manager.tailscale_enabled:
            self.net_manager.set_tailscale_enabled(True)
        self.btn_rescan.setText("🔄 Refreshing...")
        self.net_manager.rescan_network()

    def _on_tailnet_scan_status(self, msg: str):
        if msg:
            self.btn_rescan.setText("🔄 Refreshing...")
            self.lbl_footer_status.setText(msg)
        else:
            self.btn_rescan.setText("🔄 Refresh Tailnet")
            self._update_gpu_count_labels()

    def _on_tailscale_enabled_changed(self, enabled: bool):
        self._style_top_tailscale_btn(enabled)
        if hasattr(self, "act_tailscale"):
            self.act_tailscale.blockSignals(True)
            self.act_tailscale.setChecked(enabled)
            self.act_tailscale.blockSignals(False)

    def _create_summary_ribbon(self) -> QFrame:
        ribbon = QFrame()
        ribbon.setObjectName("SummaryRibbon")
        ribbon.setStyleSheet(f"""
            QFrame#SummaryRibbon {{
                background-color: {Theme.BG_PANEL};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 8px;
            }}
        """)

        layout = FlowLayout(ribbon, margin=8, h_spacing=14, v_spacing=5)

        self.lbl_sum_cpu = QLabel("💻 CPU: -- % • -- °C")
        self.lbl_sum_cpu.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Theme.CYBER_CYAN};")
        layout.addWidget(self.lbl_sum_cpu)

        self.lbl_sum_ram = QLabel("🧠 RAM: -- / -- GB")
        self.lbl_sum_ram.setStyleSheet("font-size: 11px; font-weight: bold; color: #f0f6fc;")
        layout.addWidget(self.lbl_sum_ram)

        self.lbl_sum_gpus = QLabel("⚡ GPUs: 0 Online")
        self.lbl_sum_gpus.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Theme.NVIDIA_GREEN};")
        layout.addWidget(self.lbl_sum_gpus)

        self.lbl_sum_power = QLabel("🔥 Power: 0 W")
        self.lbl_sum_power.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Theme.TEMP_WARM};")
        layout.addWidget(self.lbl_sum_power)

        self.lbl_sum_temp = QLabel("🌡 Peak GPU: -- °C")
        self.lbl_sum_temp.setStyleSheet("font-size: 11px; font-weight: bold; color: #f0f6fc;")
        layout.addWidget(self.lbl_sum_temp)

        self.lbl_sum_vram = QLabel("💾 VRAM: 0.0 / 0.0 GB")
        self.lbl_sum_vram.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Theme.TEXT_SECONDARY};")
        layout.addWidget(self.lbl_sum_vram)

        self.lbl_sum_latency = QLabel("Engine: <1ms")
        self.lbl_sum_latency.setStyleSheet(f"font-size: 10px; color: {Theme.TEXT_MUTED};")
        layout.addWidget(self.lbl_sum_latency)

        return ribbon

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        icon = self._create_app_icon()
        self.tray.setIcon(icon)
        self.setWindowIcon(icon)

        tray_menu = QMenu()
        act_show = QAction("Show GPU Sentry", self)
        act_show.triggered.connect(self._show_dashboard)
        tray_menu.addAction(act_show)

        act_hide = QAction("Minimize to Tray", self)
        act_hide.triggered.connect(self.hide)
        tray_menu.addAction(act_hide)

        tray_menu.addSeparator()

        self.act_condensed = QAction("⚡ Very Condensed View", self)
        self.act_condensed.setCheckable(True)
        self.act_condensed.setChecked(self.is_condensed)
        self.act_condensed.triggered.connect(self._on_tray_toggle_condensed)
        tray_menu.addAction(self.act_condensed)

        self.act_tailscale = QAction("🦊 Tailscale GPU Monitoring", self)
        self.act_tailscale.setCheckable(True)
        self.act_tailscale.setChecked(self.net_manager.tailscale_enabled)
        self.act_tailscale.triggered.connect(lambda c: self.net_manager.set_tailscale_enabled(c))
        tray_menu.addAction(self.act_tailscale)

        act_refresh_tailnet = QAction("🔄 Refresh Tailnet Devices", self)
        act_refresh_tailnet.triggered.connect(self._on_rescan_network)
        tray_menu.addAction(act_refresh_tailnet)

        tray_menu.addSeparator()

        self.act_taskbar = QAction("Taskbar Widget", self)
        self.act_taskbar.setCheckable(True)
        self.act_taskbar.setChecked(self.taskbar_widget.isVisible())
        self.act_taskbar.triggered.connect(self._toggle_taskbar_widget)
        tray_menu.addAction(self.act_taskbar)

        act_dock = QAction("Dock Widget Next to Clock", self)
        act_dock.triggered.connect(self.taskbar_widget.dock_to_clock)
        tray_menu.addAction(act_dock)

        tray_menu.addSeparator()

        act_settings = QAction("⚙ Settings...", self)
        act_settings.triggered.connect(self._open_settings)
        tray_menu.addAction(act_settings)

        act_update = QAction("🔄 Check for Updates", self)
        act_update.triggered.connect(lambda: self.updater.check_for_updates(silent=False, auto_install=False))
        tray_menu.addAction(act_update)

        tray_menu.addSeparator()

        self.act_start_menu = QAction("📌 Add to Start Menu", self)
        self.act_start_menu.setCheckable(True)
        self.act_start_menu.setChecked(is_start_menu_shortcut_installed())
        self.act_start_menu.triggered.connect(self._toggle_start_menu_shortcut)
        tray_menu.addAction(self.act_start_menu)

        self.act_autostart = QAction("🚀 Start on System Login", self)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(is_autostart_enabled())
        self.act_autostart.triggered.connect(self._toggle_autostart)
        tray_menu.addAction(self.act_autostart)

        tray_menu.addSeparator()

        act_quit = QAction("Exit", self)
        act_quit.triggered.connect(self._quit_app)
        tray_menu.addAction(act_quit)

        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _open_settings(self):
        dlg = SettingsDialog(
            devices=self.local_devices + self.remote_devices,
            updater=self.updater,
            net_manager=self.net_manager,
            taskbar_widget=self.taskbar_widget,
            energy_tracker=self.energy_tracker,
            parent=self,
        )
        dlg.exec()

    def _on_settings_changed(self):
        sd = self.app_settings.data
        idx = self.cb_interval.findData(sd.poll_interval_ms)
        if idx >= 0 and self.cb_interval.currentIndex() != idx:
            self.cb_interval.setCurrentIndex(idx)
        self.worker.set_interval(sd.poll_interval_ms)

        if self.net_manager.server_enabled != sd.local_agent_enabled:
            self.net_manager.set_server_enabled(sd.local_agent_enabled)
        self.net_manager.auto_scan_on_start = sd.auto_scan_network

        self.taskbar_widget.reload_from_settings()
        self.btn_taskbar.setChecked(self.taskbar_widget.isVisible())
        if hasattr(self, "act_taskbar"):
            self.act_taskbar.setChecked(self.taskbar_widget.isVisible())
        if hasattr(self, "act_autostart"):
            self.act_autostart.setChecked(is_autostart_enabled())
        if hasattr(self, "act_start_menu"):
            self.act_start_menu.setChecked(is_start_menu_shortcut_installed())

        if self.latest_summary:
            self._on_summary_updated(dict(self.latest_summary))

    # Auto-updater slots
    def _on_update_available(self, rel: ReleaseInfo):
        self._pending_release = rel
        self.lbl_update_msg.setText(f"🚀 GPU Sentry v{rel.version} is available (current: v{APP_VERSION})")
        self.btn_update_now.setEnabled(True)
        self.update_banner.setVisible(True)
        if self.tray.isVisible():
            self.tray.showMessage(
                "GPU Sentry Update Available",
                f"Version v{rel.version} is available on GitHub Releases.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )

    def _on_up_to_date(self, version: str):
        if self.isVisible():
            QMessageBox.information(self, "Up to Date", f"GPU Sentry v{version} is already up to date.")

    def _on_update_error(self, err: str):
        self.btn_update_now.setEnabled(True)
        if self.isVisible():
            QMessageBox.warning(self, "Update Error", err)

    def _trigger_install_update(self):
        if not self._pending_release:
            return
        self.btn_update_now.setEnabled(False)
        self.lbl_update_msg.setText(f"Downloading & installing v{self._pending_release.version}...")
        self.updater.install_update(self._pending_release)

    def _open_release_notes(self):
        if self._pending_release and self._pending_release.html_url:
            webbrowser.open(self._pending_release.html_url)

    def _toggle_start_menu_shortcut(self, checked: bool):
        if checked:
            ok, msg = install_start_menu_shortcut()
            self.tray.showMessage("GPU Sentry", msg, QSystemTrayIcon.MessageIcon.Information, 2500)
        else:
            remove_start_menu_shortcut()
            self.tray.showMessage("GPU Sentry", "Start Menu shortcut removed.", QSystemTrayIcon.MessageIcon.Information, 2500)

    def _toggle_autostart(self, checked: bool):
        ok, msg = set_autostart(checked, start_minimized=self.app_settings.data.autostart_minimized)
        self.tray.showMessage("GPU Sentry", msg, QSystemTrayIcon.MessageIcon.Information, 2500)

    def _create_app_icon(self) -> QIcon:
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ico_path = os.path.join(base_dir, "assets", "gpu_sentry.ico")
        if os.path.isfile(ico_path):
            return QIcon(ico_path)
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Theme.NVIDIA_GREEN))
        painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
        painter.setBrush(QColor(Theme.BG_WINDOW))
        painter.drawRoundedRect(5, 5, 22, 22, 4, 4)
        painter.setPen(QColor(Theme.NVIDIA_GREEN))
        painter.drawText(8, 21, "GPU")
        painter.end()
        return QIcon(pix)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_dashboard()

    def _jump_to_network_gpus(self):
        if self.is_condensed:
            self._apply_condensed_mode(False)
        if self.is_compact:
            self.btn_compact.setChecked(False)
            self._toggle_compact()
        self.network_card.setVisible(True)
        self.network_card.set_expanded(True)
        QTimer.singleShot(50, lambda: self.scroll_area.ensureWidgetVisible(self.network_card, 0, 20))

    def _jump_to_hardware_specs(self):
        if self.is_condensed:
            self._apply_condensed_mode(False)
        if self.is_compact:
            self.btn_compact.setChecked(False)
            self._toggle_compact()
        self.hw_specs_card.setVisible(True)
        self.hw_specs_card.set_expanded(True)
        QTimer.singleShot(50, lambda: self.scroll_area.ensureWidgetVisible(self.hw_specs_card, 0, 20))

    def _rebuild_cards_layout(self):
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if self.is_condensed:
            self.condensed_dashboard.setVisible(True)
            self.cards_layout.addWidget(self.condensed_dashboard)
            self.cards_layout.addStretch()
            return

        self.condensed_dashboard.setVisible(False)

        self.cpu_ram_card.setVisible(True)
        self.cards_layout.addWidget(self.cpu_ram_card)

        for dev in self.local_devices:
            if dev.device_id in self.cards:
                self.cards[dev.device_id].setVisible(True)
                self.cards_layout.addWidget(self.cards[dev.device_id])

        if self.net_manager.pin_remote_cards:
            for dev in self.remote_devices:
                if dev.device_id in self.remote_cards:
                    self.remote_cards[dev.device_id].setVisible(True)
                    self.cards_layout.addWidget(self.remote_cards[dev.device_id])

        self.network_card.setVisible(not self.is_compact)
        self.cards_layout.addWidget(self.network_card)

        self.hw_specs_card.setVisible(not self.is_compact)
        self.cards_layout.addWidget(self.hw_specs_card)

        self.cards_layout.addStretch()

    def _on_devices_discovered(self, devices: List[GpuDevice]):
        self.local_devices = devices
        for card in self.cards.values():
            card.deleteLater()
        self.cards.clear()

        for dev in devices:
            card = GpuCard(dev)
            card.set_compact_mode(self.is_compact)
            self.cards[dev.device_id] = card

        self.condensed_dashboard.set_local_devices(devices)
        self.hw_specs_card.set_devices(devices)
        self._rebuild_cards_layout()
        self._update_gpu_count_labels()
        self.taskbar_widget.set_devices(self.local_devices + self.remote_devices)

    def _on_network_nodes_updated(self, states: Dict[str, RemoteNodeState]):
        new_remote_devs: List[GpuDevice] = []
        new_remote_metrics: Dict[str, GpuMetrics] = {}

        for st in states.values():
            if st.online:
                for dev in st.gpus:
                    new_remote_devs.append(dev)
                    m = st.gpu_metrics.get(dev.device_id, dev.metrics)
                    new_remote_metrics[dev.device_id] = m

        self.remote_metrics = new_remote_metrics

        if new_remote_devs:
            self.btn_net_gpus.setText(f"🌐 Network ({len(new_remote_devs)})")
        else:
            self.btn_net_gpus.setText("🌐 Network GPUs")

        old_ids = [d.device_id for d in self.remote_devices]
        new_ids = [d.device_id for d in new_remote_devs]
        self.remote_devices = new_remote_devs

        if old_ids != new_ids:
            for rid in list(self.remote_cards.keys()):
                if rid not in new_ids:
                    self.remote_cards[rid].deleteLater()
                    del self.remote_cards[rid]
            for dev in new_remote_devs:
                if dev.device_id not in self.remote_cards:
                    rcard = GpuCard(dev)
                    rcard.set_compact_mode(self.is_compact)
                    self.remote_cards[dev.device_id] = rcard
            self._rebuild_cards_layout()
            self.taskbar_widget.set_devices(self.local_devices + self.remote_devices)
        else:
            for rcard in self.remote_cards.values():
                rcard.setVisible(self.net_manager.pin_remote_cards and not self.is_condensed)

        for dev_id, m in new_remote_metrics.items():
            if dev_id in self.remote_cards:
                self.remote_cards[dev_id].update_metrics(m)

        # Evaluate remote node offline alerts
        for title, msg, level in self.alert_manager.evaluate_remote_nodes(states):
            if self.tray.isVisible():
                icon = QSystemTrayIcon.MessageIcon.Critical if level == "critical" else QSystemTrayIcon.MessageIcon.Warning
                self.tray.showMessage(title, msg, icon, 4500)

        self._update_gpu_count_labels()

    def _update_gpu_count_labels(self):
        n_local = len(self.local_devices)
        n_rem = len(self.remote_devices)
        if n_rem > 0:
            self.lbl_sum_gpus.setText(f"⚡ GPUs: {n_local} Local + {n_rem} Net")
        else:
            self.lbl_sum_gpus.setText(f"⚡ GPUs: {n_local} Online")
        mb_str = f" • {self.hw_specs.motherboard.product}" if self.hw_specs.motherboard.product else ""
        ts_str = " • Tailscale: ON" if self.net_manager.tailscale_enabled else " • Tailscale: OFF"
        net_str = f" + {n_rem} Network GPUs" if n_rem > 0 else ""
        self.lbl_footer_status.setText(
            f"Active Monitoring: CPU + RAM + {n_local} Local GPUs{net_str}{ts_str}{mb_str}"
        )

    def _on_host_updated(self, host_metrics: HostMetrics):
        self.latest_host_metrics = host_metrics
        self.cpu_ram_card.update_metrics(host_metrics)
        self.condensed_dashboard.update_host_metrics(host_metrics)
        combined_metrics = {**self.cards_metrics, **self.remote_metrics}
        self.taskbar_widget.update_telemetry(host_metrics, combined_metrics, self.latest_summary)
        self.net_manager.update_local_telemetry(self.local_devices, self.cards_metrics, host_metrics)

    def _on_metrics_updated(self, metrics_by_id: Dict[str, GpuMetrics]):
        self.cards_metrics = metrics_by_id
        for dev_id, m in metrics_by_id.items():
            if dev_id in self.cards:
                self.cards[dev_id].update_metrics(m)

        self.condensed_dashboard.update_local_metrics(metrics_by_id)
        self.net_manager.update_local_telemetry(self.local_devices, metrics_by_id, self.latest_host_metrics)

        combined_metrics = {**metrics_by_id, **self.remote_metrics}
        all_devices = self.local_devices + self.remote_devices

        # Update session peaks & push to GPU cards
        self.peak_tracker.update(combined_metrics)
        for dev_id, card in {**self.cards, **self.remote_cards}.items():
            pk = self.peak_tracker.get(dev_id)
            if pk and hasattr(card, "update_session_peaks"):
                card.update_session_peaks(pk.peak_temp_c, pk.peak_power_w, pk.peak_vram_mb)

        # Evaluate thermal & VRAM alerts
        for title, msg, level in self.alert_manager.evaluate_gpus(all_devices, combined_metrics):
            if self.tray.isVisible():
                icon = QSystemTrayIcon.MessageIcon.Critical if level == "critical" else QSystemTrayIcon.MessageIcon.Warning
                self.tray.showMessage(title, msg, icon, 4500)

        # Optional CSV / JSONL telemetry logging & local Energy Burn (kWh) tracking
        self.telemetry_logger.log_snapshot(all_devices, combined_metrics, self.latest_host_metrics)
        self.energy_tracker.record_sample(all_devices, combined_metrics)
        sd = self.app_settings.data
        t_kwh, w_kwh, m_kwh = self.energy_tracker.get_totals_kwh()
        self.condensed_dashboard.update_energy_stats(
            enabled=sd.energy_tracking_enabled,
            today_kwh=t_kwh,
            week_kwh=w_kwh,
            month_kwh=m_kwh,
            per_dev_7d=self.energy_tracker.get_per_device_7d_kwh(),
            cost_per_kwh=sd.energy_cost_per_kwh,
            currency=sd.energy_currency,
        )

        self.taskbar_widget.update_telemetry(self.latest_host_metrics, combined_metrics, self.latest_summary)

        unit = self.app_settings.data.temp_unit
        peak_t = max((m.temp_core_c for m in combined_metrics.values()), default=0.0)
        if peak_t > 0:
            self._update_dynamic_tray_icon(peak_t)

        lines = [f"GPU Sentry v{APP_VERSION}:"]
        if self.latest_host_metrics:
            cpu = self.latest_host_metrics.cpu
            ram = self.latest_host_metrics.ram
            lines.append(
                f"CPU: {int(cpu.load_percent)}% • {format_temp(cpu.temp_core_c, unit)} | "
                f"RAM: {int(ram.load_percent)}% ({ram.used_gb:.1f} GB)"
            )

        for dev_id, card in self.cards.items():
            m = metrics_by_id.get(dev_id)
            if m:
                lines.append(f"{card.device.name}: {format_temp(m.temp_core_c, unit)} • {int(m.gpu_util_percent)}%")
        for dev_id, rcard in self.remote_cards.items():
            m = self.remote_metrics.get(dev_id)
            if m:
                lines.append(f"🌐 {rcard.device.name}: {format_temp(m.temp_core_c, unit)} • {int(m.gpu_util_percent)}%")
        self.tray.setToolTip("\n".join(lines))

        now_str = datetime.now().strftime("%H:%M:%S")
        self.lbl_last_updated.setText(f"Last update: {now_str}")
        try:
            mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            self.lbl_memory_footprint.setText(f"App RAM: {mem_mb:.1f} MB")
        except Exception:
            pass

    def _update_dynamic_tray_icon(self, temp: float):
        unit = self.app_settings.data.temp_unit
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setBrush(QColor(14, 17, 23, 230))
        t_col = QColor(Theme.get_temp_color(temp))
        painter.setPen(t_col)
        painter.drawRoundedRect(1, 1, 30, 30, 5, 5)

        font_sub = QFont("Segoe UI", 6)
        font_sub.setBold(True)
        painter.setFont(font_sub)
        painter.setPen(QColor(139, 148, 158))
        painter.drawText(3, 10, "GPU")

        font_val = QFont("Segoe UI", 9 if unit == "F" else 10)
        font_val.setBold(True)
        painter.setFont(font_val)
        painter.setPen(t_col)
        painter.drawText(2, 25, format_temp(temp, unit, show_unit=False))
        painter.end()

        self.tray.setIcon(QIcon(pix))

    def _on_summary_updated(self, summary: dict):
        unit = self.app_settings.data.temp_unit
        total_power = float(summary.get("total_power_w", 0.0))
        peak_t = float(summary.get("peak_temp_c", 0.0))
        peak_gpu = str(summary.get("peak_temp_gpu", ""))
        used_gb = float(summary.get("total_vram_used_gb", 0.0))
        cap_gb = float(summary.get("total_vram_cap_gb", 0.0))

        for dev in self.remote_devices:
            m = self.remote_metrics.get(dev.device_id)
            if m:
                total_power += m.power_draw_w
                used_gb += m.vram_used_mb / 1024.0
                cap_gb += m.vram_total_mb / 1024.0
                if m.temp_core_c > peak_t:
                    peak_t = m.temp_core_c
                    peak_gpu = dev.name

        summary["total_power_w"] = round(total_power, 1)
        summary["peak_temp_c"] = round(peak_t, 1)
        summary["peak_temp_gpu"] = peak_gpu
        summary["total_vram_used_gb"] = round(used_gb, 2)
        summary["total_vram_cap_gb"] = round(cap_gb, 2)

        self.latest_summary = summary
        combined_metrics = {**self.cards_metrics, **self.remote_metrics}
        self.taskbar_widget.update_telemetry(self.latest_host_metrics, combined_metrics, summary)

        cpu_pct = summary.get("cpu_load_pct", 0)
        cpu_temp = summary.get("cpu_temp_c", 0)
        self.lbl_sum_cpu.setText(f"💻 CPU: {cpu_pct:.0f}% • {format_temp(cpu_temp, unit)}")

        ram_u = summary.get("ram_used_gb", 0)
        ram_tot = summary.get("ram_total_gb", 0)
        ram_pct = summary.get("ram_load_pct", 0)
        ram_speed_str = f" • {self.hw_specs.ram.configured_speed_mts} MT/s" if self.hw_specs.ram.configured_speed_mts else ""
        self.lbl_sum_ram.setText(f"🧠 RAM: {ram_u:.1f}/{ram_tot:.1f} GB ({ram_pct:.0f}%{ram_speed_str})")

        self.lbl_sum_power.setText(f"🔥 Power: {summary.get('total_power_w', 0)} W")

        self.lbl_sum_temp.setText(f"🌡 Peak GPU: {format_temp(peak_t, unit)} ({peak_gpu[:18]})")
        color = Theme.get_temp_color(peak_t)
        self.lbl_sum_temp.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {color};")

        self.lbl_sum_vram.setText(f"💾 VRAM: {used_gb:.1f}/{cap_gb:.1f} GB")

        lat = summary.get("poll_latency_ms", 0)
        self.lbl_sum_latency.setText(f"Poll: {lat} ms")

    def _change_interval(self, index):
        ms = self.cb_interval.currentData()
        if ms:
            self.worker.set_interval(ms)
            self.app_settings.set("poll_interval_ms", int(ms))

    def _toggle_always_on_top(self):
        self.always_on_top = self.btn_pin.isChecked()
        self.app_settings.set("always_on_top", self.always_on_top)
        flags = self.windowFlags()
        if self.always_on_top:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            self.btn_pin.setText("📌 Pinned")
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            self.btn_pin.setText("📌 Pin")
        self.show()

    def _toggle_condensed(self):
        self._apply_condensed_mode(self.btn_condensed.isChecked())

    def _on_tray_toggle_condensed(self, checked: bool):
        self._apply_condensed_mode(checked)

    def _apply_condensed_mode(self, condensed: bool, initial: bool = False):
        self.is_condensed = bool(condensed)
        self.net_manager.set_condensed_view(self.is_condensed)

        self.btn_condensed.blockSignals(True)
        self.btn_condensed.setChecked(self.is_condensed)
        self.btn_condensed.blockSignals(False)

        if hasattr(self, "act_condensed"):
            self.act_condensed.blockSignals(True)
            self.act_condensed.setChecked(self.is_condensed)
            self.act_condensed.blockSignals(False)

        if self.is_condensed:
            self.root_layout.setContentsMargins(10, 8, 10, 6)
            self.root_layout.setSpacing(6)
            self.lbl_sub.setVisible(False)
            self._rebuild_cards_layout()
        else:
            self.root_layout.setContentsMargins(14, 12, 14, 10)
            self.root_layout.setSpacing(10)
            self.lbl_sub.setVisible(True)
            self._rebuild_cards_layout()

    def _apply_compact_state(self):
        self.cpu_ram_card.set_compact_mode(self.is_compact)
        for card in self.cards.values():
            card.set_compact_mode(self.is_compact)
        for rcard in self.remote_cards.values():
            rcard.set_compact_mode(self.is_compact)
        self.network_card.setVisible(not self.is_compact)
        self.hw_specs_card.setVisible(not self.is_compact)
        self.summary_ribbon.setVisible(not self.is_compact)
        self.btn_compact.setText("🗖 Expanded" if self.is_compact else "🗗 Compact")

    def _toggle_compact(self):
        if self.is_condensed and self.btn_compact.isChecked():
            self._apply_condensed_mode(False)
        self.is_compact = self.btn_compact.isChecked()
        self.app_settings.set("compact_mode", self.is_compact)
        self._apply_compact_state()

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        self.worker.set_paused(self.is_paused)
        if self.is_paused:
            self.btn_pause.setText("▶ Resume")
            self.lbl_live_dot.setStyleSheet(f"color: {Theme.TEMP_WARM}; font-size: 14px; font-weight: bold;")
        else:
            self.btn_pause.setText("⏸ Pause")
            self.lbl_live_dot.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 14px; font-weight: bold;")

    def _toggle_taskbar_widget(self):
        if self.taskbar_widget.isVisible():
            self.taskbar_widget.hide_widget()
        else:
            self.taskbar_widget.show_widget()
            if self.app_settings.data.taskbar_x is None:
                self.taskbar_widget.dock_to_clock()

    def _on_widget_visibility_changed(self, visible: bool):
        self.btn_taskbar.setChecked(visible)
        if hasattr(self, "act_taskbar"):
            self.act_taskbar.setChecked(visible)

    def _show_dashboard(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self):
        self._is_quitting = True
        self._save_window_geometry()
        self.close()
        QApplication.quit()

    def closeEvent(self, event):
        self._save_window_geometry()
        if (
            not getattr(self, "_is_quitting", False)
            and self.app_settings.data.close_to_tray
            and (self.taskbar_widget.isVisible() or self.tray.isVisible())
        ):
            event.ignore()
            self.hide()
            return

        self.energy_tracker.save(force=True)
        self.net_manager.stop()
        self.worker.stop()
        self.taskbar_widget.close()
        self.tray.hide()
        event.accept()
