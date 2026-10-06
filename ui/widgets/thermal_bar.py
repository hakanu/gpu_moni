"""
Custom thermal readout and gradient bar widget.
Displays core temperature, status badge, hotspot temperature, and fan telemetry.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QLinearGradient, QColor, QFont, QPen

from ui.theme import Theme


class ThermalBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.temp_c: float = 0.0
        self.hotspot_c: float = 0.0
        self.fan_pct: float = 0.0
        self.fan_rpm: int = 0

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Top row: Temp Label + Status Badge
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.lbl_temp = QLabel("0°C")
        self.lbl_temp.setStyleSheet("font-size: 22px; font-weight: bold; color: #f0f6fc;")

        self.lbl_status = QLabel("COOL")
        self.lbl_status.setStyleSheet(
            f"background-color: #00e67622; color: {Theme.TEMP_COOL}; "
            "border: 1px solid #00e67655; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold;"
        )

        top_row.addWidget(self.lbl_temp)
        top_row.addWidget(self.lbl_status)
        top_row.addStretch()

        self.lbl_fan = QLabel("Fan: --")
        self.lbl_fan.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px;")
        top_row.addWidget(self.lbl_fan)

        layout.addLayout(top_row)

        # Thermal gradient bar Canvas
        self.bar_canvas = _ThermalCanvas(self)
        self.bar_canvas.setFixedHeight(10)
        layout.addWidget(self.bar_canvas)

        # Bottom row: Hotspot / Secondary
        bot_row = QHBoxLayout()
        self.lbl_hotspot = QLabel("Hotspot: --")
        self.lbl_hotspot.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px;")
        bot_row.addWidget(self.lbl_hotspot)
        bot_row.addStretch()
        layout.addLayout(bot_row)

    def set_thermal_data(self, temp_c: float, hotspot_c: float = None, fan_pct: float = None, fan_rpm: int = None):
        self.temp_c = temp_c
        color_hex = Theme.get_temp_color(temp_c)
        status_text = Theme.get_temp_status(temp_c)

        self.lbl_temp.setText(f"{int(round(temp_c))}°C")
        self.lbl_temp.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color_hex};")

        self.lbl_status.setText(status_text)
        self.lbl_status.setStyleSheet(
            f"background-color: {color_hex}22; color: {color_hex}; "
            f"border: 1px solid {color_hex}55; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: bold;"
        )

        # Fan
        if fan_pct is not None and fan_pct >= 0:
            if fan_rpm and fan_rpm > 0:
                self.lbl_fan.setText(f"Fan: {int(fan_pct)}% ({fan_rpm} RPM)")
            else:
                self.lbl_fan.setText(f"Fan: {int(fan_pct)}%")
        else:
            self.lbl_fan.setText("Fan: N/A")

        # Hotspot
        if hotspot_c is not None and hotspot_c > 0:
            self.lbl_hotspot.setText(f"Hotspot / Extra: {int(round(hotspot_c))}°C")
        else:
            self.lbl_hotspot.setText("Hotspot: Normal")

        self.bar_canvas.set_temp(temp_c)


class _ThermalCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.temp_c: float = 0.0

    def set_temp(self, temp: float):
        self.temp_c = max(0.0, min(100.0, temp))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())

        # Track background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Theme.BG_SUBTLE))
        painter.drawRoundedRect(QRectF(0, 0, w, h), h / 2.0, h / 2.0)

        # Gradient bar
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(Theme.TEMP_COOL))
        grad.setColorAt(0.55, QColor(Theme.TEMP_OPTIMAL))
        grad.setColorAt(0.72, QColor(Theme.TEMP_WARM))
        grad.setColorAt(0.85, QColor(Theme.TEMP_HOT))
        grad.setColorAt(1.0, QColor(Theme.TEMP_CRITICAL))

        # Fill up to current temp
        fill_w = w * (self.temp_c / 100.0)
        if fill_w > 0:
            painter.setBrush(grad)
            painter.drawRoundedRect(QRectF(0, 0, max(fill_w, h), h), h / 2.0, h / 2.0)

        # Needle/indicator dot at current position
        if fill_w > 4:
            painter.setPen(QPen(QColor("#ffffff"), 1.5))
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(QRectF(fill_w - 4, 1, 8, h - 2))
