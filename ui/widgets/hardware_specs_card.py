"""
Comprehensive Hardware Specifications Card component.
Displays deep hardware telemetry and static SMBIOS/NVML/IOCTL specifications:
- System Memory (RAM): Channels, Configured MT/s, Real DRAM MHz, JEDEC, XMP/EXPO, Voltage, Per-Slot DIMM Table
- Motherboard & BIOS: Vendor, Model, Rev, Serial, BIOS Version/Date, UEFI/Secure Boot, PCIe & M.2 Slot Map
- Processor (CPU): Socket, Base/Boost/BCLK Clocks, Voltage, L1/L2/L3 Cache Hierarchy, Instruction Sets
- Graphics Adapters (GPUs): Architecture, CUDA Cores, PCIe Current/Max Link, Max Clocks, VBIOS, Driver, UUID
- Storage & OS: Physical NVMe/SATA Drives (Firmware, Serial, Bus), Partitions, and OS Build Info
"""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

from core.gpu_types import GpuDevice
from core.hardware_info import SystemHardwareSpecs, HardwareInfoCollector
from ui.theme import Theme


class HardwareSpecsCard(QFrame):
    def __init__(self, specs: Optional[SystemHardwareSpecs] = None, parent=None):
        super().__init__(parent)
        self.specs = specs or HardwareInfoCollector.collect_all()
        self.devices: List[GpuDevice] = []
        self.is_expanded = True
        self.active_filter = "all"
        self.section_widgets = {}
        self.filter_buttons = {}

        self._setup_ui()
        self._populate_data()

    def _setup_ui(self):
        self.setObjectName("HardwareSpecsCard")
        self.setStyleSheet(f"""
            QFrame#HardwareSpecsCard {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BG_CARD_BORDER};
                border-radius: 12px;
            }}
            QFrame#HardwareSpecsCard:hover {{
                border: 1px solid {Theme.BORDER_ACCENT};
            }}
        """)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(18, 16, 18, 16)
        self.main_layout.setSpacing(14)

        # 1. Header Row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        self.lbl_badge = QLabel("HARDWARE SPECS")
        self.lbl_badge.setStyleSheet(f"""
            background-color: {Theme.CYBER_PURPLE}22;
            color: {Theme.CYBER_PURPLE};
            border: 1px solid {Theme.CYBER_PURPLE}66;
            border-radius: 5px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.5px;
        """)
        header_layout.addWidget(self.lbl_badge)

        self.lbl_title = QLabel("Deep System Architecture & Hardware Specifications")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        header_layout.addWidget(self.lbl_title)

        header_layout.addStretch()

        # Copy Full Report Button
        self.btn_copy = QPushButton("📋 Copy Hardware Report")
        self.btn_copy.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.BG_PANEL};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px 10px;
                color: {Theme.TEXT_PRIMARY};
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {Theme.CYBER_CYAN};
                color: {Theme.CYBER_CYAN};
            }}
        """)
        self.btn_copy.clicked.connect(self._copy_report)
        header_layout.addWidget(self.btn_copy)

        # Refresh Button
        self.btn_refresh = QPushButton("🔄 Rescan")
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.BG_PANEL};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px 10px;
                color: {Theme.TEXT_SECONDARY};
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {Theme.NVIDIA_GREEN};
                color: {Theme.NVIDIA_GREEN};
            }}
        """)
        self.btn_refresh.clicked.connect(self.refresh_specs)
        header_layout.addWidget(self.btn_refresh)

        # Collapse / Expand Toggle
        self.btn_toggle = QPushButton("▲ Collapse")
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.BG_PANEL};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px 10px;
                color: {Theme.TEXT_SECONDARY};
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                color: {Theme.TEXT_PRIMARY};
            }}
        """)
        self.btn_toggle.clicked.connect(self.toggle_expanded)
        header_layout.addWidget(self.btn_toggle)

        self.main_layout.addLayout(header_layout)

        # Collapsible Body Container
        self.body_widget = QWidget()
        self.body_layout = QVBoxLayout(self.body_widget)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(14)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {Theme.BORDER_DEFAULT}; max-height: 1px;")
        self.body_layout.addWidget(divider)

        # Category Filter Bar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        categories = [
            ("all", "🔭 All Subsystems"),
            ("ram", "🧠 RAM & DIMM Slots"),
            ("mobo", "🎛️ Motherboard, BIOS & Slots"),
            ("cpu", "💻 CPU, Clocks & Cache"),
            ("gpu", "⚡ GPU Deep Specs"),
            ("storage", "💽 NVMe / SATA & OS"),
        ]
        for key, label in categories:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.clicked.connect(lambda checked, k=key: self._set_filter(k))
            self.filter_buttons[key] = btn
            filter_row.addWidget(btn)
        filter_row.addStretch()
        self._update_filter_button_styles()
        self.body_layout.addLayout(filter_row)

        # Dynamic Content Container
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(16)
        self.body_layout.addWidget(self.content_widget)

        self.main_layout.addWidget(self.body_widget)

    def _update_filter_button_styles(self):
        for key, btn in self.filter_buttons.items():
            active = (key == self.active_filter)
            btn.setChecked(active)
            if active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {Theme.CYBER_CYAN}22;
                        border: 1px solid {Theme.CYBER_CYAN};
                        border-radius: 6px;
                        padding: 5px 12px;
                        color: {Theme.CYBER_CYAN};
                        font-size: 11px;
                        font-weight: 700;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {Theme.BG_PANEL};
                        border: 1px solid {Theme.BORDER_DEFAULT};
                        border-radius: 6px;
                        padding: 5px 12px;
                        color: {Theme.TEXT_SECONDARY};
                        font-size: 11px;
                        font-weight: 600;
                    }}
                    QPushButton:hover {{
                        border-color: {Theme.TEXT_MUTED};
                        color: {Theme.TEXT_PRIMARY};
                    }}
                """)

    def _set_filter(self, key: str):
        self.active_filter = key
        self._update_filter_button_styles()
        for sec_key, widget in self.section_widgets.items():
            widget.setVisible(key == "all" or key == sec_key)

    def toggle_expanded(self):
        self.set_expanded(not self.is_expanded)

    def set_expanded(self, expanded: bool):
        self.is_expanded = expanded
        self.body_widget.setVisible(expanded)
        self.btn_toggle.setText("▲ Collapse" if expanded else "▼ Expand Specs")

    def set_devices(self, devices: List[GpuDevice]):
        self.devices = devices
        self._populate_data()

    def refresh_specs(self):
        self.specs = HardwareInfoCollector.collect_all()
        self._populate_data()

    def _clear_layout(self, layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _create_section_frame(self, title: str, badge_text: str, accent_color: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.BG_ROOT};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 10px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        badge = QLabel(badge_text)
        badge.setStyleSheet(f"""
            background-color: {accent_color}22;
            color: {accent_color};
            border: 1px solid {accent_color}55;
            border-radius: 4px;
            padding: 2px 7px;
            font-size: 10px;
            font-weight: 800;
        """)
        hdr.addWidget(badge)

        lbl = QLabel(title)
        lbl.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        layout.addLayout(hdr)

        return frame, layout

    def _create_kv_cell(self, label: str, value: str, subtext: str = "", value_color: str = "#f0f6fc") -> QFrame:
        cell = QFrame()
        cell.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 6px;
            }}
        """)
        vbox = QVBoxLayout(cell)
        vbox.setContentsMargins(10, 7, 10, 7)
        vbox.setSpacing(2)

        lbl_k = QLabel(label.upper())
        lbl_k.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 9px; font-weight: 700; letter-spacing: 0.4px; border: none;")
        vbox.addWidget(lbl_k)

        lbl_v = QLabel(value if value else "N/A")
        lbl_v.setStyleSheet(f"color: {value_color}; font-size: 12px; font-weight: 700; border: none;")
        lbl_v.setWordWrap(True)
        lbl_v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        vbox.addWidget(lbl_v)

        if subtext:
            lbl_s = QLabel(subtext)
            lbl_s.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; border: none;")
            lbl_s.setWordWrap(True)
            lbl_s.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            vbox.addWidget(lbl_s)

        return cell

    def _populate_data(self):
        self._clear_layout(self.content_layout)
        self.section_widgets.clear()

        # 1. MEMORY (RAM) SECTION
        ram_frame = self._build_ram_section()
        self.section_widgets["ram"] = ram_frame
        self.content_layout.addWidget(ram_frame)

        # 2. MOTHERBOARD & BIOS SECTION
        mobo_frame = self._build_mobo_section()
        self.section_widgets["mobo"] = mobo_frame
        self.content_layout.addWidget(mobo_frame)

        # 3. PROCESSOR (CPU) SECTION
        cpu_frame = self._build_cpu_section()
        self.section_widgets["cpu"] = cpu_frame
        self.content_layout.addWidget(cpu_frame)

        # 4. GRAPHICS ADAPTERS (GPU) SECTION
        gpu_frame = self._build_gpu_section()
        self.section_widgets["gpu"] = gpu_frame
        self.content_layout.addWidget(gpu_frame)

        # 5. STORAGE & OS SECTION
        storage_frame = self._build_storage_section()
        self.section_widgets["storage"] = storage_frame
        self.content_layout.addWidget(storage_frame)

        # Apply active filter visibility
        self._set_filter(self.active_filter)

    def _build_ram_section(self) -> QFrame:
        ram = self.specs.ram
        frame, layout = self._create_section_frame(
            "System Memory (RAM) — Channels, Clocks, Timings & Physical DIMM Slots",
            "MEMORY & CHANNELS",
            Theme.CYBER_CYAN,
        )

        grid = QGridLayout()
        grid.setSpacing(8)

        # Row 0
        max_cap_str = f"Max Board Support: {ram.max_board_capacity_gb:.0f} GB" if ram.max_board_capacity_gb > 0 else "Physical Memory"
        grid.addWidget(
            self._create_kv_cell("Total Installed RAM", f"{ram.total_installed_gb:.0f} GB ({ram.mem_type})", max_cap_str, "#ffffff"),
            0, 0
        )
        grid.addWidget(
            self._create_kv_cell(
                "Channel Architecture",
                ram.channel_mode or "Unknown",
                f"{ram.slots_used} of {ram.slots_total} DIMM Slots Populated",
                Theme.NVIDIA_GREEN if "Dual" in ram.channel_mode or "Quad" in ram.channel_mode else "#f0f6fc",
            ),
            0, 1
        )
        active_speed_str = f"{ram.configured_speed_mts} MT/s" if ram.configured_speed_mts else "N/A"
        real_clk_str = f"Real DRAM Clock: {ram.dram_freq_mhz} MHz (DDR)" if ram.dram_freq_mhz else ""
        grid.addWidget(
            self._create_kv_cell("Active Configured Speed", active_speed_str, real_clk_str, Theme.CYBER_CYAN),
            0, 2
        )
        jedec_str = f"{ram.jedec_speed_mts} MT/s ({ram.jedec_speed_mts // 2} MHz)" if ram.jedec_speed_mts else "Standard JEDEC"
        expo_str = f"Rated Profile: {ram.xmp_expo_spec}" if ram.xmp_expo_spec else "SPD Standard"
        grid.addWidget(
            self._create_kv_cell("JEDEC & XMP / EXPO Profile", expo_str if ram.xmp_expo_spec else jedec_str, f"JEDEC Base: {jedec_str}", "#ffab00" if ram.xmp_expo_spec else "#f0f6fc"),
            0, 3
        )

        # Row 1
        volt_str = f"{ram.voltage_v:.2f} V" if ram.voltage_v > 0 else "Auto"
        ecc_str = "ECC Enabled" if ram.ecc_supported else "Non-ECC Unbuffered"
        grid.addWidget(
            self._create_kv_cell("Memory Type & Form Factor", f"{ram.mem_type} • {ram.form_factor}", ecc_str),
            1, 0
        )
        grid.addWidget(
            self._create_kv_cell("DRAM Operating Voltage", volt_str, "VDD / VDDQ Configured"),
            1, 1
        )

        # Manufacturer & Part Number summary
        populated_mods = [m for m in ram.modules if m.populated]
        vendors = sorted({m.manufacturer for m in populated_mods if m.manufacturer})
        parts = sorted({m.part_number for m in populated_mods if m.part_number})
        ranks_set = sorted({f"{m.ranks}R" for m in populated_mods if m.ranks > 0})
        grid.addWidget(
            self._create_kv_cell(
                "Module Manufacturer & Rank",
                f"{', '.join(vendors) if vendors else 'Generic'} ({', '.join(ranks_set) if ranks_set else '1R'})",
                f"Data Width: {populated_mods[0].data_width_bits if populated_mods else 64}-bit per DIMM",
            ),
            1, 2
        )
        grid.addWidget(
            self._create_kv_cell(
                "DIMM Part Number(s)",
                ", ".join(parts) if parts else "N/A",
                ram.xmp_expo_spec or "Standard SPD",
            ),
            1, 3
        )

        layout.addLayout(grid)

        # Per-Slot Physical DIMM Table
        if ram.modules:
            lbl_tbl = QLabel("PHYSICAL DIMM SLOTS BREAKDOWN")
            lbl_tbl.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: 800; border: none; margin-top: 4px;")
            layout.addWidget(lbl_tbl)

            table = QTableWidget()
            cols = [
                "Slot", "Channel / Bank", "Capacity", "Type", "Rank",
                "Configured Speed", "Real DRAM Freq", "JEDEC / Profile", "Voltage", "Manufacturer", "Part Number"
            ]
            table.setColumnCount(len(cols))
            table.setHorizontalHeaderLabels(cols)
            table.setRowCount(len(ram.modules))
            table.verticalHeader().setVisible(False)
            table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(len(cols) - 1, QHeaderView.ResizeMode.Stretch)

            row_h = 28
            for r, m in enumerate(ram.modules):
                table.setRowHeight(r, row_h)
                if m.populated:
                    profile_txt = f"{m.jedec_speed_mts} MT/s"
                    if m.xmp_expo_spec:
                        profile_txt += f" • {m.xmp_expo_spec}"
                    vals = [
                        m.slot_label,
                        m.bank_label,
                        f"{m.capacity_gb:.0f} GB",
                        f"{m.mem_type} {m.form_factor}",
                        f"{m.ranks}R" if m.ranks else "1R",
                        f"{m.configured_speed_mts} MT/s" if m.configured_speed_mts else "--",
                        f"{m.dram_freq_mhz} MHz" if m.dram_freq_mhz else "--",
                        profile_txt,
                        f"{m.voltage_v:.2f} V" if m.voltage_v else "--",
                        m.manufacturer or "Unknown",
                        m.part_number or "--",
                    ]
                else:
                    vals = [m.slot_label, m.bank_label, "Empty", "--", "--", "--", "--", "--", "--", "--", "--"]

                for c, val in enumerate(vals):
                    item = QTableWidgetItem(val)
                    if c in (0, 2, 3, 4, 5, 6, 8):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if not m.populated:
                        item.setForeground(QColor(Theme.TEXT_MUTED))
                    elif c == 5:
                        item.setForeground(QColor(Theme.CYBER_CYAN))
                    elif c == 2:
                        item.setForeground(QColor(Theme.NVIDIA_GREEN))
                    table.setItem(r, c, item)

            table.setFixedHeight(min(220, 30 + len(ram.modules) * row_h))
            layout.addWidget(table)

        return frame

    def _build_mobo_section(self) -> QFrame:
        mb = self.specs.motherboard
        frame, layout = self._create_section_frame(
            "Motherboard, UEFI BIOS & PCIe / M.2 Expansion Slots",
            "MOTHERBOARD & BIOS",
            Theme.NVIDIA_GREEN,
        )

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(
            self._create_kv_cell("Motherboard Manufacturer", mb.manufacturer or "Unknown", f"Revision: {mb.version or 'N/A'}"),
            0, 0
        )
        grid.addWidget(
            self._create_kv_cell("Motherboard Model", mb.product or "Unknown", f"Serial: {mb.serial_number or 'N/A'}", "#ffffff"),
            0, 1
        )
        grid.addWidget(
            self._create_kv_cell("BIOS Vendor & Version", f"Ver. {mb.bios_version}" if mb.bios_version else "Unknown", f"{mb.bios_vendor} • {mb.bios_date}", Theme.CYBER_CYAN),
            0, 2
        )
        sb_col = Theme.NVIDIA_GREEN if mb.secure_boot == "Enabled" else "#f0f6fc"
        grid.addWidget(
            self._create_kv_cell("Boot Mode & Security", f"{mb.boot_mode} • Secure Boot: {mb.secure_boot}", f"SMBIOS Spec: v{mb.smbios_version}", sb_col),
            0, 3
        )
        layout.addLayout(grid)

        if mb.slots:
            lbl_slots = QLabel("MOTHERBOARD PCIe & M.2 EXPANSION SLOTS (SMBIOS TOPOLOGY)")
            lbl_slots.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: 800; border: none; margin-top: 4px;")
            layout.addWidget(lbl_slots)

            slots_grid = QGridLayout()
            slots_grid.setSpacing(8)
            cols_per_row = 4
            for idx, sl in enumerate(mb.slots):
                in_use = "In Use" in sl.status
                status_col = Theme.NVIDIA_GREEN if in_use else Theme.TEXT_MUTED
                status_badge = f"● {sl.status}"
                cell = self._create_kv_cell(
                    f"{sl.designation} ({sl.bus_width})",
                    status_badge,
                    sl.slot_type,
                    status_col,
                )
                slots_grid.addWidget(cell, idx // cols_per_row, idx % cols_per_row)
            layout.addLayout(slots_grid)

        return frame

    def _build_cpu_section(self) -> QFrame:
        cpu = self.specs.cpu
        frame, layout = self._create_section_frame(
            "Processor (CPU) Microarchitecture, Clocks, Caches & Instruction Sets",
            "PROCESSOR",
            "#ff9100",
        )

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(
            self._create_kv_cell("Processor Model", cpu.name or "Unknown", f"{cpu.vendor} • {cpu.identifier}", "#ffffff"),
            0, 0
        )
        grid.addWidget(
            self._create_kv_cell(
                "Socket & Core Topology",
                f"Socket {cpu.socket or 'N/A'} • {cpu.cores_physical}C / {cpu.cores_logical}T",
                f"Virtualization: {cpu.virtualization}",
                Theme.CYBER_CYAN,
            ),
            0, 1
        )
        clk_str = f"Base: {cpu.base_clock_mhz} MHz • Boost: {cpu.boost_clock_mhz} MHz" if cpu.base_clock_mhz else "Dynamic Boost"
        bclk_str = f"Bus / BCLK: {cpu.ext_clock_mhz} MHz • Core VID: {cpu.voltage_v:.2f} V" if cpu.ext_clock_mhz else ""
        grid.addWidget(
            self._create_kv_cell("Clock Speeds & BCLK", clk_str, bclk_str, "#ffab00"),
            0, 2
        )

        l1_str = f"{cpu.l1_cache_kb} KB" if cpu.l1_cache_kb else "--"
        l2_str = f"{cpu.l2_cache_kb / 1024:.1f} MB" if cpu.l2_cache_kb >= 1024 else f"{cpu.l2_cache_kb} KB"
        l3_str = f"{cpu.l3_cache_kb / 1024:.1f} MB" if cpu.l3_cache_kb >= 1024 else f"{cpu.l3_cache_kb} KB"
        grid.addWidget(
            self._create_kv_cell("Cache Hierarchy (L1 / L2 / L3)", f"L3: {l3_str} • L2: {l2_str}", f"L1 Cache: {l1_str}", Theme.NVIDIA_GREEN),
            0, 3
        )

        if cpu.features:
            grid.addWidget(
                self._create_kv_cell(
                    "Instruction Set Extensions (ISA)",
                    " • ".join(cpu.features),
                    f"Hardware Virtualization: {cpu.virtualization}",
                ),
                1, 0, 1, 4
            )

        layout.addLayout(grid)
        return frame

    def _build_gpu_section(self) -> QFrame:
        frame, layout = self._create_section_frame(
            "Graphics Adapters (GPUs) — Architecture, PCIe Link, Clocks & Firmware",
            "GRAPHICS ADAPTERS",
            Theme.AMD_RED,
        )

        if not self.devices:
            lbl_empty = QLabel("Detecting graphics adapters...")
            lbl_empty.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; border: none;")
            layout.addWidget(lbl_empty)
            return frame

        for dev in self.devices:
            v_col = Theme.get_vendor_color(dev.vendor)
            sub_box = QFrame()
            sub_box.setStyleSheet(f"""
                QFrame {{
                    background-color: {Theme.BG_CARD};
                    border: 1px solid {Theme.BORDER_DEFAULT};
                    border-radius: 8px;
                }}
            """)
            s_layout = QVBoxLayout(sub_box)
            s_layout.setContentsMargins(10, 8, 10, 8)
            s_layout.setSpacing(6)

            hdr = QHBoxLayout()
            badge = QLabel(f"GPU {dev.index} • {dev.vendor}")
            badge.setStyleSheet(f"color: {v_col}; font-size: 11px; font-weight: 800; border: none;")
            hdr.addWidget(badge)

            title = QLabel(dev.name)
            title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none;")
            hdr.addWidget(title)
            hdr.addStretch()

            if dev.uuid:
                lbl_uuid = QLabel(dev.uuid)
                lbl_uuid.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px; border: none;")
                lbl_uuid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                hdr.addWidget(lbl_uuid)

            s_layout.addLayout(hdr)

            g = QGridLayout()
            g.setSpacing(6)

            arch_str = dev.architecture or f"{dev.vendor} Architecture"
            cores_str = f"{dev.cuda_cores} CUDA Cores" if dev.cuda_cores else "Unified Shaders"
            g.addWidget(self._create_kv_cell("Architecture & Cores", arch_str, cores_str, v_col), 0, 0)

            vram_gb = f"{dev.vram_total_mb / 1024.0:.1f} GB ({dev.vram_total_mb:.0f} MB)" if dev.vram_total_mb > 0 else "Shared Host Memory"
            tdp_str = f"Enforced Power Limit: {dev.power_limit_default_w:.0f} W" if dev.power_limit_default_w else "Dynamic Power"
            g.addWidget(self._create_kv_cell("Dedicated VRAM & TDP", vram_gb, tdp_str, "#ffffff"), 0, 1)

            if dev.pcie_max_gen and dev.pcie_max_width:
                pcie_str = f"Current: Gen {dev.pcie_gen} x{dev.pcie_width} (Max: Gen {dev.pcie_max_gen} x{dev.pcie_max_width})"
            elif dev.pcie_gen and dev.pcie_width:
                pcie_str = f"PCIe Gen {dev.pcie_gen} x{dev.pcie_width}"
            else:
                pcie_str = "Internal / PCIe Bus"
            g.addWidget(self._create_kv_cell("PCIe Link & Bus ID", pcie_str, f"Bus ID: {dev.bus_id or 'Internal'}", Theme.CYBER_CYAN), 0, 2)

            max_clk_str = (
                f"Boost: {dev.max_clock_graphics_mhz} MHz • Mem: {dev.max_clock_memory_mhz} MHz"
                if dev.max_clock_graphics_mhz else f"Driver: {dev.driver_version or 'WDDM'}"
            )
            vbios_str = f"Driver: {dev.driver_version or 'N/A'} • VBIOS: {dev.vbios_version.upper() if dev.vbios_version else 'N/A'}"
            g.addWidget(self._create_kv_cell("Max Clocks & Firmware", max_clk_str, vbios_str), 0, 3)

            s_layout.addLayout(g)
            layout.addWidget(sub_box)

        return frame

    def _build_storage_section(self) -> QFrame:
        frame, layout = self._create_section_frame(
            "Physical Storage Drives (NVMe / SATA), Mounted Volumes & Operating System",
            "STORAGE & OS",
            Theme.INTEL_BLUE,
        )

        # Physical Drives Table
        if self.specs.storage_drives:
            lbl_d = QLabel("PHYSICAL STORAGE DRIVES (NVMe & SATA CONTROLLERS)")
            lbl_d.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; font-weight: 800; border: none;")
            layout.addWidget(lbl_d)

            table = QTableWidget()
            cols = ["Disk #", "Drive Model", "Bus Interface", "Capacity", "Firmware Rev", "Hardware Serial Number"]
            table.setColumnCount(len(cols))
            table.setHorizontalHeaderLabels(cols)
            table.setRowCount(len(self.specs.storage_drives))
            table.verticalHeader().setVisible(False)
            table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

            row_h = 26
            for r, d in enumerate(self.specs.storage_drives):
                table.setRowHeight(r, row_h)
                vals = [
                    f"Disk {d.index}",
                    d.model,
                    d.bus_type,
                    f"{d.capacity_gb:.1f} GB",
                    d.firmware or "--",
                    d.serial_number or "--",
                ]
                for c, val in enumerate(vals):
                    item = QTableWidgetItem(val)
                    if c in (0, 2, 3, 4):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if c == 2:
                        item.setForeground(QColor(Theme.CYBER_CYAN if "NVMe" in d.bus_type else Theme.NVIDIA_GREEN))
                    table.setItem(r, c, item)

            table.setFixedHeight(min(180, 28 + len(self.specs.storage_drives) * row_h))
            layout.addWidget(table)

        # Partitions & OS Grid
        grid = QGridLayout()
        grid.setSpacing(8)
        for idx, p in enumerate(self.specs.partitions):
            col = Theme.TEMP_HOT if p.percent >= 90 else (Theme.TEMP_WARM if p.percent >= 75 else Theme.NVIDIA_GREEN)
            cell = self._create_kv_cell(
                f"Volume {p.mountpoint} ({p.fstype})",
                f"{p.used_gb:.1f} / {p.total_gb:.1f} GB ({p.percent:.0f}%)",
                f"Free Space: {p.free_gb:.1f} GB",
                col,
            )
            grid.addWidget(cell, idx // 4, idx % 4)
        layout.addLayout(grid)

        # OS Info Row
        os_info = self.specs.os_info
        os_grid = QGridLayout()
        os_grid.setSpacing(8)
        os_grid.addWidget(self._create_kv_cell("Operating System", os_info.os_name, f"Version: {os_info.version}"), 0, 0)
        os_grid.addWidget(self._create_kv_cell("OS Build & Architecture", f"Build {os_info.build} ({os_info.architecture})", f"Hostname: {os_info.hostname}"), 0, 1)
        os_grid.addWidget(self._create_kv_cell("System Uptime", os_info.uptime_str, "Continuous Kernel Runtime", Theme.NVIDIA_GREEN), 0, 2)
        layout.addLayout(os_grid)

        return frame

    def _copy_report(self):
        s = self.specs
        lines = [
            "# GPU Sentry — Complete Hardware Specification Report",
            "",
            "## 💻 Processor (CPU)",
            f"- **Model**: {s.cpu.name} ({s.cpu.vendor})",
            f"- **Identifier**: {s.cpu.identifier}",
            f"- **Socket**: {s.cpu.socket}",
            f"- **Topology**: {s.cpu.cores_physical} Physical Cores / {s.cpu.cores_logical} Logical Threads",
            f"- **Clocks**: Base {s.cpu.base_clock_mhz} MHz | Max Boost {s.cpu.boost_clock_mhz} MHz | BCLK {s.cpu.ext_clock_mhz} MHz | VID {s.cpu.voltage_v:.2f} V",
            f"- **Cache**: L1 {s.cpu.l1_cache_kb} KB | L2 {s.cpu.l2_cache_kb} KB | L3 {s.cpu.l3_cache_kb} KB",
            f"- **Virtualization**: {s.cpu.virtualization}",
            f"- **Instruction Sets**: {', '.join(s.cpu.features)}",
            "",
            "## 🧠 System Memory (RAM)",
            f"- **Installed Capacity**: {s.ram.total_installed_gb:.0f} GB {s.ram.mem_type} {s.ram.form_factor} (Max Board Capacity: {s.ram.max_board_capacity_gb:.0f} GB)",
            f"- **Channel Mode**: {s.ram.channel_mode} ({s.ram.slots_used}/{s.ram.slots_total} Slots Used)",
            f"- **Active Speed**: {s.ram.configured_speed_mts} MT/s ({s.ram.dram_freq_mhz} MHz Real DRAM Clock)",
            f"- **JEDEC Base Speed**: {s.ram.jedec_speed_mts} MT/s",
            f"- **XMP / EXPO Profile**: {s.ram.xmp_expo_spec or 'N/A'}",
            f"- **Voltage**: {s.ram.voltage_v:.2f} V | ECC: {'Yes' if s.ram.ecc_supported else 'No'}",
            "### Physical DIMM Slots:",
        ]
        for m in s.ram.modules:
            if m.populated:
                lines.append(
                    f"  - **{m.slot_label} ({m.bank_label})**: {m.capacity_gb:.0f} GB {m.mem_type} {m.ranks}R @ "
                    f"{m.configured_speed_mts} MT/s ({m.dram_freq_mhz} MHz) | {m.manufacturer} `{m.part_number}` ({m.voltage_v:.2f} V)"
                )
            else:
                lines.append(f"  - **{m.slot_label} ({m.bank_label})**: Empty")

        lines.extend([
            "",
            "## 🎛️ Motherboard & BIOS",
            f"- **Board**: {s.motherboard.manufacturer} {s.motherboard.product} ({s.motherboard.version})",
            f"- **Serial Number**: {s.motherboard.serial_number}",
            f"- **BIOS**: {s.motherboard.bios_vendor} Ver. {s.motherboard.bios_version} ({s.motherboard.bios_date}) | SMBIOS {s.motherboard.smbios_version}",
            f"- **Boot & Security**: {s.motherboard.boot_mode} | Secure Boot: {s.motherboard.secure_boot}",
            "### Expansion & M.2 Slots:",
        ])
        for sl in s.motherboard.slots:
            lines.append(f"  - **{sl.designation}**: {sl.slot_type} ({sl.bus_width}) — {sl.status}")

        lines.extend(["", "## ⚡ Graphics Adapters (GPUs)"])
        for dev in self.devices:
            lines.append(
                f"- **GPU {dev.index}: {dev.name}** ({dev.vendor} {dev.architecture}) | "
                f"Cores: {dev.cuda_cores or 'N/A'} | VRAM: {dev.vram_total_mb / 1024.0:.1f} GB | "
                f"PCIe: Gen {dev.pcie_gen}x{dev.pcie_width} (Max Gen {dev.pcie_max_gen}x{dev.pcie_max_width}) | "
                f"Max Clocks: {dev.max_clock_graphics_mhz}/{dev.max_clock_memory_mhz} MHz | "
                f"Driver: {dev.driver_version} | VBIOS: {dev.vbios_version}"
            )

        lines.extend(["", "## 💽 Storage Drives"])
        for d in s.storage_drives:
            lines.append(f"- **Disk {d.index}: {d.model}** ({d.bus_type}) — {d.capacity_gb:.1f} GB | FW: {d.firmware} | SN: {d.serial_number}")

        lines.extend([
            "",
            "## 🖥️ Operating System",
            f"- **OS**: {s.os_info.os_name} {s.os_info.version} ({s.os_info.architecture}) | Host: {s.os_info.hostname} | Uptime: {s.os_info.uptime_str}",
        ])

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText("\n".join(lines))
            self.btn_copy.setText("✓ Copied to Clipboard!")
            QTimer.singleShot(2200, lambda: self.btn_copy.setText("📋 Copy Hardware Report"))
