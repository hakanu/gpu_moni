"""
Host System (CPU and RAM) telemetry backend.
Collects processor load, per-core utilization, clock frequency,
thermals, memory usage, and top processes with microsecond overhead.
"""

import winreg
import psutil
from typing import List, Optional, Tuple
from core.gpu_types import HostMetrics, CpuMetrics, RamMetrics, GpuProcess


class HostBackend:
    def __init__(self, adl_backend=None):
        self.adl_backend = adl_backend
        self.cpu_name = self._get_cpu_name()
        self.cores_phys = psutil.cpu_count(logical=False) or 0
        self.cores_log = psutil.cpu_count(logical=True) or 0

        # Prime psutil CPU percent calculations
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)

    def _get_cpu_name(self) -> str:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            raw_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return " ".join(raw_name.strip().split())
        except Exception:
            return "Central Processor"

    def sample_metrics(self) -> HostMetrics:
        metrics = HostMetrics()

        # 1. CPU Load & Clocks
        cpu_load = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)

        freq_mhz = 0.0
        try:
            freq_info = psutil.cpu_freq()
            if freq_info:
                freq_mhz = round(freq_info.current, 0)
        except Exception:
            pass

        # 2. CPU Thermals & Power
        temp_core = 0.0
        temp_hotspot = None
        power_w = None

        if self.adl_backend and self.adl_backend.available:
            try:
                # Query ADL sensors for CPU package temp and power
                if hasattr(self.adl_backend.adl, "ADL2_New_QueryPMLogData_Get") and self.adl_backend.context.value:
                    import ctypes
                    buf = ctypes.create_string_buffer(4096)
                    ctypes.cast(buf, ctypes.POINTER(ctypes.c_int))[0] = 2052
                    if self.adl_backend.adl.ADL2_New_QueryPMLogData_Get(self.adl_backend.context, 0, buf) == 0:
                        int_arr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_int))
                        # S_TEMP_EXTRA_1 (28), S_TEMP_EXTRA_2 (29), S_CPU_POWER (40)
                        if int_arr[1 + 28 * 2]:
                            temp_core = float(int_arr[2 + 28 * 2])
                        elif int_arr[1 + 8 * 2]:
                            temp_core = float(int_arr[2 + 8 * 2])

                        if int_arr[1 + 29 * 2]:
                            temp_hotspot = float(int_arr[2 + 29 * 2])

                        if int_arr[1 + 40 * 2]:
                            power_w = float(int_arr[2 + 40 * 2])
            except Exception:
                pass

        metrics.cpu = CpuMetrics(
            name=self.cpu_name,
            cores_physical=self.cores_phys,
            cores_logical=self.cores_log,
            load_percent=float(cpu_load),
            per_core_load=[float(p) for p in per_core],
            freq_mhz=freq_mhz,
            temp_core_c=temp_core,
            temp_hotspot_c=temp_hotspot,
            power_draw_w=power_w,
        )

        # 3. RAM (System Memory)
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            metrics.ram = RamMetrics(
                used_gb=round(mem.used / (1024 ** 3), 2),
                total_gb=round(mem.total / (1024 ** 3), 2),
                free_gb=round(mem.available / (1024 ** 3), 2),
                load_percent=float(mem.percent),
                pagefile_used_gb=round(swap.used / (1024 ** 3), 2),
                pagefile_total_gb=round(swap.total / (1024 ** 3), 2),
            )
        except Exception:
            pass

        # 4. Top CPU Processes (limit to top 5)
        top_procs = []
        try:
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                try:
                    info = p.info
                    c_pct = info.get("cpu_percent")
                    if c_pct and c_pct > 0.5:
                        mem_info = info.get("memory_info")
                        mem_mb = round(mem_info.rss / (1024 * 1024), 1) if mem_info else None
                        top_procs.append(
                            GpuProcess(
                                pid=info["pid"],
                                name=info["name"],
                                memory_used_mb=mem_mb,
                                process_type=f"{c_pct:.1f}% CPU",
                            )
                        )
                except Exception:
                    continue
            top_procs.sort(
                key=lambda x: float(x.process_type.split("%")[0]) if "%" in x.process_type else 0.0,
                reverse=True,
            )
            metrics.top_processes = top_procs[:6]
        except Exception:
            pass

        return metrics
