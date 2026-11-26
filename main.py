"""
GPU Sentry - High-Performance Real-Time Multi-GPU Telemetry Dashboard.
Lightweight native Windows & Linux desktop application + LAN Telemetry Agent.
"""

import os
import sys
import time
import ctypes

from core.version import APP_NAME, APP_VERSION, WINDOWS_APP_ID


def get_resource_path(relative_path: str) -> str:
    """Resolves bundled asset paths for both source and PyInstaller frozen builds."""
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, relative_path)


def detach_unwanted_console():
    """
    On Windows GUI launches, prevents an empty background terminal window from
    staying open when launched via a CUI shim or double-clicked python.exe.
    Preserves the console if launched interactively from an existing shell
    (GetConsoleProcessList > 1).
    """
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        console_hwnd = kernel32.GetConsoleWindow()
        if console_hwnd:
            pids = (ctypes.c_uint32 * 4)()
            count = kernel32.GetConsoleProcessList(pids, 4)
            if count <= 1:
                user32.ShowWindow(console_hwnd, 0)  # SW_HIDE
                kernel32.FreeConsole()
                devnull = open(os.devnull, "w", encoding="utf-8")
                sys.stdout = devnull
                sys.stderr = devnull
    except Exception:
        pass

    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass


def set_windows_app_id():
    """Sets the Windows Application User Model ID for taskbar grouping and icon."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
        except Exception:
            pass


def run_headless_agent():
    """Runs GPU Sentry as a headless LAN telemetry agent (no GUI/PyQt6 required)."""
    from core.network_telemetry import LocalTelemetryServer, DEFAULT_HTTP_PORT, get_local_lan_ips
    from core.nvml_backend import NvmlBackend
    from core.adl_backend import AdlBackend
    from core.dxgi_backend import DxgiBackend
    from core.drm_backend import LinuxDrmBackend
    from core.host_backend import HostBackend
    from core.hardware_info import HardwareInfoCollector
    from core.gpu_types import GpuDevice, GpuMetrics

    port = DEFAULT_HTTP_PORT
    for idx, arg in enumerate(sys.argv):
        if arg == "--port" and idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            port = int(sys.argv[idx + 1])

    os_specs = HardwareInfoCollector.collect_os_specs()
    server = LocalTelemetryServer(port=port)
    if not server.start():
        print(f"[ERROR] Failed to start GPU Sentry Agent on port {port}.")
        sys.exit(1)

    nvml = NvmlBackend()
    adl = AdlBackend()
    dxgi = DxgiBackend()
    drm = LinuxDrmBackend(nvml_available=nvml.available)
    host = HostBackend(adl_backend=adl)

    devices: list[GpuDevice] = []
    if nvml.available:
        for d in nvml.get_devices():
            dx = dxgi.get_adapter_info("NVIDIA", d.name)
            if dx:
                d.luid = dx["luid_key"]
                if d.vram_total_mb <= 0:
                    d.vram_total_mb = dx["dedicated_vram_mb"]
            devices.append(d)
    if adl.available:
        for d in adl.get_devices():
            dx = dxgi.get_adapter_info("AMD", d.name)
            if dx:
                d.luid = dx["luid_key"]
                d.vram_total_mb = dx["dedicated_vram_mb"]
            devices.append(d)
    if drm.available:
        for d in drm.get_devices(start_index=len(devices)):
            devices.append(d)

    ips = get_local_lan_ips()
    ip_str = ips[0] if ips else "0.0.0.0"
    print(f"[GPU Sentry Agent] Broadcasting {len(devices)} GPU(s) on http://{ip_str}:{server.port}/api/telemetry (UDP Discovery :51921)")

    try:
        while True:
            metrics_by_id = {}
            pdh_mems = dxgi.sample_memory_by_luid()
            for dev in devices:
                if dev.vendor == "NVIDIA" and nvml.available and dev.device_id.startswith("nvidia_"):
                    m = nvml.sample_metrics(dev.index)
                elif dev.vendor == "AMD" and adl.available and dev.device_id.startswith("amd_"):
                    m = adl.sample_metrics(dev.index)
                    if dev.luid in pdh_mems:
                        m.vram_used_mb = pdh_mems[dev.luid]
                    m.vram_total_mb = dev.vram_total_mb
                elif dev.device_id.startswith("drm_") and drm.available:
                    m = drm.sample_metrics(dev.device_id)
                else:
                    m = GpuMetrics(vram_total_mb=dev.vram_total_mb)
                metrics_by_id[dev.device_id] = m
            host_m = host.sample_metrics()
            server.update_snapshot(devices, metrics_by_id, host_m, os_name=os_specs.os_name)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[GPU Sentry Agent] Shutting down...")
    finally:
        server.stop()
        nvml.shutdown()
        adl.shutdown()
        dxgi.shutdown()
        drm.shutdown()


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        from core.updater import print_help
        print_help("gpu-sentry")
        return

    if "--version" in sys.argv or "-v" in sys.argv or "-V" in sys.argv:
        from core.updater import get_version_string
        print(get_version_string())
        return

    if "--update" in sys.argv or "-u" in sys.argv or "update" in sys.argv[1:]:
        from core.updater import run_self_update
        sys.exit(run_self_update())

    if any(flag in sys.argv for flag in ("--tui", "-t", "--once", "--dump")):
        from ui.tui_dashboard import run_tui
        run_tui()
        return

    if "--agent" in sys.argv:
        run_headless_agent()
        return

    # Command line argument handling for shortcuts and autostart
    if "--install-shortcut" in sys.argv:
        from core.shortcut import install_start_menu_shortcut
        desktop = "--desktop" in sys.argv
        ok, msg = install_start_menu_shortcut(desktop=desktop)
        print(f"[{'OK' if ok else 'ERROR'}] {msg}")
        return

    if "--remove-shortcut" in sys.argv:
        from core.shortcut import remove_start_menu_shortcut
        ok = remove_start_menu_shortcut(desktop=True)
        print("[OK] Shortcuts removed." if ok else "[ERROR] Failed to remove shortcuts.")
        return

    if "--autostart" in sys.argv:
        from core.shortcut import set_autostart
        ok, msg = set_autostart(True)
        print(f"[{'OK' if ok else 'ERROR'}] {msg}")
        return

    if "--no-autostart" in sys.argv:
        from core.shortcut import set_autostart
        ok, msg = set_autostart(False)
        print(f"[{'OK' if ok else 'ERROR'}] {msg}")
        return

    # On headless Linux / Ubuntu SSH sessions without X11 or Wayland display, automatically launch TUI
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        from ui.tui_dashboard import run_tui
        run_tui()
        return

    # GUI mode: detach any auto-spawned console window before launching Qt
    detach_unwanted_console()

    # Clean up leftover .old binary from a previous frozen self-update
    if getattr(sys, "frozen", False):
        try:
            old_bin = os.path.abspath(sys.executable) + ".old"
            if os.path.isfile(old_bin):
                os.remove(old_bin)
        except Exception:
            pass

    # Load user settings early so UI scale can be applied before QApplication init
    from core.settings import get_settings
    app_settings = get_settings()
    scale_pct = int(app_settings.data.ui_scale_percent or 100)
    if scale_pct != 100 and "QT_SCALE_FACTOR" not in os.environ:
        clamped = max(75, min(200, scale_pct))
        os.environ["QT_SCALE_FACTOR"] = f"{clamped / 100.0:.2f}"

    # Auto-create or refresh Windows Start Menu & Autostart entries (console-free launcher)
    if sys.platform == "win32":
        try:
            from core.shortcut import (
                is_start_menu_shortcut_installed,
                install_start_menu_shortcut,
                refresh_autostart_if_enabled,
            )
            if not is_start_menu_shortcut_installed():
                install_start_menu_shortcut(desktop=False)
            refresh_autostart_if_enabled(start_minimized=app_settings.data.autostart_minimized)
        except Exception:
            pass

    # Set Windows process metadata
    set_windows_app_id()

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from ui.main_window import MainWindow

    # Enable High DPI scaling
    if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, "PassThrough"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Antigravity")
    app.setQuitOnLastWindowClosed(False)

    # Global application icon
    icon_path = get_resource_path(os.path.join("assets", "gpu_sentry.ico"))
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    start_condensed = True if "--condensed" in sys.argv else (False if "--expanded" in sys.argv else None)
    window = MainWindow(start_condensed=start_condensed)

    if "--no-tailscale" in sys.argv:
        window.net_manager.set_tailscale_enabled(False)
    elif "--tailscale" in sys.argv:
        window.net_manager.set_tailscale_enabled(True)

    start_minimized = ("--minimized" in sys.argv) or bool(app_settings.data.start_minimized)

    if start_minimized:
        window.hide()
    else:
        if app_settings.data.remember_window_geometry and app_settings.data.window_maximized:
            window.showMaximized()
        else:
            window.show()
            window.raise_()
            window.activateWindow()

    if window.taskbar_widget.isVisible():
        if sys.platform == "win32":
            try:
                tw_hwnd = int(window.taskbar_widget.winId())
                ctypes.windll.user32.ShowWindow(tw_hwnd, 4)  # SW_SHOWNOACTIVATE
            except Exception:
                pass
        if app_settings.data.taskbar_x is None or app_settings.data.taskbar_y is None:
            window.taskbar_widget.dock_to_clock()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
