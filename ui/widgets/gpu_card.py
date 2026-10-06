"""
Full-featured, responsive GPU Card component.
Contains arc gauge, thermal indicators, VRAM progress, power telemetry,
60-second rolling sparkline graph, and active processes drawer.
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QWidget, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from core.gpu_types import GpuDevice, GpuMetrics
from ui.theme import Theme
from ui.widgets.arc_gauge import ArcGauge
from ui.widgets.sparkline import SparklineChart
from ui.widgets.thermal_bar import ThermalBar


class GpuCard(QFrame):
    def __init__(self, device: GpuDevice, parent=None):
        super().__init__(parent)
        self.device = device
        self.accent_color = Theme.get_vendor_color(device.vendor)
        self.is_compact = False

        self._setup_ui()

    def _setup_ui(self):
        self.setObjectName("GpuCard")
        self.setStyleSheet(f"""
            QFrame#GpuCard {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BG_CARD_BORDER};
                border-radius: 12px;
            }}
            QFrame#GpuCard:hover {{
                border: 1px solid {Theme.BORDER_ACCENT};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # 1. Header Row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        # Vendor Badge
        self.lbl_vendor = QLabel(self.device.vendor.upper())
        self.lbl_vendor.setStyleSheet(f"""
            background-color: {self.accent_color}22;
            color: {self.accent_color};
            border: 1px solid {self.accent_color}66;
            border-radius: 5px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.5px;
        """)
        header_layout.addWidget(self.lbl_vendor)

        # GPU Name
        self.lbl_name = QLabel(self.device.name)
        self.lbl_name.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        header_layout.addWidget(self.lbl_name)

        header_layout.addStretch()

        # Bus / PCIe Info Pill
        bus_str = self.device.bus_id
        if self.device.pcie_gen and self.device.pcie_width:
            bus_str += f" • Gen{self.device.pcie_gen} x{self.device.pcie_width}"
        self.lbl_bus = QLabel(bus_str)
        self.lbl_bus.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
        header_layout.addWidget(self.lbl_bus)

        main_layout.addLayout(header_layout)

        # Divider line
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {Theme.BORDER_DEFAULT}; max-height: 1px;")
        main_layout.addWidget(divider)

        # 2. Main Stats Row (3 Columns: Gauge | Thermals & VRAM | Power & Clocks)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(20)

        # Col A: Arc Gauge
        gauge_container = QVBoxLayout()
        gauge_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gauge = ArcGauge(size=130, accent_color=self.accent_color)
        gauge_container.addWidget(self.gauge)
        stats_row.addLayout(gauge_container, stretch=0)

        # Col B: Thermals & VRAM
        mid_col = QVBoxLayout()
        mid_col.setSpacing(10)

        # Thermal Bar
        self.thermal_bar = ThermalBar()
        mid_col.addWidget(self.thermal_bar)

        # VRAM Section
        vram_box = QVBoxLayout()
        vram_box.setSpacing(4)
        vram_header = QHBoxLayout()
        lbl_vram_title = QLabel("VRAM USAGE")
        lbl_vram_title.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
        self.lbl_vram_val = QLabel("0.0 / 0.0 GB (0%)")
        self.lbl_vram_val.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: bold;")
        vram_header.addWidget(lbl_vram_title)
        vram_header.addStretch()
        vram_header.addWidget(self.lbl_vram_val)
        vram_box.addLayout(vram_header)

        # VRAM Progress Bar
        self.vram_bar = QProgressBar()
        self.vram_bar.setFixedHeight(8)
        self.vram_bar.setTextVisible(False)
        self.vram_bar.setRange(0, 100)
        self.vram_bar.setValue(0)
        self.vram_bar.setStyleSheet(f"""
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
        vram_box.addWidget(self.vram_bar)

        self.lbl_vram_free = QLabel("Free: --")
        self.lbl_vram_free.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px;")
        vram_box.addWidget(self.lbl_vram_free)
        mid_col.addLayout(vram_box)

        stats_row.addLayout(mid_col, stretch=2)

        # Col C: Power & Clocks
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        # Power Box
        power_box = QVBoxLayout()
        power_box.setSpacing(4)
        power_hdr = QHBoxLayout()
        lbl_pwr_title = QLabel("POWER DRAW")
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

        self.lbl_power_cap = QLabel("Limit: --")
        self.lbl_power_cap.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px;")
        power_box.addWidget(self.lbl_power_cap)
        right_col.addLayout(power_box)

        # Clocks Box
        clocks_box = QVBoxLayout()
        clocks_box.setSpacing(4)
        lbl_clk_title = QLabel("CORE & MEMORY CLOCKS")
        lbl_clk_title.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
        clocks_box.addWidget(lbl_clk_title)

        clks_row = QHBoxLayout()
        self.lbl_clk_core = QLabel("Core: -- MHz")
        self.lbl_clk_core.setStyleSheet("color: #f0f6fc; font-size: 11px;")
        self.lbl_clk_mem = QLabel("Mem: -- MHz")
        self.lbl_clk_mem.setStyleSheet("color: #f0f6fc; font-size: 11px;")
        clks_row.addWidget(self.lbl_clk_core)
        clks_row.addWidget(self.lbl_clk_mem)
        clocks_box.addLayout(clks_row)
        right_col.addLayout(clocks_box)

        stats_row.addLayout(right_col, stretch=2)

        main_layout.addLayout(stats_row)

        # 3. Rolling Sparkline Chart (60s History)
        self.sparkline = SparklineChart(height=85, accent_color=self.accent_color)
        main_layout.addWidget(self.sparkline)

        # 4. Collapsible Process Drawer
        self.proc_container = QWidget()
        proc_layout = QVBoxLayout(self.proc_container)
        proc_layout.setContentsMargins(0, 0, 0, 0)
        proc_layout.setSpacing(6)

        proc_hdr = QHBoxLayout()
        self.btn_proc_toggle = QPushButton("Active Processes (0) ▼")
        self.btn_proc_toggle.setStyleSheet(f"""
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
        self.btn_proc_toggle.clicked.connect(self._toggle_proc_table)
        proc_hdr.addWidget(self.btn_proc_toggle)
        proc_hdr.addStretch()
        proc_layout.addLayout(proc_hdr)

        self.table_procs = QTableWidget()
        self.table_procs.setColumnCount(3)
        self.table_procs.setHorizontalHeaderLabels(["Process Name", "PID", "Type"])
        self.table_procs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_procs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_procs.verticalHeader().setVisible(False)
        self.table_procs.setFixedHeight(95)
        self.table_procs.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table_procs.setVisible(False)
        proc_layout.addWidget(self.table_procs)

        main_layout.addWidget(self.proc_container)

    def _toggle_proc_table(self):
        is_vis = self.table_procs.isVisible()
        self.table_procs.setVisible(not is_vis)
        arrow = "▲" if not is_vis else "▼"
        cnt = self.table_procs.rowCount()
        self.btn_proc_toggle.setText(f"Active Processes ({cnt}) {arrow}")

    def set_compact_mode(self, compact: bool):
        self.is_compact = compact
        self.sparkline.setVisible(not compact)
        self.proc_container.setVisible(not compact)

    def update_metrics(self, m: GpuMetrics):
        # 1. Gauge
        self.gauge.set_value(m.gpu_util_percent, m.mem_util_percent)

        # 2. Thermals
        self.thermal_bar.set_thermal_data(
            temp_c=m.temp_core_c,
            hotspot_c=m.temp_hotspot_c or m.temp_extra_c,
            fan_pct=m.fan_speed_percent,
            fan_rpm=m.fan_speed_rpm,
        )

        # 3. VRAM
        if m.vram_total_mb > 0:
            used_gb = m.vram_used_mb / 1024.0
            total_gb = m.vram_total_mb / 1024.0
            pct = int((m.vram_used_mb / m.vram_total_mb) * 100)
            self.lbl_vram_val.setText(f"{used_gb:.1f} / {total_gb:.1f} GB ({pct}%)")
            self.vram_bar.setValue(min(100, pct))
            free_gb = max(0.0, total_gb - used_gb)
            self.lbl_vram_free.setText(f"Free: {free_gb:.1f} GB")
        else:
            self.lbl_vram_val.setText("N/A")
            self.vram_bar.setValue(0)
            self.lbl_vram_free.setText("Free: --")

        # 4. Power
        if m.power_draw_w > 0:
            if m.power_limit_w and m.power_limit_w > 0:
                p_pct = int((m.power_draw_w / m.power_limit_w) * 100)
                self.lbl_power_val.setText(f"{m.power_draw_w:.1f} W ({p_pct}%)")
                self.power_bar.setValue(min(100, p_pct))
                self.lbl_power_cap.setText(f"Limit: {m.power_limit_w:.0f} W TDP")
            else:
                self.lbl_power_val.setText(f"{m.power_draw_w:.1f} W")
                self.power_bar.setValue(int(min(100, m.power_draw_w)))
                self.lbl_power_cap.setText("Limit: --")
        else:
            self.lbl_power_val.setText("-- W")
            self.power_bar.setValue(0)
            self.lbl_power_cap.setText("Limit: --")

        # 5. Clocks
        core_clk = f"Core: {m.clock_graphics_mhz} MHz" if m.clock_graphics_mhz else "Core: --"
        mem_clk = f"Mem: {m.clock_memory_mhz} MHz" if m.clock_memory_mhz else "Mem: --"
        self.lbl_clk_core.setText(core_clk)
        self.lbl_clk_mem.setText(mem_clk)

        # 6. Sparkline
        self.sparkline.push_sample(m.gpu_util_percent, m.temp_core_c)

        # 7. Processes
        if not self.is_compact:
            self._update_process_list(m.processes)

    def _update_process_list(self, procs):
        cnt = len(procs)
        arrow = "▲" if self.table_procs.isVisible() else "▼"
        self.btn_proc_toggle.setText(f"Active Processes ({cnt}) {arrow}")

        if not self.table_procs.isVisible():
            return

        self.table_procs.setRowCount(cnt)
        for row, p in enumerate(procs):
            name_item = QTableWidgetItem(p.name)
            pid_item = QTableWidgetItem(str(p.pid))
            type_item = QTableWidgetItem(p.process_type)

            pid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.table_procs.setItem(row, 0, name_item)
            self.table_procs.setItem(row, 1, pid_item)
            self.table_procs.setItem(row, 2, type_item)
