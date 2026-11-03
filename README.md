# GPU & System Sentry ⚡

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Ubuntu%20%7C%20Linux-brightgreen.svg)]()
[![Installed with uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![CI](https://github.com/hakanu/gpu_moni/actions/workflows/ci.yml/badge.svg)](https://github.com/hakanu/gpu_moni/actions/workflows/ci.yml)

A high-performance, lightweight, modern cross-platform (**Windows, Ubuntu & Linux**) desktop and terminal telemetry & hardware inspection dashboard providing near real-time telemetry for **CPU, System RAM, Local GPUs (NVIDIA, AMD `amdgpu`, Intel), Remote Network GPUs, and Deep SMBIOS/Hardware Specifications** in one unified interface.

Built specifically for multi-GPU workstations, Ubuntu AI/ROCm servers, and LAN/Tailnet clusters (e.g., AMD Radeon RX 7000/9000 + Ryzen APUs + NVIDIA GeForce RTX + Intel Arc + remote Linux/Windows GPU nodes) alongside AMD Ryzen / Intel Core processors.

![GPU & System Sentry Dashboard Preview](assets/screenshot.png)

---

## 📑 Table of Contents

- [✨ Key Features](#-key-features)
- [📦 Install & Update with `uv` (Git Repository)](#-install--update-with-uv-git-repository)
- [🚀 Quick Start](#-quick-start)
  - [🐧 Ubuntu & Linux Setup (AMD Radeon / NVIDIA / Intel)](#-ubuntu--linux-setup-amd-radeon--nvidia--intel)
  - [🪟 Windows Setup](#-windows-setup)
- [🔴 Native AMD GPU Support on Ubuntu (`amdgpu` + TUI)](#-native-amd-gpu-support-on-ubuntu-amdgpu--tui)
- [🌐 Network & Tailscale Tailnet GPU Monitoring](#-network--tailscale-tailnet-gpu-monitoring)
- [🧬 Deep Hardware & SMBIOS Specifications](#-deep-hardware--smbios-specifications)
- [⌨️ Command Line Usage & `bpytop` TUI](#️-command-line-usage)
- [💡 Tips & Desktop Integration](#-tips--desktop-integration)
  - [Windows Taskbar Widget](#-windows-taskbar-widget)
  - [Windows Start Menu & Autostart](#-windows-start-menu--autostart)
  - [Linux Wayland & System Tray](#-linux-wayland--system-tray)
- [🏗️ Architecture](#-architecture)
- [🛠️ Development & Packaging](#️-development--packaging)
- [📄 License](#-license)

---

## ✨ Key Features

- **💻 CPU Telemetry & Microarchitecture**:
  - Processor model, vendor, family/stepping, and socket (`Socket AM5`, `FP8`, `LGA1700`, etc.).
  - Core & thread topology (`8 Physical Cores • 16 Logical Threads`), L1/L2/L3 cache hierarchy, and supported ISA extensions (`AVX-512`, `AVX2`, `SSE4.2`, Virtualization).
  - Real-time overall CPU Core Load percentage with radial arc gauge and Unicode Braille sparklines.
  - Live Core Clock frequency (MHz / GHz) alongside Base Clock, Max Boost Clock, and Bus/BCLK frequency.
  - CPU Package Temperature (°C) with dynamic thermal safety status (via kernel `hwmon` / `k10temp` / `zenpower` / `coretemp` on Linux, ADL/LHM on Windows) and CPU Power consumption in Watts (RAPL / `hwmon`).
  - Expandable **Logical Cores Breakdown**: live bar graph for every thread (`T00` through `T15+`).
- **🧠 System RAM (Memory) Telemetry & Channel Architecture**:
  - Live Used / Total System RAM (e.g., `29.6 / 64.0 GB (46%)`), Available RAM, and Pagefile / Swap usage.
  - Deep SMBIOS Type 16 & Type 17 inspection (works **without root** on Ubuntu via `/run/udev/data/+dmi:id`): **Channel Architecture** (`Dual Channel (1 DPC • 2 DIMMs)`), **Memory Type & Form Factor** (`DDR5 DIMM` / `SODIMM`), **Active Configured Speed** (`5600 MT/s`) + **Real DRAM Clock** (`2800 MHz`), **JEDEC Base Speed** (`4800 MT/s`), **XMP / EXPO Rated Profile** (`6000 MT/s CL30`), **Operating Voltage** (`1.10 V`), and **Per-Slot Physical DIMM Breakdown Table**.
- **🔴 First-Class Native AMD (`amdgpu`), NVIDIA (`NVML`) & Intel (`i915`/`xe`) GPU Monitoring**:
  - Automatically discovers and displays all physical GPUs side by side with exact marketing model names (`AMD Radeon RX 7900 XTX`, `AMD Radeon 780M Graphics`, `NVIDIA GeForce RTX 4090`), architecture (`RDNA 3`, `RDNA 3.5`, `Ada Lovelace`, `Blackwell`), VBIOS version, and current vs. max PCIe link speed (`Gen 4 x16`).
  - **Zero-dependency Linux `amdgpu` DRM + `hwmon` backend**: reads dedicated VRAM & shared GTT memory, Edge / Junction (Hotspot) / VRAM Memory temperatures, board wattage & PPT power cap, Fan RPM & PWM %, GFX / Memory / SoC DPM clocks, and active ROCm Compute (`/dev/kfd`) & Graphics (`/dev/dri`) processes via `/proc/<pid>/fdinfo`.
- **⚡ Multi-View Desktop GUI (Full Cards, Compact & Very Condensed View)**:
  - **⚡ Very Condensed View of Everything (`⚡ Condensed` button / `--condensed`)**: Packs **Host CPU & RAM**, **All Local GPUs**, **All Tailscale/Network GPUs**, **Active GPU Processes**, and **Hardware Specs Summary** into a single ultra-dense, zero-scroll window (`CondensedDashboardWidget`).
  - **🦊 1-Click Tailscale ON / OFF Controls (`🦊 Tailscale: ON/OFF` & `--no-tailscale`)**: Turn Tailscale-based GPU discovery and polling completely ON or OFF at any time from the top navigation bar, the Condensed view, the Network GPUs card, the System Tray menu, or by pressing `t` in `gpu-sentry-tui`. Individual remote nodes can also be toggled `ON` or `OFF` independently.
- **🌐 Tailscale Tailnet & LAN GPU Monitoring (VRAM, Thermals & Wattage)**:
  - **Automatic Tailscale Tailnet GPU Discovery**: Scans `tailscale status --json` and probes online Linux & Windows Tailnet peers over Tailscale SSH / agent ports to automatically discover every machine equipped with an NVIDIA (`nvidia-smi`), AMD (`amdgpu` DRM/`hwmon`), or Intel (`i915`/`xe` DRM/`hwmon`) GPU.
  - **Dedicated Tailnet VRAM, Multi-Sensor Thermals & Wattage Tracking**:
    - **VRAM Usage**: Real-time dedicated VRAM used vs. total GB, utilization percentage, and color-coded memory pressure bar (e.g., `VRAM ■■■■■■ 23.0 / 24.0 GB (96%)`), plus aggregated **Tailnet-wide VRAM usage** in the section header.
    - **Multi-Sensor GPU Thermals**: Displays **Core/Edge (°C)**, **Hotspot/Junction (°C)** (`temp2_input`), **VRAM Memory (°C)** (`temp3_input`), **Fan Speed (RPM & %)**, and dynamic thermal safety badges (`COOL` / `NORMAL` / `WARM` / `HOT` / `THROTTLE`).
    - **Wattage & Power Limits**: Live GPU power draw vs. board TDP limit (`🔥 327.0W/327W`), plus aggregated **Total Tailnet GPU Wattage** and **Peak Tailnet GPU Temperature** in the header.
  - **Zero-Config LAN Auto-Discovery & LibreHardwareMonitor (`:8085`)**: Automatically finds other PCs/servers running GPU Sentry (`gpu-sentry --agent`) on your subnet (`:51920` / `:51921`) or LibreHardwareMonitor web servers (`:8085`).
- **🖥️ `bpytop`-Inspired Terminal UI (`gpu-sentry-tui` / `gpu-sentry --tui`)**:
  - Pure-terminal 24-bit TrueColor ANSI dashboard with Unicode Braille sparklines (`⣀⣄⣤⣦⣶⣷⣿`), rounded box-drawing frames, per-core CPU bars, DDR5 channel/MHz badges, local NVIDIA/AMD/Intel GPU boxes, Tailscale Tailnet GPU table, active GPU process inspector, and SMBIOS hardware inspector.
  - Automatic headless fallback: running `gpu-sentry` over SSH on an Ubuntu server without `$DISPLAY` or `$WAYLAND_DISPLAY` automatically launches the interactive TUI.
  - Ultra-low resource footprint: **`~0.05%` CPU**, **`~38 MB` Private RAM** (no `PyQt6` loaded in TUI mode), and **`~5 ms`** local poll latency.

---

## 📦 Install & Update with `uv` (Git Repository)

GPU Sentry is packaged as a standard PEP 621 tool with entry points (`gpu-sentry`, `gpu-sentry-tui`, `gpu-sentry-cli`) so you can install and update it globally in an isolated virtual environment using [uv](https://docs.astral.sh/uv/).

### 1. Install directly from GitHub with `uv`

```bash
# Install (or overwrite) the latest version directly from the Git repository
uv tool install --reinstall --force git+https://github.com/hakanu/gpu_moni.git
```

> [!TIP]
> **Windows Troubleshooting (`Invalid environment at ...\uv\tools\gpu-sentry`)**:
> If a previous `uv` installation on Windows was interrupted while `gpu-sentry.exe` was running (leaving a partial folder without `Scripts\python.exe`), remove the stale folder and reinstall:
> ```powershell
> # PowerShell
> taskkill /F /IM gpu-sentry.exe 2>$null
> Remove-Item -Recurse -Force "$env:APPDATA\uv\tools\gpu-sentry" -ErrorAction SilentlyContinue
> uv tool install --reinstall --force git+https://github.com/hakanu/gpu_moni.git
> ```
> Or in **Command Prompt (`cmd.exe`)**:
> ```cmd
> taskkill /F /IM gpu-sentry.exe
> rmdir /s /q "%APPDATA%\uv\tools\gpu-sentry"
> uv tool install --reinstall --force git+https://github.com/hakanu/gpu_moni.git
> ```

Or install from a local clone:
```bash
git clone https://github.com/hakanu/gpu_moni.git
cd gpu_moni
uv tool install --force .
```

Once installed, the following commands are available globally in your `PATH`:
- `gpu-sentry` — Launches the GUI dashboard (or automatically falls back to TUI on headless Ubuntu/SSH sessions).
- `gpu-sentry-tui` — Launches the `bpytop`-inspired Terminal UI directly (ideal for Ubuntu servers, SSH, tmux, and Radeon/ROCm rigs).
- `gpu-sentry-cli` — CLI alias supporting `--tui`, `--agent`, `--once`, `--update`, etc.

### 2. Update from the Git Repository with `uv`

You can update `gpu-sentry` to the latest commit on `https://github.com/hakanu/gpu_moni.git` at any time using **either** the built-in self-updater flag or `uv` directly:

```bash
# Option A: Built-in self-updater (runs uv tool install --upgrade --reinstall --force git+https://github.com/hakanu/gpu_moni.git)
gpu-sentry --update
# or
gpu-sentry-tui --update

# Option B: Upgrade via uv tool upgrade
uv tool upgrade gpu-sentry

# Option C: Force reinstall latest commit directly from GitHub
uv tool install --upgrade --reinstall --force git+https://github.com/hakanu/gpu_moni.git
```

---

## 🚀 Quick Start

### 🐧 Ubuntu & Linux Setup (AMD Radeon / NVIDIA / Intel)

GPU & System Sentry runs natively on **Ubuntu (20.04 / 22.04 / 24.04 / 26.04 LTS)**, Debian, Fedora, Arch Linux, and openSUSE.
- **TUI & Headless Agent modes (`gpu-sentry-tui`, `gpu-sentry --tui`, `gpu-sentry --agent`)** do **not** require X11/Wayland or GUI libraries and work out of the box on minimal Ubuntu Server and Desktop installations.
- **GUI mode (`gpu-sentry`)** uses Qt6 (Wayland / X11).

#### 1. Install `uv` (if not already installed)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 2. Install GPU Sentry via `uv`
```bash
uv tool install git+https://github.com/hakanu/gpu_moni.git
```

#### 3. Launch in Terminal UI (TUI) Mode (Recommended for Ubuntu / SSH / AMD Rigs)
```bash
# Interactive bpytop-style Terminal UI
gpu-sentry-tui

# Or via flag
gpu-sentry --tui

# Render a single snapshot to stdout and exit (great for scripts/SSH checks)
gpu-sentry-tui --once

# Render a single snapshot with the Deep Hardware Specs panel open
gpu-sentry-tui --once --specs
```

#### 4. Launch Desktop GUI Mode (Optional Qt6 System Libraries)
If you want to run the desktop GUI window (`gpu-sentry` on X11/Wayland), ensure standard Qt6 runtime libraries are present:
- **Ubuntu / Debian / Pop!_OS / Linux Mint**:
  ```bash
  sudo apt update
  sudo apt install -y libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0
  ```
- **Fedora / RHEL**:
  ```bash
  sudo dnf install -y libglvnd-glx libglvnd-egl libxkbcommon-x11 xcb-util-cursor
  ```
- **Arch Linux**:
  ```bash
  sudo pacman -S --needed qt6-base
  ```

#### 5. Instant Launch Scripts (`run_tui.sh` / `run.sh`)
From a cloned repository:
```bash
# Launch the Terminal UI directly (auto-provisions .venv via uv if needed)
./run_tui.sh

# Launch the GUI (or auto-fallback to TUI on headless Linux)
./run.sh
```

---

### 🪟 Windows Setup

#### 1. Direct Install with `uv` (Recommended)
```powershell
# Install directly from GitHub without cloning
uv tool install git+https://github.com/hakanu/gpu_moni.git

# Launch GUI from anywhere
gpu-sentry

# Or launch Terminal UI in Windows Terminal / PowerShell
gpu-sentry-tui
```

> [!TIP]
> **Windows Start Menu**: On first launch, GPU Sentry automatically creates a Windows Start Menu shortcut (`GPU Sentry`) with its custom icon. You can also run `install_shortcut.bat` or `gpu-sentry --install-shortcut` to generate Start Menu and Desktop shortcuts anytime.

#### 2. Instant Launch (`run.bat` / `run_tui.bat`)
Double-click `run.bat` (GUI) or `run_tui.bat` (TUI) in the project root to run without installing.

---

## 🔴 Native AMD GPU Support on Ubuntu (`amdgpu` + TUI)

GPU Sentry includes a dedicated, zero-dependency Linux DRM & `hwmon` backend (`core/drm_backend.py`) engineered specifically for **AMD Radeon Discrete GPUs** (RDNA 4 / RDNA 3 / RDNA 2 / Vega / Polaris), **AMD Ryzen APUs** (Radeon 780M / 890M / 680M / Vega), and **AMD Instinct accelerators** running the standard Ubuntu `amdgpu` kernel driver—no proprietary SDKs or root privileges required:

1. **Exact AMD Marketing Name Resolution**:
   - Reads `product_name` from sysfs, matches `(device_id, revision_id)` against Ubuntu's `/usr/share/libdrm/amdgpu.ids` table, cross-references `lspci`, and falls back to a built-in PCI ID map so cards display their exact retail name (e.g. `AMD Radeon RX 7900 XTX`, `AMD Radeon 780M Graphics`).
2. **Multi-Sensor Thermal Telemetry (`hwmon`)**:
   - **Edge Temperature (`temp1_input`)**: Primary GPU die temperature with dynamic thermal status badge (`COOL`, `NORM`, `WARM`, `HOT`, `THROT`).
   - **Junction / Hotspot Temperature (`temp2_input`)**: Displayed live in TUI as `Junc:94°C` and factored into thermal safety alerts.
   - **VRAM Memory Temperature (`temp3_input`)**: GDDR6 memory junction temperature displayed as `Mem:69°C`.
   - **Fan Telemetry (`fan1_input` & `pwm1`)**: Live fan speed in both **RPM** and **PWM %** (`🌀1218RPM(29%)`).
3. **VRAM & Dynamic GTT Memory Tracking**:
   - Reads dedicated VRAM (`mem_info_vram_used` / `mem_info_vram_total`) and system-backed **GTT (Graphics Translation Table)** memory (`mem_info_gtt_used`), displaying `(GTT:1.9G)` automatically when APUs or LLM workloads allocate shared host memory.
4. **Power Draw & PPT Cap (`power1_average` / `power1_input` / `power1_cap`)**:
   - Displays real-time GPU socket/board power in Watts alongside the active PPT power limit (`🔥 327.0W/327W`).
5. **DPM Clocks (`pp_dpm_sclk`, `pp_dpm_mclk`, `pp_dpm_socclk`)**:
   - Reads real-time Graphics Shader Clock (`SCLK`), VRAM Memory Clock (`MCLK`), and SoC Clock (`SOCCLK`), plus maximum rated boost clocks.
6. **Per-Process ROCm Compute & Graphics VRAM Tracking**:
   - Scans `/proc/<pid>/fd` and `/proc/<pid>/fdinfo` (`drm-total-vram`, `drm-pdev`, `/dev/kfd` `pasid`) to list active `Compute` (e.g. `llama-server`, `ollama`, `vllm`, `strata-host`, PyTorch) and `Graphics` processes and their exact per-process VRAM footprint without requiring `rocm-smi` or `sudo`.

### Example Ubuntu AMD Radeon TUI Output (`gpu-sentry-tui`)

```text
╭─ ²local gpus (amdgpu) ───────────────────────────────────────────────── 1 GPU ─ VRAM: 23.7/24.0 GB ─ 🔥 327.0W ╮
│🔴GPU0 AMD Radeon RX 7900 XTX       ⣿⣿⣿⣿⣿⣿⣿⣿ ██████████  100% │  56°C[WARM] Junc:94°C Mem:69°C 🌀1218RPM(29%)   │
│     RDNA 3 (Samsung) • PCIe Gen4x16        │ VRAM: ████████  23.7/24.0GB(99%) │ 🔥 327.0W/327W │ Clk: 3080/1249MHz (SoC:1285) │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ ⁴active gpu processes (4/h: specs) ─────────────────────────────────────────────────────── 1 active workloads ╮
│ PID      PROCESS                        GPU    TYPE        VRAM USED │                                         │
│ 2722557  strata-host                    GPU0   Compute    24138.9 MB │                                         │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

---

## 🌐 Network & Tailscale Tailnet GPU Monitoring

Click **`🌐 Network GPUs`** in the top navigation bar (or press `3` / `s` in `gpu-sentry-tui`) to view and manage GPUs across your **Tailscale Tailnet** and **Local Area Network**:

### 1. Automatic Tailscale Tailnet GPU Discovery
- Automatically inspects `tailscale status --json`, identifies online Tailnet peers, and probes each node via `gpu-sentry --agent` (`:51920`), `LibreHardwareMonitor` (`:8085`), or agentless Tailscale SSH.
- Detects **NVIDIA** (`nvidia-smi`), **AMD** (`amdgpu` Linux DRM + `hwmon`), and **Intel** (`i915` / `xe` DRM + `hwmon` / `coretemp`) GPUs across your Tailnet without requiring manual IP configuration.

### 2. Tailnet GPU VRAM, Multi-Sensor Thermals & Wattage
Both the GUI (`Network GPUs` panel & pinned cards) and the TUI (`gpu-sentry-tui`) highlight three core telemetry metrics for every Tailnet GPU:
- **🧠 VRAM Usage & Pressure**:
  - Dedicated VRAM Used vs. Total GB, utilization percentage, and visual memory bar (e.g., `VRAM ■■■■■■ 23.0 / 24.0 GB (96%)` on a remote **AMD Radeon RX 7900 XTX** or **NVIDIA RTX** node).
  - Aggregated **Tailnet Total VRAM** (`Tailnet VRAM: 33.7 / 42.0 GB`) in the section header.
- **🌡️ Multi-Sensor GPU Thermals**:
  - **Edge / Core Temperature (`°C`)** with color-coded safety badge (`COOL`, `NORMAL`, `WARM`, `HOT`, `THROTTLE`).
  - **Hotspot / Junction Temperature (`Junc: 84°C`)** (`temp2_input` on AMD RDNA / NVIDIA Hotspot).
  - **VRAM Memory Temperature (`Mem: 80°C`)** (`temp3_input` on GDDR6/GDDR6X).
  - **Fan Speed (`🌀 1613 RPM` / `%`)** and **Peak Tailnet GPU Temperature** summary in the header.
- **🔥 Wattage & Power Limits**:
  - Real-time GPU board power draw in Watts alongside the configured TDP power limit (`🔥 341.0 / 327 W`).
  - Aggregated **Total Tailnet GPU Wattage** (`🔥 371.1 W`) across all active Tailnet GPUs.

### 3. LAN Auto-Discovery, Agentless SSH & LibreHardwareMonitor
1. **Automatic LAN Discovery (`GPU Sentry` / `gpu-sentry --agent`)**:
   - Every machine running GPU Sentry serves live JSON telemetry on TCP port `51920` (`/api/telemetry`) and responds to UDP LAN discovery broadcasts on port `51921`.
   - For headless Linux/Windows servers without a monitor, run:
     ```bash
     gpu-sentry --agent
     # Or specify a custom port:
     gpu-sentry --agent --port 51920
     ```
2. **Agentless SSH Monitoring (`SSH (nvidia-smi / amdgpu / drm)`)**:
   - Select **`SSH Agentless`** in the Network GPUs card, enter `user@hostname` (or a Tailscale MagicDNS name), and click **`➕ Connect Node`**.
3. **LibreHardwareMonitor / OpenHardwareMonitor Web Server (`:8085`)**:
   - Select **`LibreHardwareMonitor (:8085)`** and enter `host:8085` to poll remote Windows PCs running LibreHardwareMonitor's HTTP server.
4. **Full Dashboard Cards**:
   - Toggle **`📌 Show as Full GPU Cards`** to display remote Tailnet/LAN GPUs directly in the main GUI dashboard with 60-second rolling temperature & utilization sparklines and radial arc gauges.

---

## 🧬 Deep Hardware & SMBIOS Specifications

Click **`🧬 Hardware Specs`** in the top navigation bar (or press `4` / `h` in `gpu-sentry-tui`, or run `gpu-sentry-tui --once --specs`) to inspect low-level machine specifications:

- **🧠 Memory & Channels**: Total installed & max board capacity, Dual/Quad-Channel mode (`1 DPC • 2 DIMMs`), active configured MT/s & real DRAM clock (MHz), JEDEC base clock, XMP/EXPO rated profile decoded from module part numbers, voltage, and a **Per-Slot Physical DIMM Table** (works without root on Ubuntu via `/run/udev/data/+dmi:id`).
- **🎛️ Motherboard, BIOS & Slots**: Board manufacturer, model, revision, serial number, BIOS vendor/version/date, UEFI & Secure Boot state, and SMBIOS Type 9 PCIe & M.2 slot map (`In Use` vs `Available`).
- **💻 Processor (CPU)**: Full model name, stepping identifier, socket, Base / Boost / BCLK clocks, core VID, L1/L2/L3 cache sizes, virtualization status, and ISA feature flags.
- **⚡ GPU Deep Specs**: Architecture codename, compute units / CUDA core counts, dedicated VRAM, TDP power limits, current vs. max PCIe generation/width, max boost clocks, driver version, VBIOS version, and hardware UUID.
- **💽 NVMe / SATA Storage & OS**: Physical disk models, NVMe/SATA bus interface, capacity, firmware revision, serial numbers, partition usage, OS build, and kernel uptime.
- **📋 Copy Hardware Report**: Copies a formatted Markdown report of all system specifications to your clipboard in one click.

---

## ⌨️ Command Line Usage

| Command | Description |
|---|---|
| `gpu-sentry` | Launches the full GUI dashboard (auto-falls back to TUI on headless Linux/SSH) |
| `gpu-sentry --condensed` | Launches the GUI directly in **⚡ Very Condensed View of Everything** mode |
| `gpu-sentry --no-tailscale` | Starts GUI or TUI with Tailscale-based GPU discovery & polling turned **OFF** |
| `gpu-sentry --tailscale` | Starts GUI or TUI with Tailscale-based GPU discovery & polling turned **ON** |
| `gpu-sentry-tui` / `gpu-sentry --tui` | Launches the **`bpytop`-inspired Terminal UI (TUI)** directly in your terminal |
| `gpu-sentry-tui --once` | Renders one TUI telemetry snapshot to stdout and exits |
| `gpu-sentry-tui --once --specs` | Renders one TUI snapshot with the **Deep Hardware & SMBIOS Specs** panel open |
| `gpu-sentry --update` / `gpu-sentry-tui -u` | Self-updates `gpu-sentry` via `uv` from `git+https://github.com/hakanu/gpu_moni.git` |
| `gpu-sentry --version` / `-v` | Displays current package version and git revision |
| `gpu-sentry --help` / `-h` | Shows CLI usage and options |
| `./run_tui.sh` / `run_tui.bat` | Launches the `bpytop`-inspired TUI on Linux or Windows in one click |
| `gpu-sentry --minimized` | Starts GUI silently in background (Taskbar widget & system tray only) |
| `gpu-sentry --agent` | Runs as a headless LAN telemetry agent (`HTTP :51920` + `UDP :51921`, no GUI required) |
| `gpu-sentry --agent --port 51925` | Runs headless LAN telemetry agent on a custom TCP port |
| `gpu-sentry --install-shortcut` | Creates Windows Start Menu shortcut (`GPU Sentry`) or Linux `.desktop` entry |
| `gpu-sentry --install-shortcut --desktop` | Creates both Start Menu / App Launcher and Desktop shortcuts |
| `gpu-sentry --remove-shortcut` | Removes desktop & Start Menu shortcuts |
| `gpu-sentry --autostart` | Enables launching automatically on Windows/Linux system login |
| `gpu-sentry --no-autostart` | Disables system login autostart |

### 🖥️ `bpytop`-Inspired Terminal UI (TUI)

Prefer a pure terminal monitor over SSH, tmux, Ubuntu Server, or Windows Terminal? Run:
```bash
gpu-sentry-tui
# or:
gpu-sentry --tui
```

```text
╭─ 🌐 Tailnet & LAN GPUs ─ 6/6 Online ─ 6 GPUs ─ Tailnet VRAM: 33.7/42.0GB • 🔥 371.1W • 🌡 Peak 59°C ──────────────╮
│● hakuxtx   AMD Radeon RX 7900 XTX    Load █████ 100% │ VRAM ██████ 23.0/24.0GB(96%) │ 59°C[NORM] Junc:84°C Mem:80°C 🌀1613RPM │ 🔥341.0/327W │
│● gmk       AMD Radeon 780M Graphics  Load ░░░░░   0% │ VRAM ████░░ 10.7/16.0GB(67%) │ 35°C[COOL]                            │ 🔥  4.1W     │
│● mininas   AMD Radeon Barcelo        Load ░░░░░   0% │ VRAM ░░░░░░  0.0/ 2.0GB( 2%) │ 40°C[COOL]                            │ 🔥 26.0W     │
│● leno      Intel UHD Graphics 630    Load ░░░░░   0% │ VRAM ░░░░░░     Shared iGPU  │ 43°C[COOL]                            │ 🔥  --W      │
│● anneleno  Intel UHD Graphics 630    Load ░░░░░   0% │ VRAM ░░░░░░     Shared iGPU  │ 40°C[COOL]                            │ 🔥  --W      │
│● nashaku   Intel Xeon E3-1200 v3 GPU Load ░░░░░   0% │ VRAM ░░░░░░     Shared iGPU  │ 59°C[NORM]                            │ 🔥  --W      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

- **24-bit TrueColor ANSI Gradients & Unicode Braille Sparklines** (`⣀⣄⣤⣦⣶⣷⣿`).
- **Interactive Hotkeys**:
  - `1`: Show/Hide CPU, Per-Core Grid & System RAM (with DDR5 Channel/MHz badges)
  - `2`: Show/Hide Local GPUs (NVIDIA `nvml`, AMD `amdgpu`, Intel `i915`/`xe`)
  - `3`: Show/Hide Tailscale Tailnet & LAN GPUs
  - `4` / `h`: Toggle bottom panel between **Active GPU Processes** and **Deep SMBIOS Hardware Specifications**
  - `s` / `t`: Force immediate Tailscale Tailnet & LAN GPU scan
  - `+` / `-`: Increase / decrease refresh rate (`250ms` – `3000ms`)
  - `p` / `Space`: Pause / Resume telemetry
  - `q` / `Esc`: Quit cleanly
- **Ultra-Low TUI Resource Footprint** (bypasses `PyQt6` completely in `--tui` mode):

| Metric | Measured Value |
|---|---|
| **Average CPU Usage** (`1000 ms` refresh) | **`0.05%`** across logical cores |
| **Private Memory (RAM)** | **`~38.0 MB`** (`~52.2 MB` Working Set / RSS) |
| **Local Poll + Frame Render Latency** | **`~5.4 ms`** per tick (`NVML`/`DRM` + `SMBIOS` + `ANSI` render) |

---

## 💡 Tips & Desktop Integration

### 🪟 Windows Taskbar Widget
- **Dock Next to Clock**: Right-click the taskbar widget and select **`📌 Dock Next to Clock`** to automatically re-center the widget directly adjacent to the Windows notification tray.
- **Drag & Reposition**: Click and drag the widget anywhere on the taskbar or desktop. Right-click and choose **`🔒 Lock Position`** to freeze it in place.
- **Screen & Multi-Monitor Switching (`Win + Left / Right`)**:
  - Stays on top of both primary (`Shell_TrayWnd`) and secondary (`Shell_SecondaryTrayWnd`) taskbars even during Aero Snap (`Win + Left / Right`), Snap Assist, or multi-monitor window movement.
  - Uses `WS_EX_NOACTIVATE` and focus rejection so pressing `Win + Left / Right` always snaps your active application window and never hijacks the widget.
- **Virtual Desktops (`Win + Ctrl + Left / Right`)**:
  - Automatically registered with Windows Virtual Desktop Manager (`IVirtualDesktopPinnedApps`), keeping the widget visible across all virtual desktops.

### 🪟 Windows Start Menu & Autostart
- **Start Menu**: Integrates with Windows via native `IShellLinkW` COM and appears in the Windows Start Menu and Windows Search with its custom icon.
- **Start on Windows Boot**: Right-click the tray icon or taskbar widget and toggle **`🚀 Start on Windows Boot`**.

### 🐧 Linux Wayland & System Tray
- **GNOME Shell System Tray**: On GNOME, install the [AppIndicator and KStatusNotifierItem Support](https://extensions.gnome.org/extension/615/appindicator-support/) GNOME extension so system tray icons appear in the top bar.
- **KDE Plasma & XFCE**: System tray icons and floating tool windows work natively out of the box.

---

## 🏗️ Architecture

```
gpu_moni/
├── assets/
│   ├── gpu_sentry.ico             # High-res Windows application & shortcut icon
│   ├── gpu_sentry.png             # High-res Linux desktop entry icon
│   └── screenshot.png             # Dashboard preview
├── core/
│   ├── gpu_types.py               # Data classes (HostMetrics, CpuMetrics, RamMetrics, GpuDevice, GpuMetrics)
│   ├── drm_backend.py             # Native Linux DRM (amdgpu, radeon, i915, xe) + hwmon + fdinfo GPU backend
│   ├── nvml_backend.py            # Direct C ctypes wrapper for NVIDIA nvml.dll / libnvidia-ml.so
│   ├── adl_backend.py             # Direct C ctypes wrapper for Windows AMD atiadlxx.dll / ADL2 PMLog
│   ├── dxgi_backend.py            # DXGI adapter enumerator & PDH memory counters (Windows)
│   ├── host_backend.py            # Cross-platform CPU & RAM telemetry (hwmon, k10temp, RAPL, psutil, ADL)
│   ├── hardware_info.py           # Native SMBIOS 3.6 parser, udev DMI reader, CPUID & Storage inspector
│   ├── network_telemetry.py       # Tailnet/LAN discovery, HTTP/UDP telemetry server, SSH & LHM client
│   ├── monitor_worker.py          # Asynchronous QThread background telemetry engine (Windows & Linux)
│   ├── updater.py                 # Self-updater via uv tool install from Git repository
│   └── shortcut.py                # Native COM Start Menu shortcut & login autostart manager
├── ui/
│   ├── tui_dashboard.py           # Pure-terminal 24-bit ANSI bpytop-style TUI dashboard
│   ├── theme.py                   # Dark cyberpunk / Fluent modern QSS & palette
│   ├── widgets/
│   │   ├── taskbar_widget.py      # Floating/dockable taskbar telemetry widget next to clock
│   │   ├── cpu_ram_card.py        # Dedicated CPU & RAM card with per-thread breakdown & SMBIOS badges
│   │   ├── gpu_card.py            # Responsive individual GPU telemetry card (local & remote)
│   │   ├── network_nodes_card.py  # LAN & Tailnet GPU thermal monitor & node manager
│   │   ├── hardware_specs_card.py # Deep hardware specifications viewer & Markdown report exporter
│   │   ├── arc_gauge.py           # Antialiased radial circular gauge for load %
│   │   ├── sparkline.py           # 60-second real-time dual-metric rolling sparkline chart
│   │   └── thermal_bar.py         # Gradient thermal bar & status badge
│   └── main_window.py             # Main window with summary ribbon, controls, system tray
├── .github/
│   └── workflows/
│       └── ci.yml                 # Multi-OS automated build & validation workflow
├── pyproject.toml                 # Modern PEP 621 packaging for uv tool install & pip
├── main.py                        # Desktop application, TUI fallback & headless agent entry point
├── run.sh                         # Instant Linux GUI/TUI launcher
├── run_tui.sh                     # Instant Linux TUI launcher (auto-provisions via uv)
├── run.bat                        # Instant Windows GUI launcher (silent pythonw)
├── run_tui.bat                    # Instant Windows TUI launcher
├── install_shortcut.bat           # 1-click Start Menu & Desktop shortcut installer
└── requirements.txt               # Minimal dependencies (PyQt6, psutil)
```

---

## 🛠️ Development & Packaging

Building, installing, and updating with [uv](https://docs.astral.sh/uv/):

```bash
# Clone the repository
git clone https://github.com/hakanu/gpu_moni.git
cd gpu_moni

# Install globally as an isolated uv tool from local checkout
uv tool install --force .

# Or install/upgrade directly from GitHub
uv tool install --upgrade --reinstall git+https://github.com/hakanu/gpu_moni.git

# Or self-update at any time using the built-in updater
gpu-sentry --update

# Run TUI or GUI during development
uv run gpu-sentry-tui
uv run gpu-sentry

# Build source distribution and wheel
uv build
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
