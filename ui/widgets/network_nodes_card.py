"""
Network & Tailscale Tailnet Nodes + Remote GPU Thermal Monitor Card component.
Allows turning Tailscale-based GPU discovery/monitoring ON or OFF, toggling individual nodes,
switching between ultra-condensed single-line rows and detailed node cards, and monitoring
remote GPUs, thermals (Edge/Core, Junction/Hotspot, Memory), fan speeds, VRAM, power, and clocks.
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
        self.use_condensed_rows = True

        self._setup_ui()
        self.net_manager.nodes_updated.connect(self.update_nodes)
        self.net_manager.tailnet_scan_status.connect(self._on_tailnet_scan_status)
        self.net_manager.tailscale_enabled_changed.connect(self._on_tailscale_enabled_changed)

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
        self.main_layout.setContentsMargins(16, 12, 16, 12)
        self.main_layout.setSpacing(10)

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

        self.lbl_title = QLabel("Tailscale & Network GPUs")
        self.lbl_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        header_layout.addWidget(self.lbl_title)

        header_layout.addStretch()

        # Local Server IP/Port or Aggregated Tailnet Summary Badge
        lan_ips = get_local_lan_ips()
        ip_str = lan_ips[0] if lan_ips else "0.0.0.0"
        self.lbl_server_info = QLabel(f"🟢 Local Agent ({ip_str}:{self.net_manager.local_server.port})")
        self.lbl_server_info.setStyleSheet(f"color: {Theme.NVIDIA_GREEN}; font-size: 11px; font-weight: 600;")
        header_layout.addWidget(self.lbl_server_info)

        # Master Tailscale ON/OFF Toggle
        self.btn_tailscale_toggle = QPushButton()
        self.btn_tailscale_toggle.setCheckable(True)
        self.btn_tailscale_toggle.setChecked(self.net_manager.tailscale_enabled)
        self.btn_tailscale_toggle.setToolTip("Turn Tailscale-based GPU discovery & monitoring ON or OFF")
        self.btn_tailscale_toggle.clicked.connect(self._on_toggle_tailscale)
        self._apply_tailscale_btn_style(self.net_manager.tailscale_enabled)
        header_layout.addWidget(self.btn_tailscale_toggle)

        # Condensed Rows vs Detailed Cards toggle
        self.btn_dense_rows = QPushButton("⚡ Condensed Rows")
        self.btn_dense_rows.setCheckable(True)
        self.btn_dense_rows.setChecked(self.use_condensed_rows)
        self.btn_dense_rows.setToolTip("Toggle between ultra-condensed single-line GPU rows and detailed multi-line node cards")
        self.btn_dense_rows.clicked.connect(self._on_toggle_dense_rows)
        header_layout.addWidget(self.btn_dense_rows)

        # Pin remote GPUs as full GpuCards toggle
        self.btn_pin_cards = QPushButton("📌 Full Cards")
        self.btn_pin_cards.setCheckable(True)
        self.btn_pin_cards.setChecked(self.net_manager.pin_remote_cards)
        self.btn_pin_cards.setToolTip("Also render remote network GPUs as full cards with 60s sparklines in the dashboard")
        self.btn_pin_cards.clicked.connect(lambda c: self.net_manager.set_pin_remote_cards(c))
        header_layout.addWidget(self.btn_pin_cards)

        # Re-Scan Tailscale Tailnet & Network button
        self.btn_scan_tailnet = QPushButton("🔄 Re-Scan Network")
        self.btn_scan_tailnet.setToolTip("Re-scan all online machines in your Tailscale Tailnet (Linux, Windows, macOS) & LAN for GPUs")
        self.btn_scan_tailnet.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.CYBER_PURPLE}22;
                color: {Theme.CYBER_PURPLE};
                border: 1px solid {Theme.CYBER_PURPLE}66;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {Theme.CYBER_PURPLE}33;
            }}
            QPushButton:disabled {{
                background-color: {Theme.BG_SUBTLE};
                color: {Theme.TEXT_MUTED};
                border: 1px solid {Theme.BORDER_DEFAULT};
            }}
        """)
        self.btn_scan_tailnet.setEnabled(self.net_manager.tailscale_enabled)
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
        self.body_layout.setSpacing(8)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {Theme.BORDER_DEFAULT}; max-height: 1px;")
        self.body_layout.addWidget(divider)

        # 2. Add Remote Device Bar
        add_bar = QHBoxLayout()
        add_bar.setSpacing(8)

        lbl_add = QLabel("Add Node:")
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
                padding: 4px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Theme.CYBER_CYAN};
            }}
        """)
        self.txt_address.returnPressed.connect(self._on_add_node)
        add_bar.addWidget(self.txt_address, stretch=1)

        self.btn_add = QPushButton("➕ Connect")
        self.btn_add.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.CYBER_CYAN}22;
                color: {Theme.CYBER_CYAN};
                border: 1px solid {Theme.CYBER_CYAN}88;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
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
        self.nodes_layout.setSpacing(6)
        self.body_layout.addWidget(self.nodes_container)

        self.main_layout.addWidget(self.body_widget)
        self.update_nodes(self.net_manager.get_visible_states())

    def _apply_tailscale_btn_style(self, enabled: bool):
        self.btn_tailscale_toggle.blockSignals(True)
        self.btn_tailscale_toggle.setChecked(enabled)
        self.btn_tailscale_toggle.blockSignals(False)
        if enabled:
            self.btn_tailscale_toggle.setText("🦊 Tailscale: ON")
            self.btn_tailscale_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.NVIDIA_GREEN}22;
                    color: {Theme.NVIDIA_GREEN};
                    border: 1px solid {Theme.NVIDIA_GREEN}88;
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-size: 11px;
                    font-weight: 800;
                }}
                QPushButton:hover {{
                    background-color: {Theme.NVIDIA_GREEN}33;
                }}
            """)
        else:
            self.btn_tailscale_toggle.setText("🦊 Tailscale: OFF")
            self.btn_tailscale_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.BG_SUBTLE};
                    color: {Theme.TEXT_MUTED};
                    border: 1px solid {Theme.BORDER_DEFAULT};
                    border-radius: 6px;
                    padding: 5px 10px;
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
        self._apply_tailscale_btn_style(enabled)
        self.btn_scan_tailnet.setEnabled(enabled)
        self.update_nodes(self.net_manager.get_visible_states())

    def _on_toggle_dense_rows(self, checked: bool):
        self.use_condensed_rows = checked
        self.update_nodes(self.net_manager.get_visible_states())

    def _on_tailnet_scan_status(self, msg: str):
        if msg:
            self.lbl_scan_status.setText(msg)
            self.lbl_scan_status.setVisible(True)
            self.btn_scan_tailnet.setText("🔄 Scanning...")
        else:
            self.lbl_scan_status.setVisible(False)
            self.btn_scan_tailnet.setText("🔄 Re-Scan Network")

    def toggle_expanded(self):
        self.set_expanded(not self.is_expanded)

    def set_expanded(self, expanded: bool):
        self.is_expanded = expanded
        self.body_widget.setVisible(expanded)
        self.btn_toggle.setText("▲ Collapse" if expanded else "▼ Expand Network")

    def _on_scan_tailnet_clicked(self):
        if not self.net_manager.tailscale_enabled:
            self.net_manager.set_tailscale_enabled(True)
        self.btn_scan_tailnet.setText("🔄 Scanning...")
        self.net_manager.rescan_network()

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
        self.update_nodes(self.net_manager.get_visible_states())

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
        if not self.net_manager.tailscale_enabled and not states:
            self.lbl_server_info.setText(f"🦊 Tailscale OFF • 🟢 Local Agent ({ip_str}:{self.net_manager.local_server.port})")
        elif net_vram_t > 0 or net_pwr > 0:
            self.lbl_server_info.setText(
                f"💾 Net VRAM: {net_vram_u:.1f}/{net_vram_t:.1f} GB • 🔥 {net_pwr:.1f} W • 🌡 Peak: {net_peak_t:.0f}°C"
            )
        else:
            self.lbl_server_info.setText(f"🟢 Local Agent ({ip_str}:{self.net_manager.local_server.port})")

        self._clear_layout(self.nodes_layout)

        # Also inspect all configured nodes so disabled individual nodes can still be re-enabled
        all_configs = dict(self.net_manager.configs)
        all_states = dict(self.net_manager.states)

        if not self.net_manager.tailscale_enabled:
            ts_Banner = QFrame()
            ts_Banner.setStyleSheet(f"""
                QFrame {{
                    background-color: {Theme.BG_ROOT};
                    border: 1px dashed {Theme.BORDER_DEFAULT};
                    border-radius: 8px;
                }}
            """)
            bl = QHBoxLayout(ts_Banner)
            bl.setContentsMargins(12, 8, 12, 8)
            lbl_off = QLabel("🦊 Tailscale-based GPU discovery & polling is currently OFF.")
            lbl_off.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px; font-weight: 600; border: none;")
            bl.addWidget(lbl_off)
            bl.addStretch()
            btn_enable_ts = QPushButton("Turn Tailscale ON")
            btn_enable_ts.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.NVIDIA_GREEN}22;
                    color: {Theme.NVIDIA_GREEN};
                    border: 1px solid {Theme.NVIDIA_GREEN}77;
                    border-radius: 5px;
                    padding: 3px 10px;
                    font-size: 11px;
                    font-weight: 700;
                }}
            """)
            btn_enable_ts.clicked.connect(lambda: self.net_manager.set_tailscale_enabled(True))
            bl.addWidget(btn_enable_ts)
            self.nodes_layout.addWidget(ts_Banner)

        # Build list of nodes to display in the manager
        display_items = []
        for nid, st in all_states.items():
            cfg = all_configs.get(nid)
            is_ts = st.is_tailscale or (cfg.is_tailscale if cfg else False)
            if is_ts and not self.net_manager.tailscale_enabled:
                continue
            display_items.append((nid, st, cfg))

        if not display_items:
            if self.net_manager.tailscale_enabled:
                empty_box = QFrame()
                empty_box.setStyleSheet(f"""
                    QFrame {{
                        background-color: {Theme.BG_ROOT};
                        border: 1px dashed {Theme.BORDER_DEFAULT};
                        border-radius: 8px;
                    }}
                """)
                el = QVBoxLayout(empty_box)
                el.setContentsMargins(12, 10, 12, 10)
                el.setSpacing(3)
                lbl_e1 = QLabel("Scanning Tailscale Tailnet & LAN for GPU-equipped machines...")
                lbl_e1.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px; font-weight: 600; border: none;")
                lbl_e2 = QLabel(
                    "Click '🦊 Scan Tailnet' to probe online Tailscale peers via SSH / HTTP (:51920 / :8085), or add a host above."
                )
                lbl_e2.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; border: none;")
                el.addWidget(lbl_e1)
                el.addWidget(lbl_e2)
                self.nodes_layout.addWidget(empty_box)
            return

        # Sort enabled + online nodes with largest VRAM first
        def _sort_key(item):
            _, st, cfg = item
            en = cfg.enabled if cfg else True
            max_vram = max((g.vram_total_mb for g in st.gpus), default=0.0)
            return (not en, not st.online, -max_vram, st.hostname.lower())

        for node_id, st, cfg in sorted(display_items, key=_sort_key):
            if self.use_condensed_rows:
                node_widget = self._build_condensed_node_widget(node_id, st, cfg)
            else:
                node_widget = self._build_node_widget(node_id, st, cfg)
            self.nodes_layout.addWidget(node_widget)

    def _build_condensed_node_widget(self, node_id: str, st: RemoteNodeState, cfg) -> QFrame:
        """Ultra-condensed single-line row per remote GPU (or offline/disabled node)."""
        is_enabled = cfg.enabled if cfg else True
        frame = QFrame()
        border_col = Theme.BORDER_DEFAULT if (st.online and is_enabled) else "#2d1b22"
        bg_col = Theme.BG_ROOT if is_enabled else "#0c0e13"
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_col};
                border: 1px solid {border_col};
                border-radius: 6px;
            }}
        """)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(10, 5, 10, 5)
        outer.setSpacing(4)

        gpus = st.gpus if (st.online and is_enabled and st.gpus) else [None]
        for idx, dev in enumerate(gpus):
            row = QHBoxLayout()
            row.setSpacing(8)

            # 1. Status Dot + Hostname + Badge
            if not is_enabled:
                dot_col = Theme.TEXT_MUTED
                dot_txt = "⏸"
            elif st.online:
                dot_col = Theme.NVIDIA_GREEN
                dot_txt = "●"
            else:
                dot_col = Theme.TEMP_CRITICAL
                dot_txt = "○"

            lbl_host = QLabel(f"{dot_txt} {st.hostname[:14]}")
            lbl_host.setFixedWidth(115)
            lbl_host.setStyleSheet(f"color: {dot_col if not st.online or not is_enabled else '#ffffff'}; font-size: 12px; font-weight: 800; border: none;")
            lbl_host.setToolTip(f"{st.hostname} ({st.tailscale_ip or st.address}) • {st.protocol.upper()} • {st.latency_ms:.0f} ms")
            row.addWidget(lbl_host)

            if st.is_tailscale:
                b_txt = "TS"
                b_col = Theme.CYBER_PURPLE
            else:
                b_txt = st.protocol.upper()[:3]
                b_col = Theme.INTEL_BLUE
            lbl_tag = QLabel(b_txt)
            lbl_tag.setFixedWidth(28)
            lbl_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_tag.setStyleSheet(f"""
                background-color: {b_col}22;
                color: {b_col};
                border: 1px solid {b_col}55;
                border-radius: 3px;
                font-size: 9px;
                font-weight: 800;
            """)
            row.addWidget(lbl_tag)

            if dev is not None:
                m = st.gpu_metrics.get(dev.device_id, dev.metrics)
                v_col = Theme.get_vendor_color(dev.vendor)
                eff_temp = max(m.temp_core_c, (m.temp_hotspot_c - 22.0) if m.temp_hotspot_c else 0.0)
                t_col = Theme.get_temp_color(eff_temp)
                t_status = Theme.get_temp_status(eff_temp)

                # 2. GPU Model Name
                lbl_gpu = QLabel(dev.name[:28])
                lbl_gpu.setMinimumWidth(165)
                lbl_gpu.setStyleSheet(f"color: {v_col}; font-size: 11px; font-weight: 700; border: none;")
                lbl_gpu.setToolTip(f"{dev.name} ({dev.vendor})")
                row.addWidget(lbl_gpu, stretch=2)

                # 3. GPU Load mini bar + %
                load_bar = QProgressBar()
                load_bar.setFixedSize(50, 6)
                load_bar.setTextVisible(False)
                load_bar.setRange(0, 100)
                load_bar.setValue(int(min(100, max(0, m.gpu_util_percent))))
                load_bar.setStyleSheet(f"""
                    QProgressBar {{ background-color: {Theme.BG_SUBTLE}; border: none; border-radius: 3px; }}
                    QProgressBar::chunk {{ background-color: {v_col}; border-radius: 3px; }}
                """)
                row.addWidget(load_bar)

                lbl_load = QLabel(f"{m.gpu_util_percent:3.0f}%")
                lbl_load.setFixedWidth(36)
                lbl_load.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 700; border: none;")
                row.addWidget(lbl_load)

                # 4. VRAM mini bar + GB
                vram_bar = QProgressBar()
                vram_bar.setFixedSize(55, 6)
                vram_bar.setTextVisible(False)
                vram_bar.setRange(0, 100)
                if m.vram_total_mb > 0:
                    vram_u = m.vram_used_mb / 1024.0
                    vram_t = m.vram_total_mb / 1024.0
                    vram_pct = int(min(100, max(0, (m.vram_used_mb / m.vram_total_mb) * 100.0)))
                    vram_bar.setValue(vram_pct)
                    vram_txt = f"VRAM {vram_u:4.1f}/{vram_t:4.1f}G ({vram_pct:2d}%)"
                else:
                    vram_bar.setValue(0)
                    vram_txt = "Shared iGPU RAM"
                vram_bar.setStyleSheet(f"""
                    QProgressBar {{ background-color: {Theme.BG_SUBTLE}; border: none; border-radius: 3px; }}
                    QProgressBar::chunk {{ background-color: {Theme.CYBER_CYAN}; border-radius: 3px; }}
                """)
                row.addWidget(vram_bar)

                lbl_vram = QLabel(vram_txt)
                lbl_vram.setFixedWidth(135)
                lbl_vram.setStyleSheet("color: #f0f6fc; font-size: 11px; font-weight: 600; border: none;")
                row.addWidget(lbl_vram)

                # 5. Multi-Sensor Thermals (Edge + Junc + Mem + Fan)
                therm_parts = [f"🌡{m.temp_core_c:.0f}°C [{t_status[:4]}]"]
                if m.temp_hotspot_c and m.temp_hotspot_c > 0:
                    therm_parts.append(f"J:{m.temp_hotspot_c:.0f}°")
                if m.temp_memory_c and m.temp_memory_c > 0:
                    therm_parts.append(f"M:{m.temp_memory_c:.0f}°")
                if m.fan_speed_rpm and m.fan_speed_rpm > 0:
                    therm_parts.append(f"🌀{m.fan_speed_rpm}")
                elif m.fan_speed_percent is not None and m.fan_speed_percent > 0:
                    therm_parts.append(f"🌀{m.fan_speed_percent:.0f}%")
                lbl_therm = QLabel(" ".join(therm_parts))
                lbl_therm.setMinimumWidth(165)
                lbl_therm.setStyleSheet(f"color: {t_col}; font-size: 11px; font-weight: 700; border: none;")
                row.addWidget(lbl_therm, stretch=2)

                # 6. Power Draw
                if m.power_draw_w > 0:
                    pwr_s = f"🔥 {m.power_draw_w:.0f}/{m.power_limit_w:.0f}W" if m.power_limit_w else f"🔥 {m.power_draw_w:.1f}W"
                else:
                    pwr_s = "🔥 --W"
                lbl_pwr = QLabel(pwr_s)
                lbl_pwr.setFixedWidth(82)
                lbl_pwr.setStyleSheet(f"color: {Theme.TEMP_WARM}; font-size: 11px; font-weight: 700; border: none;")
                row.addWidget(lbl_pwr)
            else:
                if not is_enabled:
                    msg = "Node monitoring paused (OFF)"
                elif not st.online:
                    msg = f"Offline {('— ' + st.error_msg) if st.error_msg else ''}"
                else:
                    msg = "Online — No GPUs reported"
                lbl_msg = QLabel(msg)
                lbl_msg.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; border: none;")
                row.addWidget(lbl_msg, stretch=1)

            # 7. Per-node ON/OFF & Remove buttons (on first row of node)
            if idx == 0:
                btn_en = QPushButton("ON" if is_enabled else "OFF")
                btn_en.setFixedWidth(38)
                btn_en.setToolTip("Enable or disable polling this remote node")
                en_col = Theme.NVIDIA_GREEN if is_enabled else Theme.TEXT_MUTED
                btn_en.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        border: 1px solid {en_col}66;
                        border-radius: 4px;
                        padding: 1px 4px;
                        color: {en_col};
                        font-size: 9px;
                        font-weight: 800;
                    }}
                    QPushButton:hover {{
                        border-color: {Theme.CYBER_CYAN};
                    }}
                """)
                btn_en.clicked.connect(lambda checked=False, nid=node_id, cur=is_enabled: self.net_manager.set_node_enabled(nid, not cur))
                row.addWidget(btn_en)

                btn_rm = QPushButton("✕")
                btn_rm.setFixedWidth(22)
                btn_rm.setToolTip("Remove node")
                btn_rm.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        border: 1px solid {Theme.BORDER_DEFAULT};
                        border-radius: 4px;
                        padding: 1px;
                        color: {Theme.TEXT_MUTED};
                        font-size: 9px;
                    }}
                    QPushButton:hover {{
                        border-color: {Theme.TEMP_CRITICAL};
                        color: {Theme.TEMP_CRITICAL};
                    }}
                """)
                btn_rm.clicked.connect(lambda checked=False, nid=node_id: self.net_manager.remove_node(nid))
                row.addWidget(btn_rm)

            outer.addLayout(row)

        return frame

    def _build_node_widget(self, node_id: str, st: RemoteNodeState, cfg=None) -> QFrame:
        is_enabled = cfg.enabled if cfg else True
        frame = QFrame()
        border_col = Theme.BORDER_ACCENT if (st.online and is_enabled) else "#3d1e24"
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

        if not is_enabled:
            status_col = Theme.TEXT_MUTED
            status_txt = "⏸ PAUSED (OFF)"
        elif st.online:
            status_col = Theme.NVIDIA_GREEN
            status_txt = f"● ONLINE ({st.latency_ms:.0f} ms)"
        else:
            status_col = Theme.TEMP_CRITICAL
            status_txt = "● OFFLINE"
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
        if st.online and is_enabled and (st.host_metrics.cpu.load_percent > 0 or st.host_metrics.ram.total_gb > 0):
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

        if not st.online and is_enabled and st.error_msg:
            lbl_err = QLabel(st.error_msg)
            lbl_err.setStyleSheet(f"color: {Theme.TEMP_HOT}; font-size: 11px; border: none;")
            hdr.addWidget(lbl_err)

        btn_en = QPushButton("🟢 ON" if is_enabled else "⚪ OFF")
        btn_en.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 2px 8px;
                color: {Theme.NVIDIA_GREEN if is_enabled else Theme.TEXT_MUTED};
                font-size: 10px;
                font-weight: 700;
            }}
        """)
        btn_en.clicked.connect(lambda checked=False, nid=node_id, cur=is_enabled: self.net_manager.set_node_enabled(nid, not cur))
        hdr.addWidget(btn_en)

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
        if st.online and is_enabled and st.gpus:
            for dev in st.gpus:
                m = st.gpu_metrics.get(dev.device_id, dev.metrics)
                gpu_row = self._build_remote_gpu_thermal_row(dev, m)
                layout.addWidget(gpu_row)
        elif st.online and is_enabled:
            lbl_no_gpu = QLabel("Connected to host, but no GPUs were reported.")
            lbl_no_gpu.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px; border: none;")
            layout.addWidget(lbl_no_gpu)

        return frame

    def _build_remote_gpu_thermal_row(self, dev, m) -> QFrame:
        row_frame = QFrame()
        v_col = Theme.get_vendor_color(dev.vendor)
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

        # Col 2: Dedicated VRAM Usage & GPU Load
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
