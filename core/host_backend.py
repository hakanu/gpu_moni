"""
Host System (CPU and RAM) telemetry backend.
Collects processor load, per-core utilization, clock frequency,
thermals, and memory usage with microsecond overhead.
"""

import glob
import os
import time
import psutil
try:
    import winreg
except ImportError:
    winreg = None
from typing import List, Optional
from core.gpu_types import HostMetrics, CpuMetrics, RamMetrics, GpuProcess


class HostBackend:
    def __init__(self, adl_backend=None):
        self.adl_backend = adl_backend
        self.cpu_name = self._get_cpu_name()
        self.cores_phys = psutil.cpu_count(logical=False) or 0
        self.cores_log = psutil.cpu_count(logical=True) or 0
        self._last_rapl_uj: Optional[int] = None
        self._last_rapl_ts: float = 0.0

        # Prime psutil CPU percent calculations
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)
        self._sample_linux_cpu_power()

    def _get_cpu_name(self) -> str:
        if winreg:
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
                )
                raw_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return " ".join(raw_name.strip().split())
            except Exception:
                pass

        # Linux / Unix: parse /proc/cpuinfo
        try:
            if os.path.exists("/proc/cpuinfo"):
                with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                    for line in f:
                        if "model name" in line:
                            return line.split(":", 1)[1].strip()
        except Exception:
            pass

        import platform
        return platform.processor() or "Central Processor"

    def _sample_linux_cpu_power(self) -> Optional[float]:
        # 1. Check hwmon CPU power sensors (zenpower, zenergy, amd_energy, k10temp)
        try:
            for hw in glob.glob("/sys/class/hwmon/hwmon*"):
                name_f = os.path.join(hw, "name")
                if not os.path.isfile(name_f):
                    continue
                with open(name_f, "r", encoding="utf-8", errors="ignore") as f:
                    hname = f.read().strip().lower()
                if hname in ("zenpower", "zenergy", "amd_energy", "k10temp", "coretemp"):
                    for pf in ("power1_input", "power1_average"):
                        p_path = os.path.join(hw, pf)
                        if os.path.isfile(p_path) and os.access(p_path, os.R_OK):
                            with open(p_path, "r") as f:
                                uw = float(f.read().strip())
                                if uw > 0:
                                    return round(uw / 1_000_000.0, 1)
        except Exception:
            pass

        # 2. Check powercap intel-rapl (works on both AMD Ryzen and Intel on Linux when readable)
        rapl_path = "/sys/class/powercap/intel-rapl:0/energy_uj"
        if os.path.isfile(rapl_path) and os.access(rapl_path, os.R_OK):
            try:
                now = time.perf_counter()
                with open(rapl_path, "r") as f:
                    uj = int(f.read().strip())
                prev_uj, prev_ts = self._last_rapl_uj, self._last_rapl_ts
                self._last_rapl_uj = uj
                self._last_rapl_ts = now
                if prev_uj is not None and (now - prev_ts) >= 0.1 and uj >= prev_uj:
                    watts = (uj - prev_uj) / ((now - prev_ts) * 1_000_000.0)
                    if 0.5 <= watts <= 500.0:
                        return round(watts, 1)
            except Exception:
                pass
        return None

    def sample_metrics(self, include_top_processes: bool = False) -> HostMetrics:
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
                # Query ADL sensors for CPU package temp and power (Windows AMD)
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

        # Fallback to Linux / generic psutil hardware sensors
        if temp_core <= 0.0 and hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for s_name in ["k10temp", "coretemp", "cpu_thermal", "zenpower", "acpitz", "cpu-thermal"]:
                        if s_name in temps and temps[s_name]:
                            valid_temps = [float(e.current) for e in temps[s_name] if e.current and e.current > 0]
                            if valid_temps:
                                temp_core = valid_temps[0]
                                if len(valid_temps) > 1 and max(valid_temps) > temp_core:
                                    temp_hotspot = max(valid_temps)
                                break
            except Exception:
                pass

        if power_w is None and os.name != "nt":
            power_w = self._sample_linux_cpu_power()

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

        return metrics
