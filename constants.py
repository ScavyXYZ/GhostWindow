import os

DLL_NAME    = "GhostWindow.dll"
DLL_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), DLL_NAME)
HOTKEY_TEXT     = "Ctrl+Shift+F3"
HOTKEY_TEXT_PIN = "Ctrl+Shift+F4"


STYLESHEET = """
* {
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
    color: #d8d8e0;
}

QWidget#MainWindow {
    background-color: #0f0f13;
    border: 1px solid #1e1e26;
}

QWidget#Content {
    background-color: transparent;
}

QFrame#TitleBar {
    background-color: #0f0f13;
    border-bottom: 1px solid #1e1e26;
}

QLabel#AppTitle {
    font-size: 10pt;
    font-weight: 600;
    color: #f0f0f5;
    letter-spacing: 2px;
}

QPushButton#WinBtn, QPushButton#WinCloseBtn {
    background: transparent;
    border: none;
    color: #6a6a78;
    font-size: 13pt;
    padding: 0;
}
QPushButton#WinBtn:hover {
    color: #f0f0f5;
}
QPushButton#WinCloseBtn:hover {
    color: #ff6b6b;
}

QLabel#Header {
    font-size: 9.5pt;
    color: #6d7280;
}

QLabel#SectionTitle {
    font-size: 8pt;
    font-weight: 700;
    color: #4a4a58;
    letter-spacing: 2.5px;
}

QLabel#TargetInfo {
    font-size: 10pt;
    color: #d8d8e0;
    background-color: #16161c;
    border: 1px solid #1e1e26;
    border-radius: 6px;
    padding: 10px 14px;
}

QLabel#Status {
    font-size: 9pt;
    color: #6d7280;
    padding: 2px 0;
}

QPushButton {
    background-color: transparent;
    color: #b8b8c4;
    border: 1px solid #26262f;
    border-radius: 6px;
    padding: 9px 18px;
    font-size: 9.5pt;
}
QPushButton:hover {
    background-color: #16161c;
    border-color: #30303c;
    color: #f0f0f5;
}
QPushButton:pressed {
    background-color: #1e1e26;
}
QPushButton:disabled {
    color: #3a3a44;
    border-color: #1a1a22;
    background-color: transparent;
}

QPushButton:checked {
    background-color: #1c2a44;
    border-color: #3b6ea8;
    color: #cfe3ff;
}
QPushButton:checked:hover {
    background-color: #223255;
    border-color: #4b86c4;
    color: #ffffff;
}

QPushButton#PrimaryBtn {
    background-color: #f0f0f5;
    color: #0f0f13;
    border: 1px solid #f0f0f5;
    font-weight: 600;
}
QPushButton#PrimaryBtn:hover {
    background-color: #ffffff;
    border-color: #ffffff;
}
QPushButton#PrimaryBtn:pressed {
    background-color: #d0d0d8;
}

QPushButton#DangerBtn:hover {
    color: #ff6b6b;
    border-color: #ff6b6b;
}

QTableWidget {
    background-color: #13131a;
    alternate-background-color: #13131a;
    gridline-color: transparent;
    border: 1px solid #1e1e26;
    border-radius: 6px;
    selection-background-color: #1e1e26;
    selection-color: #ffffff;
    outline: 0;
}
QTableWidget::item {
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid #1a1a22;
}
QTableWidget::item:hover {
    background-color: #16161c;
}
QHeaderView::section {
    background-color: #0f0f13;
    color: #4a4a58;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid #1e1e26;
    font-weight: 600;
    font-size: 8pt;
    letter-spacing: 1.5px;
}
QTableCornerButton::section {
    background-color: #0f0f13;
    border: none;
}

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #26262f;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover { background: #3a3a44; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #26262f;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover { background: #3a3a44; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QMessageBox {
    background-color: #13131a;
}
QMessageBox QLabel { color: #d8d8e0; }
QMessageBox QPushButton {
    min-width: 90px;
    padding: 8px 16px;
}

QMenu {
    background-color: #16161c;
    border: 1px solid #30303c;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #1e1e26;
    color: #ffffff;
}

QCheckBox {
    color: #b8b8c4;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #30303c;
    border-radius: 3px;
    background-color: #13131a;
}
QCheckBox::indicator:hover {
    border-color: #4a4a58;
}
QCheckBox::indicator:checked {
    background-color: #3b6ea8;
    border-color: #3b6ea8;
}

QSizeGrip {
    background: transparent;
    width: 14px;
    height: 14px;
}
"""