"""
Deep Hardware Specifications & SMBIOS/Storage Discovery Engine.
Collects detailed CPU microarchitecture, cache hierarchy, RAM speed (MT/s & MHz),
channel configuration (Single/Dual/Quad), per-DIMM slot specs, Motherboard & BIOS
details, PCIe/M.2 slot status, and physical NVMe/SATA drives with sub-millisecond overhead.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import ctypes
import os
import platform
import re
import struct
import sys
import time
import psutil

try:
    import winreg
except ImportError:
    winreg = None


@dataclass
class RamSlotInfo:
    slot_label: str = ""
    bank_label: str = ""
    populated: bool = False
    capacity_gb: float = 0.0
    mem_type: str = "DDR"
    form_factor: str = "DIMM"
    configured_speed_mts: int = 0
    dram_freq_mhz: int = 0
    jedec_speed_mts: int = 0
    xmp_expo_spec: str = ""
    ranks: int = 0
    voltage_v: float = 0.0
    data_width_bits: int = 64
    total_width_bits: int = 64
    manufacturer: str = ""
    part_number: str = ""
    serial_number: str = ""


@dataclass
class MotherboardSlotInfo:
    designation: str = ""
    slot_type: str = ""
    bus_width: str = ""
    status: str = ""


@dataclass
class MotherboardSpecs:
    manufacturer: str = "Unknown"
    product: str = "Unknown"
    version: str = ""
    serial_number: str = ""
    bios_vendor: str = "Unknown"
    bios_version: str = "Unknown"
    bios_date: str = ""
    smbios_version: str = ""
    boot_mode: str = "UEFI"
    secure_boot: str = "Unknown"
    slots: List[MotherboardSlotInfo] = field(default_factory=list)


@dataclass
class CpuSpecs:
    name: str = ""
    vendor: str = ""
    identifier: str = ""
    socket: str = ""
    cores_physical: int = 0
    cores_logical: int = 0
    base_clock_mhz: int = 0
    boost_clock_mhz: int = 0
    ext_clock_mhz: int = 100
    voltage_v: Optional[float] = None
    l1_cache_kb: int = 0
    l2_cache_kb: int = 0
    l3_cache_kb: int = 0
    features: List[str] = field(default_factory=list)
    virtualization: str = "Supported"


@dataclass
class RamSpecs:
    total_installed_gb: float = 0.0
    max_board_capacity_gb: float = 0.0
    slots_used: int = 0
    slots_total: int = 0
    mem_type: str = "DDR"
    form_factor: str = "DIMM"
    channel_mode: str = "Unknown"
    configured_speed_mts: int = 0
    dram_freq_mhz: int = 0
    jedec_speed_mts: int = 0
    xmp_expo_spec: str = ""
    voltage_v: float = 0.0
    ecc_supported: bool = False
    modules: List[RamSlotInfo] = field(default_factory=list)


@dataclass
class StorageDriveInfo:
    index: int = 0
    model: str = ""
    bus_type: str = ""
    capacity_gb: float = 0.0
    firmware: str = ""
    serial_number: str = ""


@dataclass
class PartitionInfo:
    mountpoint: str = ""
    device: str = ""
    fstype: str = ""
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    percent: float = 0.0


@dataclass
class OsSpecs:
    os_name: str = ""
    version: str = ""
    build: str = ""
    architecture: str = ""
    hostname: str = ""
    uptime_str: str = ""


@dataclass
class SystemHardwareSpecs:
    cpu: CpuSpecs = field(default_factory=CpuSpecs)
    ram: RamSpecs = field(default_factory=RamSpecs)
    motherboard: MotherboardSpecs = field(default_factory=MotherboardSpecs)
    storage_drives: List[StorageDriveInfo] = field(default_factory=list)
    partitions: List[PartitionInfo] = field(default_factory=list)
    os_info: OsSpecs = field(default_factory=OsSpecs)


# SMBIOS Lookup Tables
SMBIOS_MEM_TYPES = {
    0x14: "DDR",
    0x15: "DDR2",
    0x18: "DDR3",
    0x1A: "DDR4",
    0x1B: "LPDDR",
    0x1C: "LPDDR2",
    0x1D: "LPDDR3",
    0x1E: "LPDDR4",
    0x22: "DDR5",
    0x23: "LPDDR5",
}

SMBIOS_FORM_FACTORS = {
    0x08: "SIMM",
    0x09: "DIMM",
    0x0B: "Row of Chips (Soldered)",
    0x0C: "RIMM",
    0x0D: "SODIMM",
    0x0F: "FB-DIMM",
    0x10: "Die",
}

SMBIOS_SLOT_TYPES = {
    0x06: "PCI",
    0x15: "M.2 Socket 1 (WiFi/E-Key)",
    0x16: "M.2 Socket 2",
    0x17: "M.2 Socket 3 (NVMe/M-Key)",
    0xA5: "PCIe",
    0xA6: "PCIe x1",
    0xA7: "PCIe x2",
    0xA8: "PCIe x4",
    0xA9: "PCIe x8",
    0xAA: "PCIe x16",
    0xAB: "PCIe Gen 2",
    0xAC: "PCIe Gen 2 x1",
    0xAD: "PCIe Gen 2 x2",
    0xAE: "PCIe Gen 2 x4",
    0xAF: "PCIe Gen 2 x8",
    0xB0: "PCIe Gen 2 x16",
    0xB1: "PCIe Gen 3",
    0xB2: "PCIe Gen 3 x1",
    0xB3: "PCIe Gen 3 x2",
    0xB4: "PCIe Gen 3 x4",
    0xB5: "PCIe Gen 3 x8",
    0xB6: "PCIe Gen 3 x16",
    0xB8: "PCIe Gen 4",
    0xB9: "PCIe Gen 4 x1",
    0xBA: "PCIe Gen 4 x2",
    0xBB: "PCIe Gen 4 x4",
    0xBC: "PCIe Gen 4 x8",
    0xBD: "PCIe Gen 4 x16",
    0xBE: "PCIe Gen 5",
    0xBF: "PCIe Gen 5 x1",
    0xC0: "PCIe Gen 5 x2",
    0xC1: "PCIe Gen 5 x4",
    0xC2: "PCIe Gen 5 x8",
    0xC3: "PCIe Gen 5 x16",
}

SMBIOS_SLOT_WIDTHS = {
    0x08: "x1",
    0x09: "x2",
    0x0A: "x4",
    0x0B: "x8",
    0x0C: "x12",
    0x0D: "x16",
    0x0E: "x32",
}

SMBIOS_SLOT_USAGE = {
    0x03: "Available",
    0x04: "In Use",
    0x05: "Unavailable",
}


def decode_ram_part_number_spec(part_number: str) -> str:
    """
    Extracts rated XMP/EXPO transfer rate (MT/s) and CAS Latency (CL)
    from common memory module part numbers (Corsair, G.Skill, Kingston, TeamGroup, Crucial).
    """
    if not part_number:
        return ""
    pn = part_number.strip().upper()

    # Corsair: e.g. CMK32GX5M2B6000Z30 or CMH32GX5M2B6400C32 or CMK16GX4M2B3200C16
    m = re.search(r"M\d[A-Z]?(\d{4})([CZ])(\d{2})", pn)
    if m:
        spd, prof_char, cl = m.group(1), m.group(2), m.group(3)
        profile = "AMD EXPO" if prof_char == "Z" else "Intel XMP"
        return f"{spd} MT/s CL{cl} ({profile})"

    # G.Skill: e.g. F5-6000J3038F16GX2-TZ5NR or F4-3600C16D-32GTZNC
    m = re.search(r"F[45]-(\d{4})[CJ](\d{2})", pn)
    if m:
        return f"{m.group(1)} MT/s CL{m.group(2)} (XMP/EXPO)"

    # Kingston Fury: e.g. KF560C30BBEK2-32 or KF432C16BBK2/16
    m = re.search(r"KF[45](\d{2})C(\d{2})", pn)
    if m:
        spd = int(m.group(1)) * 100
        return f"{spd} MT/s CL{m.group(2)} (XMP/EXPO)"

    # TeamGroup: e.g. FF3D532G6000HC30DC01
    m = re.search(r"(\d{4})HC(\d{2})", pn)
    if m:
        return f"{m.group(1)} MT/s CL{m.group(2)} (XMP/EXPO)"

    # Generic 4-digit speed in part number (e.g. 3200, 3600, 4800, 5200, 5600, 6000, 6400, 7200, 8000)
    m = re.search(r"(3200|3600|4000|4800|5200|5600|6000|6200|6400|6800|7200|7600|8000)", pn)
    if m:
        return f"{m.group(1)} MT/s Rated"

    return ""


class HardwareInfoCollector:
    """Collects static and semi-static detailed hardware specifications."""

    @classmethod
    def collect_all(cls) -> SystemHardwareSpecs:
        specs = SystemHardwareSpecs()
        specs.os_info = cls._collect_os_info()
        specs.partitions = cls._collect_partitions()

        # Default CPU baseline from psutil / platform
        specs.cpu.cores_physical = psutil.cpu_count(logical=False) or 0
        specs.cpu.cores_logical = psutil.cpu_count(logical=True) or 0

        if sys.platform == "win32":
            cls._collect_windows_registry_info(specs)
            cls._collect_windows_smbios(specs)
            cls._collect_windows_cpu_features(specs)
            specs.storage_drives = cls._collect_windows_drives()
        else:
            cls._collect_linux_info(specs)

        # Post-process RAM summary & Channel Mode
        cls._finalize_ram_summary(specs.ram)
        return specs

    @classmethod
    def _collect_os_info(cls) -> OsSpecs:
        info = OsSpecs()
        info.hostname = platform.node()
        info.architecture = platform.machine() or "64-bit"

        try:
            boot_ts = psutil.boot_time()
            elapsed = max(0, int(time.time() - boot_ts))
            days, rem = divmod(elapsed, 86400)
            hours, rem = divmod(rem, 3600)
            mins, _ = divmod(rem, 60)
            if days > 0:
                info.uptime_str = f"{days}d {hours}h {mins}m"
            else:
                info.uptime_str = f"{hours}h {mins}m"
        except Exception:
            info.uptime_str = "Unknown"

        if sys.platform == "win32" and winreg:
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
                )
                prod_name, _ = winreg.QueryValueEx(key, "ProductName")
                build_num, _ = winreg.QueryValueEx(key, "CurrentBuildNumber")
                display_ver = ""
                try:
                    display_ver, _ = winreg.QueryValueEx(key, "DisplayVersion")
                except Exception:
                    pass
                winreg.CloseKey(key)

                # Windows 11 has build >= 22000 even if ProductName says Windows 10
                if int(build_num) >= 22000 and "Windows 10" in prod_name:
                    prod_name = prod_name.replace("Windows 10", "Windows 11")

                info.os_name = prod_name
                info.build = str(build_num)
                info.version = f"{display_ver} (Build {build_num})" if display_ver else f"Build {build_num}"
                return info
            except Exception:
                pass

        info.os_name = f"{platform.system()} {platform.release()}"
        info.version = platform.version()
        return info

    @classmethod
    def _collect_partitions(cls) -> List[PartitionInfo]:
        parts: List[PartitionInfo] = []
        try:
            for p in psutil.disk_partitions(all=False):
                if "cdrom" in p.opts or not p.fstype:
                    continue
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    parts.append(
                        PartitionInfo(
                            mountpoint=p.mountpoint,
                            device=p.device,
                            fstype=p.fstype,
                            total_gb=round(usage.total / (1024 ** 3), 1),
                            used_gb=round(usage.used / (1024 ** 3), 1),
                            free_gb=round(usage.free / (1024 ** 3), 1),
                            percent=float(usage.percent),
                        )
                    )
                except Exception:
                    continue
        except Exception:
            pass
        return parts

    @classmethod
    def _collect_windows_registry_info(cls, specs: SystemHardwareSpecs):
        if not winreg:
            return
        # CPU Registry Info
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            try:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                specs.cpu.name = " ".join(name.strip().split())
            except Exception:
                pass
            try:
                vendor, _ = winreg.QueryValueEx(key, "VendorIdentifier")
                specs.cpu.vendor = vendor.strip()
            except Exception:
                pass
            try:
                ident, _ = winreg.QueryValueEx(key, "Identifier")
                specs.cpu.identifier = ident.strip()
            except Exception:
                pass
            try:
                mhz, _ = winreg.QueryValueEx(key, "~MHz")
                specs.cpu.base_clock_mhz = int(mhz)
            except Exception:
                pass
            winreg.CloseKey(key)
        except Exception:
            pass

        # Motherboard fallback from Hardware\Description\System\BIOS
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS"
            )
            for reg_val, attr in [
                ("BaseBoardManufacturer", "manufacturer"),
                ("BaseBoardProduct", "product"),
                ("BaseBoardVersion", "version"),
                ("BIOSVendor", "bios_vendor"),
                ("BIOSVersion", "bios_version"),
                ("BIOSReleaseDate", "bios_date"),
            ]:
                try:
                    val, _ = winreg.QueryValueEx(key, reg_val)
                    if val:
                        setattr(specs.motherboard, attr, str(val).strip())
                except Exception:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

        # Secure Boot check
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\SecureBoot\State"
            )
            sb, _ = winreg.QueryValueEx(key, "UEFISecureBootEnabled")
            specs.motherboard.secure_boot = "Enabled" if sb == 1 else "Disabled"
            specs.motherboard.boot_mode = "UEFI"
            winreg.CloseKey(key)
        except Exception:
            specs.motherboard.secure_boot = "Disabled / Legacy"

    @classmethod
    def _collect_windows_smbios(cls, specs: SystemHardwareSpecs):
        try:
            kernel32 = ctypes.windll.kernel32
            RSMB = 0x52534D42  # 'RSMB'
            size = kernel32.GetSystemFirmwareTable(RSMB, 0, None, 0)
            if size <= 8:
                return
            buf = ctypes.create_string_buffer(size)
            if kernel32.GetSystemFirmwareTable(RSMB, 0, buf, size) == 0:
                return

            raw = buf.raw
            major, minor = raw[1], raw[2]
            specs.motherboard.smbios_version = f"{major}.{minor}"
            data = raw[8:]

            i = 0
            n = len(data)
            while i < n:
                if i + 4 > n:
                    break
                t = data[i]
                length = data[i + 1]
                if length < 4 or i + length > n:
                    break
                formatted = data[i : i + length]

                # Parse unformatted string table following structure
                str_start = i + length
                strings: List[str] = []
                j = str_start
                if j + 1 < n and data[j] == 0 and data[j + 1] == 0:
                    j += 2
                else:
                    curr = bytearray()
                    while j < n:
                        if data[j] == 0:
                            strings.append(curr.decode("utf-8", errors="replace").strip())
                            curr = bytearray()
                            if j + 1 < n and data[j + 1] == 0:
                                j += 2
                                break
                        else:
                            curr.append(data[j])
                        j += 1

                def get_str(idx: int) -> str:
                    if idx == 0 or idx > len(strings):
                        return ""
                    return strings[idx - 1]

                # Type 0: BIOS Information
                if t == 0 and length >= 9:
                    vendor = get_str(formatted[4])
                    ver = get_str(formatted[5])
                    date = get_str(formatted[8])
                    if vendor:
                        specs.motherboard.bios_vendor = vendor
                    if ver:
                        specs.motherboard.bios_version = ver
                    if date:
                        specs.motherboard.bios_date = date

                # Type 2: Baseboard / Motherboard Information
                elif t == 2 and length >= 8:
                    mfg = get_str(formatted[4])
                    prod = get_str(formatted[5])
                    ver = get_str(formatted[6])
                    sn = get_str(formatted[7])
                    if mfg:
                        specs.motherboard.manufacturer = mfg
                    if prod:
                        specs.motherboard.product = prod
                    if ver:
                        specs.motherboard.version = ver
                    if sn and sn.lower() not in ("system serial number", "default string", "none"):
                        specs.motherboard.serial_number = sn

                # Type 4: Processor Information
                elif t == 4 and length >= 0x18:
                    socket = get_str(formatted[4])
                    proc_name = get_str(formatted[0x10])
                    volt_raw = formatted[0x11]
                    ext_clk = struct.unpack_from("<H", formatted, 0x12)[0]
                    max_spd = struct.unpack_from("<H", formatted, 0x14)[0]
                    cur_spd = struct.unpack_from("<H", formatted, 0x16)[0]

                    if socket:
                        specs.cpu.socket = socket
                    if proc_name and not specs.cpu.name:
                        specs.cpu.name = " ".join(proc_name.split())
                    if ext_clk > 0:
                        specs.cpu.ext_clock_mhz = ext_clk
                    if max_spd > 0:
                        specs.cpu.boost_clock_mhz = max_spd
                    if cur_spd > 0:
                        specs.cpu.base_clock_mhz = cur_spd
                    if volt_raw & 0x80:
                        v = (volt_raw & 0x7F) / 10.0
                        if 0.4 <= v <= 2.5:
                            specs.cpu.voltage_v = round(v, 2)

                # Type 7: Cache Information
                elif t == 7 and length >= 0x0B:
                    cfg = struct.unpack_from("<H", formatted, 5)[0]
                    level = (cfg & 0x7) + 1
                    size_kb = struct.unpack_from("<H", formatted, 9)[0]
                    if size_kb & 0x8000:
                        size_kb = (size_kb & 0x7FFF) * 64
                    if length >= 0x17:
                        size2 = struct.unpack_from("<I", formatted, 0x13)[0]
                        if size2 & 0x80000000:
                            size_kb = (size2 & 0x7FFFFFFF) * 64
                        elif size2 > 0:
                            size_kb = size2
                    if level == 1:
                        specs.cpu.l1_cache_kb = size_kb
                    elif level == 2:
                        specs.cpu.l2_cache_kb = size_kb
                    elif level == 3:
                        specs.cpu.l3_cache_kb = size_kb

                # Type 9: System Slots (PCIe / M.2)
                elif t == 9 and length >= 8:
                    desig = get_str(formatted[4])
                    s_type = SMBIOS_SLOT_TYPES.get(formatted[5], f"Slot({formatted[5]})")
                    s_width = SMBIOS_SLOT_WIDTHS.get(formatted[6], "")
                    s_usage = SMBIOS_SLOT_USAGE.get(formatted[7], "Unknown")
                    if desig:
                        specs.motherboard.slots.append(
                            MotherboardSlotInfo(
                                designation=desig,
                                slot_type=s_type,
                                bus_width=s_width,
                                status=s_usage,
                            )
                        )

                # Type 16: Physical Memory Array
                elif t == 16 and length >= 15:
                    location = formatted[4]
                    use = formatted[5]
                    # 0x03 = System memory
                    if use == 0x03:
                        max_cap_kb = struct.unpack_from("<I", formatted, 7)[0]
                        num_slots = struct.unpack_from("<H", formatted, 13)[0]
                        if max_cap_kb > 0 and max_cap_kb != 0x80000000:
                            specs.ram.max_board_capacity_gb = round(max_cap_kb / (1024 * 1024), 0)
                        if num_slots > 0:
                            specs.ram.slots_total = num_slots

                # Type 17: Memory Device (Per-DIMM Slot)
                elif t == 17 and length >= 0x15:
                    tot_width = struct.unpack_from("<H", formatted, 0x08)[0]
                    dat_width = struct.unpack_from("<H", formatted, 0x0A)[0]
                    raw_size = struct.unpack_from("<H", formatted, 0x0C)[0]
                    form_code = formatted[0x0E]
                    dev_loc = get_str(formatted[0x10]) if length > 0x10 else ""
                    bank_loc = get_str(formatted[0x11]) if length > 0x11 else ""
                    mem_type_code = formatted[0x12] if length > 0x12 else 0
                    jedec_spd = struct.unpack_from("<H", formatted, 0x15)[0] if length >= 0x17 else 0
                    mfg = get_str(formatted[0x17]) if length > 0x17 else ""
                    sn = get_str(formatted[0x18]) if length > 0x18 else ""
                    pn = get_str(formatted[0x1A]) if length > 0x1A else ""
                    attr = formatted[0x1B] if length > 0x1B else 0

                    size_mb = 0
                    if raw_size == 0x7FFF and length >= 0x20:
                        size_mb = struct.unpack_from("<I", formatted, 0x1C)[0]
                    elif raw_size > 0 and raw_size != 0xFFFF:
                        if raw_size & 0x8000:
                            size_mb = (raw_size & 0x7FFF) // 1024
                        else:
                            size_mb = raw_size

                    cfg_spd = struct.unpack_from("<H", formatted, 0x20)[0] if length >= 0x22 else jedec_spd
                    cfg_volt_mv = struct.unpack_from("<H", formatted, 0x26)[0] if length >= 0x28 else 0

                    populated = size_mb > 0
                    active_mts = cfg_spd if cfg_spd > 0 else jedec_spd
                    mtype_str = SMBIOS_MEM_TYPES.get(mem_type_code, "DDR")
                    ff_str = SMBIOS_FORM_FACTORS.get(form_code, "DIMM")
                    ranks = attr & 0x0F

                    slot_info = RamSlotInfo(
                        slot_label=dev_loc or f"Slot {len(specs.ram.modules) + 1}",
                        bank_label=bank_loc,
                        populated=populated,
                        capacity_gb=round(size_mb / 1024.0, 1) if populated else 0.0,
                        mem_type=mtype_str,
                        form_factor=ff_str,
                        configured_speed_mts=active_mts if populated else 0,
                        dram_freq_mhz=(active_mts // 2) if populated else 0,
                        jedec_speed_mts=jedec_spd if populated else 0,
                        xmp_expo_spec=decode_ram_part_number_spec(pn) if populated else "",
                        ranks=ranks if populated else 0,
                        voltage_v=round(cfg_volt_mv / 1000.0, 2) if cfg_volt_mv > 0 else 0.0,
                        data_width_bits=dat_width if dat_width != 0xFFFF else 64,
                        total_width_bits=tot_width if tot_width != 0xFFFF else 64,
                        manufacturer=mfg if populated else "",
                        part_number=pn if populated else "",
                        serial_number=sn if populated and sn not in ("00000000", "Unknown") else "",
                    )
                    specs.ram.modules.append(slot_info)

                i = j
                if t == 127:  # End-of-table
                    break
        except Exception:
            pass

    @classmethod
    def _collect_windows_cpu_features(cls, specs: SystemHardwareSpecs):
        try:
            k32 = ctypes.windll.kernel32
            feature_map = [
                ("SSE2", 10),
                ("SSE3", 13),
                ("SSSE3", 36),
                ("SSE4.1", 37),
                ("SSE4.2", 38),
                ("AVX", 39),
                ("AVX2", 40),
                ("AVX-512", 41),
            ]
            active = []
            for name, fid in feature_map:
                if k32.IsProcessorFeaturePresent(fid):
                    active.append(name)
            specs.cpu.features = active

            if k32.IsProcessorFeaturePresent(21):
                specs.cpu.virtualization = "Enabled (SVM / VT-x)"
            else:
                specs.cpu.virtualization = "Disabled"
        except Exception:
            pass

    @classmethod
    def _collect_windows_drives(cls) -> List[StorageDriveInfo]:
        drives: List[StorageDriveInfo] = []
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateFileW.restype = ctypes.c_void_p
            OPEN_EXISTING = 3
            FILE_SHARE_READ = 1
            FILE_SHARE_WRITE = 2
            IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
            IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0

            class STORAGE_PROPERTY_QUERY(ctypes.Structure):
                _fields_ = [
                    ("PropertyId", ctypes.c_uint32),
                    ("QueryType", ctypes.c_uint32),
                    ("AdditionalParameters", ctypes.c_byte * 1),
                ]

            class STORAGE_DEVICE_DESCRIPTOR(ctypes.Structure):
                _fields_ = [
                    ("Version", ctypes.c_uint32),
                    ("Size", ctypes.c_uint32),
                    ("DeviceType", ctypes.c_byte),
                    ("DeviceTypeModifier", ctypes.c_byte),
                    ("RemovableMedia", ctypes.c_byte),
                    ("CommandQueueing", ctypes.c_byte),
                    ("VendorIdOffset", ctypes.c_uint32),
                    ("ProductIdOffset", ctypes.c_uint32),
                    ("ProductRevisionOffset", ctypes.c_uint32),
                    ("SerialNumberOffset", ctypes.c_uint32),
                    ("BusType", ctypes.c_uint32),
                    ("RawPropertiesLength", ctypes.c_uint32),
                ]

            BUS_TYPES = {
                1: "SCSI",
                2: "ATAPI",
                3: "ATA",
                7: "USB",
                8: "RAID",
                9: "iSCSI",
                10: "SAS",
                11: "SATA",
                14: "Virtual",
                17: "NVMe",
            }

            for idx in range(16):
                path = r"\\.\PhysicalDrive" + str(idx)
                h = kernel32.CreateFileW(
                    path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None
                )
                if not h or h == -1 or h == 0xFFFFFFFFFFFFFFFF:
                    continue
                try:
                    q = STORAGE_PROPERTY_QUERY(0, 0)
                    buf = ctypes.create_string_buffer(1024)
                    returned = ctypes.c_uint32(0)
                    if kernel32.DeviceIoControl(
                        ctypes.c_void_p(h),
                        IOCTL_STORAGE_QUERY_PROPERTY,
                        ctypes.byref(q),
                        ctypes.sizeof(q),
                        buf,
                        1024,
                        ctypes.byref(returned),
                        None,
                    ):
                        desc = STORAGE_DEVICE_DESCRIPTOR.from_buffer_copy(buf)
                        raw = buf.raw

                        def get_str_at(off: int) -> str:
                            if off == 0 or off >= 1024:
                                return ""
                            end = raw.find(b"\x00", off)
                            if end == -1:
                                end = 1024
                            return raw[off:end].decode("ascii", errors="replace").strip()

                        model = get_str_at(desc.ProductIdOffset)
                        vendor = get_str_at(desc.VendorIdOffset)
                        if vendor and not model.lower().startswith(vendor.lower()):
                            model = f"{vendor} {model}".strip()
                        fw = get_str_at(desc.ProductRevisionOffset)
                        sn = get_str_at(desc.SerialNumberOffset).rstrip(".")
                        bus = BUS_TYPES.get(desc.BusType, f"Bus({desc.BusType})")

                        size_gb = 0.0
                        gbuf = ctypes.create_string_buffer(256)
                        if kernel32.DeviceIoControl(
                            ctypes.c_void_p(h),
                            IOCTL_DISK_GET_DRIVE_GEOMETRY_EX,
                            None,
                            0,
                            gbuf,
                            256,
                            ctypes.byref(returned),
                            None,
                        ):
                            disk_bytes = struct.unpack_from("<Q", gbuf.raw, 24)[0]
                            size_gb = round(disk_bytes / (1024 ** 3), 1)

                        if model:
                            drives.append(
                                StorageDriveInfo(
                                    index=idx,
                                    model=model,
                                    bus_type=bus,
                                    capacity_gb=size_gb,
                                    firmware=fw,
                                    serial_number=sn,
                                )
                            )
                finally:
                    kernel32.CloseHandle(ctypes.c_void_p(h))
        except Exception:
            pass
        return drives

    @classmethod
    def collect_os_specs(cls) -> OsSpecs:
        return cls._collect_os_info()

    @classmethod
    def _collect_linux_info(cls, specs: SystemHardwareSpecs):
        # 1. Motherboard & BIOS via /sys/class/dmi/id
        dmi_base = "/sys/class/dmi/id"
        if os.path.isdir(dmi_base):
            for fname, attr in [
                ("board_vendor", "manufacturer"),
                ("board_name", "product"),
                ("board_version", "version"),
                ("board_serial", "serial_number"),
                ("bios_vendor", "bios_vendor"),
                ("bios_version", "bios_version"),
                ("bios_date", "bios_date"),
            ]:
                fpath = os.path.join(dmi_base, fname)
                try:
                    if os.path.isfile(fpath) and os.access(fpath, os.R_OK):
                        with open(fpath, "r", encoding="utf-8") as f:
                            val = f.read().strip()
                            if val and val.lower() not in ("default string", "system serial number", "none", "to be filled by o.e.m."):
                                setattr(specs.motherboard, attr, val)
                except Exception:
                    pass

        specs.motherboard.boot_mode = "UEFI" if os.path.isdir("/sys/firmware/efi") else "Legacy BIOS"
        if os.path.isdir("/sys/firmware/efi/efivars"):
            try:
                import glob
                sb_files = glob.glob("/sys/firmware/efi/efivars/SecureBoot-*")
                if sb_files and os.access(sb_files[0], os.R_OK):
                    with open(sb_files[0], "rb") as f:
                        raw_sb = f.read()
                        if len(raw_sb) >= 5:
                            specs.motherboard.secure_boot = "Enabled" if raw_sb[-1] == 1 else "Disabled"
            except Exception:
                pass

        # 2. CPU via /proc/cpuinfo + /sys/devices/system/cpu
        cpu_fam = ""
        cpu_mod = ""
        cpu_step = ""
        cpu_mhz_list: List[float] = []
        try:
            if os.path.isfile("/proc/cpuinfo"):
                with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                    for line in f:
                        if ":" not in line:
                            continue
                        k, v = [x.strip() for x in line.split(":", 1)]
                        if k == "model name" and not specs.cpu.name:
                            specs.cpu.name = " ".join(v.split())
                        elif k == "vendor_id" and not specs.cpu.vendor:
                            specs.cpu.vendor = v
                        elif k == "cpu family" and not cpu_fam:
                            cpu_fam = v
                        elif k == "model" and not cpu_mod:
                            cpu_mod = v
                        elif k == "stepping" and not cpu_step:
                            cpu_step = v
                        elif k == "cpu MHz":
                            try:
                                cpu_mhz_list.append(float(v))
                            except Exception:
                                pass
                        elif k == "flags" and not specs.cpu.features:
                            flags = set(v.lower().split())
                            for flag_key, label in [
                                ("sse2", "SSE2"),
                                ("pni", "SSE3"),
                                ("ssse3", "SSSE3"),
                                ("sse4_1", "SSE4.1"),
                                ("sse4_2", "SSE4.2"),
                                ("avx", "AVX"),
                                ("avx2", "AVX2"),
                                ("avx512f", "AVX-512"),
                            ]:
                                if flag_key in flags:
                                    specs.cpu.features.append(label)
                            if "svm" in flags or "vmx" in flags:
                                specs.cpu.virtualization = "Enabled (SVM / VT-x)"
        except Exception:
            pass

        if cpu_fam and cpu_mod:
            specs.cpu.identifier = f"Family {cpu_fam} Model {cpu_mod}" + (f" Stepping {cpu_step}" if cpu_step else "")

        # CPU Clocks from cpufreq or model string
        try:
            max_f_path = "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"
            base_f_path = "/sys/devices/system/cpu/cpu0/cpufreq/base_frequency"
            if os.path.isfile(max_f_path):
                with open(max_f_path, "r") as f:
                    specs.cpu.boost_clock_mhz = int(round(int(f.read().strip()) / 1000.0))
            if os.path.isfile(base_f_path):
                with open(base_f_path, "r") as f:
                    specs.cpu.base_clock_mhz = int(round(int(f.read().strip()) / 1000.0))
            if not specs.cpu.base_clock_mhz and specs.cpu.name:
                m_ghz = re.search(r"@\s*(\d+\.\d+)\s*GHz", specs.cpu.name, re.IGNORECASE)
                if m_ghz:
                    specs.cpu.base_clock_mhz = int(round(float(m_ghz.group(1)) * 1000))
            if not specs.cpu.base_clock_mhz and cpu_mhz_list:
                specs.cpu.base_clock_mhz = int(round(max(cpu_mhz_list)))
            if not specs.cpu.boost_clock_mhz and specs.cpu.base_clock_mhz:
                specs.cpu.boost_clock_mhz = specs.cpu.base_clock_mhz
        except Exception:
            pass

        # CPU Cache Hierarchy via /sys/devices/system/cpu/cpu*/cache/index*
        try:
            import glob
            seen_caches = {1: set(), 2: set(), 3: set()}
            totals_kb = {1: 0, 2: 0, 3: 0}
            for idx_dir in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cache/index[0-9]*")):
                try:
                    with open(os.path.join(idx_dir, "level"), "r") as f:
                        lvl = int(f.read().strip())
                    if lvl not in (1, 2, 3):
                        continue
                    with open(os.path.join(idx_dir, "type"), "r") as f:
                        ctype = f.read().strip()
                    with open(os.path.join(idx_dir, "shared_cpu_list"), "r") as f:
                        shared = f.read().strip()
                    with open(os.path.join(idx_dir, "size"), "r") as f:
                        sz_str = f.read().strip().upper()
                    cache_key = (lvl, ctype, shared)
                    if cache_key in seen_caches[lvl]:
                        continue
                    seen_caches[lvl].add(cache_key)
                    if sz_str.endswith("K"):
                        sz_kb = int(sz_str[:-1])
                    elif sz_str.endswith("M"):
                        sz_kb = int(sz_str[:-1]) * 1024
                    else:
                        sz_kb = int(sz_str) // 1024
                    totals_kb[lvl] += sz_kb
                except Exception:
                    continue
            if totals_kb[1] > 0:
                specs.cpu.l1_cache_kb = totals_kb[1]
            if totals_kb[2] > 0:
                specs.cpu.l2_cache_kb = totals_kb[2]
            if totals_kb[3] > 0:
                specs.cpu.l3_cache_kb = totals_kb[3]
        except Exception:
            pass

        # 3. RAM & Physical DIMM Slots via /run/udev/data/+dmi:id (no root required on systemd/Ubuntu)
        udev_dmi_path = "/run/udev/data/+dmi:id"
        if os.path.isfile(udev_dmi_path) and os.access(udev_dmi_path, os.R_OK):
            try:
                dmi_props: dict = {}
                with open(udev_dmi_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("E:") and "=" in line:
                            k, v = line[2:].split("=", 1)
                            dmi_props[k.strip()] = v.strip()

                max_cap_b = dmi_props.get("MEMORY_ARRAY_MAX_CAPACITY", "")
                if max_cap_b.isdigit() and int(max_cap_b) > 0:
                    specs.ram.max_board_capacity_gb = round(int(max_cap_b) / (1024 ** 3), 0)

                # Group MEMORY_DEVICE_<idx>_<field>
                dev_indices = sorted(
                    {
                        int(m.group(1))
                        for k in dmi_props
                        for m in [re.match(r"^MEMORY_DEVICE_(\d+)_", k)]
                        if m
                    }
                )
                for d_idx in dev_indices:
                    prefix = f"MEMORY_DEVICE_{d_idx}_"
                    sz_str = dmi_props.get(prefix + "SIZE") or dmi_props.get(prefix + "VOLATILE_SIZE") or "0"
                    sz_bytes = int(sz_str) if sz_str.isdigit() else 0
                    populated = sz_bytes > 0
                    cap_gb = round(sz_bytes / (1024 ** 3), 1) if populated else 0.0
                    loc = dmi_props.get(prefix + "LOCATOR", f"Slot {d_idx + 1}")
                    bank = dmi_props.get(prefix + "BANK_LOCATOR", "")
                    mtype = dmi_props.get(prefix + "TYPE", "DDR")
                    ff = dmi_props.get(prefix + "FORM_FACTOR", "DIMM")
                    jedec_s = dmi_props.get(prefix + "SPEED_MTS", "0")
                    cfg_s = dmi_props.get(prefix + "CONFIGURED_SPEED_MTS", jedec_s)
                    jedec_mts = int(jedec_s) if jedec_s.isdigit() else 0
                    cfg_mts = int(cfg_s) if cfg_s.isdigit() else jedec_mts
                    mfg = dmi_props.get(prefix + "MANUFACTURER", "")
                    pn = dmi_props.get(prefix + "PART_NUMBER", "")
                    sn = dmi_props.get(prefix + "SERIAL_NUMBER", "")
                    rank_s = dmi_props.get(prefix + "RANK", "0")
                    ranks = int(rank_s) if rank_s.isdigit() else 0
                    dw_s = dmi_props.get(prefix + "DATA_WIDTH", "64")
                    tw_s = dmi_props.get(prefix + "TOTAL_WIDTH", "64")
                    volt_s = dmi_props.get(prefix + "CONFIGURED_VOLTAGE", "0")
                    volt_raw = float(volt_s) if volt_s.replace(".", "", 1).isdigit() else 0.0
                    if volt_raw > 100:
                        volt_v = round(volt_raw / 1000.0, 2)
                    elif volt_raw in (1.0, 2.0):
                        # udev integer truncation fallback based on DDR generation
                        volt_v = 1.10 if "DDR5" in mtype else (1.20 if "DDR4" in mtype else (1.50 if "DDR3" in mtype else volt_raw))
                    else:
                        volt_v = round(volt_raw, 2)

                    specs.ram.modules.append(
                        RamSlotInfo(
                            slot_label=loc,
                            bank_label=bank,
                            populated=populated,
                            capacity_gb=cap_gb,
                            mem_type=mtype,
                            form_factor=ff,
                            configured_speed_mts=cfg_mts if populated else 0,
                            dram_freq_mhz=(cfg_mts // 2) if populated else 0,
                            jedec_speed_mts=jedec_mts if populated else 0,
                            xmp_expo_spec=decode_ram_part_number_spec(pn) if populated else "",
                            ranks=ranks if populated else 0,
                            voltage_v=volt_v if populated else 0.0,
                            data_width_bits=int(dw_s) if dw_s.isdigit() else 64,
                            total_width_bits=int(tw_s) if tw_s.isdigit() else 64,
                            manufacturer=mfg if populated and mfg.lower() not in ("unknown", "not specified") else "",
                            part_number=pn if populated and pn.lower() not in ("unknown", "not specified") else "",
                            serial_number=sn if populated and sn not in ("00000000", "Unknown", "Not Specified") else "",
                        )
                    )
            except Exception:
                pass

        # Infer CPU Socket on Linux if not populated
        if not specs.cpu.socket:
            cname_u = specs.cpu.name.upper()
            ram_types = {m.mem_type for m in specs.ram.modules if m.populated}
            if "AMD" in specs.cpu.vendor.upper() or "RYZEN" in cname_u or "EPYC" in cname_u:
                if any(s in cname_u for s in ("HS", "HX", "U ", "PRO 7", "AI 9", "AI 7")) or any(
                    m.form_factor == "SODIMM" for m in specs.ram.modules if m.populated
                ):
                    specs.cpu.socket = "FP7 / FP8 (Mobile APU)"
                elif "DDR5" in ram_types or any(s in cname_u for s in ("7950", "7900", "7800", "7700", "7600", "8700", "8600", "9950", "9900", "9800", "9700", "9600")):
                    specs.cpu.socket = "AM5"
                else:
                    specs.cpu.socket = "AM4"
            elif "INTEL" in specs.cpu.vendor.upper():
                if "XEON" in cname_u and "V3" in cname_u:
                    specs.cpu.socket = "LGA1150"
                elif "DDR5" in ram_types:
                    specs.cpu.socket = "LGA1700 / LGA1851"
                else:
                    specs.cpu.socket = "LGA"

        # 4. Linux Block Devices (with firmware & serial)
        try:
            sys_block = "/sys/block"
            if os.path.isdir(sys_block):
                idx = 0
                for dev_name in sorted(os.listdir(sys_block)):
                    if dev_name.startswith(("loop", "ram", "dm-", "zram", "sr")):
                        continue
                    dev_dir = os.path.join(sys_block, dev_name, "device")
                    model_file = os.path.join(dev_dir, "model")
                    size_file = os.path.join(sys_block, dev_name, "size")
                    if os.path.isfile(model_file):
                        with open(model_file, "r", encoding="utf-8", errors="ignore") as f:
                            model = f.read().strip()
                        size_gb = 0.0
                        if os.path.isfile(size_file):
                            with open(size_file, "r", encoding="utf-8", errors="ignore") as f:
                                sectors = int(f.read().strip())
                                size_gb = round((sectors * 512) / (1024 ** 3), 1)
                        fw = ""
                        for fw_name in ("firmware_rev", "rev"):
                            fw_path = os.path.join(dev_dir, fw_name)
                            if os.path.isfile(fw_path) and os.access(fw_path, os.R_OK):
                                with open(fw_path, "r", encoding="utf-8", errors="ignore") as f:
                                    fw = f.read().strip()
                                if fw:
                                    break
                        sn = ""
                        sn_path = os.path.join(dev_dir, "serial")
                        if os.path.isfile(sn_path) and os.access(sn_path, os.R_OK):
                            with open(sn_path, "r", encoding="utf-8", errors="ignore") as f:
                                sn = f.read().strip()
                        bus = "NVMe" if dev_name.startswith("nvme") else "SATA/Block"
                        drives_info = StorageDriveInfo(
                            index=idx,
                            model=model,
                            bus_type=bus,
                            capacity_gb=size_gb,
                            firmware=fw,
                            serial_number=sn,
                        )
                        specs.storage_drives.append(drives_info)
                        idx += 1
        except Exception:
            pass

    @classmethod
    def _finalize_ram_summary(cls, ram: RamSpecs):
        populated = [m for m in ram.modules if m.populated]
        ram.slots_used = len(populated)
        if ram.slots_total < len(ram.modules):
            ram.slots_total = len(ram.modules)

        if populated:
            ram.total_installed_gb = round(sum(m.capacity_gb for m in populated), 1)
            ram.mem_type = populated[0].mem_type
            ram.form_factor = populated[0].form_factor
            ram.configured_speed_mts = max(m.configured_speed_mts for m in populated)
            ram.dram_freq_mhz = ram.configured_speed_mts // 2
            ram.jedec_speed_mts = max(m.jedec_speed_mts for m in populated)
            ram.voltage_v = max(m.voltage_v for m in populated)
            ram.ecc_supported = any(m.total_width_bits > m.data_width_bits for m in populated)
            for m in populated:
                if m.xmp_expo_spec:
                    ram.xmp_expo_spec = m.xmp_expo_spec
                    break

            # Determine Channel Mode from Bank/Device Locators
            channels = set()
            for m in populated:
                combined = f"{m.slot_label} {m.bank_label}".upper()
                ch_match = re.search(r"CHANNEL\s*([A-H0-7])|CH([A-H0-7])|DIMM[_\s-]*([A-H])[0-9]", combined)
                if ch_match:
                    ch_id = ch_match.group(1) or ch_match.group(2) or ch_match.group(3)
                    channels.add(ch_id)

            if not channels and ram.slots_used == 2:
                # 2 DIMMs in BANK 0 / BANK 1 is standard Dual Channel
                channels = {"A", "B"}

            num_ch = len(channels)
            if num_ch >= 4:
                ram.channel_mode = f"Quad Channel ({ram.slots_used} DIMMs)"
            elif num_ch == 3:
                ram.channel_mode = f"Triple Channel ({ram.slots_used} DIMMs)"
            elif num_ch == 2:
                dpc = ram.slots_used // 2
                ram.channel_mode = f"Dual Channel ({dpc} DPC • {ram.slots_used} DIMMs)"
            elif num_ch == 1 and ram.slots_used == 1:
                ram.channel_mode = "Single Channel (1 DIMM)"
            else:
                # Fallback by stick count
                if ram.slots_used == 1:
                    ram.channel_mode = "Single Channel (1 DIMM)"
                elif ram.slots_used in (2, 4):
                    ram.channel_mode = f"Dual Channel ({ram.slots_used} DIMMs)"
                else:
                    ram.channel_mode = f"{ram.slots_used} Active Modules"
        else:
            # Fallback to psutil total memory
            try:
                ram.total_installed_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
            except Exception:
                pass
