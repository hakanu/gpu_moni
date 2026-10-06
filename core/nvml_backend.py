"""
Native NVML (NVIDIA Management Library) backend using ctypes.
Direct in-process C-level queries with microsecond execution time.
"""

import ctypes
import os
import psutil
from typing import List, Optional, Dict
from core.gpu_types import GpuDevice, GpuMetrics, GpuProcess


# C struct definitions for NVML
class _Utilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Memory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("pid", ctypes.c_uint), ("usedGpuMemory", ctypes.c_ulonglong)]


class NvmlBackend:
    def __init__(self):
        self.available = False
        self.nvml = None
        self.devices: Dict[int, ctypes.c_void_p] = {}
        self.driver_version = ""
        self._init_nvml()

    def _init_nvml(self):
        # Locate nvml.dll
        candidates = [
            "nvml.dll",
            os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvml.dll"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvml.dll"),
        ]

        lib = None
        for path in candidates:
            try:
                lib = ctypes.CDLL(path)
                break
            except Exception:
                continue

        if not lib:
            return

        self.nvml = lib
        try:
            res = self.nvml.nvmlInit_v2()
            if res != 0:
                return

            self.available = True

            # Get driver version
            ver_buf = ctypes.create_string_buffer(80)
            if hasattr(self.nvml, "nvmlSystemGetDriverVersion"):
                if self.nvml.nvmlSystemGetDriverVersion(ver_buf, 80) == 0:
                    self.driver_version = ver_buf.value.decode("utf-8", errors="ignore")

            # Cache handles
            count = ctypes.c_uint()
            self.nvml.nvmlDeviceGetCount_v2(ctypes.byref(count))
            for i in range(count.value):
                handle = ctypes.c_void_p()
                if self.nvml.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(handle)) == 0:
                    self.devices[i] = handle
        except Exception:
            self.available = False

    def get_devices(self) -> List[GpuDevice]:
        if not self.available:
            return []

        devices = []
        for i, handle in self.devices.items():
            name_buf = ctypes.create_string_buffer(96)
            self.nvml.nvmlDeviceGetName(handle, name_buf, 96)
            name = name_buf.value.decode("utf-8", errors="ignore").strip()

            bus_buf = ctypes.create_string_buffer(32)
            bus_id = ""
            if hasattr(self.nvml, "nvmlDeviceGetPciInfo_v3"):
                pass  # or standard string
            if hasattr(self.nvml, "nvmlDeviceGetBusId"):
                if self.nvml.nvmlDeviceGetBusId(handle, bus_buf, 32) == 0:
                    bus_id = bus_buf.value.decode("utf-8", errors="ignore").strip()

            # PCIe Generation and Width
            pcie_gen = None
            curr_gen = ctypes.c_uint()
            if hasattr(self.nvml, "nvmlDeviceGetCurrPcieLinkGen"):
                if self.nvml.nvmlDeviceGetCurrPcieLinkGen(handle, ctypes.byref(curr_gen)) == 0:
                    pcie_gen = curr_gen.value

            pcie_width = None
            curr_width = ctypes.c_uint()
            if hasattr(self.nvml, "nvmlDeviceGetCurrPcieLinkWidth"):
                if self.nvml.nvmlDeviceGetCurrPcieLinkWidth(handle, ctypes.byref(curr_width)) == 0:
                    pcie_width = curr_width.value

            # VRAM total
            mem = _Memory()
            total_mb = 0.0
            if self.nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) == 0:
                total_mb = round(mem.total / (1024 * 1024), 1)

            device = GpuDevice(
                device_id=f"nvidia_{i}",
                index=i,
                name=name,
                vendor="NVIDIA",
                bus_id=bus_id,
                pcie_gen=pcie_gen,
                pcie_width=pcie_width,
                driver_version=self.driver_version,
                vram_total_mb=total_mb,
            )
            devices.append(device)

        return devices

    def sample_metrics(self, index: int) -> GpuMetrics:
        if not self.available or index not in self.devices:
            return GpuMetrics()

        handle = self.devices[index]
        metrics = GpuMetrics()

        # 1. Utilization
        util = _Utilization()
        if self.nvml.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util)) == 0:
            metrics.gpu_util_percent = float(util.gpu)
            metrics.mem_util_percent = float(util.memory)

        # 2. VRAM
        mem = _Memory()
        if self.nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) == 0:
            metrics.vram_used_mb = round(mem.used / (1024 * 1024), 1)
            metrics.vram_total_mb = round(mem.total / (1024 * 1024), 1)
            metrics.vram_free_mb = round(mem.free / (1024 * 1024), 1)

        # 3. Thermals
        temp = ctypes.c_uint()
        if self.nvml.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp)) == 0:
            metrics.temp_core_c = float(temp.value)

        # 4. Power
        pwr = ctypes.c_uint()
        if self.nvml.nvmlDeviceGetPowerUsage(handle, ctypes.byref(pwr)) == 0:
            metrics.power_draw_w = round(pwr.value / 1000.0, 1)

        pwr_lim = ctypes.c_uint()
        if hasattr(self.nvml, "nvmlDeviceGetEnforcedPowerLimit"):
            if self.nvml.nvmlDeviceGetEnforcedPowerLimit(handle, ctypes.byref(pwr_lim)) == 0:
                metrics.power_limit_w = round(pwr_lim.value / 1000.0, 1)

        # 5. Fan speed
        fan = ctypes.c_uint()
        if hasattr(self.nvml, "nvmlDeviceGetFanSpeed"):
            if self.nvml.nvmlDeviceGetFanSpeed(handle, ctypes.byref(fan)) == 0:
                metrics.fan_speed_percent = float(fan.value)

        # 6. Clocks: Graphics (0) and Memory (2)
        clk_gr = ctypes.c_uint()
        if hasattr(self.nvml, "nvmlDeviceGetClockInfo"):
            if self.nvml.nvmlDeviceGetClockInfo(handle, 0, ctypes.byref(clk_gr)) == 0:
                metrics.clock_graphics_mhz = clk_gr.value

        clk_mem = ctypes.c_uint()
        if hasattr(self.nvml, "nvmlDeviceGetClockInfo"):
            if self.nvml.nvmlDeviceGetClockInfo(handle, 2, ctypes.byref(clk_mem)) == 0:
                metrics.clock_memory_mhz = clk_mem.value

        # 7. Processes
        metrics.processes = self._get_processes(handle)

        return metrics

    def _get_processes(self, handle) -> List[GpuProcess]:
        procs_list: List[GpuProcess] = []
        seen_pids = set()

        max_procs = 64
        proc_arr = (_ProcessInfo * max_procs)()
        proc_count = ctypes.c_uint(max_procs)

        # Query compute processes
        if hasattr(self.nvml, "nvmlDeviceGetComputeRunningProcesses_v2"):
            if self.nvml.nvmlDeviceGetComputeRunningProcesses_v2(handle, ctypes.byref(proc_count), proc_arr) == 0:
                for k in range(proc_count.value):
                    pid = proc_arr[k].pid
                    if pid in seen_pids or pid == 0xFFFFFFFF or pid == 0:
                        continue
                    seen_pids.add(pid)
                    pname = self._resolve_pid_name(pid)
                    mem_used = proc_arr[k].usedGpuMemory
                    mem_mb = None
                    if mem_used > 0 and mem_used < 0x00000FFFFFFFFFFF:
                        mem_mb = round(mem_used / (1024 * 1024), 1)
                    procs_list.append(GpuProcess(pid=pid, name=pname, memory_used_mb=mem_mb, process_type="Compute"))

        # Query graphics processes
        proc_count_g = ctypes.c_uint(max_procs)
        proc_arr_g = (_ProcessInfo * max_procs)()
        if hasattr(self.nvml, "nvmlDeviceGetGraphicsRunningProcesses_v2"):
            if self.nvml.nvmlDeviceGetGraphicsRunningProcesses_v2(handle, ctypes.byref(proc_count_g), proc_arr_g) == 0:
                for k in range(proc_count_g.value):
                    pid = proc_arr_g[k].pid
                    if pid in seen_pids or pid == 0xFFFFFFFF or pid == 0:
                        continue
                    seen_pids.add(pid)
                    pname = self._resolve_pid_name(pid)
                    mem_used = proc_arr_g[k].usedGpuMemory
                    mem_mb = None
                    if mem_used > 0 and mem_used < 0x00000FFFFFFFFFFF:
                        mem_mb = round(mem_used / (1024 * 1024), 1)
                    procs_list.append(GpuProcess(pid=pid, name=pname, memory_used_mb=mem_mb, process_type="Graphics"))

        return procs_list

    def _resolve_pid_name(self, pid: int) -> str:
        try:
            return psutil.Process(pid).name()
        except Exception:
            return f"Process ({pid})"

    def shutdown(self):
        if self.available and self.nvml:
            try:
                self.nvml.nvmlShutdown()
            except Exception:
                pass
            self.available = False
