"""
Responsive FlowLayout for PyQt6.
Automatically wraps child widgets (buttons, pills, filter chips) onto subsequent
rows when horizontal space is constrained, preventing clipping and overflow.
"""

from PyQt6.QtWidgets import QLayout, QSizePolicy
from PyQt6.QtCore import Qt, QPoint, QRect, QSize


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0, h_spacing: int = 8, v_spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        if margin >= 0:
            self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self) -> int:
        return self._h_space

    def verticalSpacing(self) -> int:
        return self._v_space

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            if item.widget() and item.widget().isHidden():
                continue
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue

            item_size = item.sizeHint()
            # If a single item is wider than available width, clamp to available width
            avail_w = max(40, effective.width())
            w_width = min(item_size.width(), avail_w)
            w_height = item.heightForWidth(w_width) if item.hasHeightForWidth() else item_size.height()
            if w_height <= 0:
                w_height = item_size.height()

            next_x = x + w_width + self._h_space
            if next_x - self._h_space > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_space
                next_x = x + w_width + self._h_space
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(w_width, w_height)))

            x = next_x
            line_height = max(line_height, w_height)

        return y + line_height - rect.y() + margins.bottom()
