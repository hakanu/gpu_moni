"""
Rolling 60-second real-time sparkline graph widget.
Renders GPU Load (%) and Temperature (°C) curves with antialiasing and gradient area fills.
"""

from collections import deque
from typing import Optional
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath, QLinearGradient, QFont

from ui.theme import Theme


class SparklineChart(QWidget):
    def __init__(self, max_points: int = 60, height: int = 90, accent_color: str = Theme.NVIDIA_GREEN, parent=None):
        super().__init__(parent)
        self.max_points = max_points
        self.accent_color = accent_color
        self.setFixedHeight(height)
        self.setMinimumWidth(220)

        # Ring buffers for history
        self.load_history = deque(maxlen=max_points)
        self.temp_history = deque(maxlen=max_points)

        # Pre-fill with zeros
        for _ in range(max_points):
            self.load_history.append(0.0)
            self.temp_history.append(0.0)

    def push_sample(self, load_pct: float, temp_c: float):
        self.load_history.append(max(0.0, min(100.0, load_pct)))
        self.temp_history.append(max(0.0, min(110.0, temp_c)))
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
        top_margin = 20
        bottom_margin = 14
        left_margin = 8
        right_margin = 8
        plot_h = h - top_margin - bottom_margin
        plot_w = w - left_margin - right_margin

        # 1. Subtle Background & Border Box
        painter.setPen(QColor(Theme.BORDER_DEFAULT))
        painter.setBrush(QColor("#0d1017"))
        painter.drawRoundedRect(left_margin, top_margin, plot_w, plot_h, 4, 4)

        # 2. Horizontal Grid Lines (25%, 50%, 75%)
        grid_pen = QPen(QColor("#1a2233"), 1, Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)
        for pct in [0.25, 0.50, 0.75]:
            gy = top_margin + plot_h * (1.0 - pct)
            painter.drawLine(int(left_margin), int(gy), int(left_margin + plot_w), int(gy))

        pts_count = len(self.load_history)
        if pts_count < 2:
            return

        step_x = plot_w / (self.max_points - 1)

        # Build paths for Load (scale: 0 to 100%)
        load_path = QPainterPath()
        load_area = QPainterPath()
        first_load_pt = None

        # Build paths for Temp (scale: 0 to 100°C)
        temp_path = QPainterPath()
        first_temp_pt = None

        for i in range(pts_count):
            x = left_margin + i * step_x

            # Load
            l_val = self.load_history[i]
            ly = top_margin + plot_h * (1.0 - (l_val / 100.0))
            if i == 0:
                load_path.moveTo(x, ly)
                load_area.moveTo(x, top_margin + plot_h)
                load_area.lineTo(x, ly)
                first_load_pt = QPointF(x, ly)
            else:
                load_path.lineTo(x, ly)
                load_area.lineTo(x, ly)

            # Temp
            t_val = self.temp_history[i]
            ty = top_margin + plot_h * (1.0 - (min(t_val, 100.0) / 100.0))
            if i == 0:
                temp_path.moveTo(x, ty)
                first_temp_pt = QPointF(x, ty)
            else:
                temp_path.lineTo(x, ty)

        # Close load area
        last_x = left_margin + (pts_count - 1) * step_x
        load_area.lineTo(last_x, top_margin + plot_h)
        load_area.closeSubpath()

        # 3. Draw Load Area Gradient
        acc = QColor(self.accent_color)
        grad = QLinearGradient(0, top_margin, 0, top_margin + plot_h)
        grad.setColorAt(0.0, QColor(acc.red(), acc.green(), acc.blue(), 55))
        grad.setColorAt(1.0, QColor(acc.red(), acc.green(), acc.blue(), 0))
        painter.fillPath(load_area, grad)

        # 4. Draw Temp Curve (Warm Amber/Red line)
        temp_color = QColor("#ff9100")
        cur_temp = self.temp_history[-1] if self.temp_history else 0
        if cur_temp >= 80:
            temp_color = QColor("#ff1744")
        temp_pen = QPen(temp_color, 1.8)
        painter.setPen(temp_pen)
        painter.drawPath(temp_path)

        # 5. Draw Load Curve (Accent line)
        load_pen = QPen(acc, 2.0)
        painter.setPen(load_pen)
        painter.drawPath(load_path)

        # 6. Current Point Pulsing Dots at the right edge
        if pts_count > 0:
            cur_l = self.load_history[-1]
            cur_ly = top_margin + plot_h * (1.0 - (cur_l / 100.0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(acc)
            painter.drawEllipse(QPointF(last_x, cur_ly), 3.0, 3.0)

            cur_ty = top_margin + plot_h * (1.0 - (min(cur_temp, 100.0) / 100.0))
            painter.setBrush(temp_color)
            painter.drawEllipse(QPointF(last_x, cur_ty), 2.5, 2.5)

        # 7. Chart Header / Legend Bar
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))

        # Load indicator
        cur_l_text = f"Load: {int(self.load_history[-1])}%"
        max_l_text = f"Peak {int(max(self.load_history))}%"
        painter.setPen(acc)
        painter.drawText(left_margin + 2, top_margin - 6, f"● {cur_l_text} ({max_l_text})")

        # Temp indicator
        cur_t_text = f"Temp: {int(cur_temp)}°C"
        max_t_text = f"Peak {int(max(self.temp_history))}°C"
        painter.setPen(temp_color)
        t_legend = f"● {cur_t_text} ({max_t_text})"
        t_w = painter.fontMetrics().horizontalAdvance(t_legend)
        painter.drawText(int(left_margin + plot_w - t_w - 2), top_margin - 6, t_legend)

        # Bottom axis marker
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Normal))
        painter.setPen(QColor(Theme.TEXT_MUTED))
        painter.drawText(left_margin + 2, h - 2, "-60s")
        painter.drawText(int(left_margin + plot_w / 2 - 8), h - 2, "-30s")
        now_w = painter.fontMetrics().horizontalAdvance("NOW")
        painter.drawText(int(left_margin + plot_w - now_w), h - 2, "NOW")
