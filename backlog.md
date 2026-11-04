# GPU Sentry (`gpu_moni`) — Project Backlog

## ✅ Completed Work Items

- [x] **Packaging & `uv` Tool Installation/Update Support (`v1.1.0`)**:
  - Added proper `__init__.py` package markers (`core/`, `ui/`, `ui/widgets/`, `assets/`) and updated `pyproject.toml` (`[tool.setuptools.packages.find]`) so wheels include all submodules and assets.
  - Added `core/updater.py` and `--update` / `-u` / `update` CLI flags to both `gpu-sentry` and `gpu-sentry-tui` to self-update directly from `git+https://github.com/hakanu/gpu_moni.git` via `uv tool install --upgrade --reinstall --force`.
  - Added `--version` / `-v`, `--help` / `-h`, `--once` / `--dump`, and `--specs` CLI flags.
  - Added `run_tui.sh` and updated `run.sh` to automatically use `uv` when available.
- [x] **First-Class Native AMD GPU Support on Ubuntu (`core/drm_backend.py`)**:
  - Created zero-dependency `LinuxDrmBackend` (`amdgpu`, `radeon`, `i915`, `xe`) reading `/sys/class/drm/card*`, `hwmon`, `/usr/share/libdrm/amdgpu.ids`, `lspci`, and `/proc/<pid>/fdinfo`.
  - Resolved exact AMD marketing names (`AMD Radeon RX 7900 XTX`, `AMD Radeon 780M Graphics`, etc.), architecture (`RDNA 3`, `RDNA 3.5`, etc.), PCIe link speed/width (current & max), VBIOS, UUID, and max DPM clocks.
  - Added multi-sensor AMD thermal telemetry (Edge `temp1_input`, Hotspot/Junction `temp2_input`, Memory `temp3_input`), Fan RPM (`fan1_input`) + PWM % (`pwm1`), power draw & PPT cap, dedicated VRAM + GTT shared memory, and GFX/MCLK/SoC clocks.
  - Added per-process AMD Compute (`/dev/kfd` + `pasid`) and Graphics (`/dev/dri`) VRAM tracking via `/proc/<pid>/fdinfo` without requiring root or `rocm-smi`.
- [x] **Ubuntu TUI Mode (`ui/tui_dashboard.py`) Enhancements**:
  - Integrated `LinuxDrmBackend` into `BpytopTuiApp` so Ubuntu AMD and Intel GPUs appear natively in the Local GPUs box and Active GPU Processes panel.
  - Added automatic headless fallback in `main.py` so running `gpu-sentry` over SSH without `$DISPLAY`/`$WAYLAND_DISPLAY` launches the TUI automatically and `--agent` runs without requiring `PyQt6`.
  - Added non-root Linux SMBIOS Type 16/17 DIMM inspection via `/run/udev/data/+dmi:id` in `core/hardware_info.py`.
  - Verified on Ubuntu AMD discrete (`hakuxtx` — RX 7900 XTX) and AMD APU (`gmk` — Radeon 780M) systems.
- [x] **GUI Tailscale ON/OFF Controls & Very Condensed View of Everything**:
  - Added master **`🦊 Tailscale: ON / OFF`** toggle button in the top navigation bar (`ui/main_window.py`), `NetworkNodesCard` header (`ui/widgets/network_nodes_card.py`), `CondensedDashboardWidget` (`ui/widgets/condensed_dashboard.py`), System Tray menu, and `t` hotkey in TUI (`ui/tui_dashboard.py`), plus `--no-tailscale` / `--tailscale` CLI flags.
  - Added per-node `ON` / `OFF` enable/disable toggles in `NetworkNodesCard` and `CondensedDashboardWidget`.
  - Created **`CondensedDashboardWidget`** ([ui/widgets/condensed_dashboard.py](file:///mnt/DEV_NAS/CODE/workspace-py/gpu_moni/ui/widgets/condensed_dashboard.py)) and the **`⚡ Condensed`** toggle button (`--condensed`) to show CPU, RAM, Local GPUs, Tailscale GPUs, Active GPU Processes, and Hardware Specs in a single ultra-dense view.
  - Added **`⚡ Condensed Rows`** mode (enabled by default) inside `NetworkNodesCard`.
- [x] **Network Re-Scan Option & Apple Silicon / macOS Discovery (`v1.1.4`)**:
  - Added **`🔄 Re-Scan`** / **`🔄 Re-Scan Network`** button in the GUI navigation bar (`ui/main_window.py`), `CondensedDashboardWidget` (`ui/widgets/condensed_dashboard.py`), and `NetworkNodesCard` (`ui/widgets/network_nodes_card.py`), as well as `r` / `s` hotkey in `ui/tui_dashboard.py`.
  - Clears probed Tailscale cache and triggers an immediate parallel probe of both Tailscale Tailnet and local LAN nodes.
  - Added full macOS & Apple Silicon GPU support (`IOAccelerator` / `Metal`): parses GPU model (e.g. `Apple M4 (10-Core GPU)`), Metal driver version, core count, live `Device Utilization %`, `Renderer Utilization %`, `Tiler Utilization %`, Unified Memory (`sysctl hw.memsize` + `vm_stat`), and non-root die temperatures via `IOHIDEventSystemClient`.
  - Added clean DNS MagicDNS resolution (`DNSName`) so macOS machines with spaces or special characters in `HostName` (e.g. `hakumacmini’s Mac mini` -> `hakumacmini`) connect cleanly over SSH.
  - Added zsh compatibility guard (`setopt NO_NOMATCH`) to the remote SSH probe so zsh on macOS does not abort on Linux sysfs glob patterns.
  - Bumped version to `v1.1.4` and verified `hakumacmini` and `hakux` discovery and telemetry.
- [x] **Documentation (`README.md`)**:
  - Documented `uv` installation and git-based self-update workflows, Ubuntu setup, native AMD `amdgpu` telemetry features, TUI usage, and FAQ for Windows `taskkill` and Tailnet troubleshooting / Re-Scan.

## 📋 Future Enhancements / Backlog

- [ ] Optional AMD GPU overdrive / power cap (`power1_cap`) adjustment controls in TUI/GUI when running with elevated privileges.
- [ ] Optional ROCm SMI / `amd-smi` JSON enrichment when `amd-smi` CLI is installed alongside `amdgpu` sysfs.
- [ ] Export TUI telemetry history to CSV / JSONL log file (`--log <file>`).
