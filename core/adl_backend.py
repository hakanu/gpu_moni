"""
Native AMD ADL (AMD Display Library) backend using ctypes.
Queries AMD GPUs directly via atiadlxx.dll.
"""

import ctypes
import os
from typing import List, Optional, Dict
from core.gpu_types import GpuDevice, GpuMetrics


class AdapterInfo(ctypes.Structure):
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iAdapterIndex", ctypes.c_int),
        ("strUDID", ctypes.c_char * 256),
        ("iBusNumber", ctypes.c_int),
        ("iDeviceNumber", ctypes.c_int),
        ("iFunctionNumber", ctypes.c_int),
        ("iVendorID", ctypes.c_int),
        ("strAdapterName", ctypes.c_char * 256),
        ("strDisplayName", ctypes.c_char * 256),
        ("iPresent", ctypes.c_int),
        ("iExist", ctypes.c_int),
        ("strDriverPath", ctypes.c_char * 256),
        ("strDriverPathExt", ctypes.c_char * 256),
        ("strPNPString", ctypes.c_char * 256),
        ("iOSDisplayIndex", ctypes.c_int),
    ]


CMPFUNC = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int)


@CMPFUNC
def _adl_malloc(size):
    ctypes.pythonapi.PyMem_RawMalloc.restype = ctypes.c_void_p
    ctypes.pythonapi.PyMem_RawMalloc.argtypes = [ctypes.c_size_t]
    return ctypes.pythonapi.PyMem_RawMalloc(size)


# Known ADL_PMLOG sensor indices
S_CLK_GFXCLK = 1
S_CLK_MEMCLK = 2
S_CLK_SOCCLK = 3
S_TEMP_EDGE = 8
S_TEMP_MEM = 9
S_FAN_RPM = 14
S_FAN_PERCENT = 15
S_SOC_POWER = 17
S_ACTIVITY_GFX = 19
S_ACTIVITY_MEM = 20
S_GFX_VOLTAGE = 21
S_ASIC_POWER = 23
S_TEMP_HOTSPOT = 27
S_TEMP_EXTRA_1 = 28
S_TEMP_EXTRA_2 = 29
S_TEMP_EXTRA_3 = 30
S_TEMP_EXTRA_4 = 31


class AdlBackend:
    def __init__(self):
        self.available = False
        self.adl = None
        self.context = ctypes.c_void_p()
        self.devices: List[dict] = []
        self._init_adl()

    def _init_adl(self):
        candidates = [
            "atiadlxx.dll",
            os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "atiadlxx.dll"),
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

        self.adl = lib
        try:
            if hasattr(self.adl, "ADL2_Main_Control_Create"):
                res = self.adl.ADL2_Main_Control_Create(_adl_malloc, 1, ctypes.byref(self.context))
                if res == 0:
                    self.available = True
            elif hasattr(self.adl, "ADL_Main_Control_Create"):
                res = self.adl.ADL_Main_Control_Create(_adl_malloc, 1)
                if res == 0:
                    self.available = True

            if not self.available:
                return

            self._discover_devices()
        except Exception:
            self.available = False

    def _discover_devices(self):
        num_adapters = ctypes.c_int(0)
        if self.context.value and hasattr(self.adl, "ADL2_Adapter_NumberOfAdapters_Get"):
            res = self.adl.ADL2_Adapter_NumberOfAdapters_Get(self.context, ctypes.byref(num_adapters))
        else:
            res = self.adl.ADL_Adapter_NumberOfAdapters_Get(ctypes.byref(num_adapters))

        if res != 0 or num_adapters.value <= 0:
            return

        ArrType = AdapterInfo * num_adapters.value
        arr = ArrType()
        if self.context.value and hasattr(self.adl, "ADL2_Adapter_AdapterInfo_Get"):
            res = self.adl.ADL2_Adapter_AdapterInfo_Get(self.context, arr, ctypes.sizeof(arr))
        else:
            res = self.adl.ADL_Adapter_AdapterInfo_Get(arr, ctypes.sizeof(arr))

        if res != 0:
            return

        seen_buses = set()
        for i in range(num_adapters.value):
            info = arr[i]
            if not info.iPresent:
                continue
            name = info.strAdapterName.decode("utf-8", errors="ignore").strip()
            # Only AMD adapters
            if "AMD" not in name.upper() and "RADEON" not in name.upper():
                continue

            bus = info.iBusNumber
            if bus in seen_buses and bus != 0:
                continue
            seen_buses.add(bus)

            self.devices.append({
                "adapter_index": info.iAdapterIndex,
                "name": name,
                "bus_id": f"PCIe Bus {bus}",
                "bus_number": bus,
                "vendor_id": info.iVendorID,
            })

    def get_devices(self) -> List[GpuDevice]:
        if not self.available:
            return []

        devs = []
        for idx, dev_info in enumerate(self.devices):
            device = GpuDevice(
                device_id=f"amd_{idx}",
                index=idx,
                name=dev_info["name"],
                vendor="AMD",
                bus_id=dev_info["bus_id"],
                driver_version="Adrenalin Driver",
            )
            devs.append(device)
        return devs

    def sample_metrics(self, index: int) -> GpuMetrics:
        if not self.available or index >= len(self.devices):
            return GpuMetrics()

        dev_info = self.devices[index]
        adapter_idx = dev_info["adapter_index"]
        metrics = GpuMetrics()

        # Query PMLog
        if hasattr(self.adl, "ADL2_New_QueryPMLogData_Get") and self.context.value:
            try:
                buf = ctypes.create_string_buffer(4096)
                ctypes.cast(buf, ctypes.POINTER(ctypes.c_int))[0] = 2052
                res = self.adl.ADL2_New_QueryPMLogData_Get(self.context, adapter_idx, buf)
                if res == 0:
                    int_arr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_int))

                    def get_sensor(s_idx):
                        supp = int_arr[1 + s_idx * 2]
                        val = int_arr[2 + s_idx * 2]
                        return val if supp else None

                    # Utilization
                    act_gfx = get_sensor(S_ACTIVITY_GFX)
                    if act_gfx is not None:
                        metrics.gpu_util_percent = float(act_gfx)

                    act_mem = get_sensor(S_ACTIVITY_MEM)
                    if act_mem is not None:
                        metrics.mem_util_percent = float(act_mem)

                    # Thermals: Core (Edge or Extra1/2), Hotspot
                    temp_edge = get_sensor(S_TEMP_EDGE)
                    temp_extra1 = get_sensor(S_TEMP_EXTRA_1)
                    temp_extra2 = get_sensor(S_TEMP_EXTRA_2)
                    temp_hotspot = get_sensor(S_TEMP_HOTSPOT)

                    # For APUs, extra1 or extra2 typically holds package/core temp
                    core_candidates = [t for t in [temp_edge, temp_extra1, temp_extra2] if t is not None and t > 0]
                    if core_candidates:
                        metrics.temp_core_c = float(core_candidates[0])

                    if temp_hotspot is not None and temp_hotspot > 0:
                        metrics.temp_hotspot_c = float(temp_hotspot)
                    elif temp_extra2 is not None and temp_extra2 > 0 and temp_extra2 != metrics.temp_core_c:
                        metrics.temp_hotspot_c = float(temp_extra2)

                    # Power
                    asic_pwr = get_sensor(S_ASIC_POWER)
                    soc_pwr = get_sensor(S_SOC_POWER)
                    if asic_pwr is not None and asic_pwr > 0:
                        metrics.power_draw_w = float(asic_pwr)
                    elif soc_pwr is not None and soc_pwr > 0:
                        metrics.power_draw_w = float(soc_pwr)

                    # Clocks
                    clk_gfx = get_sensor(S_CLK_GFXCLK)
                    if clk_gfx is not None and clk_gfx > 0:
                        metrics.clock_graphics_mhz = clk_gfx

                    clk_mem = get_sensor(S_CLK_MEMCLK)
                    if clk_mem is not None and clk_mem > 0:
                        metrics.clock_memory_mhz = clk_mem

                    clk_soc = get_sensor(S_CLK_SOCCLK)
                    if clk_soc is not None and clk_soc > 0:
                        metrics.clock_soc_mhz = clk_soc

                    # Fan
                    fan_pct = get_sensor(S_FAN_PERCENT)
                    if fan_pct is not None:
                        metrics.fan_speed_percent = float(fan_pct)
                    fan_rpm = get_sensor(S_FAN_RPM)
                    if fan_rpm is not None:
                        metrics.fan_speed_rpm = fan_rpm
            except Exception:
                pass

        return metrics

    def shutdown(self):
        if self.available and self.adl:
            try:
                if hasattr(self.adl, "ADL2_Main_Control_Destroy") and self.context.value:
                    self.adl.ADL2_Main_Control_Destroy(self.context)
                elif hasattr(self.adl, "ADL_Main_Control_Destroy"):
                    self.adl.ADL_Main_Control_Destroy()
            except Exception:
                pass
            self.available = False
