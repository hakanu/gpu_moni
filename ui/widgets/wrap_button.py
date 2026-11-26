"""
Word-wrapping QPushButton for PyQt6.
Standard QPushButton clips text when constrained horizontally; WrapButton
automatically wraps multi-word labels onto multiple lines and adjusts its height
so button text always remains 100% readable.
"""

from PyQt6.QtWidgets import QPushButton, QStyleOptionButton, QStyle, QSizePolicy
from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import QPainter


class WrapButton(QPushButton):
    """QPushButton that wraps text cleanly instead of clipping when narrow."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def hasHeightForWidth(self) -> bool:
        return True

    def _text_padding(self) -> tuple[int, int]:
        # Horizontal and vertical padding matching Theme stylesheet
        return (22, 12)

    def heightForWidth(self, width: int) -> int:
        h_pad, v_pad = self._text_padding()
        text_w = max(24, width - h_pad)
        fm = self.fontMetrics()
        rect = fm.boundingRect(
            QRect(0, 0, text_w, 1000),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self.text(),
        )
        return max(30, rect.height() + v_pad)

    def sizeHint(self) -> QSize:
        h_pad, v_pad = self._text_padding()
        fm = self.fontMetrics()
        text_rect = fm.boundingRect(
            QRect(0, 0, 1000, 100),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine,
            self.text(),
        )
        w = text_rect.width() + h_pad
        h = max(30, text_rect.height() + v_pad)
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:
        h_pad, v_pad = self._text_padding()
        fm = self.fontMetrics()
        # Minimum width = widest single word + padding so words don't split mid-word
        words = self.text().split() or [self.text()]
        max_word_w = max((fm.horizontalAdvance(w) for w in words), default=40)
        w = min(self.sizeHint().width(), max_word_w + h_pad)
        h = self.heightForWidth(w)
        return QSize(max(52, w), h)

    def paintEvent(self, event):
        painter = QPainter(self)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        # Draw button chrome/background via QStyle without default single-line text
        text = opt.text
        opt.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, painter, self)

        # Draw wrapped centered text inside the button rect
        h_pad, v_pad = self._text_padding()
        text_rect = self.rect().adjusted(h_pad // 2 - 2, 2, -(h_pad // 2 - 2), -2)
        painter.setFont(self.font())
        painter.setPen(opt.palette.buttonText().color())
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            text,
        )
        painter.end()
