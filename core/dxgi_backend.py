"""
DirectX DXGI and Windows Performance Data Helper (PDH) backend.
Provides universal adapter enumeration, memory limits, and WDDM memory counters.
"""

import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", LUID),
        ("Flags", wintypes.UINT),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


IID_IDXGIFactory1 = GUID(
    0x770AAE78,
    0xF26F,
    0x4DBA,
    (ctypes.c_byte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
)


class PDH_FMT_COUNTERVALUE_DBL(ctypes.Structure):
    _fields_ = [
        ("CStatus", wintypes.DWORD),
        ("padding", wintypes.DWORD),
        ("doubleValue", ctypes.c_double),
    ]


class PDH_FMT_ITEM_DBL(ctypes.Structure):
    _fields_ = [
        ("szName", wintypes.LPWSTR),
        ("FmtValue", PDH_FMT_COUNTERVALUE_DBL),
    ]


class DxgiBackend:
    def __init__(self):
        self.adapters: List[dict] = []
        self._enumerate_adapters()
        self._init_pdh()

    def _enumerate_adapters(self):
        try:
            dxgi = ctypes.windll.dxgi
            pFactory = ctypes.c_void_p()
            hr = dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(pFactory))
            if hr != 0:
                return

            vtable = ctypes.cast(
                ctypes.cast(pFactory, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(ctypes.c_void_p),
            )
            # EnumAdapters1 is at index 12 in IDXGIFactory1
            EnumAdapters1_proto = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)
            )
            EnumAdapters1 = EnumAdapters1_proto(vtable[12])

            idx = 0
            while True:
                pAdapter = ctypes.c_void_p()
                if EnumAdapters1(pFactory, idx, ctypes.byref(pAdapter)) != 0:
                    break

                adapter_vt = ctypes.cast(
                    ctypes.cast(pAdapter, ctypes.POINTER(ctypes.c_void_p)).contents,
                    ctypes.POINTER(ctypes.c_void_p),
                )
                # GetDesc1 is index 8
                GetDesc1_proto = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1)
                )
                GetDesc1 = GetDesc1_proto(adapter_vt[8])

                desc = DXGI_ADAPTER_DESC1()
                if GetDesc1(pAdapter, ctypes.byref(desc)) == 0:
                    # Skip software adapters (DXGI_ADAPTER_FLAG_SOFTWARE = 2)
                    if not (desc.Flags & 2):
                        luid_key = f"0x{desc.AdapterLuid.HighPart:08x}_0x{desc.AdapterLuid.LowPart:08x}".upper()
                        self.adapters.append({
                            "description": desc.Description,
                            "vendor_id": desc.VendorId,
                            "dedicated_vram_mb": round(desc.DedicatedVideoMemory / (1024 * 1024), 1),
                            "shared_vram_mb": round(desc.SharedSystemMemory / (1024 * 1024), 1),
                            "luid_key": luid_key,
                        })
                idx += 1
        except Exception:
            pass

    def _init_pdh(self):
        self.pdh = None
        self.hQuery = None
        self.hCounterMem = None
        try:
            self.pdh = ctypes.windll.pdh
            hQ = ctypes.c_void_p()
            if self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(hQ)) == 0:
                self.hQuery = hQ
                hC = ctypes.c_void_p()
                if self.pdh.PdhAddEnglishCounterW(
                    self.hQuery, r"\GPU Adapter Memory(*)\Dedicated Usage", 0, ctypes.byref(hC)
                ) == 0:
                    self.hCounterMem = hC
                    self.pdh.PdhCollectQueryData(self.hQuery)
        except Exception:
            self.pdh = None

    def sample_memory_by_luid(self) -> Dict[str, float]:
        """Returns map of LUID -> Dedicated VRAM used in MB."""
        if not self.pdh or not self.hQuery or not self.hCounterMem:
            return {}

        res_map = {}
        try:
            self.pdh.PdhCollectQueryData(self.hQuery)
            bufSize = wintypes.DWORD(0)
            itemCount = wintypes.DWORD(0)
            PDH_FMT_DOUBLE = 0x00000200

            self.pdh.PdhGetFormattedCounterArrayW(
                self.hCounterMem, PDH_FMT_DOUBLE, ctypes.byref(bufSize), ctypes.byref(itemCount), None
            )
            if bufSize.value > 0:
                buf = ctypes.create_string_buffer(bufSize.value)
                if (
                    self.pdh.PdhGetFormattedCounterArrayW(
                        self.hCounterMem, PDH_FMT_DOUBLE, ctypes.byref(bufSize), ctypes.byref(itemCount), buf
                    )
                    == 0
                ):
                    items = ctypes.cast(buf, ctypes.POINTER(PDH_FMT_ITEM_DBL))
                    for i in range(itemCount.value):
                        name = items[i].szName or ""
                        val = items[i].FmtValue.doubleValue
                        if "luid_" in name:
                            # Parse LUID from instance name: luid_0x00000000_0x0000F7E6_phys_0
                            parts = name.split("luid_")[1].split("_phys")[0].upper()
                            res_map[parts] = round(val / (1024 * 1024), 1)
        except Exception:
            pass
        return res_map

    def get_adapter_info(self, vendor_str: str, name_substr: str = "") -> Optional[dict]:
        vendor_id_map = {"NVIDIA": 0x10DE, "AMD": 0x1002, "INTEL": 0x8086}
        target_vid = vendor_id_map.get(vendor_str.upper())

        for a in self.adapters:
            if target_vid and a["vendor_id"] == target_vid:
                if not name_substr or name_substr.lower() in a["description"].lower():
                    return a
            elif not target_vid and name_substr and name_substr.lower() in a["description"].lower():
                return a
        return None

    def shutdown(self):
        if self.pdh and self.hQuery:
            try:
                self.pdh.PdhCloseQuery(self.hQuery)
            except Exception:
                pass
            self.hQuery = None
