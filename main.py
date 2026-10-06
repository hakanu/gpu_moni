"""
GPU Sentry - High-Performance Real-Time Multi-GPU Telemetry Dashboard.
Lightweight native Windows desktop application.
"""

import sys
import ctypes
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from ui.main_window import MainWindow


def set_windows_app_id():
    """Sets the Windows Application User Model ID for taskbar grouping and icon."""
    try:
        app_id = "antigravity.gpusentry.monitor.1.0"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def main():
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

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
