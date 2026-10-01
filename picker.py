"""
Picker overlay — countdown window for selecting a target under the cursor.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

from constants import HOTKEY_TEXT
from helpers import apply_stealth_to_hwnd, window_under_cursor


class PickerOverlay(QWidget):
    finished = Signal(object)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(320, 60)
        self.move(24, 24)

        self.setStyleSheet("""
            QWidget {
                background-color: #0f0f13;
                border: 1px solid #30303c;
            }
            QLabel {
                color: #d8d8e0;
                font-size: 9.5pt;
            }
            QLabel#Count {
                color: #f0f0f5;
                font-weight: 700;
                font-size: 12pt;
            }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(14)

        self.count_lbl = QLabel("5")
        self.count_lbl.setObjectName("Count")
        self.count_lbl.setFixedWidth(20)
        self.count_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.count_lbl)

        text_wrap = QVBoxLayout()
        text_wrap.setSpacing(0)
        t1 = QLabel("Point the cursor at a window")
        t2 = QLabel(f"{HOTKEY_TEXT} — cancel")
        t2.setStyleSheet("color: #6d7280; font-size: 8.5pt;")
        text_wrap.addWidget(t1)
        text_wrap.addWidget(t2)
        lay.addLayout(text_wrap, 1)

        self.remaining = 5
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.show()
        QTimer.singleShot(60, lambda: apply_stealth_to_hwnd(int(self.winId())))
        self._tick()
        self.timer.start(1000)

    def _tick(self):
        if self.remaining > 0:
            self.count_lbl.setText(str(self.remaining))
            self.remaining -= 1
            return
        self.timer.stop()
        self.hide()   # out of hit-testing BEFORE WindowFromPoint
        hwnd = window_under_cursor()
        self.close()
        self.finished.emit(hwnd)

    def cancel(self):
        self.timer.stop()
        self.close()
        self.finished.emit(None)
