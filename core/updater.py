"""
Self-update & version utilities for GPU Sentry using `uv` and Git repository.
"""

import shutil
import subprocess
import sys
from core import __version__

GIT_REPO_URL = "https://github.com/hakanu/gpu_moni.git"
UV_GIT_SPEC = f"git+{GIT_REPO_URL}"


def get_version_string() -> str:
    return f"gpu-sentry v{__version__} ({GIT_REPO_URL})"


def print_help(prog_name: str = "gpu-sentry"):
    help_text = f"""⚡ GPU & System Sentry v{__version__}
High-Performance Real-Time Multi-GPU (NVIDIA, AMD, Intel) & CPU Telemetry Dashboard

Usage:
  {prog_name} [OPTIONS]
  gpu-sentry-tui [OPTIONS]

Modes & Options:
  (default)               Launch GUI dashboard (automatically falls back to TUI on headless Linux/SSH)
  --condensed             Launch GUI in Very Condensed View of Everything mode
  --no-tailscale          Start with Tailscale-based GPU discovery & polling turned OFF
  --tailscale             Start with Tailscale-based GPU discovery & polling turned ON
  --tui, -t               Launch bpytop-inspired 24-bit TrueColor Terminal UI (TUI)
  --once, --dump          Render a single TUI telemetry frame to stdout and exit
  --interval <ms>         Set TUI polling interval in milliseconds (default: 1000)
  --agent                 Run as a headless LAN/Tailnet telemetry agent (HTTP :51920 + UDP :51921)
  --port <port>           Custom HTTP port for --agent mode (default: 51920)
  --minimized             Start GUI minimized to system tray & taskbar widget
  --update, -u, update    Self-update gpu-sentry to latest commit from GitHub via uv
  --version, -v           Show version information and exit
  --help, -h              Show this help message and exit

Desktop Integration:
  --install-shortcut      Create Start Menu / Linux XDG application launcher entry
  --desktop               Also create a Desktop shortcut (use with --install-shortcut)
  --remove-shortcut       Remove Start Menu & Desktop shortcuts
  --autostart             Enable automatic launch on system login
  --no-autostart          Disable automatic launch on system login

Install & Update with uv:
  uv tool install {UV_GIT_SPEC}
  uv tool upgrade gpu-sentry
  uv tool install --upgrade --reinstall {UV_GIT_SPEC}
  gpu-sentry --update
"""
    print(help_text.strip())


def run_self_update() -> int:
    """
    Updates gpu-sentry from its canonical GitHub repository using `uv`.
    """
    uv_bin = shutil.which("uv")
    if not uv_bin:
        print("[ERROR] `uv` was not found in PATH. Install uv from https://docs.astral.sh/uv/")
        print(f"        Then run: uv tool install --upgrade --reinstall {UV_GIT_SPEC}")
        return 1

    print(f"[GPU Sentry] Updating from {UV_GIT_SPEC} via uv...")
    cmd = [uv_bin, "tool", "install", "--upgrade", "--reinstall", "--force", UV_GIT_SPEC]
    try:
        proc = subprocess.run(cmd)
        if proc.returncode == 0:
            print(f"[OK] GPU Sentry successfully updated from {GIT_REPO_URL}!")
            return 0
        # Fallback to `uv tool upgrade gpu-sentry`
        proc2 = subprocess.run([uv_bin, "tool", "upgrade", "gpu-sentry"])
        return proc2.returncode
    except Exception as e:
        print(f"[ERROR] Self-update failed: {e}")
        return 1
