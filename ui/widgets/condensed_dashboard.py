"""
Ultra-Condensed Single-Screen Dashboard Widget (`CondensedDashboardWidget`).
Provides a high-density, `bpytop`-inspired GUI view of Everything in one compact layout:
- Host CPU & System RAM (2 dense rows with progress bars, temps, power, clocks, SMBIOS channel/DIMM info)
- Local GPUs (1 dense row per GPU with Load bar, VRAM/GTT bar, Edge/Junc/Mem temps, Fan RPM, Power, Clocks)
- Tailscale & LAN Network GPUs (inline Tailscale ON/OFF toggle, per-node ON/OFF, 1 dense row per remote GPU)
- Active GPU Workloads (Compute/Graphics processes + VRAM MB) & Hardware Specs Summary Strip
"""

from typing import Dict, List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QProgressBar, QPushButton, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.gpu_types import GpuDevice, GpuMetrics, HostMetrics
from core.hardware_info import SystemHardwareSpecs
from core.network_telemetry import NetworkTelemetryManager, RemoteNodeState
from ui.theme import Theme


def _make_bar(color: str, width: int = 64, height: int = 6) -> QProgressBar:
    bar = QProgressBar()
    bar.setFixedSize(width, height)
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
            background-color: {color};
            border-radius: 3px;
        }}
    """)
    return bar


class CondensedDashboardWidget(QWidget):
    request_full_specs = pyqtSignal()
    request_manage_network = pyqtSignal()

    def __init__(
        self,
        hw_specs: SystemHardwareSpecs,
        net_manager: NetworkTelemetryManager,
        parent=None,
    ):
        super().__init__(parent)
        self.hw_specs = hw_specs
        self.net_manager = net_manager
        self.local_devices: List[GpuDevice] = []
        self.local_metrics: Dict[str, GpuMetrics] = {}
        self.host_metrics: Optional[HostMetrics] = None
        self._local_row_widgets: Dict[str, dict] = {}

        self._setup_ui()
        self.net_manager.nodes_updated.connect(self.update_network_nodes)
        self.net_manager.tailscale_enabled_changed.connect(self._on_tailscale_enabled_changed)
        self.net_manager.tailnet_scan_status.connect(self._on_tailnet_scan_status)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # =====================================================================
        # 1. HOST CPU & SYSTEM RAM CONDENSED BOX
        # =====================================================================
        self.host_frame = QFrame()
        self.host_frame.setStyleSheet(f"""
            QFrame#CondHostFrame {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BG_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        self.host_frame.setObjectName("CondHostFrame")
        host_layout = QVBoxLayout(self.host_frame)
        host_layout.setContentsMargins(10, 7, 10, 7)
        host_layout.setSpacing(5)

        # Row 1: CPU
        cpu_row = QHBoxLayout()
        cpu_row.setSpacing(8)

        lbl_cpu_tag = QLabel("CPU")
        lbl_cpu_tag.setFixedWidth(36)
        lbl_cpu_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_cpu_tag.setStyleSheet(f"""
            background-color: {Theme.CYBER_CYAN}22;
            color: {Theme.CYBER_CYAN};
            border: 1px solid {Theme.CYBER_CYAN}66;
            border-radius: 4px;
            font-size: 9px;
            font-weight: 800;
            padding: 1px 4px;
        """)
        cpu_row.addWidget(lbl_cpu_tag)

        cpu_name = self.hw_specs.cpu.name or "Processor"
        self.lbl_cpu_name = QLabel(cpu_name[:38])
        self.lbl_cpu_name.setMinimumWidth(190)
        self.lbl_cpu_name.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: 700;")
        cpu_row.addWidget(self.lbl_cpu_name, stretch=2)

        self.cpu_bar = _make_bar(Theme.CYBER_CYAN, 70, 6)
        cpu_row.addWidget(self.cpu_bar)

        self.lbl_cpu_load = QLabel("  0%")
        self.lbl_cpu_load.setFixedWidth(38)
        self.lbl_cpu_load.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 800;")
        cpu_row.addWidget(self.lbl_cpu_load)

        self.lbl_cpu_temp = QLabel("🌡 --°C")
        self.lbl_cpu_temp.setFixedWidth(105)
        self.lbl_cpu_temp.setStyleSheet(f"color: {Theme.TEMP_COOL}; font-size: 11px; font-weight: 700;")
        cpu_row.addWidget(self.lbl_cpu_temp)

        self.lbl_cpu_pwr = QLabel("⚡ -- W")
        self.lbl_cpu_pwr.setFixedWidth(68)
        self.lbl_cpu_pwr.setStyleSheet(f"color: {Theme.TEMP_WARM}; font-size: 11px; font-weight: 700;")
        cpu_row.addWidget(self.lbl_cpu_pwr)

        self.lbl_cpu_clk = QLabel("-- GHz")
        self.lbl_cpu_clk.setMinimumWidth(140)
        self.lbl_cpu_clk.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
        cpu_row.addWidget(self.lbl_cpu_clk, stretch=2)

        host_layout.addLayout(cpu_row)

        # Row 2: System RAM & Platform
        ram_row = QHBoxLayout()
        ram_row.setSpacing(8)

        lbl_ram_tag = QLabel("RAM")
        lbl_ram_tag.setFixedWidth(36)
        lbl_ram_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_ram_tag.setStyleSheet(f"""
            background-color: {Theme.CYBER_PURPLE}22;
            color: {Theme.CYBER_PURPLE};
            border: 1px solid {Theme.CYBER_PURPLE}66;
            border-radius: 4px;
            font-size: 9px;
            font-weight: 800;
            padding: 1px 4px;
        """)
        ram_row.addWidget(lbl_ram_tag)

        r = self.hw_specs.ram
        ch_short = "Dual-Ch" if "Dual" in r.channel_mode else ("Quad-Ch" if "Quad" in r.channel_mode else (r.channel_mode or "System RAM"))
        ram_desc = f"{r.mem_type} {ch_short}"
        if r.configured_speed_mts:
            ram_desc += f" @ {r.configured_speed_mts} MT/s"
        if r.slots_used and r.slots_total:
            ram_desc += f" ({r.slots_used}/{r.slots_total} DIMMs)"
        self.lbl_ram_spec = QLabel(ram_desc[:38])
        self.lbl_ram_spec.setMinimumWidth(190)
        self.lbl_ram_spec.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: 700;")
        ram_row.addWidget(self.lbl_ram_spec, stretch=2)

        self.ram_bar = _make_bar(Theme.CYBER_PURPLE, 70, 6)
        ram_row.addWidget(self.ram_bar)

        self.lbl_ram_pct = QLabel("  0%")
        self.lbl_ram_pct.setFixedWidth(38)
        self.lbl_ram_pct.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 800;")
        ram_row.addWidget(self.lbl_ram_pct)

        self.lbl_ram_used = QLabel("0.0 / 0.0 GB")
        self.lbl_ram_used.setFixedWidth(105)
        self.lbl_ram_used.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 700;")
        ram_row.addWidget(self.lbl_ram_used)

        self.lbl_ram_free = QLabel("Free: -- GB")
        self.lbl_ram_free.setFixedWidth(85)
        self.lbl_ram_free.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px;")
        ram_row.addWidget(self.lbl_ram_free)

        mb = self.hw_specs.motherboard
        mb_txt = f"{mb.product} (BIOS {mb.bios_version})" if mb.product else ""
        self.lbl_mobo = QLabel(mb_txt[:42])
        self.lbl_mobo.setMinimumWidth(120)
        self.lbl_mobo.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px; font-weight: 600;")
        ram_row.addWidget(self.lbl_mobo, stretch=2)

        host_layout.addLayout(ram_row)
        root.addWidget(self.host_frame)

        # =====================================================================
        # 2. LOCAL GPUs CONDENSED BOX
        # =====================================================================
        self.local_frame = QFrame()
        self.local_frame.setObjectName("CondLocalFrame")
        self.local_frame.setStyleSheet(f"""
            QFrame#CondLocalFrame {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BG_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        local_outer = QVBoxLayout(self.local_frame)
        local_outer.setContentsMargins(10, 6, 10, 7)
        local_outer.setSpacing(4)

        local_hdr = QHBoxLayout()
        local_hdr.setSpacing(8)
        self.lbl_local_title = QLabel("⚡ LOCAL GPUs (0)")
        self.lbl_local_title.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 11px; font-weight: 800; letter-spacing: 0.4px;")
        local_hdr.addWidget(self.lbl_local_title)
        local_hdr.addStretch()
        self.lbl_local_summary = QLabel("VRAM: 0.0/0.0 GB • 🔥 0.0 W")
        self.lbl_local_summary.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: 700;")
        local_hdr.addWidget(self.lbl_local_summary)
        local_outer.addLayout(local_hdr)

        self.local_rows_container = QWidget()
        self.local_rows_layout = QVBoxLayout(self.local_rows_container)
        self.local_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.local_rows_layout.setSpacing(4)
        local_outer.addWidget(self.local_rows_container)

        root.addWidget(self.local_frame)

        # =====================================================================
        # 3. TAILSCALE & NETWORK GPUs CONDENSED BOX
        # =====================================================================
        self.net_frame = QFrame()
        self.net_frame.setObjectName("CondNetFrame")
        self.net_frame.setStyleSheet(f"""
            QFrame#CondNetFrame {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BG_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        net_outer = QVBoxLayout(self.net_frame)
        net_outer.setContentsMargins(10, 6, 10, 7)
        net_outer.setSpacing(4)

        net_hdr = QHBoxLayout()
        net_hdr.setSpacing(6)

        self.lbl_net_title = QLabel("🌐 TAILSCALE & NETWORK GPUs")
        self.lbl_net_title.setStyleSheet(f"color: {Theme.CYBER_PURPLE}; font-size: 11px; font-weight: 800; letter-spacing: 0.4px;")
        net_hdr.addWidget(self.lbl_net_title)

        self.lbl_net_summary = QLabel("")
        self.lbl_net_summary.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: 700;")
        net_hdr.addWidget(self.lbl_net_summary)

        net_hdr.addStretch()

        # Inline Tailscale ON/OFF toggle button
        self.btn_ts_toggle = QPushButton()
        self.btn_ts_toggle.setCheckable(True)
        self.btn_ts_toggle.setChecked(self.net_manager.tailscale_enabled)
        self.btn_ts_toggle.setToolTip("Turn Tailscale-based GPU monitoring ON or OFF")
        self.btn_ts_toggle.clicked.connect(lambda c: self.net_manager.set_tailscale_enabled(c))
        self._style_ts_btn(self.net_manager.tailscale_enabled)
        net_hdr.addWidget(self.btn_ts_toggle)

        # Scan Tailnet mini button
        self.btn_ts_scan = QPushButton("🦊 Scan")
        self.btn_ts_scan.setToolTip("Scan Tailscale Tailnet for GPU machines")
        self.btn_ts_scan.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.CYBER_PURPLE}22;
                color: {Theme.CYBER_PURPLE};
                border: 1px solid {Theme.CYBER_PURPLE}66;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {Theme.CYBER_PURPLE}33; }}
        """)
        self.btn_ts_scan.clicked.connect(self._on_scan_tailnet)
        net_hdr.addWidget(self.btn_ts_scan)

        # Manage nodes mini button
        self.btn_net_manage = QPushButton("⚙ Nodes")
        self.btn_net_manage.setToolTip("Open Network Nodes Manager to add/remove custom hosts")
        self.btn_net_manage.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.BG_SUBTLE};
                color: {Theme.TEXT_SECONDARY};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{ color: #ffffff; }}
        """)
        self.btn_net_manage.clicked.connect(self.request_manage_network.emit)
        net_hdr.addWidget(self.btn_net_manage)

        net_outer.addLayout(net_hdr)

        self.net_rows_container = QWidget()
        self.net_rows_layout = QVBoxLayout(self.net_rows_container)
        self.net_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.net_rows_layout.setSpacing(3)
        net_outer.addWidget(self.net_rows_container)

        root.addWidget(self.net_frame)

        # =====================================================================
        # 4. ACTIVE GPU WORKLOADS & HARDWARE SPECS STRIP
        # =====================================================================
        self.bottom_frame = QFrame()
        self.bottom_frame.setObjectName("CondBottomFrame")
        self.bottom_frame.setStyleSheet(f"""
            QFrame#CondBottomFrame {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BG_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        bot_outer = QVBoxLayout(self.bottom_frame)
        bot_outer.setContentsMargins(10, 6, 10, 6)
        bot_outer.setSpacing(4)

        # Processes Row
        proc_hdr = QHBoxLayout()
        proc_hdr.setSpacing(8)
        self.lbl_procs_title = QLabel("⚙ ACTIVE GPU WORKLOADS (0)")
        self.lbl_procs_title.setStyleSheet(f"color: {Theme.CYBER_CYAN}; font-size: 10px; font-weight: 800;")
        proc_hdr.addWidget(self.lbl_procs_title)

        self.lbl_procs_inline = QLabel("No active compute/graphics GPU processes.")
        self.lbl_procs_inline.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: 600;")
        proc_hdr.addWidget(self.lbl_procs_inline, stretch=1)
        bot_outer.addLayout(proc_hdr)

        # Hardware Specs Summary Strip
        hw_row = QHBoxLayout()
        hw_row.setSpacing(8)
        lbl_hw_tag = QLabel("🧬 SPECS")
        lbl_hw_tag.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 10px; font-weight: 800;")
        hw_row.addWidget(lbl_hw_tag)

        self.lbl_hw_summary = QLabel(self._build_hw_one_liner())
        self.lbl_hw_summary.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px; font-weight: 600;")
        hw_row.addWidget(self.lbl_hw_summary, stretch=1)

        self.btn_copy_hw = QPushButton("📋 Copy Specs")
        self.btn_copy_hw.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.BG_SUBTLE};
                color: {Theme.TEXT_SECONDARY};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{ color: #ffffff; }}
        """)
        self.btn_copy_hw.clicked.connect(self._copy_hw_summary)
        hw_row.addWidget(self.btn_copy_hw)

        self.btn_open_specs = QPushButton("🧬 Full Specs")
        self.btn_open_specs.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.BG_SUBTLE};
                color: {Theme.TEXT_SECONDARY};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{ color: #ffffff; }}
        """)
        self.btn_open_specs.clicked.connect(self.request_full_specs.emit)
        hw_row.addWidget(self.btn_open_specs)

        bot_outer.addLayout(hw_row)
        root.addWidget(self.bottom_frame)

        root.addStretch(1)
        self.update_network_nodes(self.net_manager.get_visible_states())

    def _build_hw_one_liner(self) -> str:
        s = self.hw_specs
        parts = []
        if s.cpu.name:
            parts.append(f"{s.cpu.name} ({s.cpu.cores_physical}C/{s.cpu.cores_logical}T)")
        if s.ram.total_installed_gb > 0:
            parts.append(f"{s.ram.total_installed_gb:.0f}GB {s.ram.mem_type} @ {s.ram.configured_speed_mts or '--'} MT/s")
        if s.motherboard.product:
            parts.append(f"Board: {s.motherboard.product}")
        if s.storage_drives:
            parts.append(f"Disks: {len(s.storage_drives)} ({s.storage_drives[0].model[:20]})")
        if s.os_info.os_name:
            parts.append(s.os_info.os_name)
        return " • ".join(parts)

    def _copy_hw_summary(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._build_hw_one_liner())
            self.btn_copy_hw.setText("✅ Copied")

    def _style_ts_btn(self, enabled: bool):
        self.btn_ts_toggle.blockSignals(True)
        self.btn_ts_toggle.setChecked(enabled)
        self.btn_ts_toggle.blockSignals(False)
        if enabled:
            self.btn_ts_toggle.setText("🦊 Tailscale: ON")
            self.btn_ts_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.NVIDIA_GREEN}22;
                    color: {Theme.NVIDIA_GREEN};
                    border: 1px solid {Theme.NVIDIA_GREEN}88;
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 10px;
                    font-weight: 800;
                }}
                QPushButton:hover {{ background-color: {Theme.NVIDIA_GREEN}33; }}
            """)
        else:
            self.btn_ts_toggle.setText("🦊 Tailscale: OFF")
            self.btn_ts_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.BG_SUBTLE};
                    color: {Theme.TEXT_MUTED};
                    border: 1px solid {Theme.BORDER_DEFAULT};
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 10px;
                    font-weight: 700;
                }}
                QPushButton:hover {{ color: {Theme.TEXT_PRIMARY}; }}
            """)

    def _on_tailscale_enabled_changed(self, enabled: bool):
        self._style_ts_btn(enabled)
        self.btn_ts_scan.setEnabled(enabled)
        self.update_network_nodes(self.net_manager.get_visible_states())

    def _on_tailnet_scan_status(self, msg: str):
        if msg:
            self.btn_ts_scan.setText("🦊 Scanning...")
        else:
            self.btn_ts_scan.setText("🦊 Scan")

    def _on_scan_tailnet(self):
        if not self.net_manager.tailscale_enabled:
            self.net_manager.set_tailscale_enabled(True)
        self.btn_ts_scan.setText("🦊 Scanning...")
        self.net_manager.request_tailnet_scan(force_reprobe=True)

    def _clear_layout(self, layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def set_local_devices(self, devices: List[GpuDevice]):
        self.local_devices = devices
        self._local_row_widgets.clear()
        self._clear_layout(self.local_rows_layout)

        self.lbl_local_title.setText(f"⚡ LOCAL GPUs ({len(devices)})")
        if not devices:
            lbl = QLabel("No local discrete/integrated GPUs detected.")
            lbl.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
            self.local_rows_layout.addWidget(lbl)
            return

        for dev in devices:
            row_w = QFrame()
            row_w.setStyleSheet(f"""
                QFrame {{
                    background-color: {Theme.BG_ROOT};
                    border: 1px solid {Theme.BORDER_DEFAULT};
                    border-radius: 5px;
                }}
            """)
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(8, 4, 8, 4)
            rl.setSpacing(8)

            v_col = Theme.get_vendor_color(dev.vendor)
            badge = QLabel(f"GPU{dev.index}")
            badge.setFixedWidth(40)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"""
                background-color: {v_col}22;
                color: {v_col};
                border: 1px solid {v_col}66;
                border-radius: 3px;
                font-size: 9px;
                font-weight: 800;
            """)
            rl.addWidget(badge)

            arch_s = f" ({dev.architecture})" if dev.architecture else ""
            lbl_name = QLabel(f"{dev.name[:28]}{arch_s[:14]}")
            lbl_name.setMinimumWidth(185)
            lbl_name.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: 700; border: none;")
            lbl_name.setToolTip(f"{dev.name} • {dev.architecture} • PCIe Gen{dev.pcie_gen}x{dev.pcie_width} • Driver {dev.driver_version}")
            rl.addWidget(lbl_name, stretch=2)

            load_bar = _make_bar(v_col, 55, 6)
            rl.addWidget(load_bar)

            lbl_load = QLabel("  0%")
            lbl_load.setFixedWidth(36)
            lbl_load.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 700; border: none;")
            rl.addWidget(lbl_load)

            vram_bar = _make_bar(Theme.CYBER_CYAN, 55, 6)
            rl.addWidget(vram_bar)

            lbl_vram = QLabel("VRAM --")
            lbl_vram.setFixedWidth(155)
            lbl_vram.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 600; border: none;")
            rl.addWidget(lbl_vram)

            lbl_therm = QLabel("🌡 --°C")
            lbl_therm.setMinimumWidth(175)
            lbl_therm.setStyleSheet(f"color: {Theme.TEMP_COOL}; font-size: 11px; font-weight: 700; border: none;")
            rl.addWidget(lbl_therm, stretch=2)

            lbl_pwr_clk = QLabel("🔥 -- W • -- MHz")
            lbl_pwr_clk.setMinimumWidth(145)
            lbl_pwr_clk.setStyleSheet(f"color: {Theme.TEMP_WARM}; font-size: 11px; font-weight: 700; border: none;")
            rl.addWidget(lbl_pwr_clk, stretch=1)

            self.local_rows_layout.addWidget(row_w)
            self._local_row_widgets[dev.device_id] = {
                "load_bar": load_bar,
                "lbl_load": lbl_load,
                "vram_bar": vram_bar,
                "lbl_vram": lbl_vram,
                "lbl_therm": lbl_therm,
                "lbl_pwr_clk": lbl_pwr_clk,
            }

    def update_host_metrics(self, host_metrics: HostMetrics):
        self.host_metrics = host_metrics
        cpu = host_metrics.cpu
        ram = host_metrics.ram

        if cpu.name:
            self.lbl_cpu_name.setText(cpu.name[:38])
        self.cpu_bar.setValue(int(min(100, max(0, cpu.load_percent))))
        self.lbl_cpu_load.setText(f"{cpu.load_percent:3.0f}%")

        t_col = Theme.get_temp_color(cpu.temp_core_c)
        t_stat = Theme.get_temp_status(cpu.temp_core_c)[:4]
        if cpu.temp_core_c > 0:
            self.lbl_cpu_temp.setText(f"🌡 {cpu.temp_core_c:.0f}°C [{t_stat}]")
            self.lbl_cpu_temp.setStyleSheet(f"color: {t_col}; font-size: 11px; font-weight: 700;")
        else:
            self.lbl_cpu_temp.setText("🌡 --°C")

        if cpu.power_draw_w and cpu.power_draw_w > 0:
            self.lbl_cpu_pwr.setText(f"⚡ {cpu.power_draw_w:.1f}W")
        else:
            self.lbl_cpu_pwr.setText("⚡ -- W")

        clk_s = f"{cpu.freq_mhz / 1000.0:.2f} GHz" if cpu.freq_mhz > 0 else "-- GHz"
        if cpu.per_core_load:
            peak_c = max(cpu.per_core_load)
            clk_s += f" • Peak Core: {peak_c:.0f}%"
        self.lbl_cpu_clk.setText(clk_s)

        if ram.total_gb > 0:
            self.ram_bar.setValue(int(min(100, max(0, ram.load_percent))))
            self.lbl_ram_pct.setText(f"{ram.load_percent:3.0f}%")
            self.lbl_ram_used.setText(f"{ram.used_gb:.1f}/{ram.total_gb:.1f} GB")
            self.lbl_ram_free.setText(f"Free: {ram.free_gb:.1f}G")

    def update_local_metrics(self, metrics_by_id: Dict[str, GpuMetrics]):
        self.local_metrics = metrics_by_id
        tot_u = 0.0
        tot_t = 0.0
        tot_w = 0.0
        all_procs = []

        for dev in self.local_devices:
            m = metrics_by_id.get(dev.device_id)
            if not m:
                continue
            tot_u += m.vram_used_mb / 1024.0
            tot_t += m.vram_total_mb / 1024.0
            tot_w += m.power_draw_w
            for p in m.processes:
                all_procs.append((f"GPU{dev.index}", p))

            w = self._local_row_widgets.get(dev.device_id)
            if not w:
                continue

            w["load_bar"].setValue(int(min(100, max(0, m.gpu_util_percent))))
            w["lbl_load"].setText(f"{m.gpu_util_percent:3.0f}%")

            if m.vram_total_mb > 0:
                u_gb = m.vram_used_mb / 1024.0
                t_gb = m.vram_total_mb / 1024.0
                v_pct = int(min(100, max(0, (m.vram_used_mb / m.vram_total_mb) * 100.0)))
                w["vram_bar"].setValue(v_pct)
                gtt_s = f" +{m.shared_used_mb/1024.0:.1f}G" if m.shared_used_mb >= 100 else ""
                w["lbl_vram"].setText(f"{u_gb:4.1f}/{t_gb:4.1f}GB ({v_pct:2d}%){gtt_s}")
            else:
                w["vram_bar"].setValue(0)
                w["lbl_vram"].setText("Shared Host RAM")

            eff_t = max(m.temp_core_c, (m.temp_hotspot_c - 22.0) if m.temp_hotspot_c else 0.0)
            t_col = Theme.get_temp_color(eff_t)
            t_stat = Theme.get_temp_status(eff_t)[:4]
            t_parts = [f"🌡{m.temp_core_c:.0f}°C [{t_stat}]"]
            if m.temp_hotspot_c and m.temp_hotspot_c > 0:
                t_parts.append(f"J:{m.temp_hotspot_c:.0f}°")
            if m.temp_memory_c and m.temp_memory_c > 0:
                t_parts.append(f"M:{m.temp_memory_c:.0f}°")
            if m.fan_speed_rpm and m.fan_speed_rpm > 0:
                t_parts.append(f"🌀{m.fan_speed_rpm}")
            elif m.fan_speed_percent is not None and m.fan_speed_percent > 0:
                t_parts.append(f"🌀{m.fan_speed_percent:.0f}%")
            w["lbl_therm"].setText(" ".join(t_parts))
            w["lbl_therm"].setStyleSheet(f"color: {t_col}; font-size: 11px; font-weight: 700; border: none;")

            if m.power_draw_w > 0:
                p_s = f"🔥{m.power_draw_w:.0f}/{m.power_limit_w:.0f}W" if m.power_limit_w else f"🔥{m.power_draw_w:.1f}W"
            else:
                p_s = "🔥--W"
            c_s = f"{m.clock_graphics_mhz or '--'}/{m.clock_memory_mhz or '--'}MHz"
            w["lbl_pwr_clk"].setText(f"{p_s} • {c_s}")

        self.lbl_local_summary.setText(f"VRAM: {tot_u:.1f}/{tot_t:.1f} GB • 🔥 {tot_w:.1f} W")

        # Update processes inline summary
        self.lbl_procs_title.setText(f"⚙ ACTIVE GPU WORKLOADS ({len(all_procs)})")
        if all_procs:
            proc_strs = []
            for gpu_tag, p in all_procs[:5]:
                mem_s = f" ({p.memory_used_mb:.0f}MB)" if p.memory_used_mb else ""
                proc_strs.append(f"[{gpu_tag}] {p.name} (PID {p.pid}, {p.process_type}{mem_s})")
            self.lbl_procs_inline.setText("   •   ".join(proc_strs))
        else:
            self.lbl_procs_inline.setText("No active compute/graphics GPU processes.")

    def update_network_nodes(self, states: Dict[str, RemoteNodeState]):
        self._clear_layout(self.net_rows_layout)

        online_gpus = [
            (st, g, st.gpu_metrics.get(g.device_id, g.metrics))
            for st in states.values() if st.online for g in st.gpus
        ]
        net_u = sum(m.vram_used_mb for _, _, m in online_gpus) / 1024.0
        net_t = sum(m.vram_total_mb for _, _, m in online_gpus) / 1024.0
        net_w = sum(m.power_draw_w for _, _, m in online_gpus)
        peak_t = max((m.temp_core_c for _, _, m in online_gpus), default=0.0)

        self.lbl_net_title.setText(f"🌐 TAILSCALE & NETWORK GPUs ({len(online_gpus)})")
        if online_gpus:
            self.lbl_net_summary.setText(
                f"— VRAM: {net_u:.1f}/{net_t:.1f} GB • 🔥 {net_w:.1f} W • 🌡 Peak {peak_t:.0f}°C"
            )
        elif not self.net_manager.tailscale_enabled:
            self.lbl_net_summary.setText("— Tailscale Monitoring OFF")
        else:
            self.lbl_net_summary.setText("— Scanning / Idle")

        if not self.net_manager.tailscale_enabled and not states:
            lbl = QLabel("🦊 Tailscale GPU monitoring is turned OFF. Click '🦊 Tailscale: OFF' above to enable.")
            lbl.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
            self.net_rows_layout.addWidget(lbl)
            return

        if not states:
            lbl = QLabel("No remote Tailnet/LAN GPUs currently active. Click '🦊 Scan' to probe Tailscale peers.")
            lbl.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
            self.net_rows_layout.addWidget(lbl)
            return

        def _sort_key(item):
            _, st = item
            max_vram = max((g.vram_total_mb for g in st.gpus), default=0.0)
            return (not st.online, -max_vram, st.hostname.lower())

        for node_id, st in sorted(states.items(), key=_sort_key):
            if not st.online or not st.gpus:
                continue
            for dev in st.gpus:
                m = st.gpu_metrics.get(dev.device_id, dev.metrics)
                row_w = QFrame()
                row_w.setStyleSheet(f"""
                    QFrame {{
                        background-color: {Theme.BG_ROOT};
                        border: 1px solid {Theme.BORDER_DEFAULT};
                        border-radius: 5px;
                    }}
                """)
                rl = QHBoxLayout(row_w)
                rl.setContentsMargins(8, 3, 8, 3)
                rl.setSpacing(8)

                lbl_host = QLabel(f"● {st.hostname[:12]}")
                lbl_host.setFixedWidth(105)
                lbl_host.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 11px; font-weight: 800; border: none;")
                lbl_host.setToolTip(f"{st.hostname} ({st.tailscale_ip or st.address}) • {st.latency_ms:.0f} ms")
                rl.addWidget(lbl_host)

                v_col = Theme.get_vendor_color(dev.vendor)
                lbl_gpu = QLabel(dev.name[:28])
                lbl_gpu.setMinimumWidth(175)
                lbl_gpu.setStyleSheet(f"color: {v_col}; font-size: 11px; font-weight: 700; border: none;")
                rl.addWidget(lbl_gpu, stretch=2)

                load_bar = _make_bar(v_col, 50, 6)
                load_bar.setValue(int(min(100, max(0, m.gpu_util_percent))))
                rl.addWidget(load_bar)

                lbl_load = QLabel(f"{m.gpu_util_percent:3.0f}%")
                lbl_load.setFixedWidth(36)
                lbl_load.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 700; border: none;")
                rl.addWidget(lbl_load)

                vram_bar = _make_bar(Theme.CYBER_CYAN, 55, 6)
                if m.vram_total_mb > 0:
                    u_gb = m.vram_used_mb / 1024.0
                    t_gb = m.vram_total_mb / 1024.0
                    v_pct = int(min(100, max(0, (m.vram_used_mb / m.vram_total_mb) * 100.0)))
                    vram_bar.setValue(v_pct)
                    v_txt = f"{u_gb:4.1f}/{t_gb:4.1f}GB ({v_pct:2d}%)"
                else:
                    vram_bar.setValue(0)
                    v_txt = "Shared iGPU RAM"
                rl.addWidget(vram_bar)

                lbl_vram = QLabel(v_txt)
                lbl_vram.setFixedWidth(135)
                lbl_vram.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 600; border: none;")
                rl.addWidget(lbl_vram)

                eff_t = max(m.temp_core_c, (m.temp_hotspot_c - 22.0) if m.temp_hotspot_c else 0.0)
                t_col = Theme.get_temp_color(eff_t)
                t_stat = Theme.get_temp_status(eff_t)[:4]
                t_parts = [f"🌡{m.temp_core_c:.0f}°C [{t_stat}]"]
                if m.temp_hotspot_c and m.temp_hotspot_c > 0:
                    t_parts.append(f"J:{m.temp_hotspot_c:.0f}°")
                if m.temp_memory_c and m.temp_memory_c > 0:
                    t_parts.append(f"M:{m.temp_memory_c:.0f}°")
                if m.fan_speed_rpm and m.fan_speed_rpm > 0:
                    t_parts.append(f"🌀{m.fan_speed_rpm}")
                lbl_therm = QLabel(" ".join(t_parts))
                lbl_therm.setMinimumWidth(165)
                lbl_therm.setStyleSheet(f"color: {t_col}; font-size: 11px; font-weight: 700; border: none;")
                rl.addWidget(lbl_therm, stretch=2)

                if m.power_draw_w > 0:
                    p_s = f"🔥{m.power_draw_w:.0f}/{m.power_limit_w:.0f}W" if m.power_limit_w else f"🔥{m.power_draw_w:.1f}W"
                else:
                    p_s = "🔥--W"
                lbl_pwr = QLabel(p_s)
                lbl_pwr.setFixedWidth(78)
                lbl_pwr.setStyleSheet(f"color: {Theme.TEMP_WARM}; font-size: 11px; font-weight: 700; border: none;")
                rl.addWidget(lbl_pwr)

                btn_off = QPushButton("OFF")
                btn_off.setFixedWidth(34)
                btn_off.setToolTip(f"Disable polling {st.hostname}")
                btn_off.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        border: 1px solid {Theme.BORDER_DEFAULT};
                        border-radius: 3px;
                        padding: 1px 3px;
                        color: {Theme.TEXT_MUTED};
                        font-size: 9px;
                        font-weight: 700;
                    }}
                    QPushButton:hover {{
                        border-color: {Theme.TEMP_CRITICAL};
                        color: {Theme.TEMP_CRITICAL};
                    }}
                """)
                btn_off.clicked.connect(lambda checked=False, nid=node_id: self.net_manager.set_node_enabled(nid, False))
                rl.addWidget(btn_off)

                self.net_rows_layout.addWidget(row_w)
