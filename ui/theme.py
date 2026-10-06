"""
Visual theme constants, palettes, and global Qt stylesheets.
Cyber/Fluent modern dark aesthetic.
"""

from PyQt6.QtGui import QColor


class Theme:
    # Backgrounds
    BG_ROOT = "#0a0c10"
    BG_WINDOW = "#0e1117"
    BG_CARD = "#141822"
    BG_CARD_HOVER = "#181d2a"
    BG_CARD_BORDER = "#1f2638"
    BG_SUBTLE = "#1a202c"
    BG_PANEL = "#11141c"

    # Accents by Vendor
    NVIDIA_GREEN = "#00e676"
    NVIDIA_DARK_GREEN = "#00b248"
    NVIDIA_GLOW = "#00e67633"

    AMD_RED = "#ff3366"
    AMD_DARK_RED = "#cc0033"
    AMD_GLOW = "#ff336633"

    INTEL_BLUE = "#00b0ff"
    INTEL_DARK_BLUE = "#0081cb"
    INTEL_GLOW = "#00b0ff33"

    CYBER_CYAN = "#00e5ff"
    CYBER_PURPLE = "#b388ff"

    # Thermal scale colors
    TEMP_COOL = "#00e676"      # < 55°C
    TEMP_OPTIMAL = "#29b6f6"   # 55 - 65°C
    TEMP_WARM = "#ffb300"      # 65 - 75°C
    TEMP_HOT = "#ff7043"       # 75 - 84°C
    TEMP_CRITICAL = "#ff1744"  # >= 85°C

    # Text
    TEXT_PRIMARY = "#f0f6fc"
    TEXT_SECONDARY = "#8b949e"
    TEXT_MUTED = "#555f6d"
    TEXT_ACCENT = "#58a6ff"

    # Borders & Dividers
    BORDER_DEFAULT = "#21283b"
    BORDER_ACCENT = "#303c54"

    @staticmethod
    def get_temp_color(temp_c: float) -> str:
        if temp_c < 55:
            return Theme.TEMP_COOL
        elif temp_c < 68:
            return Theme.TEMP_OPTIMAL
        elif temp_c < 78:
            return Theme.TEMP_WARM
        elif temp_c < 86:
            return Theme.TEMP_HOT
        else:
            return Theme.TEMP_CRITICAL

    @staticmethod
    def get_temp_status(temp_c: float) -> str:
        if temp_c < 55:
            return "COOL"
        elif temp_c < 68:
            return "NORMAL"
        elif temp_c < 78:
            return "WARM"
        elif temp_c < 86:
            return "HOT"
        else:
            return "THROTTLE"

    @staticmethod
    def get_vendor_color(vendor: str) -> str:
        v = vendor.upper()
        if "NVIDIA" in v:
            return Theme.NVIDIA_GREEN
        elif "AMD" in v:
            return Theme.AMD_RED
        elif "INTEL" in v:
            return Theme.INTEL_BLUE
        return Theme.CYBER_CYAN


GLOBAL_STYLESHEET = f"""
QMainWindow {{
    background-color: {Theme.BG_WINDOW};
}}

QWidget#CentralWidget {{
    background-color: {Theme.BG_WINDOW};
}}

QScrollArea {{
    background-color: transparent;
    border: none;
}}

QScrollBar:vertical {{
    background: {Theme.BG_WINDOW};
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {Theme.BORDER_ACCENT};
    min-height: 25px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: #415170;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QLabel {{
    color: {Theme.TEXT_PRIMARY};
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
}}

QComboBox {{
    background-color: {Theme.BG_SUBTLE};
    color: {Theme.TEXT_PRIMARY};
    border: 1px solid {Theme.BORDER_DEFAULT};
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}}

QComboBox:hover {{
    border: 1px solid {Theme.BORDER_ACCENT};
    background-color: {Theme.BG_CARD_HOVER};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {Theme.BG_CARD};
    color: {Theme.TEXT_PRIMARY};
    selection-background-color: {Theme.BG_SUBTLE};
    selection-color: {Theme.NVIDIA_GREEN};
    border: 1px solid {Theme.BORDER_DEFAULT};
    outline: none;
}}

QPushButton {{
    background-color: {Theme.BG_SUBTLE};
    color: {Theme.TEXT_PRIMARY};
    border: 1px solid {Theme.BORDER_DEFAULT};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: {Theme.BG_CARD_HOVER};
    border: 1px solid {Theme.BORDER_ACCENT};
    color: #ffffff;
}}

QPushButton:pressed {{
    background-color: #242c3d;
}}

QPushButton:checked {{
    background-color: #1e3a2e;
    color: {Theme.NVIDIA_GREEN};
    border: 1px solid {Theme.NVIDIA_GREEN};
}}

QTableWidget {{
    background-color: {Theme.BG_ROOT};
    gridline-color: {Theme.BORDER_DEFAULT};
    color: {Theme.TEXT_PRIMARY};
    border: 1px solid {Theme.BORDER_DEFAULT};
    border-radius: 6px;
}}

QHeaderView::section {{
    background-color: {Theme.BG_SUBTLE};
    color: {Theme.TEXT_SECONDARY};
    padding: 4px;
    border: none;
    font-size: 11px;
    font-weight: 600;
}}
"""
