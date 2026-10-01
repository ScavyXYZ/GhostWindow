"""
Global hotkey filter for Qt's native event loop.
"""

from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

from winapi import WM_HOTKEY


class HotkeyFilter(QAbstractNativeEventFilter):
    """Catches WM_HOTKEY in the main (Qt) thread.

    RegisterHotKey + a native event filter replaces the old low-level
    keyboard hook thread entirely: simpler, and the hotkey still works
    while the main window is hidden because the Qt loop keeps running.

    NOTE: the Python side must keep a reference to this object for as
    long as the filter is installed — otherwise the garbage collector
    destroys the C++ filter and WM_HOTKEY is silently lost.
    """

    def __init__(self, hotkey_id, callback):
        super().__init__()
        self._id = hotkey_id
        self._cb = callback

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._id:
                    self._cb()
        except Exception:
            import traceback
            traceback.print_exc()
        return False, 0
