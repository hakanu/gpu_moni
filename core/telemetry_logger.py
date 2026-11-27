"""
Session Peak Tracker & CSV/JSONL Telemetry Logger for GPU Sentry.
Tracks per-GPU session highs (Peak Temp, Peak Power, Peak VRAM, Peak Load)
and optionally logs timestamped telemetry snapshots to CSV or JSONL files.
"""

import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from core.gpu_types import GpuDevice, GpuMetrics, HostMetrics
from core.settings import get_settings


DEFAULT_LOG_DIR = os.path.join(os.path.expanduser("~"), "GPU_Sentry_Logs")


@dataclass
class DevicePeakStats:
    peak_temp_c: float = 0.0
    peak_power_w: float = 0.0
    peak_vram_mb: float = 0.0
    peak_load_pct: float = 0.0


class SessionPeakTracker:
    """Tracks session-wide peaks for every local and remote GPU."""

    def __init__(self):
        self.peaks: Dict[str, DevicePeakStats] = {}

    def update(self, metrics_by_id: Dict[str, GpuMetrics]):
        for dev_id, m in metrics_by_id.items():
            st = self.peaks.get(dev_id)
            if st is None:
                st = DevicePeakStats()
                self.peaks[dev_id] = st
            if m.temp_core_c > st.peak_temp_c:
                st.peak_temp_c = round(m.temp_core_c, 1)
            if m.power_draw_w > st.peak_power_w:
                st.peak_power_w = round(m.power_draw_w, 1)
            if m.vram_used_mb > st.peak_vram_mb:
                st.peak_vram_mb = round(m.vram_used_mb, 1)
            if m.gpu_util_percent > st.peak_load_pct:
                st.peak_load_pct = round(m.gpu_util_percent, 1)

    def get(self, dev_id: str) -> Optional[DevicePeakStats]:
        return self.peaks.get(dev_id)

    def reset(self):
        self.peaks.clear()


class TelemetryLogger:
    """Appends live GPU & Host telemetry snapshots to CSV or JSONL files."""

    CSV_HEADERS = [
        "timestamp",
        "cpu_load_pct",
        "cpu_temp_c",
        "ram_used_gb",
        "ram_total_gb",
        "device_id",
        "gpu_name",
        "gpu_util_pct",
        "temp_core_c",
        "temp_hotspot_c",
        "vram_used_mb",
        "vram_total_mb",
        "power_draw_w",
        "top_workload",
    ]

    def get_log_dir(self) -> str:
        custom = (get_settings().data.logging_dir or "").strip()
        return custom if custom else DEFAULT_LOG_DIR

    def log_snapshot(
        self,
        devices: List[GpuDevice],
        metrics_by_id: Dict[str, GpuMetrics],
        host_metrics: Optional[HostMetrics],
    ):
        sd = get_settings().data
        if not sd.logging_enabled:
            return

        log_dir = self.get_log_dir()
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            return

        now = datetime.now()
        ts = now.isoformat(timespec="seconds")
        day_tag = now.strftime("%Y%m%d")
        fmt = (sd.logging_format or "csv").lower()

        cpu_pct = round(host_metrics.cpu.load_percent, 1) if host_metrics else 0.0
        cpu_t = round(host_metrics.cpu.temp_core_c, 1) if host_metrics else 0.0
        ram_u = round(host_metrics.ram.used_gb, 2) if host_metrics else 0.0
        ram_t = round(host_metrics.ram.total_gb, 2) if host_metrics else 0.0

        try:
            if fmt == "jsonl":
                fpath = os.path.join(log_dir, f"gpu_sentry_{day_tag}.jsonl")
                entry = {
                    "timestamp": ts,
                    "cpu_load_pct": cpu_pct,
                    "cpu_temp_c": cpu_t,
                    "ram_used_gb": ram_u,
                    "ram_total_gb": ram_t,
                    "gpus": [],
                }
                for dev in devices:
                    m = metrics_by_id.get(dev.device_id)
                    if not m:
                        continue
                    top_wl = ""
                    if m.processes:
                        p0 = m.processes[0]
                        top_wl = p0.workload_label or p0.name
                    entry["gpus"].append({
                        "device_id": dev.device_id,
                        "name": dev.name,
                        "util_pct": round(m.gpu_util_percent, 1),
                        "temp_core_c": round(m.temp_core_c, 1),
                        "temp_hotspot_c": round(m.temp_hotspot_c, 1) if m.temp_hotspot_c else None,
                        "vram_used_mb": round(m.vram_used_mb, 1),
                        "vram_total_mb": round(m.vram_total_mb, 1),
                        "power_draw_w": round(m.power_draw_w, 1),
                        "top_workload": top_wl,
                    })
                with open(fpath, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            else:
                fpath = os.path.join(log_dir, f"gpu_sentry_{day_tag}.csv")
                need_header = not os.path.isfile(fpath) or os.path.getsize(fpath) == 0
                with open(fpath, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    if need_header:
                        writer.writerow(self.CSV_HEADERS)
                    for dev in devices:
                        m = metrics_by_id.get(dev.device_id)
                        if not m:
                            continue
                        top_wl = ""
                        if m.processes:
                            p0 = m.processes[0]
                            top_wl = p0.workload_label or p0.name
                        writer.writerow([
                            ts,
                            cpu_pct,
                            cpu_t,
                            ram_u,
                            ram_t,
                            dev.device_id,
                            dev.name,
                            round(m.gpu_util_percent, 1),
                            round(m.temp_core_c, 1),
                            round(m.temp_hotspot_c, 1) if m.temp_hotspot_c else "",
                            round(m.vram_used_mb, 1),
                            round(m.vram_total_mb, 1),
                            round(m.power_draw_w, 1),
                            top_wl,
                        ])
        except Exception:
            pass
