"""
Main Dashboard Window for multi-GPU monitoring.
Hosts global summary telemetry, controls, responsive GPU cards, network GPU nodes,
Tailscale ON/OFF toggle, Very Condensed View of Everything, deep hardware specs, and system tray.
"""

import os
import psutil
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QScrollArea, QFrame, QSystemTrayIcon,
    QMenu, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QAction, QColor, QPainter, QPixmap, QFont

from core.gpu_types import GpuDevice, GpuMetrics, HostMetrics
from core.hardware_info import HardwareInfoCollector
from core.network_telemetry import NetworkTelemetryManager, RemoteNodeState
from core.monitor_worker import MonitorWorker
from ui.theme import Theme, GLOBAL_STYLESHEET
from ui.widgets.gpu_card import GpuCard
from ui.widgets.cpu_ram_card import CpuRamCard
from ui.widgets.hardware_specs_card import HardwareSpecsCard
from ui.widgets.network_nodes_card import NetworkNodesCard
from ui.widgets.condensed_dashboard import CondensedDashboardWidget
from ui.widgets.taskbar_widget import TaskbarWidget
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
        self.setWindowTitle("GPU Sentry - Multi-GPU & Network Hardware Dashboard")
        self.resize(1100, 880)
        self.setMinimumSize(640, 360)

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
        self.net_manager.nodes_updated.connect(self._on_network_nodes_updated)
        self.net_manager.tailscale_enabled_changed.connect(self._on_tailscale_enabled_changed)
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
        self.is_compact = False
        self.is_paused = False
        self.always_on_top = False

        # Taskbar Widget (Docked near Windows Clock)
        self.taskbar_widget = TaskbarWidget(main_window=self)
        self.taskbar_widget.visibility_changed.connect(self._on_widget_visibility_changed)
        self.taskbar_widget.request_show_dashboard.connect(self._show_dashboard)
        self.taskbar_widget.request_exit_app.connect(self._quit_app)

        # Apply global styles
        self.setStyleSheet(GLOBAL_STYLESHEET)

        # Worker initialization
        self.worker = MonitorWorker(interval_ms=1000)
        self.worker.devices_discovered.connect(self._on_devices_discovered)
        self.worker.metrics_updated.connect(self._on_metrics_updated)
        self.worker.host_updated.connect(self._on_host_updated)
        self.worker.summary_updated.connect(self._on_summary_updated)

        self._setup_ui()
        self._setup_tray()

        if self.is_condensed:
            self._apply_condensed_mode(True, initial=True)

        # Start worker and network manager
        self.worker.start()
        self.net_manager.start()

    def _setup_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        self.root_layout = QVBoxLayout(central_widget)
        self.root_layout.setContentsMargins(14, 12, 14, 10)
        self.root_layout.setSpacing(10)

        # 1. Top Navigation Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        # App Brand & Status
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(1)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)

        # Neon Live Dot
        self.lbl_live_dot = QLabel("●")
        self.lbl_live_dot.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 14px; font-weight: bold;")
        title_row.addWidget(self.lbl_live_dot)

        lbl_app_name = QLabel("GPU SENTRY")
        lbl_app_name.setStyleSheet("font-size: 17px; font-weight: 800; letter-spacing: 1px; color: #ffffff;")
        title_row.addWidget(lbl_app_name)

        self.lbl_sub = QLabel("LOCAL & NETWORK HARDWARE TELEMETRY")
        self.lbl_sub.setStyleSheet(f"font-size: 9px; font-weight: 700; color: {Theme.TEXT_MUTED}; letter-spacing: 0.5px;")

        brand_layout.addLayout(title_row)
        brand_layout.addWidget(self.lbl_sub)
        top_bar.addLayout(brand_layout)

        top_bar.addStretch()

        # Controls Section
        lbl_refresh = QLabel("Interval:")
        lbl_refresh.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
        top_bar.addWidget(lbl_refresh)

        self.cb_interval = QComboBox()
        self.cb_interval.addItem("500 ms", 500)
        self.cb_interval.addItem("1.0 s", 1000)
        self.cb_interval.addItem("2.0 s", 2000)
        self.cb_interval.addItem("3.0 s", 3000)
        self.cb_interval.setCurrentIndex(1)  # 1.0s default
        self.cb_interval.currentIndexChanged.connect(self._change_interval)
        top_bar.addWidget(self.cb_interval)

        # Master Tailscale ON / OFF Toggle Button
        self.btn_tailscale = QPushButton()
        self.btn_tailscale.setCheckable(True)
        self.btn_tailscale.setChecked(self.net_manager.tailscale_enabled)
        self.btn_tailscale.setToolTip("Turn Tailscale-based GPU discovery & monitoring ON or OFF")
        self.btn_tailscale.clicked.connect(self._on_toggle_tailscale)
        self._style_top_tailscale_btn(self.net_manager.tailscale_enabled)
        top_bar.addWidget(self.btn_tailscale)

        # Very Condensed View of Everything Toggle Button
        self.btn_condensed = QPushButton("⚡ Condensed")
        self.btn_condensed.setCheckable(True)
        self.btn_condensed.setChecked(self.is_condensed)
        self.btn_condensed.setToolTip("Switch to Very Condensed View of Everything (CPU, RAM, Local GPUs, Tailscale GPUs & Processes in one dense view)")
        self.btn_condensed.clicked.connect(self._toggle_condensed)
        top_bar.addWidget(self.btn_condensed)

        # Compact Card View toggle
        self.btn_compact = QPushButton("🗗 Compact")
        self.btn_compact.setCheckable(True)
        self.btn_compact.setToolTip("Hide sparkline graphs and drawers on GPU/CPU cards")
        self.btn_compact.clicked.connect(self._toggle_compact)
        top_bar.addWidget(self.btn_compact)

        # Network GPUs Jump button
        self.btn_net_gpus = QPushButton("🌐 Network GPUs")
        self.btn_net_gpus.setToolTip("Jump to LAN & Tailscale Network GPUs Manager")
        self.btn_net_gpus.clicked.connect(self._jump_to_network_gpus)
        top_bar.addWidget(self.btn_net_gpus)

        # Hardware Specs Jump button
        self.btn_hw_specs = QPushButton("🧬 Specs")
        self.btn_hw_specs.setToolTip("Jump to Deep Hardware Specifications (RAM MHz, Channels, Motherboard, BIOS, CPU, PCIe, NVMe)")
        self.btn_hw_specs.clicked.connect(self._jump_to_hardware_specs)
        top_bar.addWidget(self.btn_hw_specs)

        # Always On Top toggle
        self.btn_pin = QPushButton("📌 Pin")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip("Keep window always on top")
        self.btn_pin.clicked.connect(self._toggle_always_on_top)
        top_bar.addWidget(self.btn_pin)

        # Taskbar Widget toggle
        self.btn_taskbar = QPushButton("📊 Widget")
        self.btn_taskbar.setCheckable(True)
        self.btn_taskbar.setChecked(self.taskbar_widget.isVisible())
        self.btn_taskbar.setToolTip("Show/Hide live telemetry widget on taskbar near clock")
        self.btn_taskbar.clicked.connect(self._toggle_taskbar_widget)
        top_bar.addWidget(self.btn_taskbar)

        # Pause / Resume button
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.clicked.connect(self._toggle_pause)
        top_bar.addWidget(self.btn_pause)

        self.root_layout.addLayout(top_bar)

        # 2. Global Telemetry Summary Ribbon
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
        footer.setSpacing(14)

        self.lbl_footer_status = QLabel("Engine: Initializing...")
        self.lbl_footer_status.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self.lbl_footer_status)

        footer.addStretch()

        self.lbl_memory_footprint = QLabel("App RAM: -- MB")
        self.lbl_memory_footprint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self.lbl_memory_footprint)

        self.lbl_last_updated = QLabel("Last update: --")
        self.lbl_last_updated.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self.lbl_last_updated)

        self.root_layout.addLayout(footer)

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
                padding: 3px;
            }}
        """)

        layout = QHBoxLayout(ribbon)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(16)

        # Pill 1: CPU
        self.lbl_sum_cpu = QLabel("💻 CPU: -- % • -- °C")
        self.lbl_sum_cpu.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Theme.CYBER_CYAN};")
        layout.addWidget(self.lbl_sum_cpu)

        # Pill 2: RAM
        self.lbl_sum_ram = QLabel("🧠 RAM: -- / -- GB")
        self.lbl_sum_ram.setStyleSheet("font-size: 11px; font-weight: bold; color: #f0f6fc;")
        layout.addWidget(self.lbl_sum_ram)

        # Pill 3: GPUs Online
        self.lbl_sum_gpus = QLabel("⚡ GPUs: 0 Online")
        self.lbl_sum_gpus.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Theme.NVIDIA_GREEN};")
        layout.addWidget(self.lbl_sum_gpus)

        # Pill 4: Total GPU Power
        self.lbl_sum_power = QLabel("🔥 GPU Power: 0 W")
        self.lbl_sum_power.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Theme.TEMP_WARM};")
        layout.addWidget(self.lbl_sum_power)

        # Pill 5: Peak GPU Temp
        self.lbl_sum_temp = QLabel("🌡 Peak GPU: -- °C")
        self.lbl_sum_temp.setStyleSheet("font-size: 11px; font-weight: bold; color: #f0f6fc;")
        layout.addWidget(self.lbl_sum_temp)

        # Pill 6: Total VRAM
        self.lbl_sum_vram = QLabel("💾 Total VRAM: 0.0 / 0.0 GB")
        self.lbl_sum_vram.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Theme.TEXT_SECONDARY};")
        layout.addWidget(self.lbl_sum_vram)

        layout.addStretch()

        # Engine latency badge
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
        act_show.triggered.connect(self.showNormal)
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

    def _toggle_start_menu_shortcut(self, checked: bool):
        if checked:
            ok, msg = install_start_menu_shortcut()
            self.tray.showMessage("GPU Sentry", msg, QSystemTrayIcon.MessageIcon.Information, 2500)
        else:
            remove_start_menu_shortcut()
            self.tray.showMessage("GPU Sentry", "Start Menu shortcut removed.", QSystemTrayIcon.MessageIcon.Information, 2500)

    def _toggle_autostart(self, checked: bool):
        ok, msg = set_autostart(checked)
        self.tray.showMessage("GPU Sentry", msg, QSystemTrayIcon.MessageIcon.Information, 2500)

    def _create_app_icon(self) -> QIcon:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(root_dir, "assets", "gpu_sentry.ico")
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
                self.showNormal()
                self.activateWindow()

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
        # Detach existing widgets from layout without deleting persistent ones
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

        # 1. Host System (CPU & RAM) Card
        self.cpu_ram_card.setVisible(True)
        self.cards_layout.addWidget(self.cpu_ram_card)

        # 2. Local GPU Cards
        for dev in self.local_devices:
            if dev.device_id in self.cards:
                self.cards[dev.device_id].setVisible(True)
                self.cards_layout.addWidget(self.cards[dev.device_id])

        # 3. Pinned Remote GPU Cards (if enabled)
        if self.net_manager.pin_remote_cards:
            for dev in self.remote_devices:
                if dev.device_id in self.remote_cards:
                    self.remote_cards[dev.device_id].setVisible(True)
                    self.cards_layout.addWidget(self.remote_cards[dev.device_id])

        # 4. Network Nodes & Remote GPU Thermal Monitor Card
        self.network_card.setVisible(not self.is_compact)
        self.cards_layout.addWidget(self.network_card)

        # 5. Deep Hardware Specifications Card
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

        # Notify taskbar widget
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

        # Update top navbar button badge
        if new_remote_devs:
            self.btn_net_gpus.setText(f"🌐 Network ({len(new_remote_devs)})")
        else:
            self.btn_net_gpus.setText("🌐 Network GPUs")

        # Check if remote device list or pin setting changed
        old_ids = [d.device_id for d in self.remote_devices]
        new_ids = [d.device_id for d in new_remote_devs]
        self.remote_devices = new_remote_devs

        if old_ids != new_ids:
            # Remove stale remote cards
            for rid in list(self.remote_cards.keys()):
                if rid not in new_ids:
                    self.remote_cards[rid].deleteLater()
                    del self.remote_cards[rid]
            # Create new remote cards
            for dev in new_remote_devs:
                if dev.device_id not in self.remote_cards:
                    rcard = GpuCard(dev)
                    rcard.set_compact_mode(self.is_compact)
                    self.remote_cards[dev.device_id] = rcard
            self._rebuild_cards_layout()
            self.taskbar_widget.set_devices(self.local_devices + self.remote_devices)
        else:
            # Make sure visibility matches pin_remote_cards and condensed mode
            for rcard in self.remote_cards.values():
                rcard.setVisible(self.net_manager.pin_remote_cards and not self.is_condensed)

        # Push live metrics to pinned remote GPU cards
        for dev_id, m in new_remote_metrics.items():
            if dev_id in self.remote_cards:
                self.remote_cards[dev_id].update_metrics(m)

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

        # Share local snapshot with network server
        self.net_manager.update_local_telemetry(self.local_devices, metrics_by_id, self.latest_host_metrics)

        combined_metrics = {**metrics_by_id, **self.remote_metrics}

        # Update taskbar widget
        self.taskbar_widget.update_telemetry(self.latest_host_metrics, combined_metrics, self.latest_summary)

        # Dynamic tray icon with peak temperature across local + remote GPUs
        peak_t = max((m.temp_core_c for m in combined_metrics.values()), default=0.0)
        if peak_t > 0:
            self._update_dynamic_tray_icon(peak_t)

        # Update tray tooltip with live system, local GPUs, and remote GPUs
        lines = ["GPU Sentry:"]
        if self.latest_host_metrics:
            cpu = self.latest_host_metrics.cpu
            ram = self.latest_host_metrics.ram
            lines.append(f"CPU: {int(cpu.load_percent)}% • {int(cpu.temp_core_c)}°C | RAM: {int(ram.load_percent)}% ({ram.used_gb:.1f} GB)")

        for dev_id, card in self.cards.items():
            m = metrics_by_id.get(dev_id)
            if m:
                lines.append(f"{card.device.name}: {int(m.temp_core_c)}°C • {int(m.gpu_util_percent)}%")
        for dev_id, rcard in self.remote_cards.items():
            m = self.remote_metrics.get(dev_id)
            if m:
                lines.append(f"🌐 {rcard.device.name}: {int(m.temp_core_c)}°C • {int(m.gpu_util_percent)}%")
        self.tray.setToolTip("\n".join(lines))

        # Update footer memory & time
        now_str = datetime.now().strftime("%H:%M:%S")
        self.lbl_last_updated.setText(f"Last update: {now_str}")
        try:
            mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            self.lbl_memory_footprint.setText(f"App RAM: {mem_mb:.1f} MB")
        except Exception:
            pass

    def _update_dynamic_tray_icon(self, temp: float):
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rounded background
        painter.setBrush(QColor(14, 17, 23, 230))
        t_col = QColor(Theme.get_temp_color(temp))
        painter.setPen(t_col)
        painter.drawRoundedRect(1, 1, 30, 30, 5, 5)

        font_sub = QFont("Segoe UI", 6)
        font_sub.setBold(True)
        painter.setFont(font_sub)
        painter.setPen(QColor(139, 148, 158))
        painter.drawText(3, 10, "GPU")

        font_val = QFont("Segoe UI", 10)
        font_val.setBold(True)
        painter.setFont(font_val)
        painter.setPen(t_col)
        painter.drawText(3, 25, f"{int(temp)}°")
        painter.end()

        self.tray.setIcon(QIcon(pix))

    def _on_summary_updated(self, summary: dict):
        # Merge remote GPU stats into global summary if remote GPUs are online
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

        # CPU & RAM summaries
        cpu_pct = summary.get("cpu_load_pct", 0)
        cpu_temp = summary.get("cpu_temp_c", 0)
        self.lbl_sum_cpu.setText(f"💻 CPU: {cpu_pct:.0f}% • {cpu_temp:.0f}°C")

        ram_u = summary.get("ram_used_gb", 0)
        ram_tot = summary.get("ram_total_gb", 0)
        ram_pct = summary.get("ram_load_pct", 0)
        ram_speed_str = f" • {self.hw_specs.ram.configured_speed_mts} MT/s" if self.hw_specs.ram.configured_speed_mts else ""
        self.lbl_sum_ram.setText(f"🧠 RAM: {ram_u:.1f}/{ram_tot:.1f} GB ({ram_pct:.0f}%{ram_speed_str})")

        # GPU summaries
        self.lbl_sum_power.setText(f"🔥 Power: {summary.get('total_power_w', 0)} W")

        self.lbl_sum_temp.setText(f"🌡 Peak GPU: {peak_t:.0f}°C ({peak_gpu[:18]})")
        color = Theme.get_temp_color(peak_t)
        self.lbl_sum_temp.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {color};")

        self.lbl_sum_vram.setText(f"💾 VRAM: {used_gb:.1f}/{cap_gb:.1f} GB")

        lat = summary.get("poll_latency_ms", 0)
        self.lbl_sum_latency.setText(f"Poll: {lat} ms")

    def _change_interval(self, index):
        ms = self.cb_interval.currentData()
        if ms:
            self.worker.set_interval(ms)

    def _toggle_always_on_top(self):
        self.always_on_top = self.btn_pin.isChecked()
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
            self.resize(960, 500)
        else:
            self.root_layout.setContentsMargins(14, 12, 14, 10)
            self.root_layout.setSpacing(10)
            self.lbl_sub.setVisible(True)
            self._rebuild_cards_layout()
            if not initial:
                self.resize(1100, 880)

    def _toggle_compact(self):
        if self.is_condensed and self.btn_compact.isChecked():
            self._apply_condensed_mode(False)
        self.is_compact = self.btn_compact.isChecked()
        self.cpu_ram_card.set_compact_mode(self.is_compact)
        for card in self.cards.values():
            card.set_compact_mode(self.is_compact)
        for rcard in self.remote_cards.values():
            rcard.set_compact_mode(self.is_compact)
        self.network_card.setVisible(not self.is_compact)
        self.hw_specs_card.setVisible(not self.is_compact)
        if self.is_compact:
            self.summary_ribbon.setVisible(False)
            self.btn_compact.setText("🗖 Expanded")
            self.resize(780, 520)
        else:
            self.summary_ribbon.setVisible(True)
            self.btn_compact.setText("🗗 Compact")
            self.resize(1100, 880)

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
            self.taskbar_widget.dock_to_clock()

    def _on_widget_visibility_changed(self, visible: bool):
        self.btn_taskbar.setChecked(visible)
        if hasattr(self, "act_taskbar"):
            self.act_taskbar.setChecked(visible)

    def _show_dashboard(self):
        self.showNormal()
        self.activateWindow()

    def _quit_app(self):
        self._is_quitting = True
        self.close()

    def closeEvent(self, event):
        if not getattr(self, "_is_quitting", False) and (self.taskbar_widget.isVisible() or self.tray.isVisible()):
            # Keep monitoring active on the taskbar and system tray
            event.ignore()
            self.hide()
            return

        self.net_manager.stop()
        self.worker.stop()
        self.taskbar_widget.close()
        self.tray.hide()
        event.accept()
