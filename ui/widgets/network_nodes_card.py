"""
Network & Tailscale Tailnet Nodes + Remote GPU Thermal Monitor Card component.
Allows auto-discovering Tailscale Tailnet GPU machines and LAN GPU Sentry nodes,
adding remote hosts via IP/SSH/LibreHardwareMonitor, and monitoring every remote machine's
GPUs, thermal status (Edge/Core, Junction/Hotspot, Memory), fan speeds, VRAM, power, and clocks.
"""

from typing import Dict
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QLineEdit, QComboBox, QProgressBar, QGridLayout
)
from PyQt6.QtCore import Qt, QTimer

from core.network_telemetry import (
    NetworkTelemetryManager,
    RemoteNodeState,
    get_local_lan_ips,
)
from ui.theme import Theme


class NetworkNodesCard(QFrame):
    def __init__(self, net_manager: NetworkTelemetryManager, parent=None):
        super().__init__(parent)
        self.net_manager = net_manager
        self.is_expanded = True

        self._setup_ui()
        self.net_manager.nodes_updated.connect(self.update_nodes)
        self.net_manager.tailnet_scan_status.connect(self._on_tailnet_scan_status)

    def _setup_ui(self):
        self.setObjectName("NetworkNodesCard")
        self.setStyleSheet(f"""
            QFrame#NetworkNodesCard {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BG_CARD_BORDER};
                border-radius: 12px;
            }}
            QFrame#NetworkNodesCard:hover {{
                border: 1px solid {Theme.BORDER_ACCENT};
            }}
        """)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(18, 16, 18, 16)
        self.main_layout.setSpacing(12)

        # 1. Header Row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.lbl_badge = QLabel("TAILNET & LAN GPUs")
        self.lbl_badge.setStyleSheet(f"""
            background-color: {Theme.INTEL_BLUE}22;
            color: {Theme.INTEL_BLUE};
            border: 1px solid {Theme.INTEL_BLUE}66;
            border-radius: 5px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.5px;
        """)
        header_layout.addWidget(self.lbl_badge)

        self.lbl_title = QLabel("Tailscale Tailnet & Network Devices — GPU & Thermal Telemetry")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        header_layout.addWidget(self.lbl_title)

        header_layout.addStretch()

        # Local Server IP/Port Badge
        lan_ips = get_local_lan_ips()
        ip_str = lan_ips[0] if lan_ips else "0.0.0.0"
        self.lbl_server_info = QLabel(f"🟢 Local Agent ({ip_str}:{self.net_manager.local_server.port})")
        self.lbl_server_info.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 11px; font-weight: 600;")
        header_layout.addWidget(self.lbl_server_info)

        # Pin remote GPUs as full GpuCards toggle
        self.btn_pin_cards = QPushButton("📌 Show as Full GPU Cards")
        self.btn_pin_cards.setCheckable(True)
        self.btn_pin_cards.setChecked(self.net_manager.pin_remote_cards)
        self.btn_pin_cards.setToolTip("Also render remote network GPUs as full cards with 60s sparklines in the dashboard")
        self.btn_pin_cards.clicked.connect(lambda c: self.net_manager.set_pin_remote_cards(c))
        header_layout.addWidget(self.btn_pin_cards)

        # Scan Tailscale Tailnet button
        self.btn_scan_tailnet = QPushButton("🦊 Scan Tailnet")
        self.btn_scan_tailnet.setToolTip("Scan all online machines in your Tailscale Tailnet and auto-discover hosts with GPUs")
        self.btn_scan_tailnet.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.CYBER_PURPLE}22;
                color: {Theme.CYBER_PURPLE};
                border: 1px solid {Theme.CYBER_PURPLE}66;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {Theme.CYBER_PURPLE}33;
            }}
        """)
        self.btn_scan_tailnet.clicked.connect(self._on_scan_tailnet_clicked)
        header_layout.addWidget(self.btn_scan_tailnet)

        # Scan LAN button
        self.btn_scan = QPushButton("🔍 Scan LAN")
        self.btn_scan.setToolTip("Broadcast UDP discovery to find other GPU Sentry machines on your local network")
        self.btn_scan.clicked.connect(self._on_scan_clicked)
        header_layout.addWidget(self.btn_scan)

        # Collapse / Expand button
        self.btn_toggle = QPushButton("▲ Collapse")
        self.btn_toggle.clicked.connect(self.toggle_expanded)
        header_layout.addWidget(self.btn_toggle)

        self.main_layout.addLayout(header_layout)

        # Collapsible Body
        self.body_widget = QWidget()
        self.body_layout = QVBoxLayout(self.body_widget)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {Theme.BORDER_DEFAULT}; max-height: 1px;")
        self.body_layout.addWidget(divider)

        # 2. Add Remote Device Bar
        add_bar = QHBoxLayout()
        add_bar.setSpacing(8)

        lbl_add = QLabel("Add Device:")
        lbl_add.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 700;")
        add_bar.addWidget(lbl_add)

        self.cb_proto = QComboBox()
        self.cb_proto.addItem("Auto / GPU Sentry (:51920)", "auto")
        self.cb_proto.addItem("SSH Agentless (NVIDIA / AMD / Intel)", "ssh")
        self.cb_proto.addItem("LibreHardwareMonitor (:8085)", "lhm")
        add_bar.addWidget(self.cb_proto)

        self.txt_address = QLineEdit()
        self.txt_address.setPlaceholderText("Enter Tailscale host / IP / SSH (e.g. hakanu@hakuxtx or 100.88.172.48 or 192.168.1.50)...")
        self.txt_address.setStyleSheet(f"""
            QLineEdit {{
                background-color: {Theme.BG_ROOT};
                color: {Theme.TEXT_PRIMARY};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Theme.CYBER_CYAN};
            }}
        """)
        self.txt_address.returnPressed.connect(self._on_add_node)
        add_bar.addWidget(self.txt_address, stretch=1)

        self.btn_add = QPushButton("➕ Connect Node")
        self.btn_add.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.CYBER_CYAN}22;
                color: {Theme.CYBER_CYAN};
                border: 1px solid {Theme.CYBER_CYAN}88;
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {Theme.CYBER_CYAN}33;
            }}
        """)
        self.btn_add.clicked.connect(self._on_add_node)
        add_bar.addWidget(self.btn_add)

        self.body_layout.addLayout(add_bar)

        # Status Banner for active Tailnet scan
        self.lbl_scan_status = QLabel("")
        self.lbl_scan_status.setStyleSheet(f"color: {Theme.CYBER_PURPLE}; font-size: 11px; font-weight: 700;")
        self.lbl_scan_status.setVisible(False)
        self.body_layout.addWidget(self.lbl_scan_status)

        # 3. Nodes Container
        self.nodes_container = QWidget()
        self.nodes_layout = QVBoxLayout(self.nodes_container)
        self.nodes_layout.setContentsMargins(0, 0, 0, 0)
        self.nodes_layout.setSpacing(10)
        self.body_layout.addWidget(self.nodes_container)

        self.main_layout.addWidget(self.body_widget)
        self.update_nodes(self.net_manager.states)

    def _on_tailnet_scan_status(self, msg: str):
        if msg:
            self.lbl_scan_status.setText(msg)
            self.lbl_scan_status.setVisible(True)
            self.btn_scan_tailnet.setText("🦊 Scanning Tailnet...")
        else:
            self.lbl_scan_status.setVisible(False)
            self.btn_scan_tailnet.setText("🦊 Scan Tailnet")

    def toggle_expanded(self):
        self.set_expanded(not self.is_expanded)

    def set_expanded(self, expanded: bool):
        self.is_expanded = expanded
        self.body_widget.setVisible(expanded)
        self.btn_toggle.setText("▲ Collapse" if expanded else "▼ Expand Network")

    def _on_scan_tailnet_clicked(self):
        self.btn_scan_tailnet.setText("🦊 Scanning Tailnet...")
        self.net_manager.request_tailnet_scan(force_reprobe=True)

    def _on_scan_clicked(self):
        self.btn_scan.setText("🔍 Scanning...")
        self.net_manager.request_lan_scan()
        QTimer.singleShot(1200, lambda: self.btn_scan.setText("🔍 Scan LAN"))

    def _on_add_node(self):
        addr = self.txt_address.text().strip()
        if not addr:
            return
        proto = self.cb_proto.currentData()
        self.net_manager.add_node(addr, protocol=proto)
        self.txt_address.clear()
        self.net_manager.request_lan_scan()
        self.update_nodes(self.net_manager.states)

    def _clear_layout(self, layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def update_nodes(self, states: Dict[str, RemoteNodeState]):
        lan_ips = get_local_lan_ips()
        ip_str = lan_ips[0] if lan_ips else "0.0.0.0"

        net_vram_u = sum(
            st.gpu_metrics.get(g.device_id, g.metrics).vram_used_mb
            for st in states.values() if st.online for g in st.gpus
        ) / 1024.0
        net_vram_t = sum(
            st.gpu_metrics.get(g.device_id, g.metrics).vram_total_mb
            for st in states.values() if st.online for g in st.gpus
        ) / 1024.0
        net_pwr = sum(
            st.gpu_metrics.get(g.device_id, g.metrics).power_draw_w
            for st in states.values() if st.online for g in st.gpus
        )
        net_peak_t = max(
            (st.gpu_metrics.get(g.device_id, g.metrics).temp_core_c for st in states.values() if st.online for g in st.gpus),
            default=0.0,
        )
        if net_vram_t > 0 or net_pwr > 0:
            self.lbl_server_info.setText(
                f"💾 Tailnet VRAM: {net_vram_u:.1f}/{net_vram_t:.1f} GB • 🔥 {net_pwr:.1f} W • 🌡 Peak: {net_peak_t:.0f}°C"
            )
        else:
            self.lbl_server_info.setText(f"🟢 Local Agent ({ip_str}:{self.net_manager.local_server.port})")

        self._clear_layout(self.nodes_layout)

        if not states:
            empty_box = QFrame()
            empty_box.setStyleSheet(f"""
                QFrame {{
                    background-color: {Theme.BG_ROOT};
                    border: 1px dashed {Theme.BORDER_DEFAULT};
                    border-radius: 8px;
                }}
            """)
            el = QVBoxLayout(empty_box)
            el.setContentsMargins(14, 12, 14, 12)
            el.setSpacing(4)
            lbl_e1 = QLabel(
                "Scanning Tailscale Tailnet & LAN for GPU-equipped machines..."
            )
            lbl_e1.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px; font-weight: 600; border: none;")
            lbl_e2 = QLabel(
                "Click '🦊 Scan Tailnet' to probe all online Tailscale peers via SSH / HTTP (:51920 / :8085), or add any host manually above."
            )
            lbl_e2.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; border: none;")
            el.addWidget(lbl_e1)
            el.addWidget(lbl_e2)
            self.nodes_layout.addWidget(empty_box)
            return

        # Sort online nodes with discrete GPUs (largest VRAM) first
        def _sort_key(item):
            _, st = item
            max_vram = max((g.vram_total_mb for g in st.gpus), default=0.0)
            return (not st.online, -max_vram, st.hostname.lower())

        for node_id, st in sorted(states.items(), key=_sort_key):
            node_frame = self._build_node_widget(node_id, st)
            self.nodes_layout.addWidget(node_frame)

    def _build_node_widget(self, node_id: str, st: RemoteNodeState) -> QFrame:
        frame = QFrame()
        border_col = Theme.BORDER_ACCENT if st.online else "#3d1e24"
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.BG_ROOT};
                border: 1px solid {border_col};
                border-radius: 10px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # Node Top Header
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        status_col = Theme.NVIDIA_GREEN if st.online else Theme.TEMP_CRITICAL
        status_txt = f"● ONLINE ({st.latency_ms:.0f} ms)" if st.online else "● OFFLINE"
        lbl_status = QLabel(status_txt)
        lbl_status.setStyleSheet(f"color: {status_col}; font-size: 11px; font-weight: 800; border: none;")
        hdr.addWidget(lbl_status)

        if st.is_tailscale:
            ts_badge = QLabel("TAILSCALE")
            ts_badge.setStyleSheet(f"""
                background-color: {Theme.CYBER_PURPLE}22;
                color: {Theme.CYBER_PURPLE};
                border: 1px solid {Theme.CYBER_PURPLE}66;
                border-radius: 4px;
                padding: 1px 6px;
                font-size: 9px;
                font-weight: 800;
            """)
            hdr.addWidget(ts_badge)

        proto_badge = QLabel(st.protocol.upper())
        proto_badge.setStyleSheet(f"""
            background-color: {Theme.INTEL_BLUE}22;
            color: {Theme.INTEL_BLUE};
            border: 1px solid {Theme.INTEL_BLUE}55;
            border-radius: 4px;
            padding: 1px 6px;
            font-size: 9px;
            font-weight: 800;
        """)
        hdr.addWidget(proto_badge)

        host_title = f"🖥️ {st.hostname}"
        if st.tailscale_ip:
            host_title += f" ({st.tailscale_ip})"
        elif st.address and st.address != st.hostname:
            host_title += f" ({st.address})"
        lbl_host = QLabel(host_title)
        lbl_host.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 700; border: none;")
        hdr.addWidget(lbl_host)

        # Remote CPU & RAM summary pill if available
        if st.online and (st.host_metrics.cpu.load_percent > 0 or st.host_metrics.ram.total_gb > 0):
            cpu = st.host_metrics.cpu
            ram = st.host_metrics.ram
            cpu_t_col = Theme.get_temp_color(cpu.temp_core_c) if cpu.temp_core_c > 0 else Theme.CYBER_CYAN
            cpu_temp_str = f" • {cpu.temp_core_c:.0f}°C" if cpu.temp_core_c > 0 else ""
            lbl_host_stats = QLabel(
                f"Host CPU: {cpu.load_percent:.0f}%{cpu_temp_str}   |   RAM: {ram.used_gb:.1f}/{ram.total_gb:.1f} GB ({ram.load_percent:.0f}%)"
            )
            lbl_host_stats.setStyleSheet(f"color: {cpu_t_col}; font-size: 11px; font-weight: 700; border: none;")
            hdr.addWidget(lbl_host_stats)

        hdr.addStretch()

        if not st.online and st.error_msg:
            lbl_err = QLabel(st.error_msg)
            lbl_err.setStyleSheet(f"color: {Theme.TEMP_HOT}; font-size: 11px; border: none;")
            hdr.addWidget(lbl_err)

        btn_remove = QPushButton("✕ Remove")
        btn_remove.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 2px 8px;
                color: {Theme.TEXT_MUTED};
                font-size: 10px;
            }}
            QPushButton:hover {{
                border-color: {Theme.TEMP_CRITICAL};
                color: {Theme.TEMP_CRITICAL};
            }}
        """)
        btn_remove.clicked.connect(lambda checked=False, nid=node_id: self.net_manager.remove_node(nid))
        hdr.addWidget(btn_remove)

        layout.addLayout(hdr)

        # Remote GPUs & Thermal Rows
        if st.online and st.gpus:
            for dev in st.gpus:
                m = st.gpu_metrics.get(dev.device_id, dev.metrics)
                gpu_row = self._build_remote_gpu_thermal_row(dev, m)
                layout.addWidget(gpu_row)
        elif st.online:
            lbl_no_gpu = QLabel("Connected to host, but no GPUs were reported.")
            lbl_no_gpu.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; border: none;")
            layout.addWidget(lbl_no_gpu)

        return frame

    def _build_remote_gpu_thermal_row(self, dev, m) -> QFrame:
        row_frame = QFrame()
        v_col = Theme.get_vendor_color(dev.vendor)
        # Junction/Hotspot on modern GPUs (e.g. RDNA 3) runs ~20-25°C above Edge (max 110°C)
        effective_temp = max(m.temp_core_c, (m.temp_hotspot_c - 22.0) if m.temp_hotspot_c else 0.0)
        t_col = Theme.get_temp_color(effective_temp)
        t_status = Theme.get_temp_status(effective_temp)

        row_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 8px;
            }}
        """)
        grid = QGridLayout(row_frame)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setSpacing(12)

        # Col 0: GPU Name & Vendor
        name_box = QVBoxLayout()
        name_box.setSpacing(2)
        lbl_name = QLabel(dev.name)
        lbl_name.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700; border: none;")
        name_box.addWidget(lbl_name)

        sub_parts = [dev.vendor]
        if dev.architecture:
            sub_parts.append(dev.architecture)
        if dev.driver_version:
            sub_parts.append(f"Driver: {dev.driver_version}")
        lbl_sub = QLabel(" • ".join(sub_parts))
        lbl_sub.setStyleSheet(f"color: {v_col}; font-size: 10px; font-weight: 600; border: none;")
        name_box.addWidget(lbl_sub)
        grid.addLayout(name_box, 0, 0)

        # Col 1: Thermal Status & Temp Bar (Edge, Junction/Hotspot, Memory, Fan)
        therm_box = QVBoxLayout()
        therm_box.setSpacing(3)
        t_hdr = QHBoxLayout()
        t_hdr.setSpacing(6)
        lbl_t_val = QLabel(f"🌡 {m.temp_core_c:.0f}°C")
        lbl_t_val.setStyleSheet(f"color: {t_col}; font-size: 13px; font-weight: 800; border: none;")
        t_hdr.addWidget(lbl_t_val)

        lbl_t_badge = QLabel(t_status)
        lbl_t_badge.setStyleSheet(f"""
            background-color: {t_col}22;
            color: {t_col};
            border: 1px solid {t_col}66;
            border-radius: 4px;
            padding: 1px 6px;
            font-size: 9px;
            font-weight: 800;
        """)
        t_hdr.addWidget(lbl_t_badge)

        if m.temp_hotspot_c:
            hs_col = Theme.get_temp_color(m.temp_hotspot_c - 22.0)
            lbl_hs = QLabel(f"Junc: {m.temp_hotspot_c:.0f}°C")
            lbl_hs.setStyleSheet(f"color: {hs_col}; font-size: 10px; font-weight: 700; border: none;")
            t_hdr.addWidget(lbl_hs)

        if m.temp_memory_c:
            lbl_mem_t = QLabel(f"Mem: {m.temp_memory_c:.0f}°C")
            lbl_mem_t.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; border: none;")
            t_hdr.addWidget(lbl_mem_t)

        if m.fan_speed_rpm:
            lbl_fan = QLabel(f"🌀 {m.fan_speed_rpm} RPM")
            lbl_fan.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; border: none;")
            t_hdr.addWidget(lbl_fan)
        elif m.fan_speed_percent is not None:
            lbl_fan = QLabel(f"🌀 {m.fan_speed_percent:.0f}%")
            lbl_fan.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; border: none;")
            t_hdr.addWidget(lbl_fan)

        t_hdr.addStretch()
        therm_box.addLayout(t_hdr)

        t_bar = QProgressBar()
        t_bar.setFixedHeight(6)
        t_bar.setTextVisible(False)
        t_bar.setRange(0, 100)
        t_bar.setValue(int(min(100, max(0, m.temp_core_c))))
        t_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Theme.BG_SUBTLE};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {t_col};
                border-radius: 3px;
            }}
        """)
        therm_box.addWidget(t_bar)
        grid.addLayout(therm_box, 0, 1)

        # Col 2: Dedicated VRAM Usage & GPU Load (VRAM Bar prominent)
        load_box = QVBoxLayout()
        load_box.setSpacing(3)
        if m.vram_total_mb > 0:
            vram_u_gb = m.vram_used_mb / 1024.0
            vram_t_gb = m.vram_total_mb / 1024.0
            vram_pct = int(min(100, max(0, (m.vram_used_mb / m.vram_total_mb) * 100.0)))
            vram_txt = f"💾 VRAM: {vram_u_gb:.1f} / {vram_t_gb:.1f} GB ({vram_pct}%)   |   ⚡ Load: {m.gpu_util_percent:.0f}%"
            bar_val = vram_pct
        else:
            vram_txt = f"💾 VRAM: Shared RAM   |   ⚡ Load: {m.gpu_util_percent:.0f}%"
            bar_val = int(min(100, max(0, m.gpu_util_percent)))
        lbl_load = QLabel(vram_txt)
        lbl_load.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 700; border: none;")
        load_box.addWidget(lbl_load)

        u_bar = QProgressBar()
        u_bar.setFixedHeight(6)
        u_bar.setTextVisible(False)
        u_bar.setRange(0, 100)
        u_bar.setValue(bar_val)
        u_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Theme.BG_SUBTLE};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {Theme.CYBER_CYAN if m.vram_total_mb > 0 else v_col};
                border-radius: 3px;
            }}
        """)
        load_box.addWidget(u_bar)
        grid.addLayout(load_box, 0, 2)

        # Col 3: Wattage (Power Draw & Cap) & Clocks
        pwr_box = QVBoxLayout()
        pwr_box.setSpacing(2)
        if m.power_draw_w > 0:
            pwr_str = f"🔥 Wattage: {m.power_draw_w:.1f} W"
            if m.power_limit_w:
                pwr_str += f" / {m.power_limit_w:.0f} W"
        else:
            pwr_str = "🔥 Wattage: -- W"
        lbl_pwr = QLabel(pwr_str)
        lbl_pwr.setStyleSheet(f"color: {Theme.TEMP_WARM}; font-size: 12px; font-weight: 800; border: none;")
        pwr_box.addWidget(lbl_pwr)

        clk_str = f"Core: {m.clock_graphics_mhz or '--'} MHz • Mem: {m.clock_memory_mhz or '--'} MHz"
        lbl_clk = QLabel(clk_str)
        lbl_clk.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 10px; border: none;")
        pwr_box.addWidget(lbl_clk)
        grid.addLayout(pwr_box, 0, 3)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(3, 1)

        return row_frame
