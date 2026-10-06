# GPU & System Sentry ⚡

A high-performance, lightweight, modern Windows desktop telemetry dashboard providing near real-time telemetry for **CPU, System RAM, and all GPUs** simultaneously in one unified interface.

Built specifically for multi-GPU setups (e.g., dual NVIDIA GeForce RTX + AMD Radeon Graphics / APU / Intel Arc) alongside AMD Ryzen / Intel Core processors.

---

## ✨ Key Features

- **💻 CPU Telemetry**:
  - Processor model detection (e.g. `AMD Ryzen 7 7700 8-Core Processor`).
  - Core & thread specification (`8 Cores • 16 Threads`).
  - Real-time overall CPU Core Load percentage with radial arc gauge.
  - Core Clock frequency (MHz / GHz).
  - CPU Package Temperature (°C) with dynamic thermal safety status.
  - CPU Power consumption in Watts.
  - Expandable **Logical Cores Breakdown**: live bar graph for every thread (`T00` through `T15+`).
- **🧠 System RAM (Memory) Telemetry**:
  - Live Used / Total System RAM (e.g., `29.6 / 63.1 GB (47%)`).
  - Available / Free system RAM.
  - Pagefile and commit charge tracking (`Used / Total GB`).
- **⚡ Multi-GPU Monitoring in One Dashboard**:
  - Automatically discovers and displays all physical GPUs side by side:
    - **NVIDIA GeForce RTX 4060 Ti**
    - **NVIDIA GeForce RTX 5060 Ti**
    - **AMD Radeon™ Graphics**
    - Support for Intel Arc / UHD adapters via DXGI.
- **🏎️ Ultra-Lightweight & Near Zero CPU Overhead (~0.0% CPU)**:
  - Direct in-process C-level hardware queries using native `nvml.dll`, `atiadlxx.dll`, and Win32 kernel calls via `ctypes`.
  - **No external heavy runtimes** or slow subprocess spawning (like polling `nvidia-smi` in loops).
  - Background queries run in < 1 millisecond on a dedicated asynchronous `QThread`.
- **🌡️ Comprehensive Thermal Telemetry**:
  - Core Temperatures (°C) for CPU and all GPUs.
  - Dynamic thermal safety badges: `COOL` (<55°C), `NORMAL` (55-67°C), `WARM` (68-77°C), `HOT` (78-85°C), `THROTTLE` (≥86°C).
  - Hotspot / Junction / SoC Temperatures.
  - Thermal gradient indicator bars with live needles.
  - Fan Speed (%) & Fan RPM.
- **📊 Real-Time Rolling History Graphs**:
  - Smooth antialiased 60-second rolling sparklines showing both **Core Load (%)** and **Temperature (°C)** simultaneously for CPU and every GPU.
  - Live Peak and Min indicators.
- **💾 VRAM & Power Telemetry**:
  - Dedicated and shared VRAM usage (GB used / Total GB, percentage, free VRAM).
  - Real-time power draw in Watts, power limits (TDP), and percentage.
  - Real-time Core Clock (MHz) and Memory Clock (MHz).
- **📋 Active GPU Workloads Drawer**:
  - Expandable drawer per GPU displaying active compute and graphics processes (e.g. `llama-server.exe`, `whisper-server.exe`, web browsers) with PID.
- **🖥️ Modern Windows Desktop UX**:
  - Windows 11 Fluent dark theme styling with glowing neon accents.
  - **Pin on Top**: Keep the monitor floating above games, benchmarks, or training runs.
  - **Compact Mode**: Collapse sparklines and drawers into an ultra-compact mini widget.
  - **Refresh Rate Control**: Choose between 500 ms, 1.0 s, 2.0 s, or 3.0 s polling intervals.
  - **System Tray Integration**: Minimize to Windows system tray; hover over tray icon to see live temperatures and loads for CPU, RAM, and all GPUs!

---

## 🚀 Quick Start

### 1. Launch with One Click
Double-click `run.bat` in the project root:
```bat
run.bat
```

### 2. Or Launch via Python
Activate your virtual environment or run with Python 3.11+:
```powershell
.\.venv\Scripts\python.exe main.py
```

---

## 🏗️ Architecture

```
gpu_moni/
├── core/
│   ├── gpu_types.py          # Data classes (HostMetrics, CpuMetrics, RamMetrics, GpuDevice, GpuMetrics)
│   ├── host_backend.py       # CPU & RAM telemetry engine (load, per-core, thermals, power, RAM)
│   ├── nvml_backend.py       # Direct C ctypes wrapper for NVIDIA nvml.dll
│   ├── adl_backend.py        # Direct C ctypes wrapper for AMD atiadlxx.dll / ADL2 PMLog
│   ├── dxgi_backend.py       # DXGI adapter enumerator & PDH memory counters
│   └── monitor_worker.py     # Asynchronous QThread background telemetry engine
├── ui/
│   ├── theme.py              # Dark cyberpunk / Windows 11 Fluent QSS & palette
│   ├── widgets/
│   │   ├── cpu_ram_card.py   # Dedicated CPU & RAM card with core breakdown
│   │   ├── gpu_card.py       # Responsive individual GPU telemetry card
│   │   ├── arc_gauge.py      # Antialiased radial circular gauge for load %
│   │   ├── sparkline.py      # 60-second real-time dual-metric sparkline chart
│   │   └── thermal_bar.py    # Gradient thermal bar & status badge
│   └── main_window.py        # Main window with summary ribbon, controls, tray
├── main.py                   # Desktop application entry point
├── run.bat                   # Instant Windows launcher
└── requirements.txt          # Minimal dependencies (PyQt6, psutil)
```
