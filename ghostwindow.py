import os
import sys
import ctypes

from PySide6.QtWidgets import QApplication, QMessageBox

from winapi import (
    user32,
    HOTKEY_ID, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT, VK_F3,
    HOTKEY_ID_PIN, VK_F4,                                          # NEW
)
from constants import DLL_NAME, DLL_PATH, STYLESHEET, HOTKEY_TEXT, HOTKEY_TEXT_PIN
from hotkey import HotkeyFilter
from main_window import GhostWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GhostWindow")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    if not os.path.exists(DLL_PATH):
        QMessageBox.critical(
            None, "GhostWindow",
            f"{DLL_NAME} not found next to the script:\n{DLL_PATH}")
        sys.exit(1)

    is_admin = False
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        pass

    win = GhostWindow()
    win.show()

    if not is_admin:
        QMessageBox.warning(
            None, "Administrator rights required",
            "GhostWindow is not running as administrator.\n\n"
            "Injection into elevated or other-user processes will fail.\n"
            "Restart the program as administrator for full functionality.")
        win._set_status("No admin rights — injection may fail", "err")

    # --- hotkey для show/hide ---
    hotkey_filter = HotkeyFilter(HOTKEY_ID, win.on_hotkey)

    if user32.RegisterHotKey(None, HOTKEY_ID,
                             MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_F3):
        app.installNativeEventFilter(hotkey_filter)
        app.aboutToQuit.connect(
            lambda: user32.UnregisterHotKey(None, HOTKEY_ID))
    else:
        win._set_status(
            f"Hotkey {HOTKEY_TEXT} is already taken by another application",
            "err")

    # NEW: hotkey для pin/unpin
    pin_filter = HotkeyFilter(HOTKEY_ID_PIN, win.on_hotkey_pin)

    if user32.RegisterHotKey(None, HOTKEY_ID_PIN,
                             MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_F4):
        app.installNativeEventFilter(pin_filter)
        app.aboutToQuit.connect(
            lambda: user32.UnregisterHotKey(None, HOTKEY_ID_PIN))
    else:
        win._set_status(
            f"Hotkey {HOTKEY_TEXT_PIN} is already taken by another application",
            "err")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()