"""
Host System (CPU and RAM) Card component.
Displays processor load, per-core utilization, CPU thermals & power,
RAM usage, rolling history sparkline, and logical core heatmap.
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QWidget, QPushButton, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from core.gpu_types import HostMetrics
from ui.theme import Theme
from ui.widgets.arc_gauge import ArcGauge
from ui.widgets.sparkline import SparklineChart
from ui.widgets.thermal_bar import ThermalBar


class CpuRamCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.accent_color = Theme.CYBER_CYAN
        self.is_compact = False
        self.core_bars = []
        self.core_labels = []

        self._setup_ui()

    def _setup_ui(self):
        self.setObjectName("CpuRamCard")
        self.setStyleSheet(f"""
            QFrame#CpuRamCard {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BG_CARD_BORDER};
                border-radius: 12px;
            }}
            QFrame#CpuRamCard:hover {{
                border: 1px solid {Theme.BORDER_ACCENT};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # 1. Header Row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        # Badge
        self.lbl_badge = QLabel("CPU & RAM")
        self.lbl_badge.setStyleSheet(f"""
            background-color: {self.accent_color}22;
            color: {self.accent_color};
            border: 1px solid {self.accent_color}66;
            border-radius: 5px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.5px;
        """)
        header_layout.addWidget(self.lbl_badge)

        # CPU Name
        self.lbl_name = QLabel("Processor & System Memory")
        self.lbl_name.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        header_layout.addWidget(self.lbl_name)

        header_layout.addStretch()

        # Cores & RAM specs pill
        self.lbl_specs = QLabel("Detecting hardware...")
        self.lbl_specs.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        header_layout.addWidget(self.lbl_specs)

        main_layout.addLayout(header_layout)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {Theme.BORDER_DEFAULT}; max-height: 1px;")
        main_layout.addWidget(divider)

        # 2. Main Stats Row (3 Columns: CPU Gauge | CPU Thermals & Power | RAM Section)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(20)

        # Col A: CPU Arc Gauge
        gauge_container = QVBoxLayout()
        gauge_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gauge = ArcGauge(size=130, accent_color=self.accent_color)
        self.gauge.title = "CPU LOAD"
        gauge_container.addWidget(self.gauge)
        stats_row.addLayout(gauge_container, stretch=0)

        # Col B: CPU Thermals & Power
        mid_col = QVBoxLayout()
        mid_col.setSpacing(10)

        # Thermal Bar
        self.thermal_bar = ThermalBar()
        mid_col.addWidget(self.thermal_bar)

        # CPU Power & Freq Box
        power_box = QVBoxLayout()
        power_box.setSpacing(4)
        power_hdr = QHBoxLayout()
        lbl_pwr_title = QLabel("CPU POWER & CLOCKS")
        lbl_pwr_title.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
        self.lbl_power_val = QLabel("0 W")
        self.lbl_power_val.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: bold;")
        power_hdr.addWidget(lbl_pwr_title)
        power_hdr.addStretch()
        power_hdr.addWidget(self.lbl_power_val)
        power_box.addLayout(power_hdr)

        self.power_bar = QProgressBar()
        self.power_bar.setFixedHeight(8)
        self.power_bar.setTextVisible(False)
        self.power_bar.setRange(0, 100)
        self.power_bar.setValue(0)
        self.power_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Theme.BG_SUBTLE};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: #ff9100;
                border-radius: 4px;
            }}
        """)
        power_box.addWidget(self.power_bar)

        self.lbl_freq = QLabel("Frequency: -- MHz")
        self.lbl_freq.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px;")
        power_box.addWidget(self.lbl_freq)
        mid_col.addLayout(power_box)

        stats_row.addLayout(mid_col, stretch=2)

        # Col C: RAM (System Memory)
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        # RAM Usage Section
        ram_box = QVBoxLayout()
        ram_box.setSpacing(4)
        ram_hdr = QHBoxLayout()
        lbl_ram_title = QLabel("SYSTEM RAM (MEMORY)")
        lbl_ram_title.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
        self.lbl_ram_val = QLabel("0.0 / 0.0 GB (0%)")
        self.lbl_ram_val.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: bold;")
        ram_hdr.addWidget(lbl_ram_title)
        ram_hdr.addStretch()
        ram_hdr.addWidget(self.lbl_ram_val)
        ram_box.addLayout(ram_hdr)

        self.ram_bar = QProgressBar()
        self.ram_bar.setFixedHeight(8)
        self.ram_bar.setTextVisible(False)
        self.ram_bar.setRange(0, 100)
        self.ram_bar.setValue(0)
        self.ram_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Theme.BG_SUBTLE};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {self.accent_color};
                border-radius: 4px;
            }}
        """)
        ram_box.addWidget(self.ram_bar)

        self.lbl_ram_free = QLabel("Available: -- GB")
        self.lbl_ram_free.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px;")
        ram_box.addWidget(self.lbl_ram_free)
        right_col.addLayout(ram_box)

        # Pagefile / Commit Box
        page_box = QVBoxLayout()
        page_box.setSpacing(4)
        lbl_page_title = QLabel("PAGEFILE / COMMIT CHARGE")
        lbl_page_title.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
        page_box.addWidget(lbl_page_title)

        self.lbl_page_val = QLabel("Pagefile: -- / -- GB")
        self.lbl_page_val.setStyleSheet("color: #f0f6fc; font-size: 11px;")
        page_box.addWidget(self.lbl_page_val)
        right_col.addLayout(page_box)

        stats_row.addLayout(right_col, stretch=2)

        main_layout.addLayout(stats_row)

        # 3. Rolling Sparkline Chart (60s History of CPU Load & CPU Temp)
        self.sparkline = SparklineChart(height=85, accent_color=self.accent_color)
        main_layout.addWidget(self.sparkline)

        # 4. Collapsible Logical Cores Heatmap Drawer
        self.cores_container = QWidget()
        cores_layout = QVBoxLayout(self.cores_container)
        cores_layout.setContentsMargins(0, 0, 0, 0)
        cores_layout.setSpacing(6)

        cores_hdr = QHBoxLayout()
        self.btn_cores_toggle = QPushButton("Logical Cores Breakdown (16 Threads) ▼")
        self.btn_cores_toggle.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {Theme.TEXT_SECONDARY};
                font-size: 11px;
                font-weight: bold;
                text-align: left;
                padding: 0px;
            }}
            QPushButton:hover {{
                color: {Theme.TEXT_PRIMARY};
            }}
        """)
        self.btn_cores_toggle.clicked.connect(self._toggle_cores_grid)
        cores_hdr.addWidget(self.btn_cores_toggle)
        cores_hdr.addStretch()
        cores_layout.addLayout(cores_hdr)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        self.grid_layout.setSpacing(6)
        self.grid_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {Theme.BG_ROOT};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 6px;
            }}
        """)
        self.grid_widget.setVisible(False)
        cores_layout.addWidget(self.grid_widget)

        main_layout.addWidget(self.cores_container)

    def _setup_cores_grid(self, count: int):
        # Clear existing
        while self.grid_layout.count() > 0:
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.core_bars.clear()
        self.core_labels.clear()

        # Place in 4 columns
        cols = 4
        for i in range(count):
            row = i // cols
            col = i % cols

            cell = QWidget()
            c_layout = QHBoxLayout(cell)
            c_layout.setContentsMargins(6, 2, 6, 2)
            c_layout.setSpacing(6)

            lbl_t = QLabel(f"T{i:02d}")
            lbl_t.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
            c_layout.addWidget(lbl_t)

            bar = QProgressBar()
            bar.setFixedHeight(6)
            bar.setTextVisible(False)
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {Theme.BG_SUBTLE};
                    border: none;
                    border-radius: 3px;
                }}
                QProgressBar::chunk {{
                    background-color: {self.accent_color};
                    border-radius: 3px;
                }}
            """)
            c_layout.addWidget(bar)

            lbl_val = QLabel("0%")
            lbl_val.setStyleSheet("color: #f0f6fc; font-size: 10px; min-width: 28px;")
            c_layout.addWidget(lbl_val)

            self.core_bars.append(bar)
            self.core_labels.append(lbl_val)
            self.grid_layout.addWidget(cell, row, col)

    def _toggle_cores_grid(self):
        is_vis = self.grid_widget.isVisible()
        self.grid_widget.setVisible(not is_vis)
        arrow = "▲" if not is_vis else "▼"
        cnt = len(self.core_bars)
        self.btn_cores_toggle.setText(f"Logical Cores Breakdown ({cnt} Threads) {arrow}")

    def set_compact_mode(self, compact: bool):
        self.is_compact = compact
        self.sparkline.setVisible(not compact)
        self.cores_container.setVisible(not compact)

    def update_metrics(self, m: HostMetrics):
        cpu = m.cpu
        ram = m.ram

        # Setup cores grid once
        if len(self.core_bars) != len(cpu.per_core_load) and len(cpu.per_core_load) > 0:
            self._setup_cores_grid(len(cpu.per_core_load))
            self.btn_cores_toggle.setText(f"Logical Cores Breakdown ({len(cpu.per_core_load)} Threads) ▼")

        # Header info
        if cpu.name:
            self.lbl_name.setText(cpu.name)
            self.lbl_specs.setText(f"{cpu.cores_physical} Cores • {cpu.cores_logical} Threads • {ram.total_gb:.0f} GB System RAM")

        # 1. Gauge
        self.gauge.set_value(cpu.load_percent)

        # 2. Thermals
        self.thermal_bar.set_thermal_data(
            temp_c=cpu.temp_core_c,
            hotspot_c=cpu.temp_hotspot_c,
            fan_pct=None,
        )

        # 3. CPU Power & Freq
        if cpu.power_draw_w is not None and cpu.power_draw_w > 0:
            self.lbl_power_val.setText(f"{cpu.power_draw_w:.1f} W")
            self.power_bar.setValue(int(min(100, cpu.power_draw_w)))
        else:
            self.lbl_power_val.setText("-- W")
            self.power_bar.setValue(0)

        if cpu.freq_mhz > 0:
            self.lbl_freq.setText(f"Frequency: {int(cpu.freq_mhz)} MHz ({cpu.freq_mhz/1000.0:.2f} GHz)")

        # 4. RAM
        if ram.total_gb > 0:
            self.lbl_ram_val.setText(f"{ram.used_gb:.1f} / {ram.total_gb:.1f} GB ({int(ram.load_percent)}%)")
            self.ram_bar.setValue(int(min(100, ram.load_percent)))
            self.lbl_ram_free.setText(f"Available: {ram.free_gb:.1f} GB")

        if ram.pagefile_total_gb > 0:
            self.lbl_page_val.setText(f"Pagefile: {ram.pagefile_used_gb:.1f} / {ram.pagefile_total_gb:.1f} GB")

        # 5. Sparkline
        self.sparkline.push_sample(cpu.load_percent, cpu.temp_core_c)

        # 6. Cores grid values
        if self.grid_widget.isVisible():
            for idx, c_load in enumerate(cpu.per_core_load):
                if idx < len(self.core_bars):
                    self.core_bars[idx].setValue(int(min(100, c_load)))
                    self.core_labels[idx].setText(f"{int(c_load)}%")
