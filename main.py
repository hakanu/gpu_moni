"""
GPU Sentry - High-Performance Real-Time Multi-GPU Telemetry Dashboard.
Lightweight native Windows & Linux desktop application + LAN Telemetry Agent.
"""

import os
import sys
import time
import ctypes


def set_windows_app_id():
    """Sets the Windows Application User Model ID for taskbar grouping and icon."""
    if sys.platform == "win32":
        try:
            app_id = "antigravity.gpusentry.monitor.1.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
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

    if "--version" in sys.argv or "-v" in sys.argv:
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

    # Auto-create Windows Start Menu shortcut on first launch
    if sys.platform == "win32":
        try:
            from core.shortcut import is_start_menu_shortcut_installed, install_start_menu_shortcut
            if not is_start_menu_shortcut_installed():
                install_start_menu_shortcut(desktop=False)
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
    app.setApplicationName("GPU Sentry")
    app.setOrganizationName("Antigravity")

    # Global application icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "gpu_sentry.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()

    if "--minimized" in sys.argv:
        window.hide()
    else:
        window.show()
        window.showNormal()
        window.raise_()
        window.activateWindow()
        if sys.platform == "win32":
            try:
                hwnd = int(window.winId())
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL (overrides parent SW_HIDE)
                # Briefly set TOPMOST then NOTOPMOST (unless pinned) to bypass Windows foreground lock
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_SHOWWINDOW = 0x0040
                ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                if not window.always_on_top:
                    ctypes.windll.user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
        if window.taskbar_widget.isVisible():
            if sys.platform == "win32":
                try:
                    tw_hwnd = int(window.taskbar_widget.winId())
                    ctypes.windll.user32.ShowWindow(tw_hwnd, 4)  # SW_SHOWNOACTIVATE
                except Exception:
                    pass
            window.taskbar_widget.dock_to_clock()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
