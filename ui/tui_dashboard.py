"""
bpytop / btop inspired Terminal User Interface (TUI) for GPU Sentry.
Features:
- 24-bit TrueColor ANSI gradients (Thermal & Load scales)
- High-density Unicode Braille rolling sparklines (2x4 dot matrix per cell)
- Rounded box-drawing panels with embedded keybinding badges (¹cpu, ²gpu, ³tailnet, ⁴specs/procs)
- Flicker-free double-buffered alternate screen rendering
- Live local CPU/RAM/GPU telemetry + Tailscale Tailnet & LAN GPU thermal monitoring + Deep SMBIOS Hardware Specs
"""

import collections
import ctypes
import os
import re
import shutil
import sys
import time
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional, Tuple

from core.gpu_types import GpuDevice, GpuMetrics, HostMetrics
from core.hardware_info import HardwareInfoCollector, SystemHardwareSpecs
from core.nvml_backend import NvmlBackend
from core.adl_backend import AdlBackend
from core.dxgi_backend import DxgiBackend
from core.drm_backend import LinuxDrmBackend
from core.host_backend import HostBackend
from core.network_telemetry import NetworkTelemetryManager, RemoteNodeState


# ANSI Escape Helpers
ESC = "\x1b"
RESET = f"{ESC}[0m"
BOLD = f"{ESC}[1m"
DIM = f"{ESC}[2m"
ALT_SCREEN_ON = f"{ESC}[?1049h"
ALT_SCREEN_OFF = f"{ESC}[?1049l"
CURSOR_HIDE = f"{ESC}[?25l"
CURSOR_SHOW = f"{ESC}[?25h"
CURSOR_HOME = f"{ESC}[H"
CLEAR_SCREEN = f"{ESC}[2J"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def fg(r: int, g: int, b: int) -> str:
    return f"{ESC}[38;2;{r};{g};{b}m"


def bg(r: int, g: int, b: int) -> str:
    return f"{ESC}[48;2;{r};{g};{b}m"


# Palette matching GPU Sentry & bpytop dark theme
C_BORDER = fg(48, 60, 84)
C_BORDER_HI = fg(0, 229, 255)
C_TEXT = fg(240, 246, 252)
C_SUB = fg(139, 148, 158)
C_MUTED = fg(85, 95, 109)
C_CYAN = fg(0, 229, 255)
C_GREEN = fg(0, 230, 118)
C_PURPLE = fg(179, 136, 255)
C_RED = fg(255, 51, 102)
C_BLUE = fg(0, 176, 255)
C_AMBER = fg(255, 179, 0)
C_KEY = f"{BOLD}{fg(255, 82, 82)}"


def visible_len(s: str) -> int:
    return len(ANSI_RE.sub("", s))


def pad_ansi(s: str, width: int, align: str = "left") -> str:
    vlen = visible_len(s)
    if vlen >= width:
        # Truncate preserving ANSI resets
        out = []
        cur = 0
        i = 0
        while i < len(s) and cur < width:
            m = ANSI_RE.match(s, i)
            if m:
                out.append(m.group(0))
                i = m.end()
            else:
                out.append(s[i])
                cur += 1
                i += 1
        out.append(RESET)
        return "".join(out)
    pad = width - vlen
    if align == "right":
        return (" " * pad) + s
    elif align == "center":
        lpad = pad // 2
        rpad = pad - lpad
        return (" " * lpad) + s + (" " * rpad)
    return s + (" " * pad)


def temp_rgb(temp_c: float) -> Tuple[int, int, int]:
    if temp_c < 55:
        return (0, 230, 118)     # Cool Neon Green (< 55°C)
    elif temp_c <= 70:
        return (41, 182, 246)    # Normal Cyan-Blue (55 - 70°C)
    elif temp_c <= 80:
        return (255, 179, 0)     # Warm Amber (71 - 80°C)
    elif temp_c <= 88:
        return (255, 112, 67)    # Hot Orange (81 - 88°C)
    return (255, 23, 68)         # Critical Red (> 88°C)


def temp_badge(temp_c: float, status_temp_c: Optional[float] = None) -> str:
    eval_t = status_temp_c if status_temp_c is not None else temp_c
    r, g, b = temp_rgb(eval_t)
    if eval_t < 55:
        st = "COOL"
    elif eval_t <= 70:
        st = "NORM"
    elif eval_t <= 80:
        st = "WARM"
    elif eval_t <= 88:
        st = "HOT!"
    else:
        st = "THRT"
    return f"{fg(r, g, b)}{BOLD}{temp_c:3.0f}°C{RESET}{bg(r // 5, g // 5, b // 5)}{fg(r, g, b)}[{st}]{RESET}"


def load_rgb(pct: float) -> Tuple[int, int, int]:
    pct = max(0.0, min(100.0, pct))
    if pct < 35:
        return (0, 229, 255)     # Cyan
    elif pct < 65:
        return (0, 230, 118)     # Green
    elif pct < 85:
        return (255, 179, 0)     # Amber
    return (255, 51, 102)        # Red-Pink


def meter_bar(pct: float, width: int = 16, color_override: Optional[Tuple[int, int, int]] = None) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round((pct / 100.0) * width))
    empty = max(0, width - filled)
    out = []
    for i in range(filled):
        pos_pct = ((i + 1) / max(1, width)) * 100.0
        r, g, b = color_override if color_override else load_rgb(pos_pct)
        out.append(f"{fg(r, g, b)}■")
    if empty > 0:
        out.append(f"{C_MUTED}{'□' * empty}")
    out.append(RESET)
    return "".join(out)


# Braille 2x4 dot bitmask lookup:
# Left col (dots 1,2,3,7 -> bits 0x01, 0x02, 0x04, 0x40 from top to bottom)
# Right col (dots 4,5,6,8 -> bits 0x08, 0x10, 0x20, 0x80 from top to bottom)
_LEFT_DOTS = [0x40, 0x04, 0x02, 0x01]   # bottom to top (0..3)
_RIGHT_DOTS = [0x80, 0x20, 0x10, 0x08]  # bottom to top (0..3)


def braille_sparkline(history: List[float], width: int, color_fn: Callable[[float], Tuple[int, int, int]] = load_rgb) -> str:
    """Renders a 1-row high-resolution Braille area graph (2 samples per character cell, 4 vertical levels)."""
    needed_samples = width * 2
    if len(history) < needed_samples:
        padded = [0.0] * (needed_samples - len(history)) + list(history)
    else:
        padded = list(history[-needed_samples:])

    chars = []
    for c in range(width):
        v_left = max(0.0, min(100.0, padded[c * 2]))
        v_right = max(0.0, min(100.0, padded[c * 2 + 1]))
        lvl_l = int(round((v_left / 100.0) * 4))
        lvl_r = int(round((v_right / 100.0) * 4))
        mask = 0
        for d in range(lvl_l):
            mask |= _LEFT_DOTS[d]
        for d in range(lvl_r):
            mask |= _RIGHT_DOTS[d]
        ch = chr(0x2800 + mask)
        avg_v = max(v_left, v_right)
        if mask == 0:
            chars.append(f"{C_MUTED}⣀")
        else:
            r, g, b = color_fn(avg_v)
            chars.append(f"{fg(r, g, b)}{ch}")
    chars.append(RESET)
    return "".join(chars)


def draw_box(
    title: str,
    lines: List[str],
    width: int,
    border_color: str = C_BORDER,
    right_title: str = "",
) -> List[str]:
    inner_w = max(10, width - 2)
    title_block = f"─ {title} "
    if visible_len(title_block) > inner_w:
        title_block = pad_ansi(title_block, inner_w)
    t_vlen = visible_len(title_block)

    if right_title:
        r_block = f" {right_title} ─"
        r_vlen = visible_len(r_block)
        if t_vlen + r_vlen > inner_w:
            avail_r = inner_w - t_vlen - 3
            if avail_r > 8:
                r_block = f" {pad_ansi(right_title, avail_r)} {border_color}─"
                r_vlen = visible_len(r_block)
            else:
                r_block = ""
                r_vlen = 0
    else:
        r_block = ""
        r_vlen = 0

    fill_len = max(0, inner_w - t_vlen - r_vlen)
    top = f"{border_color}╭{title_block}{border_color}{'─' * fill_len}{r_block}{border_color}╮{RESET}"
    out = [top]
    for ln in lines:
        padded = pad_ansi(ln, inner_w - 2)
        out.append(f"{border_color}│{RESET} {padded} {border_color}│{RESET}")
    bot = f"{border_color}╰{'─' * inner_w}╯{RESET}"
    out.append(bot)
    return out


class BpytopTuiApp:
    """
    bpytop-inspired Terminal UI for GPU Sentry.
    """

    def __init__(self, interval_ms: int = 1000):
        self.interval_ms = interval_ms
        self.running = True
        self.paused = False

        # Visible box toggles (like bpytop 1/2/3/4 keys)
        self.show_cpu = True
        self.show_gpu = True
        self.show_net = True
        self.bottom_mode = "procs"  # "procs" or "specs"

        # Hardware & Telemetry Backends (Zero PyQt6 dependency in TUI mode)
        self.nvml = NvmlBackend()
        self.adl = AdlBackend()
        self.dxgi = DxgiBackend()
        self.drm = LinuxDrmBackend(nvml_available=self.nvml.available)
        self.host = HostBackend(adl_backend=self.adl)
        self.devices: List[GpuDevice] = self._discover_local_devices()
        self.hw_specs: SystemHardwareSpecs = HardwareInfoCollector.collect_all()
        self.net_manager = NetworkTelemetryManager(os_name=self.hw_specs.os_info.os_name)
        self.net_manager.server_enabled = False

        # Rolling history buffers (120 samples)
        self.cpu_history: Deque[float] = collections.deque([0.0] * 120, maxlen=120)
        self.gpu_histories: Dict[str, Deque[float]] = {}
        for dev in self.devices:
            self.gpu_histories[dev.device_id] = collections.deque([0.0] * 120, maxlen=120)

        self.latest_host: HostMetrics = HostMetrics()
        self.latest_gpu_metrics: Dict[str, GpuMetrics] = {}
        self.poll_latency_ms: float = 0.0
        self.app_ram_mb: float = 0.0

    def _discover_local_devices(self) -> List[GpuDevice]:
        discovered: List[GpuDevice] = []
        used_luids = set()
        if self.nvml.available:
            for d in self.nvml.get_devices():
                dx = self.dxgi.get_adapter_info("NVIDIA", d.name)
                if dx:
                    d.luid = dx["luid_key"]
                    used_luids.add(d.luid)
                    if d.vram_total_mb <= 0:
                        d.vram_total_mb = dx["dedicated_vram_mb"]
                discovered.append(d)
        if self.adl.available:
            for d in self.adl.get_devices():
                dx = self.dxgi.get_adapter_info("AMD", d.name)
                if dx:
                    d.luid = dx["luid_key"]
                    used_luids.add(d.luid)
                    d.vram_total_mb = dx["dedicated_vram_mb"]
                discovered.append(d)
        for adp in self.dxgi.adapters:
            if adp["luid_key"] in used_luids:
                continue
            desc_lower = adp["description"].lower()
            if "basic render" in desc_lower or "software" in desc_lower or adp["dedicated_vram_mb"] <= 0:
                continue
            v_name = "Intel" if adp["vendor_id"] == 0x8086 else "Other"
            discovered.append(
                GpuDevice(
                    device_id=f"dxgi_{len(discovered)}",
                    index=len(discovered),
                    name=adp["description"],
                    vendor=v_name,
                    vram_total_mb=adp["dedicated_vram_mb"],
                    luid=adp["luid_key"],
                )
            )
        if self.drm.available:
            for d in self.drm.get_devices(start_index=len(discovered)):
                if not any(existing.device_id == d.device_id for existing in discovered):
                    discovered.append(d)
        return discovered

    def _enable_windows_vt_mode(self):
        if sys.platform == "win32":
            try:
                k32 = ctypes.windll.kernel32
                handle = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
                mode = ctypes.c_ulong()
                if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                    k32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            except Exception:
                pass

    def _poll_local(self):
        t0 = time.perf_counter()
        pdh_mems = self.dxgi.sample_memory_by_luid()
        metrics_by_id: Dict[str, GpuMetrics] = {}

        for dev in self.devices:
            m = GpuMetrics()
            if dev.vendor == "NVIDIA" and self.nvml.available and dev.device_id.startswith("nvidia_"):
                m = self.nvml.sample_metrics(dev.index)
            elif dev.vendor == "AMD" and self.adl.available and dev.device_id.startswith("amd_"):
                m = self.adl.sample_metrics(dev.index)
                if dev.luid in pdh_mems:
                    m.vram_used_mb = pdh_mems[dev.luid]
                m.vram_total_mb = dev.vram_total_mb
                if m.vram_total_mb > 0:
                    m.vram_free_mb = max(0.0, m.vram_total_mb - m.vram_used_mb)
            elif dev.device_id.startswith("drm_") and self.drm.available:
                m = self.drm.sample_metrics(dev.device_id)
            else:
                if dev.luid in pdh_mems:
                    m.vram_used_mb = pdh_mems[dev.luid]
                m.vram_total_mb = dev.vram_total_mb

            metrics_by_id[dev.device_id] = m
            if dev.device_id not in self.gpu_histories:
                self.gpu_histories[dev.device_id] = collections.deque([0.0] * 120, maxlen=120)
            self.gpu_histories[dev.device_id].append(m.gpu_util_percent)

        self.latest_gpu_metrics = metrics_by_id
        self.latest_host = self.host.sample_metrics()
        self.cpu_history.append(self.latest_host.cpu.load_percent)
        self.poll_latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        try:
            import psutil
            mem_info = psutil.Process().memory_info()
            raw_bytes = mem_info.vms if sys.platform == "win32" else mem_info.rss
            self.app_ram_mb = round(raw_bytes / (1024 * 1024), 1)
        except Exception:
            pass

        # Share with LAN/Tailnet server
        self.net_manager.update_local_telemetry(
            self.devices,
            self.latest_gpu_metrics,
            self.latest_host,
        )

    def _read_key_nonblocking(self) -> str:
        if sys.platform == "win32":
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0") and msvcrt.kbhit():
                    msvcrt.getwch()
                    return ""
                return ch
            return ""
        else:
            import select
            dr, _, _ = select.select([sys.stdin], [], [], 0.0)
            if dr:
                return sys.stdin.read(1)
            return ""

    def _handle_key(self, key: str):
        if not key:
            return
        k = key.lower()
        if k in ("q", "\x1b", "\x03"):
            self.running = False
        elif k == "1":
            self.show_cpu = not self.show_cpu
        elif k == "2":
            self.show_gpu = not self.show_gpu
        elif k == "3":
            self.show_net = not self.show_net
        elif k in ("4", "h"):
            self.bottom_mode = "specs" if self.bottom_mode == "procs" else "procs"
        elif k == "5":
            self.bottom_mode = "procs"
        elif k in ("s", "r"):
            self.net_manager.rescan_network()
        elif k == "t":
            self.net_manager.set_tailscale_enabled(not self.net_manager.tailscale_enabled)
        elif k in ("+", "="):
            self.interval_ms = max(250, self.interval_ms - 250)
        elif k in ("-", "_"):
            self.interval_ms = min(3000, self.interval_ms + 250)
        elif k in ("p", " "):
            self.paused = not self.paused

    def _render_frame(self, cols: int, rows: int) -> str:
        width = max(76, cols)
        lines: List[str] = []

        # Calculate global stats
        total_pwr = sum(m.power_draw_w for m in self.latest_gpu_metrics.values())
        peak_temp = max((m.temp_core_c for m in self.latest_gpu_metrics.values()), default=0.0)
        net_states = self.net_manager.get_visible_states()
        online_net_gpus = sum(len(st.gpus) for st in net_states.values() if st.online)

        # 0. Top bpytop Header Bar
        now_str = datetime.now().strftime("%H:%M:%S")
        status_dot = f"{C_AMBER}⏸ PAUSED{RESET}" if self.paused else f"{C_GREEN}● LIVE{RESET}"
        k1 = f"{C_KEY}¹{C_CYAN if self.show_cpu else C_MUTED}cpu{RESET}"
        k2 = f"{C_KEY}²{C_GREEN if self.show_gpu else C_MUTED}gpu{RESET}"
        k3 = f"{C_KEY}³{C_PURPLE if self.show_net else C_MUTED}tailnet({online_net_gpus}){RESET}"
        k4 = f"{C_KEY}⁴{C_AMBER if self.bottom_mode == 'specs' else C_TEXT}{'specs' if self.bottom_mode == 'specs' else 'procs'}{RESET}"
        kt = f"{C_KEY}t{C_GREEN if self.net_manager.tailscale_enabled else C_MUTED}s:{'on' if self.net_manager.tailscale_enabled else 'off'}{RESET}"
        kr = f"{C_KEY}r{C_SUB}escan{RESET}"
        kq = f"{C_KEY}q{C_SUB}uit{RESET}"

        hdr_left = (
            f"{BOLD}{C_GREEN}⚡ GPU SENTRY{RESET} {C_SUB}bpytop-tui ({self.app_ram_mb:.0f}MB){RESET} │ "
            f"{status_dot} {C_SUB}{self.interval_ms}ms ({self.poll_latency_ms}ms){RESET} │ "
            f"{C_AMBER}🔥 {total_pwr:.0f}W{RESET} │ {C_TEXT}🌡 Peak {peak_temp:.0f}°C{RESET}"
        )
        hdr_right = f"{k1} {k2} {k3} {k4} {kt} {kr} {C_KEY}+/-{RESET} {kq} │ {BOLD}{C_TEXT}{now_str}{RESET}"
        gap = max(1, width - visible_len(hdr_left) - visible_len(hdr_right) - 2)
        lines.append(" " + hdr_left + (" " * gap) + hdr_right)

        # 1. CPU & System Memory Box
        if self.show_cpu:
            lines.extend(self._build_cpu_ram_box(width))

        # 2. Local GPUs Box
        if self.show_gpu:
            lines.extend(self._build_local_gpus_box(width))

        # 3. Tailscale Tailnet & Network GPUs Box
        if self.show_net:
            lines.extend(self._build_network_gpus_box(width, net_states))

        # 4. Bottom Box: Active GPU Processes OR Deep Hardware Specifications
        remaining_rows = max(6, rows - len(lines) - 1)
        if self.bottom_mode == "specs":
            lines.extend(self._build_hardware_specs_box(width, remaining_rows))
        else:
            lines.extend(self._build_processes_box(width, remaining_rows))

        # Crop to terminal height to prevent scrolling
        cropped = lines[: max(1, rows - 1)]
        return CURSOR_HOME + "\n".join(pad_ansi(ln, width) for ln in cropped)

    def _build_cpu_ram_box(self, width: int) -> List[str]:
        cpu = self.latest_host.cpu
        ram = self.latest_host.ram
        c_spec = self.hw_specs.cpu
        r_spec = self.hw_specs.ram
        mb_spec = self.hw_specs.motherboard

        title = f"{C_KEY}¹{BOLD}{C_CYAN}cpu & memory{RESET} ─ {BOLD}{C_TEXT}{cpu.name or c_spec.name}{RESET}"
        r_title = (
            f"{C_SUB}Socket {c_spec.socket} • {c_spec.cores_physical}C/{c_spec.cores_logical}T • "
            f"L3 {c_spec.l3_cache_kb // 1024}MB • {mb_spec.product} (BIOS {mb_spec.bios_version}){RESET}"
        )

        inner_w = width - 4
        spark_w = max(8, min(38, inner_w - 68))
        bar_w = 12 if inner_w >= 105 else 8
        spark = braille_sparkline(list(self.cpu_history), spark_w, load_rgb)

        pwr_str = f"{cpu.power_draw_w:.1f}W" if cpu.power_draw_w else "--W"
        freq_ghz = cpu.freq_mhz / 1000.0 if cpu.freq_mhz else 0.0

        row1 = (
            f"{C_SUB}CPU{RESET} {spark} {meter_bar(cpu.load_percent, bar_w)} "
            f"{BOLD}{C_CYAN}{cpu.load_percent:5.1f}%{RESET} │ "
            f"{temp_badge(cpu.temp_core_c)} │ "
            f"{C_AMBER}⚡ {pwr_str:>6}{RESET} │ "
            f"{C_TEXT}{freq_ghz:.2f} GHz{RESET} {C_MUTED}(Boost {c_spec.boost_clock_mhz} MHz){RESET}"
        )

        # Per-core compact bpytop grid (up to 8 cores per row)
        core_loads = cpu.per_core_load or []
        core_lines = []
        if core_loads:
            per_row = 8 if inner_w >= 110 else 4
            for i in range(0, min(16, len(core_loads)), per_row):
                chunk = core_loads[i : i + per_row]
                cells = []
                for idx_offset, cl in enumerate(chunk):
                    c_idx = i + idx_offset
                    r, g, b = load_rgb(cl)
                    mini_bar = meter_bar(cl, 4)
                    cells.append(f"{C_SUB}C{c_idx:02d}{RESET} {mini_bar} {fg(r, g, b)}{cl:3.0f}%{RESET}")
                core_lines.append("  ".join(cells))

        # RAM + Channels + Speed row
        ch_short = "Dual-Channel" if "Dual" in r_spec.channel_mode else r_spec.channel_mode
        ram_bar = meter_bar(ram.load_percent, 18)
        expo_tag = f" • EXPO/XMP {r_spec.xmp_expo_spec.split()[0]}" if r_spec.xmp_expo_spec else ""
        ram_row = (
            f"{C_SUB}MEM{RESET} {ram_bar} {BOLD}{C_TEXT}{ram.used_gb:4.1f}/{ram.total_gb:4.1f} GB{RESET} "
            f"({C_CYAN}{ram.load_percent:4.1f}%{RESET}) │ "
            f"{C_GREEN}Free: {ram.free_gb:4.1f} GB{RESET} │ "
            f"{C_PURPLE}{BOLD}{r_spec.mem_type} {ch_short} @ {r_spec.configured_speed_mts} MT/s ({r_spec.dram_freq_mhz} MHz){RESET}"
            f"{C_SUB} • {r_spec.slots_used}/{r_spec.slots_total} DIMMs{expo_tag}{RESET}"
        )

        box_lines = [row1] + core_lines + [ram_row]
        return draw_box(title, box_lines, width, C_BORDER, r_title)

    def _build_local_gpus_box(self, width: int) -> List[str]:
        devs = self.devices
        title = f"{C_KEY}²{BOLD}{C_GREEN}local gpus ({len(devs)} online){RESET}"
        backend_label = "Direct C NVML / AMDGPU DRM & hwmon Telemetry" if sys.platform.startswith("linux") else "Direct C NVML / ADL / DXGI Telemetry"
        r_title = f"{C_SUB}{backend_label}{RESET}"

        if not devs:
            return draw_box(
                title,
                [f"{C_MUTED}No local dedicated or integrated GPUs detected on this host.{RESET}"],
                width,
                C_BORDER,
                r_title,
            )

        box_lines = []
        inner_w = width - 4
        spark_w = max(12, min(28, inner_w // 5))

        for i, dev in enumerate(devs):
            m = self.latest_gpu_metrics.get(dev.device_id, GpuMetrics())
            hist = list(self.gpu_histories.get(dev.device_id, [0.0] * 30))
            spark = braille_sparkline(hist, spark_w, load_rgb)

            v_col = C_GREEN if "NVIDIA" in dev.vendor.upper() else (C_RED if "AMD" in dev.vendor.upper() else C_BLUE)
            arch_info = f"{dev.architecture}" if dev.architecture else dev.vendor
            if dev.cuda_cores:
                arch_info += f" • {dev.cuda_cores} Cores"
            if dev.pcie_gen and dev.pcie_width:
                arch_info += f" • PCIe Gen{dev.pcie_gen}x{dev.pcie_width}"
                if dev.pcie_max_gen and (
                    dev.pcie_max_gen != dev.pcie_gen
                    or dev.pcie_max_width != dev.pcie_width
                    or len(arch_info) <= 24
                ):
                    arch_info += f"(Max Gen{dev.pcie_max_gen}x{dev.pcie_max_width})"

            vram_u_gb = m.vram_used_mb / 1024.0
            vram_t_gb = m.vram_total_mb / 1024.0 if m.vram_total_mb > 0 else 0.0
            vram_pct = (m.vram_used_mb / m.vram_total_mb * 100.0) if m.vram_total_mb > 0 else 0.0

            pwr_txt = f"{m.power_draw_w:5.1f}W" if m.power_draw_w > 0 else "  --W"
            if m.power_limit_w and m.power_limit_w > 0:
                pwr_txt += f"/{m.power_limit_w:.0f}W"

            # Multi-sensor thermal details (Edge + Junction/Hotspot + Memory + Fan RPM/%)
            eff_temp = max(m.temp_core_c, (m.temp_hotspot_c - 22.0) if m.temp_hotspot_c else 0.0)
            extra_therm = []
            if m.temp_hotspot_c and m.temp_hotspot_c > 0:
                extra_therm.append(f"Junc:{m.temp_hotspot_c:.0f}°C")
            if m.temp_memory_c and m.temp_memory_c > 0:
                extra_therm.append(f"Mem:{m.temp_memory_c:.0f}°C")
            if m.fan_speed_rpm is not None and m.fan_speed_rpm > 0:
                if m.fan_speed_percent is not None and m.fan_speed_percent > 0:
                    extra_therm.append(f"🌀{m.fan_speed_rpm}RPM({m.fan_speed_percent:.0f}%)")
                else:
                    extra_therm.append(f"🌀{m.fan_speed_rpm}RPM")
            elif m.fan_speed_percent is not None:
                extra_therm.append(f"🌀{m.fan_speed_percent:.0f}%")
            else:
                extra_therm.append("🌀--%")
            therm_detail = " ".join(extra_therm)

            clk_txt = f"{m.clock_graphics_mhz or '--'}/{m.clock_memory_mhz or '--'}MHz"
            if m.clock_soc_mhz:
                clk_txt += f" (SoC:{m.clock_soc_mhz})"

            if m.vram_total_mb > 0:
                gtt_tag = f" {C_MUTED}(GTT:{m.shared_used_mb / 1024.0:.1f}G){RESET}" if m.shared_used_mb >= 100 else ""
                vram_section = f"{C_SUB}VRAM:{RESET} {meter_bar(vram_pct, 8)} {BOLD}{C_TEXT}{vram_u_gb:4.1f}/{vram_t_gb:4.1f}GB{RESET}({vram_pct:2.0f}%){gtt_tag}"
            else:
                vram_section = f"{C_SUB}VRAM:{RESET} {C_MUTED}Shared Host RAM{RESET}"

            line1 = (
                f"{v_col}{BOLD}GPU{dev.index} {dev.name[:28]:<28}{RESET} {spark} "
                f"{meter_bar(m.gpu_util_percent, 10)} {BOLD}{C_TEXT}{m.gpu_util_percent:4.0f}%{RESET} │ "
                f"{temp_badge(m.temp_core_c, eff_temp)} {C_SUB}{therm_detail}{RESET}"
            )
            line2 = (
                f"     {C_SUB}{arch_info[:34]:<34}{RESET} │ "
                f"{vram_section} │ "
                f"{C_AMBER}🔥 {pwr_txt:<10}{RESET} │ {C_SUB}Clk: {clk_txt}{RESET}"
            )
            box_lines.append(line1)
            box_lines.append(line2)
            if i < len(devs) - 1:
                box_lines.append(f"{C_MUTED}{'┄' * inner_w}{RESET}")

        return draw_box(title, box_lines, width, C_BORDER, r_title)

    def _build_network_gpus_box(self, width: int, states: Dict[str, RemoteNodeState]) -> List[str]:
        scan_msg = ""
        if self.net_manager._tailnet_scan_requested:
            scan_msg = f" {C_PURPLE}(Scanning Tailnet...){RESET}"
        title = f"{C_KEY}³{BOLD}{C_PURPLE}tailscale tailnet & network gpus{RESET}{scan_msg}"

        net_vram_u = sum(
            st.gpu_metrics.get(g.device_id, g.metrics).vram_used_mb
            for st in states.values() if st.online for g in st.gpus
        ) / 1024.0
        net_vram_t = sum(
            st.gpu_metrics.get(g.device_id, g.metrics).vram_total_mb
            for st in states.values() if st.online for g in st.gpus
        ) / 1024.0
        net_pwr = sum(
            st.gpu_metrics.get(g.device_id, g.metrics).power_draw_w
            for st in states.values() if st.online for g in st.gpus
        )
        net_peak_t = max(
            (st.gpu_metrics.get(g.device_id, g.metrics).temp_core_c for st in states.values() if st.online for g in st.gpus),
            default=0.0,
        )
        r_title = (
            f"{C_CYAN}Tailnet VRAM: {net_vram_u:.1f}/{net_vram_t:.1f}GB{RESET} • "
            f"{C_AMBER}🔥 {net_pwr:.1f}W{RESET} • "
            f"{C_TEXT}🌡 Peak {net_peak_t:.0f}°C{RESET} • {C_SUB}[{C_KEY}s{C_SUB}]can{RESET}"
        )

        if not states:
            if not self.net_manager.tailscale_enabled:
                lines = [
                    f"{C_MUTED}Tailscale GPU monitoring is OFF. (Press {C_KEY}t{C_MUTED} to enable Tailscale){RESET}"
                ]
            else:
                lines = [
                    f"{C_SUB}Scanning Tailscale Tailnet & LAN for GPU-equipped machines... (Press {C_KEY}s{C_SUB} to force scan, {C_KEY}t{C_SUB} to toggle Tailscale){RESET}"
                ]
            return draw_box(title, lines, width, C_BORDER, r_title)

        def _sort_key(item):
            _, st = item
            max_vram = max((g.vram_total_mb for g in st.gpus), default=0.0)
            return (not st.online, -max_vram, st.hostname.lower())

        box_lines = []
        for _, st in sorted(states.items(), key=_sort_key):
            if not st.online:
                box_lines.append(
                    f"{C_RED}● OFFLINE{RESET} {BOLD}{st.hostname:<12}{RESET} ({st.tailscale_ip or st.address}) ─ {C_MUTED}{st.error_msg}{RESET}"
                )
                continue

            net_tag = f"{C_PURPLE}[TAILSCALE]{RESET}" if st.is_tailscale else f"{C_BLUE}[LAN]{RESET}"
            cpu_t = f"{st.host_metrics.cpu.temp_core_c:.0f}°C" if st.host_metrics.cpu.temp_core_c > 0 else "--°C"
            host_summary = (
                f"{C_SUB}Host CPU:{RESET} {st.host_metrics.cpu.load_percent:3.0f}% ({cpu_t}) "
                f"{C_SUB}RAM:{RESET} {st.host_metrics.ram.used_gb:.1f}/{st.host_metrics.ram.total_gb:.1f}GB"
            )

            for g in st.gpus:
                m = st.gpu_metrics.get(g.device_id, g.metrics)
                v_col = C_GREEN if "NVIDIA" in g.vendor.upper() else (C_RED if "AMD" in g.vendor.upper() else C_BLUE)
                clean_gname = g.name.replace(f"[{st.hostname}] ", "")
                # Junction/Hotspot on modern GPUs (e.g. RDNA 3) runs ~20-25°C above Edge (max 110°C)
                eff_temp = max(m.temp_core_c, (m.temp_hotspot_c - 22.0) if m.temp_hotspot_c else 0.0)

                extra_therm = []
                if m.temp_hotspot_c:
                    extra_therm.append(f"Junc:{m.temp_hotspot_c:.0f}°C")
                if m.temp_memory_c:
                    extra_therm.append(f"Mem:{m.temp_memory_c:.0f}°C")
                if m.fan_speed_rpm:
                    extra_therm.append(f"🌀{m.fan_speed_rpm}RPM")
                elif m.fan_speed_percent is not None:
                    extra_therm.append(f"🌀{m.fan_speed_percent:.0f}%")
                therm_detail = (" " + C_SUB + " ".join(extra_therm) + RESET) if extra_therm else ""

                if m.vram_total_mb > 0:
                    vu = m.vram_used_mb / 1024.0
                    vt = m.vram_total_mb / 1024.0
                    vpct = (m.vram_used_mb / m.vram_total_mb) * 100.0
                    vbar = meter_bar(vpct, 6)
                    vram_str = f"{vbar} {BOLD}{C_CYAN}{vu:4.1f}/{vt:4.1f}GB{RESET}({vpct:2.0f}%)"
                else:
                    vram_str = f"{C_MUTED}Shared Host RAM   {RESET}"

                if m.power_draw_w > 0:
                    if m.power_limit_w and m.power_limit_w > 0:
                        pwr_str = f"{BOLD}{C_AMBER}🔥{m.power_draw_w:5.1f}/{m.power_limit_w:.0f}W{RESET}"
                    else:
                        pwr_str = f"{BOLD}{C_AMBER}🔥{m.power_draw_w:5.1f}W{RESET}    "
                else:
                    pwr_str = f"{C_MUTED}🔥   --W    {RESET}"

                row = (
                    f"{C_GREEN}●{RESET} {BOLD}{C_PURPLE}{st.hostname[:8]:<8}{RESET} "
                    f"│ {v_col}{BOLD}{clean_gname[:20]:<20}{RESET} "
                    f"│ {C_SUB}VRAM{RESET} {vram_str} "
                    f"│ {temp_badge(m.temp_core_c, eff_temp)}{therm_detail} "
                    f"│ {pwr_str} "
                    f"│ {C_SUB}Load:{RESET}{BOLD}{m.gpu_util_percent:3.0f}%{RESET}"
                )
                box_lines.append(row)

        return draw_box(title, box_lines, width, C_BORDER, r_title)

    def _build_processes_box(self, width: int, max_rows: int) -> List[str]:
        title = f"{C_KEY}⁴{BOLD}{C_TEXT}active gpu workloads{RESET} {C_SUB}(Press {C_KEY}4{C_SUB} or {C_KEY}h{C_SUB} to switch to Deep Hardware Specs){RESET}"
        all_procs = []
        for dev in self.devices:
            m = self.latest_gpu_metrics.get(dev.device_id, GpuMetrics())
            for p in m.processes:
                all_procs.append((f"GPU{dev.index} ({dev.name})", p))

        box_lines = [
            f"{BOLD}{C_SUB}{'PID':<8} {'PROCESS NAME':<30} {'TYPE':<12} {'VRAM':<12} {'ADAPTER'}{RESET}"
        ]
        if not all_procs:
            box_lines.append(f"{C_MUTED}No active compute/graphics GPU processes detected.{RESET}")
        else:
            for gname, p in all_procs[: max(2, max_rows - 3)]:
                vram_s = f"{p.memory_used_mb:.1f} MB" if p.memory_used_mb else "--"
                t_col = C_CYAN if p.process_type == "Compute" else C_GREEN
                box_lines.append(
                    f"{C_TEXT}{p.pid:<8}{RESET} {BOLD}{C_TEXT}{p.name:<30}{RESET} "
                    f"{t_col}{p.process_type:<12}{RESET} {C_AMBER}{vram_s:<12}{RESET} {C_SUB}{gname}{RESET}"
                )
        return draw_box(title, box_lines, width, C_BORDER)

    def _build_hardware_specs_box(self, width: int, max_rows: int) -> List[str]:
        title = f"{C_KEY}⁴{BOLD}{C_AMBER}deep hardware & smbios specifications{RESET} {C_SUB}(Press {C_KEY}4{C_SUB} or {C_KEY}5{C_SUB} for GPU Processes){RESET}"
        s = self.hw_specs
        vid_str = f" • VID {s.cpu.voltage_v:.2f}V" if s.cpu.voltage_v is not None else ""
        lines = [
            f"{C_CYAN}{BOLD}CPU:{RESET} {s.cpu.name} ({s.cpu.identifier or s.cpu.vendor}) • Socket {s.cpu.socket or 'N/A'} • "
            f"Base {s.cpu.base_clock_mhz}MHz / Boost {s.cpu.boost_clock_mhz}MHz / BCLK {s.cpu.ext_clock_mhz}MHz{vid_str}",
            f"{C_CYAN}{BOLD}CACHE & ISA:{RESET} L1: {s.cpu.l1_cache_kb}KB │ L2: {s.cpu.l2_cache_kb // 1024}MB │ L3: {s.cpu.l3_cache_kb // 1024}MB │ "
            f"Virt: {s.cpu.virtualization} │ {', '.join(s.cpu.features)}",
            f"{C_PURPLE}{BOLD}RAM:{RESET} {s.ram.total_installed_gb:.0f}GB {s.ram.mem_type} {s.ram.form_factor} • {C_GREEN}{BOLD}{s.ram.channel_mode}{RESET} • "
            f"Active: {C_CYAN}{BOLD}{s.ram.configured_speed_mts} MT/s ({s.ram.dram_freq_mhz} MHz){RESET} • JEDEC: {s.ram.jedec_speed_mts} MT/s • "
            f"Profile: {C_AMBER}{s.ram.xmp_expo_spec or 'Standard'}{RESET} • {s.ram.voltage_v:.2f}V",
        ]
        # DIMM slots summary
        dimm_strs = [
            f"{m.slot_label}({m.bank_label}): {m.capacity_gb:.0f}GB {m.ranks}R {m.manufacturer} {m.part_number}"
            for m in s.ram.modules if m.populated
        ]
        if dimm_strs:
            lines.append(f"{C_PURPLE}{BOLD}DIMMs:{RESET} " + " │ ".join(dimm_strs[:2]))
            if len(dimm_strs) > 2:
                lines.append(f"       " + " │ ".join(dimm_strs[2:4]))

        # Local GPUs Deep Specs summary
        if self.devices:
            gpu_strs = [
                f"GPU{d.index} {d.name} ({d.architecture or d.vendor}, {d.vram_total_mb / 1024.0:.1f}GB, "
                f"PCIe Gen{d.pcie_gen or '?'}x{d.pcie_width or '?'}, VBIOS {d.vbios_version or 'N/A'})"
                for d in self.devices
            ]
            lines.append(f"{C_RED}{BOLD}GPUs:{RESET} " + " │ ".join(gpu_strs[:2]))

        # Motherboard & Slots
        slot_strs = [
            f"{sl.designation}({sl.bus_width}):{C_GREEN if 'In Use' in sl.status else C_MUTED}{sl.status}{RESET}"
            for sl in s.motherboard.slots
        ]
        lines.append(
            f"{C_GREEN}{BOLD}MOBO & BIOS:{RESET} {s.motherboard.manufacturer} {BOLD}{s.motherboard.product}{RESET} ({s.motherboard.version}) • "
            f"BIOS {s.motherboard.bios_version} ({s.motherboard.bios_date}) • {s.motherboard.boot_mode} (SecureBoot: {s.motherboard.secure_boot})"
        )
        if slot_strs:
            lines.append(f"{C_GREEN}{BOLD}PCIe/M.2:{RESET} " + " │ ".join(slot_strs))

        # Storage Drives
        drv_strs = [f"{d.model} ({d.bus_type} {d.capacity_gb:.0f}GB FW:{d.firmware or '--'})" for d in s.storage_drives]
        if drv_strs:
            lines.append(f"{C_BLUE}{BOLD}DRIVES:{RESET} " + " │ ".join(drv_strs))

        return draw_box(title, lines[: max(3, max_rows - 2)], width, C_BORDER)

    def run_once(self):
        """Polls local hardware once and prints a single rendered TUI frame to stdout."""
        sys.stdout.reconfigure(encoding="utf-8")
        self._enable_windows_vt_mode()
        self._poll_local()
        term_size = shutil.get_terminal_size((136, 38))
        cols = max(136, term_size.columns)
        rows = max(38, term_size.lines)
        frame = self._render_frame(cols, rows)
        # Strip CURSOR_HOME for clean stdout dump
        if frame.startswith(CURSOR_HOME):
            frame = frame[len(CURSOR_HOME):]
        sys.stdout.write(frame + RESET + "\n")
        sys.stdout.flush()
        self.nvml.shutdown()
        self.adl.shutdown()
        self.dxgi.shutdown()
        self.drm.shutdown()

    def run(self):
        sys.stdout.reconfigure(encoding="utf-8")
        self._enable_windows_vt_mode()
        self.net_manager.start()

        old_term_settings = None
        if sys.platform != "win32" and sys.stdin.isatty():
            try:
                import termios
                import tty
                old_term_settings = termios.tcgetattr(sys.stdin.fileno())
                tty.setcbreak(sys.stdin.fileno())
            except Exception:
                old_term_settings = None

        sys.stdout.write(ALT_SCREEN_ON + CURSOR_HIDE + CLEAR_SCREEN)
        sys.stdout.flush()

        try:
            last_poll = 0.0
            while self.running:
                now = time.perf_counter()
                if not self.paused and (now - last_poll >= self.interval_ms / 1000.0):
                    self._poll_local()
                    last_poll = now

                term_size = shutil.get_terminal_size((120, 38))
                frame = self._render_frame(term_size.columns, term_size.lines)
                sys.stdout.write(frame)
                sys.stdout.flush()

                # Sleep in short slices for instant keyboard response
                deadline = time.perf_counter() + 0.15
                while time.perf_counter() < deadline and self.running:
                    key = self._read_key_nonblocking()
                    if key:
                        self._handle_key(key)
                        break
                    time.sleep(0.03)
        except KeyboardInterrupt:
            pass
        finally:
            if old_term_settings is not None:
                try:
                    import termios
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term_settings)
                except Exception:
                    pass
            sys.stdout.write(CURSOR_SHOW + ALT_SCREEN_OFF + RESET + "\n")
            sys.stdout.flush()
            self.net_manager.stop()
            self.nvml.shutdown()
            self.adl.shutdown()
            self.dxgi.shutdown()
            self.drm.shutdown()


def run_tui():
    if "--help" in sys.argv or "-h" in sys.argv:
        from core.updater import print_help
        print_help("gpu-sentry-tui")
        return

    if "--version" in sys.argv or "-v" in sys.argv:
        from core.updater import get_version_string
        print(get_version_string())
        return

    if "--update" in sys.argv or "-u" in sys.argv or "update" in sys.argv[1:]:
        from core.updater import run_self_update
        sys.exit(run_self_update())

    interval = 1000
    for idx, arg in enumerate(sys.argv):
        if arg == "--interval" and idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            interval = int(sys.argv[idx + 1])
    app = BpytopTuiApp(interval_ms=interval)
    if "--no-tailscale" in sys.argv:
        app.net_manager.set_tailscale_enabled(False)
    elif "--tailscale" in sys.argv:
        app.net_manager.set_tailscale_enabled(True)
    if "--specs" in sys.argv:
        app.bottom_mode = "specs"
    if "--once" in sys.argv or "--dump" in sys.argv:
        app.run_once()
    else:
        app.run()
