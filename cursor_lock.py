# cursor_lock.py
#
# Локальна (in-process) версія CursorLockProc з GhostWindow.cpp.
# Перехоплює WM_SETCURSOR на корені GhostWindow і всіх дочірніх HWND,
# а також переставляє стрілку після mouse-повідомлень, щоб подолати
# прямі SetCursor() виклики всередині Qt.

import ctypes
from ctypes import wintypes

from winapi import user32, kernel32


# --- WinAPI, яких немає у winapi.py -----------------------------------------

GWL_WNDPROC     = -4
GWLP_WNDPROC    = -4

WM_SETCURSOR    = 0x0020

WM_MOUSEMOVE     = 0x0200
WM_NCMOUSEMOVE   = 0x00A0
WM_LBUTTONDOWN   = 0x0201
WM_LBUTTONUP     = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN   = 0x0204
WM_RBUTTONUP     = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_MBUTTONDOWN   = 0x0207
WM_MBUTTONUP     = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP   = 0x00A2
WM_NCRBUTTONDOWN = 0x00A4
WM_NCRBUTTONUP   = 0x00A5

IDC_ARROW = 32512

_MOUSE_MSGS = frozenset([
    WM_MOUSEMOVE, WM_NCMOUSEMOVE,
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK,
    WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK,
    WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK,
    WM_NCLBUTTONDOWN, WM_NCLBUTTONUP,
    WM_NCRBUTTONDOWN, WM_NCRBUTTONUP,
])

# Сигнатури (у winapi.py вони не всі налаштовані)
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                   wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CallWindowProcW.restype  = ctypes.c_ssize_t

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype  = ctypes.c_ssize_t

user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype  = ctypes.c_ssize_t

user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadCursorW.restype  = wintypes.HANDLE

user32.SetCursor.argtypes = [wintypes.HANDLE]
user32.SetCursor.restype  = wintypes.HANDLE

user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
user32.EnumChildWindows.restype  = wintypes.BOOL


# --- WNDPROC тип -------------------------------------------------------------

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
)

_arrow_cursor = user32.LoadCursorW(None, ctypes.c_wchar_p(IDC_ARROW))

# Тримаємо посилання на callback-об'єкти, інакше Python їх збере.
_hooks: dict[int, dict] = {}   # hwnd -> {"proc": WNDPROC, "orig": int}


# --- Callback ----------------------------------------------------------------

def _wnd_proc(hwnd, msg, wp, lp):
    data = _hooks.get(int(hwnd))
    if not data:
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    if msg == WM_SETCURSOR:
        user32.SetCursor(_arrow_cursor)
        return 1  # TRUE — оброблено, не пускаємо далі

    # Викликаємо оригінальну процедуру Qt
    res = user32.CallWindowProcW(
        ctypes.c_void_p(data["orig"]), hwnd, msg, wp, lp
    )

    # Після mouse-повідомлень Qt міг сам викликати SetCursor — перебиваємо
    if msg in _MOUSE_MSGS:
        user32.SetCursor(_arrow_cursor)

    return res


_keep_alive_proc = WNDPROC(_wnd_proc)


# --- Публічне API ------------------------------------------------------------

def _enum_child(hwnd, lparam):
    _hook_one(hwnd)
    return True


_enum_cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(
    _enum_child
)


def _hook_one(hwnd: int):
    if not hwnd or int(hwnd) in _hooks:
        return
    if not user32.IsWindow(hwnd):
        return

    SetWindowLongPtrW = user32.SetWindowLongPtrW
    GetWindowLongPtrW = user32.GetWindowLongPtrW

    ctypes.set_last_error(0)
    orig = GetWindowLongPtrW(hwnd, GWLP_WNDPROC)
    if not orig:
        return

    ctypes.set_last_error(0)
    prev = SetWindowLongPtrW(hwnd, GWLP_WNDPROC,
                             ctypes.cast(_keep_alive_proc, ctypes.c_void_p).value)
    if prev == 0 and ctypes.get_last_error() != 0:
        return  # не вдалось (protected class тощо)

    _hooks[int(hwnd)] = {"proc": _keep_alive_proc, "orig": int(prev)}


def install(hwnd: int):
    """Вішає lock на корінь GhostWindow і всі дочірні HWND."""
    if not hwnd or not user32.IsWindow(hwnd):
        return
    _hook_one(hwnd)
    user32.EnumChildWindows(hwnd, _enum_cb, 0)


def uninstall(hwnd: int):
    """Знімає lock з кореня і всіх дочірніх HWND (для коректного закриття)."""
    for h in list(_hooks.keys()):
        if not user32.IsWindow(h):
            _hooks.pop(h, None)
    if hwnd and int(hwnd) in _hooks:
        _restore_one(int(hwnd))
    # дочірніх не чіпаємо — Qt їх знищить разом з батьком


def _restore_one(hwnd: int):
    data = _hooks.pop(hwnd, None)
    if not data:
        return
    if user32.IsWindow(hwnd):
        user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, data["orig"])