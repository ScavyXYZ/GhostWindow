"""
Custom title bar widget for the frameless main window.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from constants import HOTKEY_TEXT


class TitleBar(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(40)
        self._parent = parent
        self._drag_pos = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 8, 0)
        lay.setSpacing(0)

        title = QLabel("GHOSTWINDOW")
        title.setObjectName("AppTitle")
        lay.addWidget(title)
        lay.addStretch()

        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("WinCloseBtn")
        self.close_btn.setFixedSize(32, 28)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip(f"Hide ({HOTKEY_TEXT} — restore)")
        self.close_btn.clicked.connect(parent.hide_self)
        lay.addWidget(self.close_btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = (e.globalPosition().toPoint()
                              - self._parent.frameGeometry().topLeft())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.LeftButton):
            self._parent.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
