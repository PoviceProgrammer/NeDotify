"""
NeDotify - Sidebar Navigation
Compact left panel with icon-only navigation matching Dotify reference UI.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QSpacerItem, QSizePolicy, QToolTip
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QFont, QColor, QPainter, QCursor


class IconButton(QPushButton):
    """An icon-only sidebar navigation button with active state."""

    def __init__(self, icon_char: str, tooltip_text: str = "", parent=None):
        super().__init__(parent)
        self.setText(icon_char)
        self.setToolTip(tooltip_text)
        self.setCheckable(True)
        self.setFixedSize(48, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("iconSidebarButton")
        self.setProperty("active", False)

        # Style will be handled by the global stylesheet, 
        # but we add a specific object name for targeting.

    def set_active(self, active: bool):
        self.setChecked(active)
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)


class Sidebar(QWidget):
    """
    Compact left sidebar navigation panel.
    Icons only.
    """

    # Signal emitted when a navigation item is clicked
    navigation_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("compactSidebar")
        self.setFixedWidth(70)
        self.setMinimumHeight(400)

        self._buttons: dict[str, IconButton] = {}
        self._current_page = ""

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 20, 11, 20)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # Top navigation buttons
        self._add_button("home", "⌂", "Главная")
        self._add_button("explore", "◧", "Обзор")
        self._add_button("player", "▶", "Плеер")
        self._add_button("search", "⌕", "Поиск")
        self._add_button("library", "▦", "Библиотека")

        # Spacer to push bottom buttons down
        layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        # Bottom buttons
        self._add_button("settings", "⚙", "Настройки")
        self._add_button("profile", "⍟", "Профиль")

    def _add_button(self, name: str, icon_char: str, tooltip: str):
        btn = IconButton(icon_char, tooltip)
        btn.clicked.connect(lambda checked, n=name: self._on_button_clicked(n))
        self.layout().addWidget(btn)
        self._buttons[name] = btn

    def _on_button_clicked(self, name: str):
        """Handle sidebar button click."""
        for btn_name, btn in self._buttons.items():
            btn.set_active(btn_name == name)
        
        self._current_page = name
        self.navigation_changed.emit(name)

    def set_active_page(self, name: str):
        """Programmatically set the active page."""
        if name in self._buttons:
            self._on_button_clicked(name)

    def update_service_status(self, service: str, online: bool):
        """No longer used in compact sidebar, handled in settings page."""
        pass
