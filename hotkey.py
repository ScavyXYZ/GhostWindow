from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

from winapi import WM_HOTKEY


class HotkeyFilter(QAbstractNativeEventFilter):
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