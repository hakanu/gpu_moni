"""
Data structures for GPU monitoring.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GpuProcess:
    pid: int
    name: str
    memory_used_mb: Optional[float] = None
    process_type: str = "Compute"  # Compute, Graphics, Context


@dataclass
class GpuMetrics:
    # Utilization
    gpu_util_percent: float = 0.0
    mem_util_percent: float = 0.0

    # Thermals
    temp_core_c: float = 0.0
    temp_hotspot_c: Optional[float] = None
    temp_memory_c: Optional[float] = None
    temp_extra_c: Optional[float] = None

    # Memory (VRAM)
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    vram_free_mb: float = 0.0
    shared_used_mb: float = 0.0

    # Power
    power_draw_w: float = 0.0
    power_limit_w: Optional[float] = None

    # Fans & Clocks
    fan_speed_percent: Optional[float] = None
    fan_speed_rpm: Optional[int] = None
    clock_graphics_mhz: Optional[int] = None
    clock_memory_mhz: Optional[int] = None
    clock_soc_mhz: Optional[int] = None

    # Active processes
    processes: List[GpuProcess] = field(default_factory=list)


@dataclass
class GpuDevice:
    device_id: str
    index: int
    name: str
    vendor: str  # "NVIDIA", "AMD", "Intel", "Other"
    bus_id: str = ""
    pcie_gen: Optional[int] = None
    pcie_width: Optional[int] = None
    driver_version: str = ""
    vram_total_mb: float = 0.0
    luid: str = ""
    metrics: GpuMetrics = field(default_factory=GpuMetrics)


@dataclass
class CpuMetrics:
    name: str = ""
    cores_physical: int = 0
    cores_logical: int = 0
    load_percent: float = 0.0
    per_core_load: List[float] = field(default_factory=list)
    freq_mhz: float = 0.0
    temp_core_c: float = 0.0
    temp_hotspot_c: Optional[float] = None
    power_draw_w: Optional[float] = None


@dataclass
class RamMetrics:
    used_gb: float = 0.0
    total_gb: float = 0.0
    free_gb: float = 0.0
    load_percent: float = 0.0
    pagefile_used_gb: float = 0.0
    pagefile_total_gb: float = 0.0


@dataclass
class HostMetrics:
    cpu: CpuMetrics = field(default_factory=CpuMetrics)
    ram: RamMetrics = field(default_factory=RamMetrics)
    top_processes: List[GpuProcess] = field(default_factory=list)

