"""
Unified background monitor worker using QThread.
Collects real-time metrics across all detected GPUs asynchronously without UI blocking.
"""

import time
from typing import Dict, List, Optional
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker

from core.gpu_types import GpuDevice, GpuMetrics, HostMetrics
from core.nvml_backend import NvmlBackend
from core.adl_backend import AdlBackend
from core.dxgi_backend import DxgiBackend
from core.host_backend import HostBackend


class MonitorWorker(QThread):
    # Signals
    devices_discovered = pyqtSignal(list)       # List[GpuDevice]
    metrics_updated = pyqtSignal(dict)          # Dict[str, GpuMetrics]
    host_updated = pyqtSignal(object)           # HostMetrics
    summary_updated = pyqtSignal(dict)          # Global summary dict

    def __init__(self, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.interval_ms = interval_ms
        self._running = True
        self._paused = False
        self._mutex = QMutex()

        self.nvml = NvmlBackend()
        self.adl = AdlBackend()
        self.dxgi = DxgiBackend()
        self.host = HostBackend(adl_backend=self.adl)

        self.devices: List[GpuDevice] = []
        self._init_devices()

    def _init_devices(self):
        discovered: List[GpuDevice] = []
        used_luid_keys = set()

        # 1. NVIDIA Devices
        if self.nvml.available:
            nv_devs = self.nvml.get_devices()
            for d in nv_devs:
                # Find matching DXGI adapter for LUID
                dx_match = self.dxgi.get_adapter_info("NVIDIA", d.name)
                if dx_match:
                    d.luid = dx_match["luid_key"]
                    used_luid_keys.add(dx_match["luid_key"])
                    if d.vram_total_mb <= 0:
                        d.vram_total_mb = dx_match["dedicated_vram_mb"]
                discovered.append(d)

        # 2. AMD Devices
        if self.adl.available:
            amd_devs = self.adl.get_devices()
            for d in amd_devs:
                dx_match = self.dxgi.get_adapter_info("AMD", d.name)
                if dx_match:
                    d.luid = dx_match["luid_key"]
                    used_luid_keys.add(dx_match["luid_key"])
                    d.vram_total_mb = dx_match["dedicated_vram_mb"]
                discovered.append(d)

        # 3. Any additional physical non-software adapters from DXGI (e.g. Intel Arc/iGPU)
        for adp in self.dxgi.adapters:
            if adp["luid_key"] in used_luid_keys:
                continue
            desc_lower = adp["description"].lower()
            if "basic render" in desc_lower or "software" in desc_lower or adp["dedicated_vram_mb"] <= 0:
                continue
            v_name = "Intel" if adp["vendor_id"] == 0x8086 else "Other"
            dev_id = f"dxgi_{len(discovered)}"
            new_dev = GpuDevice(
                device_id=dev_id,
                index=len(discovered),
                name=adp["description"],
                vendor=v_name,
                vram_total_mb=adp["dedicated_vram_mb"],
                luid=adp["luid_key"],
            )
            discovered.append(new_dev)

        self.devices = discovered

    def set_interval(self, interval_ms: int):
        with QMutexLocker(self._mutex):
            self.interval_ms = max(200, interval_ms)

    def set_paused(self, paused: bool):
        with QMutexLocker(self._mutex):
            self._paused = paused

    def stop(self):
        with QMutexLocker(self._mutex):
            self._running = False
        self.wait(2000)
        self.nvml.shutdown()
        self.adl.shutdown()
        self.dxgi.shutdown()

    def run(self):
        # Emit initial device list
        self.devices_discovered.emit(self.devices)

        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
                paused = self._paused
                interval = self.interval_ms

            if not paused:
                t0 = time.perf_counter()
                metrics_by_id: Dict[str, GpuMetrics] = {}
                pdh_mems = self.dxgi.sample_memory_by_luid()

                total_power = 0.0
                max_temp = 0.0
                max_load = 0.0
                total_vram_used = 0.0
                total_vram_cap = 0.0
                peak_temp_gpu = ""

                for dev in self.devices:
                    m = GpuMetrics()
                    if dev.vendor == "NVIDIA" and self.nvml.available:
                        m = self.nvml.sample_metrics(dev.index)
                    elif dev.vendor == "AMD" and self.adl.available:
                        m = self.adl.sample_metrics(dev.index)
                        # Set VRAM from PDH and DXGI
                        if dev.luid in pdh_mems:
                            m.vram_used_mb = pdh_mems[dev.luid]
                        m.vram_total_mb = dev.vram_total_mb
                        if m.vram_total_mb > 0:
                            m.vram_free_mb = max(0.0, m.vram_total_mb - m.vram_used_mb)
                    else:
                        # Fallback for generic/Intel
                        if dev.luid in pdh_mems:
                            m.vram_used_mb = pdh_mems[dev.luid]
                        m.vram_total_mb = dev.vram_total_mb

                    metrics_by_id[dev.device_id] = m

                    # Accumulate summary stats
                    total_power += m.power_draw_w
                    if m.temp_core_c > max_temp:
                        max_temp = m.temp_core_c
                        peak_temp_gpu = dev.name
                    if m.gpu_util_percent > max_load:
                        max_load = m.gpu_util_percent
                    total_vram_used += m.vram_used_mb
                    total_vram_cap += m.vram_total_mb

                # Sample Host (CPU & RAM)
                host_m = self.host.sample_metrics()
                self.host_updated.emit(host_m)

                summary = {
                    "gpu_count": len(self.devices),
                    "total_power_w": round(total_power, 1),
                    "peak_temp_c": round(max_temp, 1),
                    "peak_temp_gpu": peak_temp_gpu,
                    "peak_load_pct": round(max_load, 1),
                    "total_vram_used_gb": round(total_vram_used / 1024, 2),
                    "total_vram_cap_gb": round(total_vram_cap / 1024, 2),
                    "cpu_name": host_m.cpu.name,
                    "cpu_load_pct": round(host_m.cpu.load_percent, 1),
                    "cpu_temp_c": round(host_m.cpu.temp_core_c, 1),
                    "ram_used_gb": host_m.ram.used_gb,
                    "ram_total_gb": host_m.ram.total_gb,
                    "ram_load_pct": round(host_m.ram.load_percent, 1),
                    "poll_latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                }

                self.metrics_updated.emit(metrics_by_id)
                self.summary_updated.emit(summary)

            self.msleep(interval)
