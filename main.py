"""
GPU Sentry - High-Performance Real-Time Multi-GPU Telemetry Dashboard.
Lightweight native Windows desktop application.
"""

import os
import sys
import ctypes
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from ui.main_window import MainWindow


def set_windows_app_id():
    """Sets the Windows Application User Model ID for taskbar grouping and icon."""
    if sys.platform == "win32":
        try:
            app_id = "antigravity.gpusentry.monitor.1.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass


def main():
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
