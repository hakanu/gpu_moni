"""
Custom QPainter circular arc gauge widget for GPU core load and memory bus activity.
Features antialiased smooth rendering and glowing gradients.
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QConicalGradient, QBrush

from ui.theme import Theme


class ArcGauge(QWidget):
    def __init__(self, size: int = 140, accent_color: str = Theme.NVIDIA_GREEN, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.value: float = 0.0          # 0 to 100
        self.sub_value: float = 0.0      # Secondary (e.g., memory controller %)
        self.title: str = "CORE LOAD"
        self.accent_color: str = accent_color
        self._target_value: float = 0.0

    def set_value(self, value: float, sub_value: float = 0.0):
        self.value = max(0.0, min(100.0, value))
        self.sub_value = max(0.0, min(100.0, sub_value))
        self.update()

    def set_accent_color(self, color_hex: str):
        self.accent_color = color_hex
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        stroke_width = 10.0
        padding = 12.0

        rect = QRectF(padding, padding, w - 2 * padding, h - 2 * padding)

        # Angles in 1/16ths of a degree
        # Arc sweeps 260 degrees, from 220 deg to -40 deg
        start_angle = 220 * 16
        span_total = -260 * 16

        # 1. Background Track Arc
        bg_pen = QPen(QColor(Theme.BG_SUBTLE), stroke_width)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect, start_angle, span_total)

        # 2. Value Arc
        if self.value > 0.0:
            val_span = int(span_total * (self.value / 100.0))

            # Pick color based on load or accent
            arc_color = QColor(self.accent_color)
            if self.value >= 90:
                arc_color = QColor("#ff5252")  # Red highlight when maxed out
            elif self.value >= 75:
                arc_color = QColor("#ffa726")  # Amber

            # Outer subtle glow pen
            glow_pen = QPen(QColor(arc_color.red(), arc_color.green(), arc_color.blue(), 60), stroke_width + 4)
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow_pen)
            painter.drawArc(rect, start_angle, val_span)

            # Main crisp pen
            val_pen = QPen(arc_color, stroke_width)
            val_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(val_pen)
            painter.drawArc(rect, start_angle, val_span)

        # 3. Text in Center
        cx = w / 2.0
        cy = h / 2.0

        # Percentage Number
        painter.setPen(QColor(Theme.TEXT_PRIMARY))
        font_pct = QFont("Segoe UI", 21, QFont.Weight.Bold)
        painter.setFont(font_pct)
        pct_text = f"{int(round(self.value))}%"
        metrics = painter.fontMetrics()
        tx = cx - metrics.horizontalAdvance(pct_text) / 2.0
        ty = cy + metrics.height() / 4.0 - 4
        painter.drawText(int(tx), int(ty), pct_text)

        # Subtitle ("CORE LOAD")
        font_sub = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font_sub)
        painter.setPen(QColor(Theme.TEXT_SECONDARY))
        sub_metrics = painter.fontMetrics()
        sub_tx = cx - sub_metrics.horizontalAdvance(self.title) / 2.0
        sub_ty = ty + 16
        painter.drawText(int(sub_tx), int(sub_ty), self.title)

        # Bottom secondary metric ("Mem: XX%")
        if self.sub_value > 0:
            font_mem = QFont("Segoe UI", 7, QFont.Weight.Normal)
            painter.setFont(font_mem)
            painter.setPen(QColor(Theme.TEXT_MUTED))
            mem_text = f"Mem Bus {int(round(self.sub_value))}%"
            mem_tx = cx - painter.fontMetrics().horizontalAdvance(mem_text) / 2.0
            painter.drawText(int(mem_tx), h - 4, mem_text)
