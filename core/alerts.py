"""
Thermal, VRAM Pressure, and Remote Node Offline Alert Engine for GPU Sentry.
Uses per-device cooldowns so desktop notifications inform without spamming.
"""

import time
from typing import Dict, List, Tuple

from core.gpu_types import GpuDevice, GpuMetrics
from core.settings import get_settings, format_temp


class AlertManager:
    """Evaluates telemetry against user thresholds and emits deduplicated alerts."""

    def __init__(self):
        self._last_fired: Dict[str, float] = {}
        self._prev_online: Dict[str, bool] = {}

    def evaluate_gpus(
        self,
        devices: List[GpuDevice],
        metrics_by_id: Dict[str, GpuMetrics],
    ) -> List[Tuple[str, str, str]]:
        """Returns list of (title, message, level) alerts where level is 'warning' or 'critical'."""
        sd = get_settings().data
        if not sd.alerts_enabled:
            return []

        now = time.time()
        cooldown = max(15, int(sd.alert_cooldown_sec or 120))
        temp_thresh = float(sd.alert_temp_c or 85)
        vram_thresh = float(sd.alert_vram_pct or 95)
        unit = sd.temp_unit
        alerts: List[Tuple[str, str, str]] = []

        for dev in devices:
            m = metrics_by_id.get(dev.device_id)
            if not m:
                continue

            # 1. Thermal Alert
            if m.temp_core_c >= temp_thresh and temp_thresh > 0:
                key = f"temp:{dev.device_id}"
                if now - self._last_fired.get(key, 0.0) >= cooldown:
                    self._last_fired[key] = now
                    level = "critical" if m.temp_core_c >= temp_thresh + 5 else "warning"
                    alerts.append((
                        f"High GPU Temperature — {dev.name}",
                        f"{dev.name} reached {format_temp(m.temp_core_c, unit)} (threshold: {format_temp(temp_thresh, unit)}).",
                        level,
                    ))

            # 2. VRAM Pressure Alert
            if m.vram_total_mb > 0 and vram_thresh > 0:
                vram_pct = (m.vram_used_mb / m.vram_total_mb) * 100.0
                if vram_pct >= vram_thresh:
                    key = f"vram:{dev.device_id}"
                    if now - self._last_fired.get(key, 0.0) >= cooldown:
                        self._last_fired[key] = now
                        used_gb = m.vram_used_mb / 1024.0
                        tot_gb = m.vram_total_mb / 1024.0
                        alerts.append((
                            f"VRAM Nearly Full — {dev.name}",
                            f"{dev.name} is at {vram_pct:.0f}% VRAM ({used_gb:.1f} / {tot_gb:.1f} GB).",
                            "warning",
                        ))

        return alerts

    def evaluate_remote_nodes(self, states: Dict[str, object]) -> List[Tuple[str, str, str]]:
        """Emits alerts when a previously-online remote Tailnet/LAN node goes offline."""
        sd = get_settings().data
        if not sd.alerts_enabled or not sd.alert_node_offline:
            return []

        now = time.time()
        cooldown = max(30, int(sd.alert_cooldown_sec or 120))
        alerts: List[Tuple[str, str, str]] = []

        for nid, st in states.items():
            is_on = bool(getattr(st, "online", False))
            was_on = self._prev_online.get(nid)
            self._prev_online[nid] = is_on
            if was_on is True and not is_on:
                key = f"offline:{nid}"
                if now - self._last_fired.get(key, 0.0) >= cooldown:
                    self._last_fired[key] = now
                    hn = getattr(st, "hostname", nid)
                    alerts.append((
                        f"Remote GPU Node Offline — {hn}",
                        f"{hn} is no longer reachable ({getattr(st, 'error_msg', 'offline')}).",
                        "warning",
                    ))
        return alerts
