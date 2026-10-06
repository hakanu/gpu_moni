"""
Main Dashboard Window for multi-GPU monitoring.
Hosts global summary telemetry, controls, responsive GPU cards, and system tray.
"""

import os
import psutil
from datetime import datetime
from typing import Dict, List

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QScrollArea, QFrame, QSystemTrayIcon,
    QMenu, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QAction, QColor, QPainter, QPixmap

from core.gpu_types import GpuDevice, GpuMetrics, HostMetrics
from core.monitor_worker import MonitorWorker
from ui.theme import Theme, GLOBAL_STYLESHEET
from ui.widgets.gpu_card import GpuCard
from ui.widgets.cpu_ram_card import CpuRamCard


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPU Sentry - Multi-GPU Dashboard")
        self.resize(1000, 820)
        self.setMinimumSize(780, 520)

        # State
        # Cards state
        self.cards: Dict[str, GpuCard] = {}
        self.cpu_ram_card = CpuRamCard()
        self.latest_host_metrics: Optional[HostMetrics] = None
        self.is_compact = False
        self.is_paused = False
        self.always_on_top = False

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

        # Start worker
        self.worker.start()

    def _setup_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(16, 14, 16, 12)
        root_layout.setSpacing(12)

        # 1. Top Navigation Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        # App Brand & Status
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        # Neon Live Dot
        self.lbl_live_dot = QLabel("●")
        self.lbl_live_dot.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 14px; font-weight: bold;")
        title_row.addWidget(self.lbl_live_dot)

        lbl_app_name = QLabel("GPU SENTRY")
        lbl_app_name.setStyleSheet("font-size: 18px; font-weight: 800; letter-spacing: 1px; color: #ffffff;")
        title_row.addWidget(lbl_app_name)

        lbl_sub = QLabel("REAL-TIME HARDWARE MONITOR")
        lbl_sub.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {Theme.TEXT_MUTED}; letter-spacing: 0.5px;")

        brand_layout.addLayout(title_row)
        brand_layout.addWidget(lbl_sub)
        top_bar.addLayout(brand_layout)

        top_bar.addStretch()

        # Controls Section
        # Refresh rate combo
        lbl_refresh = QLabel("Interval:")
        lbl_refresh.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px; font-weight: 600;")
        top_bar.addWidget(lbl_refresh)

        self.cb_interval = QComboBox()
        self.cb_interval.addItem("500 ms", 500)
        self.cb_interval.addItem("1.0 s", 1000)
        self.cb_interval.addItem("2.0 s", 2000)
        self.cb_interval.addItem("3.0 s", 3000)
        self.cb_interval.setCurrentIndex(1)  # 1.0s default
        self.cb_interval.currentIndexChanged.connect(self._change_interval)
        top_bar.addWidget(self.cb_interval)

        # Always On Top toggle
        self.btn_pin = QPushButton("📌 Pin on Top")
        self.btn_pin.setCheckable(True)
        self.btn_pin.clicked.connect(self._toggle_always_on_top)
        top_bar.addWidget(self.btn_pin)

        # Compact View toggle
        self.btn_compact = QPushButton("🗗 Compact")
        self.btn_compact.setCheckable(True)
        self.btn_compact.clicked.connect(self._toggle_compact)
        top_bar.addWidget(self.btn_compact)

        # Pause / Resume button
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.clicked.connect(self._toggle_pause)
        top_bar.addWidget(self.btn_pause)

        root_layout.addLayout(top_bar)

        # 2. Global Telemetry Summary Ribbon
        self.summary_ribbon = self._create_summary_ribbon()
        root_layout.addWidget(self.summary_ribbon)

        # 3. Scrollable GPU Cards Container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 4, 0, 4)
        self.cards_layout.setSpacing(14)
        self.cards_layout.addStretch()

        scroll.setWidget(self.cards_container)
        root_layout.addWidget(scroll, stretch=1)

        # 4. Footer Status Bar
        footer = QHBoxLayout()
        footer.setSpacing(16)

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

        root_layout.addLayout(footer)

    def _create_summary_ribbon(self) -> QFrame:
        ribbon = QFrame()
        ribbon.setObjectName("SummaryRibbon")
        ribbon.setStyleSheet(f"""
            QFrame#SummaryRibbon {{
                background-color: {Theme.BG_PANEL};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 4px;
            }}
        """)

        layout = QHBoxLayout(ribbon)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(20)

        # Pill 1: CPU
        self.lbl_sum_cpu = QLabel("💻 CPU: -- % • -- °C")
        self.lbl_sum_cpu.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {Theme.CYBER_CYAN};")
        layout.addWidget(self.lbl_sum_cpu)

        # Pill 2: RAM
        self.lbl_sum_ram = QLabel("🧠 RAM: -- / -- GB")
        self.lbl_sum_ram.setStyleSheet("font-size: 12px; font-weight: bold; color: #f0f6fc;")
        layout.addWidget(self.lbl_sum_ram)

        # Pill 3: GPUs Online
        self.lbl_sum_gpus = QLabel("⚡ GPUs: 0 Online")
        self.lbl_sum_gpus.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {Theme.NVIDIA_GREEN};")
        layout.addWidget(self.lbl_sum_gpus)

        # Pill 4: Total GPU Power
        self.lbl_sum_power = QLabel("🔥 GPU Power: 0 W")
        self.lbl_sum_power.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {Theme.TEMP_WARM};")
        layout.addWidget(self.lbl_sum_power)

        # Pill 5: Peak GPU Temp
        self.lbl_sum_temp = QLabel("🌡 Peak GPU: -- °C")
        self.lbl_sum_temp.setStyleSheet("font-size: 12px; font-weight: bold; color: #f0f6fc;")
        layout.addWidget(self.lbl_sum_temp)

        # Pill 6: Total VRAM
        self.lbl_sum_vram = QLabel("💾 Total VRAM: 0.0 / 0.0 GB")
        self.lbl_sum_vram.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {Theme.TEXT_SECONDARY};")
        layout.addWidget(self.lbl_sum_vram)

        layout.addStretch()

        # Engine latency badge
        self.lbl_sum_latency = QLabel("Engine: <1ms")
        self.lbl_sum_latency.setStyleSheet(f"font-size: 11px; color: {Theme.TEXT_MUTED};")
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

        act_quit = QAction("Exit", self)
        act_quit.triggered.connect(self.close)
        tray_menu.addAction(act_quit)

        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _create_app_icon(self) -> QIcon:
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

    def _on_devices_discovered(self, devices: List[GpuDevice]):
        # Clear stretch and previous widgets
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            if item.widget() and item.widget() != self.cpu_ram_card:
                item.widget().deleteLater()

        self.cards.clear()

        # 1. Host System (CPU & RAM) Card
        self.cards_layout.addWidget(self.cpu_ram_card)

        # 2. Individual GPU Cards
        for dev in devices:
            card = GpuCard(dev)
            self.cards[dev.device_id] = card
            self.cards_layout.addWidget(card)

        self.cards_layout.addStretch()
        self.lbl_sum_gpus.setText(f"⚡ GPUs: {len(devices)} Online")
        self.lbl_footer_status.setText(f"Active Monitoring: CPU + RAM + {len(devices)} GPUs (Direct C Telemetry)")

    def _on_host_updated(self, host_metrics: HostMetrics):
        self.latest_host_metrics = host_metrics
        self.cpu_ram_card.update_metrics(host_metrics)

    def _on_metrics_updated(self, metrics_by_id: Dict[str, GpuMetrics]):
        for dev_id, m in metrics_by_id.items():
            if dev_id in self.cards:
                self.cards[dev_id].update_metrics(m)

        # Update tray tooltip with live system and GPU temperatures
        lines = ["GPU Sentry:"]
        if self.latest_host_metrics:
            cpu = self.latest_host_metrics.cpu
            ram = self.latest_host_metrics.ram
            lines.append(f"CPU: {int(cpu.load_percent)}% • {int(cpu.temp_core_c)}°C | RAM: {int(ram.load_percent)}% ({ram.used_gb:.1f} GB)")

        for dev_id, card in self.cards.items():
            m = metrics_by_id.get(dev_id)
            if m:
                lines.append(f"{card.device.name}: {int(m.temp_core_c)}°C • {int(m.gpu_util_percent)}%")
        self.tray.setToolTip("\n".join(lines))

        # Update footer memory & time
        now_str = datetime.now().strftime("%H:%M:%S")
        self.lbl_last_updated.setText(f"Last update: {now_str}")
        try:
            mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            self.lbl_memory_footprint.setText(f"App RAM: {mem_mb:.1f} MB")
        except Exception:
            pass

    def _on_summary_updated(self, summary: dict):
        # CPU & RAM summaries
        cpu_pct = summary.get("cpu_load_pct", 0)
        cpu_temp = summary.get("cpu_temp_c", 0)
        self.lbl_sum_cpu.setText(f"💻 CPU: {cpu_pct:.0f}% • {cpu_temp:.0f}°C")

        ram_u = summary.get("ram_used_gb", 0)
        ram_tot = summary.get("ram_total_gb", 0)
        ram_pct = summary.get("ram_load_pct", 0)
        self.lbl_sum_ram.setText(f"🧠 RAM: {ram_u:.1f} / {ram_tot:.1f} GB ({ram_pct:.0f}%)")

        # GPU summaries
        self.lbl_sum_power.setText(f"🔥 GPU Power: {summary.get('total_power_w', 0)} W")

        peak_t = summary.get("peak_temp_c", 0)
        peak_gpu = summary.get("peak_temp_gpu", "")
        self.lbl_sum_temp.setText(f"🌡 Peak GPU: {peak_t}°C ({peak_gpu})")
        color = Theme.get_temp_color(peak_t)
        self.lbl_sum_temp.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color};")

        used_gb = summary.get("total_vram_used_gb", 0)
        cap_gb = summary.get("total_vram_cap_gb", 0)
        self.lbl_sum_vram.setText(f"💾 Total VRAM: {used_gb:.1f} / {cap_gb:.1f} GB")

        lat = summary.get("poll_latency_ms", 0)
        self.lbl_sum_latency.setText(f"Poll Latency: {lat} ms")

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
            self.btn_pin.setText("📌 Pin on Top")
        self.show()

    def _toggle_compact(self):
        self.is_compact = self.btn_compact.isChecked()
        self.cpu_ram_card.set_compact_mode(self.is_compact)
        for card in self.cards.values():
            card.set_compact_mode(self.is_compact)
        if self.is_compact:
            self.summary_ribbon.setVisible(False)
            self.btn_compact.setText("🗖 Expanded")
            self.resize(780, 520)
        else:
            self.summary_ribbon.setVisible(True)
            self.btn_compact.setText("🗗 Compact")
            self.resize(1000, 820)

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        self.worker.set_paused(self.is_paused)
        if self.is_paused:
            self.btn_pause.setText("▶ Resume")
            self.lbl_live_dot.setStyleSheet(f"color: {Theme.TEMP_WARM}; font-size: 14px; font-weight: bold;")
        else:
            self.btn_pause.setText("⏸ Pause")
            self.lbl_live_dot.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 14px; font-weight: bold;")

    def closeEvent(self, event):
        self.worker.stop()
        self.tray.hide()
        event.accept()
