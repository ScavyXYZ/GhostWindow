"""
GhostWindow — hides a specific window from OBS / Zoom / Discord,
removes it from the taskbar, keeps it always on top.

UI: PySide6. Minimal dark interface.
Hotkey Ctrl+Shift+F1 — show/hide the GhostWindow window.
The "Quit" button restores all windows, detaches the DLL, and exits.
Run as administrator.

Files:
    ghostwindow.py  — this file (entry point)
    main_window.py  — main window UI and logic
    winapi.py       — WinAPI constants and ctypes declarations
    helpers.py      — window/process helper functions
    injection.py    — DLL injection and remote export calling
    constants.py    — app-wide constants and stylesheet
    hotkey.py       — global hotkey filter
    titlebar.py     — custom title bar widget
    picker.py       — picker overlay for window selection
    GhostWindow.dll — built from GhostWindow.cpp (see its header)
    GhostWindow.def — export definitions
"""

import os
import sys
import ctypes

from PySide6.QtWidgets import QApplication, QMessageBox

from winapi import user32, HOTKEY_ID, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT, VK_F1
from constants import DLL_NAME, DLL_PATH, STYLESHEET, HOTKEY_TEXT
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

    # Global hotkey Ctrl+Shift+F1 — registered for the main thread,
    # delivered through Qt's message loop (no hook thread needed).
    #
    # FIX: keep a Python reference to the filter. Previously the filter
    # object was created inline inside installNativeEventFilter(...);
    # Qt does NOT take ownership of native event filters, so the garbage
    # collector destroyed the C++ object and WM_HOTKEY was silently lost.
    hotkey_filter = HotkeyFilter(HOTKEY_ID, win.on_hotkey)   # keep alive!

    if user32.RegisterHotKey(None, HOTKEY_ID,
                             MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_F1):
        app.installNativeEventFilter(hotkey_filter)
        app.aboutToQuit.connect(
            lambda: user32.UnregisterHotKey(None, HOTKEY_ID))
    else:
        win._set_status(
            f"Hotkey {HOTKEY_TEXT} is already taken by another application",
            "err")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
