# cursor_lock.py
#
# Локальна (in-process) версія CursorLockProc з GhostWindow.cpp.
#
# Шари захисту:
#  1) WM_SETCURSOR на корені і всіх дочірніх HWND -> завжди стрілка.
#  2) Після mouse-повідомлень ще раз ставимо стрілку (перебиваємо прямі SetCursor).
#  3) Watchdog-таймер на GUI-потоці (~30 мс): якщо миша над нашим вікном,
#     примусово ставимо стрілку. Закриває випадки, коли Qt викликає SetCursor
#     поза mouse-повідомленнями (programmatic setCursor, show/hide віджета,
#     зміна layout під нерухомою мишею тощо). Заодно підчіплює дочірні HWND,
#     створені ПІСЛЯ install().
#
# Додатково для Qt-коду рекомендовано QGuiApplication.setOverrideCursor(...)
# (див. приклад у відповіді) — це перший і найнадійніший шар для Qt-віджетів.

import ctypes
from ctypes import wintypes

# FIX: `user32` is a single shared ctypes.WinDLL object — winapi.py and this
# module both set .argtypes on its functions, and whoever runs last wins
# globally, for every caller. GetCursorPos/WindowFromPoint are already
# configured in winapi.py against winapi's own POINT structure (used by
# helpers.window_under_cursor and picker.py). Re-declaring them here with
# ctypes.wintypes.POINT — a different, merely structurally-identical class —
# silently breaks every other caller with
# "TypeError: expected LP_POINT instance instead of pointer to POINT".
# Always reuse winapi.POINT instead of introducing a second POINT type.
from winapi import user32, POINT


# --- Константи ---------------------------------------------------------------

GWLP_WNDPROC = -4
GA_ROOT      = 2

WM_SETCURSOR     = 0x0020
WM_NCDESTROY     = 0x0082
WM_TIMER         = 0x0113

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

_WATCHDOG_ID = 0xC0DE   # id віконного таймера на корені
_WATCHDOG_MS = 30

_MOUSE_MSGS = frozenset([
    WM_MOUSEMOVE, WM_NCMOUSEMOVE,
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK,
    WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK,
    WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK,
    WM_NCLBUTTONDOWN, WM_NCLBUTTONUP,
    WM_NCRBUTTONDOWN, WM_NCRBUTTONUP,
])


# --- Сигнатури ---------------------------------------------------------------
# Важливо задати argtypes для всього, що приймає WPARAM/LPARAM/HWND:
# без них ctypes на x64 truncate-ить значення до 32 біт.

user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                   wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CallWindowProcW.restype  = ctypes.c_ssize_t

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype  = ctypes.c_ssize_t

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype  = ctypes.c_ssize_t

user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype  = ctypes.c_ssize_t

# lpCursorName — це MAKEINTRESOURCE, тому передаємо як void*
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype  = wintypes.HANDLE

user32.SetCursor.argtypes = [wintypes.HANDLE]
user32.SetCursor.restype  = wintypes.HANDLE

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype  = wintypes.BOOL

user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
user32.EnumChildWindows.restype  = wintypes.BOOL

user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype  = wintypes.BOOL

user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype  = wintypes.HWND

user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype  = wintypes.HWND

user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype  = ctypes.c_size_t

user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype  = wintypes.BOOL


# --- Типи / стан -------------------------------------------------------------

WNDPROC   = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                               wintypes.WPARAM, wintypes.LPARAM)
_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_arrow_cursor = user32.LoadCursorW(None, IDC_ARROW)

_active = False                 # глобальний перемикач: lock увімкнено?
_hooks: dict[int, int] = {}     # hwnd -> оригінальний WNDPROC


# --- Допоміжне ---------------------------------------------------------------

def _cursor_over(root: int) -> bool:
    """Чи знаходиться курсор миші над root або його нащадком (з урахуванням z-order)."""
    pt = POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return False
    h = user32.WindowFromPoint(pt)
    if not h:
        return False
    return int(user32.GetAncestor(h, GA_ROOT) or 0) == int(root)


# --- Callback ----------------------------------------------------------------

def _wnd_proc(hwnd, msg, wp, lp):
    hwnd = int(hwnd or 0)
    orig = _hooks.get(hwnd)
    if orig is None:
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    if _active:
        if msg == WM_SETCURSOR:
            user32.SetCursor(_arrow_cursor)
            return 1  # TRUE — оброблено, далі не пускаємо

        if msg == WM_TIMER and wp == _WATCHDOG_ID:
            _hook_tree(hwnd)                    # підхопити нові дочірні HWND
            if _cursor_over(hwnd):
                user32.SetCursor(_arrow_cursor)
            return 0

    res = user32.CallWindowProcW(orig, hwnd, msg, wp, lp)

    if msg == WM_NCDESTROY:
        # HWND може бути перевикористаний системою — не лишаємо сміття
        _hooks.pop(hwnd, None)
    elif _active and msg in _MOUSE_MSGS:
        # Qt міг сам викликати SetCursor під час обробки — перебиваємо
        user32.SetCursor(_arrow_cursor)

    return res


_keep_alive_proc = WNDPROC(_wnd_proc)
_PROC_ADDR = ctypes.cast(_keep_alive_proc, ctypes.c_void_p).value


# --- Хукання -----------------------------------------------------------------

def _hook_one(hwnd: int):
    hwnd = int(hwnd or 0)
    if not hwnd or hwnd in _hooks or not user32.IsWindow(hwnd):
        return

    ctypes.set_last_error(0)
    prev = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, _PROC_ADDR)
    if prev == 0 and ctypes.get_last_error() != 0:
        return  # не вдалось (protected class тощо)

    _hooks[hwnd] = int(prev)


def _enum_child(hwnd, lparam):
    _hook_one(hwnd)
    return True


_enum_cb = _ENUMPROC(_enum_child)


def _hook_tree(root: int):
    _hook_one(root)
    # EnumChildWindows сам обходить усіх нащадків (діти дітей теж)
    user32.EnumChildWindows(root, _enum_cb, 0)


def _restore_one(hwnd: int):
    orig = _hooks.get(hwnd)
    if orig is None:
        return
    if not user32.IsWindow(hwnd):
        _hooks.pop(hwnd, None)
        return
    if user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC) == _PROC_ADDR:
        # Наш хук ще зверху ланцюжка — безпечно відновити
        user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, orig)
        _hooks.pop(hwnd, None)
    # Інакше поверх нас хтось підклассив вікно. Відновлювати не можна —
    # вирвемо чужу процедуру з ланцюжка. Лишаємось у pass-through (_active=False).


# --- Публічне API ------------------------------------------------------------

def install(hwnd: int):
    """Вмикає lock на корені та всіх дочірніх HWND + запускає watchdog."""
    global _active
    if not hwnd or not user32.IsWindow(hwnd):
        return
    _active = True
    _hook_tree(hwnd)
    user32.SetTimer(hwnd, _WATCHDOG_ID, _WATCHDOG_MS, None)
    if _cursor_over(hwnd):
        user32.SetCursor(_arrow_cursor)   # одразу, не чекаючи руху миші


def uninstall(hwnd: int):
    """Вимикає lock: зупиняє watchdog і знімає хуки з УСІХ вікон (де це безпечно)."""
    global _active
    _active = False                       # одразу переводить усі хуки в pass-through
    if hwnd:
        user32.KillTimer(hwnd, _WATCHDOG_ID)
    for h in list(_hooks.keys()):
        _restore_one(h)