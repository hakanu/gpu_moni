"""
Native Linux DRM & AMDGPU sysfs/hwmon/fdinfo backend.
Provides zero-dependency, sub-millisecond hardware discovery and real-time telemetry
for AMD Radeon / Instinct (amdgpu / radeon) and Intel (i915 / xe) GPUs on Ubuntu & Linux.
"""

import glob
import os
import platform
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

import psutil

from core.gpu_types import GpuDevice, GpuMetrics, GpuProcess


# Fallback PCI Device ID -> Marketing Name lookup for AMD GPUs when libdrm/lspci is unavailable
AMD_PCI_ID_FALLBACKS: Dict[Tuple[str, Optional[str]], str] = {
    ("744C", "C8"): "AMD Radeon RX 7900 XTX",
    ("744C", "CC"): "AMD Radeon RX 7900 XT",
    ("744C", "CE"): "AMD Radeon RX 7900 GRE",
    ("744C", "CF"): "AMD Radeon RX 7900M",
    ("744C", None): "AMD Radeon RX 7900 Series",
    ("747E", None): "AMD Radeon RX 7800 XT",
    ("7470", None): "AMD Radeon PRO W7700",
    ("7480", None): "AMD Radeon RX 7600 / 7600 XT",
    ("7550", None): "AMD Radeon RX 9070 XT",
    ("73BF", "C0"): "AMD Radeon RX 6900 XT",
    ("73BF", "C1"): "AMD Radeon RX 6800 XT",
    ("73BF", "C3"): "AMD Radeon RX 6800",
    ("73BF", None): "AMD Radeon RX 6800 / 6900 Series",
    ("73AF", None): "AMD Radeon RX 6950 XT",
    ("73DF", None): "AMD Radeon RX 6700 XT / 6750 XT",
    ("73EF", None): "AMD Radeon RX 6650 XT",
    ("73FF", None): "AMD Radeon RX 6600 / 6600 XT",
    ("731F", None): "AMD Radeon RX 5700 XT / 5700",
    ("1900", None): "AMD Radeon 780M Graphics",
    ("15BF", None): "AMD Radeon 780M / 760M Graphics",
    ("150E", None): "AMD Radeon 890M / 880M Graphics",
    ("1681", None): "AMD Radeon 680M / 660M Graphics",
    ("164C", None): "AMD Radeon Graphics (Rembrandt)",
    ("15E7", None): "AMD Radeon Graphics (Barcelo)",
    ("1638", None): "AMD Radeon Graphics (Cezanne)",
    ("1636", None): "AMD Radeon Graphics (Renoir)",
    ("15D8", None): "AMD Radeon Vega Graphics",
}


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return ""


def _read_int(path: str) -> Optional[int]:
    txt = _read_text(path)
    if not txt:
        return None
    try:
        return int(txt, 0)
    except Exception:
        try:
            return int(float(txt))
        except Exception:
            return None


def _read_float(path: str) -> Optional[float]:
    txt = _read_text(path)
    if not txt:
        return None
    try:
        return float(txt)
    except Exception:
        return None


def _parse_pcie_gen(link_speed_str: str) -> Optional[int]:
    """Converts Linux sysfs link speed (e.g. '16.0 GT/s PCIe') to PCIe Generation integer."""
    if not link_speed_str:
        return None
    s = link_speed_str.upper()
    if "64.0" in s or "64 GT" in s:
        return 6
    if "32.0" in s or "32 GT" in s:
        return 5
    if "16.0" in s or "16 GT" in s:
        return 4
    if "8.0" in s or "8 GT" in s:
        return 3
    if "5.0" in s or "5 GT" in s:
        return 2
    if "2.5" in s:
        return 1
    return None


def _parse_dpm_clock(dpm_path: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Parses amdgpu pp_dpm_sclk / pp_dpm_mclk / pp_dpm_socclk.
    Returns (active_clock_mhz, max_clock_mhz).
    Example lines:
      0: 500Mhz
      1: 1285Mhz *
      2: 2482Mhz
    """
    txt = _read_text(dpm_path)
    if not txt:
        return None, None
    active_mhz: Optional[int] = None
    max_mhz: Optional[int] = None
    for line in txt.splitlines():
        m = re.search(r":\s*(\d+)\s*Mhz", line, re.IGNORECASE)
        if not m:
            continue
        val = int(m.group(1))
        if max_mhz is None or val > max_mhz:
            max_mhz = val
        if "*" in line:
            active_mhz = val
    return active_mhz, max_mhz


def _load_amdgpu_ids() -> Dict[Tuple[str, Optional[str]], str]:
    """Loads /usr/share/libdrm/amdgpu.ids into a lookup dict keyed by (dev_hex, rev_hex)."""
    table: Dict[Tuple[str, Optional[str]], str] = dict(AMD_PCI_ID_FALLBACKS)
    candidates = [
        "/usr/share/libdrm/amdgpu.ids",
        "/usr/local/share/libdrm/amdgpu.ids",
        "/opt/amdgpu/share/libdrm/amdgpu.ids",
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        dev_id = parts[0].upper()
                        rev_id = parts[1].upper()
                        name = ", ".join(parts[2:]).strip()
                        if len(dev_id) == 4 and name:
                            table[(dev_id, rev_id)] = name
                            if (dev_id, None) not in table:
                                table[(dev_id, None)] = name
        except Exception:
            continue
    return table


def _infer_amd_architecture(dev_hex: str, vram_vendor: str = "") -> str:
    d = dev_hex.upper()
    arch = "AMD Radeon Architecture"
    if d.startswith(("755", "759")):
        arch = "RDNA 4"
    elif d.startswith("150E"):
        arch = "RDNA 3.5"
    elif d.startswith(("744", "745", "747", "748", "1900", "15BF", "15C8")):
        arch = "RDNA 3"
    elif d.startswith(("73A", "73B", "73C", "73D", "73E", "73F", "164", "1681", "1435")):
        arch = "RDNA 2"
    elif d.startswith(("731", "734", "736")):
        arch = "RDNA 1"
    elif d.startswith(("74A", "74B")):
        arch = "CDNA 3"
    elif d.startswith(("740", "741")):
        arch = "CDNA 2"
    elif d.startswith(("738",)):
        arch = "CDNA 1"
    elif d.startswith(("15D", "15E", "163", "686", "687", "66A")):
        arch = "GCN 5 (Vega)"
    elif d.startswith(("67D", "67E", "67F", "698", "699")):
        arch = "GCN 4 (Polaris)"

    if vram_vendor:
        arch = f"{arch} ({vram_vendor.capitalize()})"
    return arch


class LinuxDrmBackend:
    """
    Native Linux DRM sysfs/hwmon/fdinfo backend for AMD (amdgpu/radeon) and Intel (i915/xe) GPUs.
    """

    def __init__(self, nvml_available: bool = False):
        self.nvml_available = nvml_available
        self.available = False
        self._amdgpu_ids: Dict[Tuple[str, Optional[str]], str] = {}
        self.cards: List[dict] = []
        self._proc_cache: Dict[str, List[GpuProcess]] = {}
        self._last_proc_scan: float = 0.0
        if sys.platform.startswith("linux") and os.path.isdir("/sys/class/drm"):
            self._amdgpu_ids = _load_amdgpu_ids()
            self._discover_cards()

    def _discover_cards(self):
        self.cards.clear()
        try:
            entries = sorted(os.listdir("/sys/class/drm"))
        except Exception:
            return

        for entry in entries:
            if not re.match(r"^card\d+$", entry):
                continue
            card_path = os.path.join("/sys/class/drm", entry)
            dev_path = os.path.join(card_path, "device")
            if not os.path.isdir(dev_path):
                continue

            uevent_txt = _read_text(os.path.join(dev_path, "uevent"))
            kv: Dict[str, str] = {}
            for line in uevent_txt.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip()

            driver = kv.get("DRIVER", "").lower()
            pci_id = kv.get("PCI_ID", "").upper()
            pci_slot = kv.get("PCI_SLOT_NAME", "")

            vendor_hex = _read_text(os.path.join(dev_path, "vendor")).lower().replace("0x", "")
            device_hex = _read_text(os.path.join(dev_path, "device")).upper().replace("0X", "")
            rev_hex = _read_text(os.path.join(dev_path, "revision")).upper().replace("0X", "")

            if not vendor_hex and ":" in pci_id:
                vendor_hex = pci_id.split(":", 1)[0].lower()
                device_hex = pci_id.split(":", 1)[1].upper()

            # Skip NVIDIA cards when NVML is already managing them
            if (vendor_hex == "10de" or "nvidia" in driver) and self.nvml_available:
                continue

            # Only include real GPU drivers (amdgpu, radeon, i915, xe, nouveau)
            if driver not in ("amdgpu", "radeon", "i915", "xe", "nouveau"):
                if vendor_hex not in ("1002", "8086", "10de"):
                    continue

            vendor = (
                "AMD"
                if (vendor_hex == "1002" or driver in ("amdgpu", "radeon"))
                else ("Intel" if (vendor_hex == "8086" or driver in ("i915", "xe")) else "NVIDIA")
            )

            name = self._resolve_gpu_name(entry, dev_path, vendor, device_hex, rev_hex, pci_slot)
            hwmon_dir = self._find_hwmon_dir(dev_path)

            # Static / semi-static specs
            vram_total_bytes = _read_int(os.path.join(dev_path, "mem_info_vram_total")) or 0
            gtt_total_bytes = _read_int(os.path.join(dev_path, "mem_info_gtt_total")) or 0
            vram_total_mb = round(vram_total_bytes / (1024 * 1024), 1)
            vram_vendor = _read_text(os.path.join(dev_path, "mem_info_vram_vendor"))

            pcie_gen = _parse_pcie_gen(_read_text(os.path.join(dev_path, "current_link_speed")))
            pcie_width = _read_int(os.path.join(dev_path, "current_link_width"))
            pcie_max_gen = _parse_pcie_gen(_read_text(os.path.join(dev_path, "max_link_speed")))
            pcie_max_width = _read_int(os.path.join(dev_path, "max_link_width"))

            vbios = _read_text(os.path.join(dev_path, "vbios_version"))
            unique_id = _read_text(os.path.join(dev_path, "unique_id"))

            _, max_sclk = _parse_dpm_clock(os.path.join(dev_path, "pp_dpm_sclk"))
            _, max_mclk = _parse_dpm_clock(os.path.join(dev_path, "pp_dpm_mclk"))

            pwr_default_w: Optional[float] = None
            if hwmon_dir:
                cap_uw = _read_int(os.path.join(hwmon_dir, "power1_cap_default")) or _read_int(
                    os.path.join(hwmon_dir, "power1_cap")
                )
                if cap_uw and cap_uw > 0:
                    pwr_default_w = round(cap_uw / 1_000_000.0, 1)

            architecture = (
                _infer_amd_architecture(device_hex, vram_vendor)
                if vendor == "AMD"
                else (f"{driver} ({pci_id})" if pci_id else driver)
            )
            driver_ver = self._resolve_driver_version(driver)

            self.cards.append(
                {
                    "card_name": entry,
                    "dev_id": f"drm_{entry}",
                    "dev_path": dev_path,
                    "hwmon_dir": hwmon_dir,
                    "vendor": vendor,
                    "driver": driver,
                    "driver_version": driver_ver,
                    "name": name,
                    "pci_slot": pci_slot,
                    "pci_id": pci_id,
                    "device_hex": device_hex,
                    "rev_hex": rev_hex,
                    "vram_total_mb": vram_total_mb,
                    "gtt_total_mb": round(gtt_total_bytes / (1024 * 1024), 1),
                    "pcie_gen": pcie_gen,
                    "pcie_width": pcie_width,
                    "pcie_max_gen": pcie_max_gen,
                    "pcie_max_width": pcie_max_width,
                    "vbios_version": vbios,
                    "uuid": unique_id,
                    "architecture": architecture,
                    "max_clock_graphics_mhz": max_sclk,
                    "max_clock_memory_mhz": max_mclk,
                    "power_limit_default_w": pwr_default_w,
                }
            )

        self.available = len(self.cards) > 0

    def _find_hwmon_dir(self, dev_path: str) -> str:
        hwmon_dirs = sorted(glob.glob(os.path.join(dev_path, "hwmon", "hwmon*")))
        return hwmon_dirs[0] if hwmon_dirs else ""

    def _resolve_driver_version(self, driver: str) -> str:
        kver = platform.release()
        if driver == "amdgpu":
            rocm_ver = _read_text("/opt/rocm/.info/version")
            mod_ver = _read_text("/sys/module/amdgpu/version")
            if rocm_ver:
                return f"amdgpu (ROCm {rocm_ver} • Linux {kver})"
            if mod_ver:
                return f"amdgpu {mod_ver} (Linux {kver})"
            return f"amdgpu (Linux {kver})"
        return f"{driver} (Linux {kver})" if driver else f"Linux {kver}"

    def _resolve_gpu_name(
        self,
        card_entry: str,
        dev_path: str,
        vendor: str,
        device_hex: str,
        rev_hex: str,
        pci_slot: str,
    ) -> str:
        # 1. sysfs product_name if exposed by driver
        prod_name = _read_text(os.path.join(dev_path, "product_name"))
        if prod_name:
            if vendor == "AMD" and not prod_name.upper().startswith("AMD"):
                return f"AMD {prod_name}"
            return prod_name

        # 2. For AMD GPUs, check libdrm amdgpu.ids + built-in fallback table
        if vendor == "AMD" and device_hex:
            exact = self._amdgpu_ids.get((device_hex, rev_hex))
            if exact:
                return exact
            generic = self._amdgpu_ids.get((device_hex, None))
            if generic:
                return generic

        # 3. Try lspci -s <pci_slot>
        if pci_slot:
            for lspci_bin in ("/usr/bin/lspci", "/sbin/lspci", "lspci"):
                try:
                    proc = subprocess.run(
                        [lspci_bin, "-s", pci_slot],
                        capture_output=True,
                        text=True,
                        timeout=1.0,
                    )
                    if proc.returncode == 0 and proc.stdout:
                        line = proc.stdout.strip().splitlines()[0]
                        desc = line.split(": ", 1)[-1]
                        desc = re.sub(r"\s*\(rev [0-9a-fA-F]+\)$", "", desc)
                        brackets = re.findall(r"\[([^\]]+)\]", desc)
                        model_brackets = [
                            b
                            for b in brackets
                            if "AMD" not in b
                            and "ATI" not in b
                            and not re.match(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$", b)
                        ]
                        if model_brackets:
                            model_str = model_brackets[-1]
                            if not model_str.upper().startswith(vendor.upper()):
                                return f"{vendor} {model_str}"
                            return model_str
                        desc_clean = re.sub(
                            r"Advanced Micro Devices, Inc\.\s*\[AMD/ATI\]\s*",
                            "AMD Radeon ",
                            desc,
                        )
                        desc_clean = re.sub(r"Intel Corporation\s*", "Intel ", desc_clean)
                        return desc_clean.strip()
                except Exception:
                    continue

        return f"{vendor} Graphics ({card_entry})"

    def get_devices(self, start_index: int = 0) -> List[GpuDevice]:
        if not self.available:
            return []
        devices: List[GpuDevice] = []
        for offset, c in enumerate(self.cards):
            devices.append(
                GpuDevice(
                    device_id=c["dev_id"],
                    index=start_index + offset,
                    name=c["name"],
                    vendor=c["vendor"],
                    bus_id=c["pci_slot"] or c["card_name"],
                    pcie_gen=c["pcie_gen"],
                    pcie_width=c["pcie_width"],
                    pcie_max_gen=c["pcie_max_gen"],
                    pcie_max_width=c["pcie_max_width"],
                    driver_version=c["driver_version"],
                    vbios_version=c["vbios_version"],
                    architecture=c["architecture"],
                    uuid=c["uuid"],
                    max_clock_graphics_mhz=c["max_clock_graphics_mhz"],
                    max_clock_memory_mhz=c["max_clock_memory_mhz"],
                    power_limit_default_w=c["power_limit_default_w"],
                    vram_total_mb=c["vram_total_mb"],
                )
            )
        return devices

    def sample_metrics(self, device_id: str) -> GpuMetrics:
        card = next((c for c in self.cards if c["dev_id"] == device_id), None)
        if not card:
            return GpuMetrics()

        dev_path = card["dev_path"]
        hwmon_dir = card["hwmon_dir"] or self._find_hwmon_dir(dev_path)
        m = GpuMetrics()

        # 1. GPU & Memory Controller Utilization
        busy = _read_float(os.path.join(dev_path, "gpu_busy_percent"))
        if busy is not None:
            m.gpu_util_percent = max(0.0, min(100.0, busy))

        mem_busy = _read_float(os.path.join(dev_path, "mem_busy_percent"))
        if mem_busy is not None:
            m.mem_util_percent = max(0.0, min(100.0, mem_busy))

        # 2. VRAM & GTT (Shared Memory)
        vram_u_bytes = _read_int(os.path.join(dev_path, "mem_info_vram_used"))
        vram_t_bytes = _read_int(os.path.join(dev_path, "mem_info_vram_total"))
        gtt_u_bytes = _read_int(os.path.join(dev_path, "mem_info_gtt_used"))

        if vram_t_bytes and vram_t_bytes > 0:
            m.vram_total_mb = round(vram_t_bytes / (1024 * 1024), 1)
            m.vram_used_mb = round((vram_u_bytes or 0) / (1024 * 1024), 1)
            m.vram_free_mb = max(0.0, round(m.vram_total_mb - m.vram_used_mb, 1))
            if mem_busy is None and m.vram_total_mb > 0:
                m.mem_util_percent = round((m.vram_used_mb / m.vram_total_mb) * 100.0, 1)
        else:
            m.vram_total_mb = card["vram_total_mb"]

        if gtt_u_bytes and gtt_u_bytes > 0:
            m.shared_used_mb = round(gtt_u_bytes / (1024 * 1024), 1)

        # 3. hwmon sensors: Thermals, Power, Fans, Clocks
        if hwmon_dir and os.path.isdir(hwmon_dir):
            # Thermals (temp1=edge, temp2=junction/hotspot, temp3=mem)
            for t_idx in (1, 2, 3, 4):
                t_val_mdeg = _read_float(os.path.join(hwmon_dir, f"temp{t_idx}_input"))
                if t_val_mdeg is None or t_val_mdeg <= 0:
                    continue
                t_c = round(t_val_mdeg / 1000.0, 1)
                lbl = _read_text(os.path.join(hwmon_dir, f"temp{t_idx}_label")).lower()
                if lbl == "edge" or (t_idx == 1 and m.temp_core_c <= 0):
                    m.temp_core_c = t_c
                elif lbl in ("junction", "hotspot") or (t_idx == 2 and m.temp_hotspot_c is None):
                    m.temp_hotspot_c = t_c
                elif lbl in ("mem", "memory") or (t_idx == 3 and m.temp_memory_c is None):
                    m.temp_memory_c = t_c
                else:
                    m.temp_extra_c = t_c

            # Power Draw & Power Limit (microwatts -> Watts)
            pwr_avg_uw = _read_float(os.path.join(hwmon_dir, "power1_average"))
            pwr_in_uw = _read_float(os.path.join(hwmon_dir, "power1_input"))
            # Use power1_input if power1_average is missing/0, or on APUs where power1_input is live PPT
            pwr_uw = pwr_avg_uw if (pwr_avg_uw and pwr_avg_uw > 0) else pwr_in_uw
            if pwr_in_uw and pwr_avg_uw and pwr_in_uw > pwr_avg_uw * 1.5 and m.gpu_util_percent > 20:
                pwr_uw = pwr_in_uw
            if pwr_uw and pwr_uw > 0:
                m.power_draw_w = round(pwr_uw / 1_000_000.0, 1)

            pwr_cap_uw = _read_float(os.path.join(hwmon_dir, "power1_cap")) or _read_float(
                os.path.join(hwmon_dir, "power1_cap_default")
            )
            if pwr_cap_uw and pwr_cap_uw > 0:
                m.power_limit_w = round(pwr_cap_uw / 1_000_000.0, 1)

            # Fan RPM & PWM %
            fan_rpm = _read_int(os.path.join(hwmon_dir, "fan1_input"))
            if fan_rpm is not None and fan_rpm >= 0:
                m.fan_speed_rpm = fan_rpm

            pwm = _read_float(os.path.join(hwmon_dir, "pwm1"))
            pwm_max = _read_float(os.path.join(hwmon_dir, "pwm1_max")) or 255.0
            if pwm is not None and pwm_max > 0:
                m.fan_speed_percent = round(max(0.0, min(100.0, (pwm / pwm_max) * 100.0)), 1)
            elif fan_rpm is not None:
                fan_max = _read_float(os.path.join(hwmon_dir, "fan1_max"))
                if fan_max and fan_max > 0:
                    m.fan_speed_percent = round(max(0.0, min(100.0, (fan_rpm / fan_max) * 100.0)), 1)

            # Clocks via hwmon freq1_input (sclk) / freq2_input (mclk) in Hz
            f1_hz = _read_float(os.path.join(hwmon_dir, "freq1_input"))
            if f1_hz is not None and f1_hz > 0:
                m.clock_graphics_mhz = int(round(f1_hz / 1_000_000.0))
            f2_hz = _read_float(os.path.join(hwmon_dir, "freq2_input"))
            if f2_hz is not None and f2_hz > 0:
                m.clock_memory_mhz = int(round(f2_hz / 1_000_000.0))

        # 4. Fallback / additional clocks via pp_dpm_*
        if not m.clock_graphics_mhz:
            act_sclk, _ = _parse_dpm_clock(os.path.join(dev_path, "pp_dpm_sclk"))
            if act_sclk is not None:
                m.clock_graphics_mhz = act_sclk
        if not m.clock_memory_mhz:
            act_mclk, _ = _parse_dpm_clock(os.path.join(dev_path, "pp_dpm_mclk"))
            if act_mclk is not None:
                m.clock_memory_mhz = act_mclk

        act_soc, _ = _parse_dpm_clock(os.path.join(dev_path, "pp_dpm_socclk"))
        if act_soc is not None:
            m.clock_soc_mhz = act_soc

        # Intel i915/xe clock fallback
        if card["vendor"] == "Intel" and not m.clock_graphics_mhz:
            intel_clk = _read_int(os.path.join("/sys/class/drm", card["card_name"], "gt_cur_freq_mhz")) or _read_int(
                os.path.join("/sys/class/drm", card["card_name"], "device/tile0/gt0/freq0/cur_freq")
            )
            if intel_clk:
                m.clock_graphics_mhz = intel_clk

        # Fallback temperature for iGPUs sharing CPU die without dedicated DRM hwmon temp
        if m.temp_core_c <= 0.0 and hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                for s_name in ("k10temp", "coretemp", "zenpower", "acpitz"):
                    if s_name in temps and temps[s_name]:
                        m.temp_core_c = round(float(temps[s_name][0].current), 1)
                        break
            except Exception:
                pass

        # 5. Active GPU Processes via Linux /proc/<pid>/fdinfo
        now = time.perf_counter()
        if now - self._last_proc_scan >= 2.0 or not self._proc_cache:
            self._proc_cache = self._scan_drm_processes()
            self._last_proc_scan = now
        m.processes = list(self._proc_cache.get(card["dev_id"], []))

        return m

    def _scan_drm_processes(self) -> Dict[str, List[GpuProcess]]:
        """
        Scans /proc/<pid>/fd and /proc/<pid>/fdinfo for processes holding open
        /dev/dri/* or /dev/kfd handles and extracts per-process VRAM usage.
        """
        result: Dict[str, List[GpuProcess]] = {c["dev_id"]: [] for c in self.cards}
        if not self.cards:
            return result

        slot_to_dev_id = {c["pci_slot"]: c["dev_id"] for c in self.cards if c["pci_slot"]}
        default_amd_id = next((c["dev_id"] for c in self.cards if c["vendor"] == "AMD"), self.cards[0]["dev_id"])

        # Map: dev_id -> {pid: (name, vram_mb, proc_type)}
        per_card_procs: Dict[str, Dict[int, Tuple[str, float, str]]] = {
            c["dev_id"]: {} for c in self.cards
        }

        try:
            proc_entries = [d for d in os.listdir("/proc") if d.isdigit()]
        except Exception:
            return result

        for pid_str in proc_entries:
            fd_dir = f"/proc/{pid_str}/fd"
            try:
                fds = os.listdir(fd_dir)
            except Exception:
                continue

            dri_fds: List[str] = []
            has_kfd = False
            for fd in fds:
                try:
                    target = os.readlink(f"{fd_dir}/{fd}")
                except Exception:
                    continue
                if target == "/dev/kfd":
                    has_kfd = True
                elif target.startswith("/dev/dri/"):
                    dri_fds.append(fd)

            if not dri_fds and not has_kfd:
                continue

            pid = int(pid_str)
            pname = _read_text(f"/proc/{pid_str}/comm") or f"pid-{pid}"
            best_vram_kb = 0
            best_gtt_kb = 0
            matched_dev_id = default_amd_id
            is_compute = has_kfd

            for fd in dri_fds[:12]:
                fdinfo_txt = _read_text(f"/proc/{pid_str}/fdinfo/{fd}")
                if not fdinfo_txt or "drm-" not in fdinfo_txt:
                    continue
                pdev = ""
                vram_kb = 0
                gtt_kb = 0
                for line in fdinfo_txt.splitlines():
                    if line.startswith("drm-pdev:"):
                        pdev = line.split(":", 1)[1].strip()
                    elif line.startswith(("drm-total-vram:", "drm-resident-vram:", "drm-memory-vram:")):
                        parts = line.split(":", 1)[1].strip().split()
                        if parts and parts[0].isdigit():
                            vram_kb = max(vram_kb, int(parts[0]))
                    elif line.startswith(("drm-total-gtt:", "drm-memory-gtt:")):
                        parts = line.split(":", 1)[1].strip().split()
                        if parts and parts[0].isdigit():
                            gtt_kb = max(gtt_kb, int(parts[0]))
                    elif line.startswith("pasid:"):
                        is_compute = True

                if pdev and pdev in slot_to_dev_id:
                    matched_dev_id = slot_to_dev_id[pdev]
                if vram_kb > best_vram_kb:
                    best_vram_kb = vram_kb
                if gtt_kb > best_gtt_kb:
                    best_gtt_kb = gtt_kb

            used_kb = best_vram_kb if best_vram_kb > 0 else best_gtt_kb
            # Skip idle compositor/context handles with < 1 MB unless using /dev/kfd compute
            if used_kb < 1024 and not has_kfd:
                continue

            mem_mb = round(used_kb / 1024.0, 1) if used_kb > 0 else None
            p_type = "Compute" if is_compute else "Graphics"
            existing = per_card_procs[matched_dev_id].get(pid)
            if not existing or ((mem_mb or 0.0) > (existing[1] or 0.0)):
                per_card_procs[matched_dev_id][pid] = (pname, mem_mb or 0.0, p_type)

        for dev_id, pid_map in per_card_procs.items():
            sorted_procs = sorted(pid_map.items(), key=lambda x: x[1][1], reverse=True)
            result[dev_id] = [
                GpuProcess(
                    pid=pid,
                    name=info[0],
                    memory_used_mb=info[1] if info[1] > 0 else None,
                    process_type=info[2],
                )
                for pid, info in sorted_procs
            ]

        return result

    def shutdown(self):
        self.available = False
