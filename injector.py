"""
GhostWindow — hides a specific window from OBS / Zoom / Discord,
removes it from the taskbar, keeps it always on top.

UI: PySide6. Minimal dark interface.
Hotkey Ctrl+Shift+F1 — show/hide the GhostWindow window.
The "Quit" button restores all windows, detaches the DLL, and exits.
Run as administrator.

Files:
    ghostwindow.py    — this file (injector + UI)
    GhostWindow.dll   — built from GhostWindow.cpp (see its header)
    GhostWindow.def   — export definitions
"""

import ctypes
from ctypes import wintypes
import os
import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal, QAbstractNativeEventFilter
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFrame,
    QAbstractItemView, QSizeGrip,
)


# ─────────────────────── WinAPI ───────────────────────

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32   = ctypes.WinDLL("user32",   use_last_error=True)

# ── Process access rights (minimal required, less AV noise) ──
PROCESS_CREATE_THREAD     = 0x0002
PROCESS_VM_OPERATION      = 0x0008
PROCESS_VM_READ           = 0x0010
PROCESS_VM_WRITE          = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED     = 0x1000

INJECT_ACCESS = (PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                 PROCESS_VM_OPERATION  | PROCESS_VM_WRITE | PROCESS_VM_READ)
CALL_ACCESS   = (PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                 PROCESS_VM_OPERATION  | PROCESS_VM_READ)

MEM_COMMIT     = 0x00001000
MEM_RESERVE    = 0x00002000
MEM_RELEASE    = 0x00008000
PAGE_READWRITE = 0x04
INFINITE       = 0xFFFFFFFF
TH32CS_SNAPMODULE   = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
GA_ROOT = 2

WDA_EXCLUDEFROMCAPTURE = 0x00000011
WDA_MONITOR            = 0x00000001
WDA_NONE               = 0x00000000

SW_HIDE    = 0
SW_SHOW    = 5
SW_RESTORE = 9

GWL_EXSTYLE      = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW  = 0x00040000

SWP_NOSIZE       = 0x0001
SWP_NOMOVE       = 0x0002
SWP_NOZORDER     = 0x0004
SWP_NOACTIVATE   = 0x0010
SWP_FRAMECHANGED = 0x0020

# ── Global hotkey (RegisterHotKey, handled through the Qt message loop) ──
WM_HOTKEY    = 0x0312
MOD_CONTROL  = 0x0002
MOD_SHIFT    = 0x0004
MOD_NOREPEAT = 0x4000
HOTKEY_ID    = 1

VK_F1           = 0x70
VK_MENU         = 0x12
KEYEVENTF_KEYUP = 0x0002


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize",        wintypes.DWORD),
        ("th32ModuleID",  wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage",  wintypes.DWORD),
        ("ProccntUsage",  wintypes.DWORD),
        ("modBaseAddr",   ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize",   wintypes.DWORD),
        ("hModule",       wintypes.HMODULE),
        ("szModule",      wintypes.WCHAR * 256),
        ("szExePath",     wintypes.WCHAR * 260),
    ]


kernel32.OpenProcess.argtypes        = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype         = wintypes.HANDLE
kernel32.CloseHandle.argtypes        = [wintypes.HANDLE]
kernel32.CloseHandle.restype         = wintypes.BOOL
kernel32.VirtualAllocEx.argtypes     = [wintypes.HANDLE, wintypes.LPVOID,
                                        ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype      = wintypes.LPVOID
kernel32.VirtualFreeEx.argtypes      = [wintypes.HANDLE, wintypes.LPVOID,
                                        ctypes.c_size_t, wintypes.DWORD]
kernel32.VirtualFreeEx.restype       = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                        wintypes.LPCVOID, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype  = wintypes.BOOL
kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                        ctypes.c_size_t, wintypes.LPVOID,
                                        wintypes.LPVOID, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateRemoteThread.restype  = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype  = wintypes.DWORD
kernel32.GetExitCodeThread.argtypes  = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeThread.restype   = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes   = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype    = wintypes.HMODULE
kernel32.GetProcAddress.argtypes     = [wintypes.HMODULE, wintypes.LPCSTR]
kernel32.GetProcAddress.restype      = wintypes.LPVOID
kernel32.LoadLibraryW.argtypes       = [wintypes.LPCWSTR]
kernel32.LoadLibraryW.restype        = wintypes.HMODULE
kernel32.FreeLibrary.argtypes        = [wintypes.HMODULE]
kernel32.FreeLibrary.restype         = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD,
    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype  = wintypes.HANDLE
kernel32.Module32FirstW.argtypes     = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32FirstW.restype      = wintypes.BOOL
kernel32.Module32NextW.argtypes      = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32NextW.restype       = wintypes.BOOL
kernel32.GetConsoleWindow.argtypes   = []
kernel32.GetConsoleWindow.restype    = wintypes.HWND

user32.GetCursorPos.argtypes         = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype          = wintypes.BOOL
user32.WindowFromPoint.argtypes      = [POINT]
user32.WindowFromPoint.restype       = wintypes.HWND
user32.GetAncestor.argtypes          = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype           = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype  = wintypes.DWORD
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype  = ctypes.c_int
user32.GetWindowTextW.argtypes       = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype        = ctypes.c_int
user32.IsWindow.argtypes             = [wintypes.HWND]
user32.IsWindow.restype              = wintypes.BOOL
user32.IsIconic.argtypes             = [wintypes.HWND]
user32.IsIconic.restype              = wintypes.BOOL
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype  = wintypes.BOOL
user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowDisplayAffinity.restype  = wintypes.BOOL
user32.ShowWindow.argtypes           = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype            = wintypes.BOOL
user32.SetForegroundWindow.argtypes  = [wintypes.HWND]
user32.SetForegroundWindow.restype   = wintypes.BOOL
user32.GetWindowLongW.argtypes       = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype        = ctypes.c_long
user32.SetWindowLongW.argtypes       = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype        = ctypes.c_long
user32.SetWindowPos.argtypes         = [wintypes.HWND, wintypes.HWND,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype          = wintypes.BOOL
user32.keybd_event.argtypes          = [wintypes.BYTE, wintypes.BYTE,
                                        wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.restype           = None
user32.RegisterHotKey.argtypes       = [wintypes.HWND, ctypes.c_int,
                                        wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype        = wintypes.BOOL
user32.UnregisterHotKey.argtypes     = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype      = wintypes.BOOL
user32.PeekMessageW.argtypes         = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                        wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype          = wintypes.BOOL


# ─────────────────────── Helpers ───────────────────────

def get_root(hwnd):
    if not hwnd:
        return 0
    r = user32.GetAncestor(hwnd, GA_ROOT)
    return r if r else hwnd


def get_pid(hwnd):
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_under_cursor():
    pt = POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return None
    hwnd = user32.WindowFromPoint(pt)
    return get_root(hwnd) if hwnd else None


def is_process_alive(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return False
    kernel32.CloseHandle(h)
    return True


def get_process_name(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return "?"


def find_module_base(pid, dll_name):
    snap = kernel32.CreateToolhelp32Snapshot(
        TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap in (None, -1, wintypes.HANDLE(-1).value):
        return None
    try:
        me = MODULEENTRY32W()
        me.dwSize = ctypes.sizeof(me)
        if kernel32.Module32FirstW(snap, ctypes.byref(me)):
            while True:
                if me.szModule.lower() == dll_name.lower():
                    return int(me.hModule) if me.hModule else None
                if not kernel32.Module32NextW(snap, ctypes.byref(me)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return None


def stealth_is_active(hwnd):
    """True if the window still has capture-exclusion enabled."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    aff = wintypes.DWORD(0)
    if not user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(aff)):
        return False
    return aff.value in (WDA_EXCLUDEFROMCAPTURE, WDA_MONITOR)


def _restore_window(hwnd):
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def force_foreground(hwnd):
    """Bring hwnd to the foreground even from a background process.

    Windows blocks SetForegroundWindow from processes that don't own the
    current foreground window. A quick ALT press/release unlocks it.
    """
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)

        user32.keybd_event(VK_MENU, 0, 0, None)                # ALT down
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)  # ALT up

        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def apply_stealth_to_hwnd(hwnd):
    """Local (same-process) variant used on GhostWindow's own windows."""
    try:
        hwnd = get_root(hwnd)
        if not hwnd:
            return
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex |= WS_EX_TOOLWINDOW
        ex &= ~WS_EX_APPWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                            SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass


def hide_console():
    try:
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, SW_HIDE)
    except Exception:
        pass


# ─────────────────────── Global hotkey ───────────────────────

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


# ─────────────────────── Injection ───────────────────────

def inject_dll(pid, dll_path):
    dll_path = os.path.abspath(dll_path)
    h = kernel32.OpenProcess(INJECT_ACCESS, False, pid)
    if not h:
        raise OSError(f"OpenProcess failed: {ctypes.get_last_error()}. "
                      f"Run as administrator.")
    try:
        path_bytes = (dll_path + "\0").encode("utf-16-le")
        mem = kernel32.VirtualAllocEx(h, None, len(path_bytes),
                                      MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not mem:
            raise OSError(f"VirtualAllocEx failed: {ctypes.get_last_error()}")
        try:
            written = ctypes.c_size_t(0)
            if not kernel32.WriteProcessMemory(
                    h, mem, path_bytes, len(path_bytes), ctypes.byref(written)):
                raise OSError(f"WriteProcessMemory failed: {ctypes.get_last_error()}")
            k32 = kernel32.GetModuleHandleW("kernel32.dll")
            load_lib = kernel32.GetProcAddress(k32, b"LoadLibraryW")
            th = kernel32.CreateRemoteThread(h, None, 0, load_lib, mem, 0, None)
            if not th:
                raise OSError(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
            kernel32.WaitForSingleObject(th, INFINITE)
            code = wintypes.DWORD(0)
            kernel32.GetExitCodeThread(th, ctypes.byref(code))
            kernel32.CloseHandle(th)
            if code.value == 0:
                raise OSError("LoadLibraryW returned NULL "
                              "(check that DLL architecture matches the process)")
        finally:
            kernel32.VirtualFreeEx(h, mem, 0, MEM_RELEASE)
    finally:
        kernel32.CloseHandle(h)


_ERR_HINTS = {
    5:    "access denied",
    87:   "invalid parameter",
    1400: "invalid window handle",
}


def call_export(pid, dll_name, dll_path, func_name, param=0):
    """Call an exported DWORD WINAPI f(LPVOID) inside the target process.

    Raises OSError if the remote export returned a non-zero error code.
    """
    dll_path = os.path.abspath(dll_path)
    target_base = find_module_base(pid, dll_name)
    if not target_base:
        raise OSError(f"DLL '{dll_name}' is not loaded in process {pid}")
    h_local = kernel32.LoadLibraryW(dll_path)
    if not h_local:
        raise OSError(f"LoadLibraryW failed: {ctypes.get_last_error()}")
    try:
        local_func = kernel32.GetProcAddress(h_local, func_name.encode())
        if not local_func:
            raise OSError(f"Export '{func_name}' not found "
                          f"(error {ctypes.get_last_error()})")
        offset = local_func - h_local
    finally:
        kernel32.FreeLibrary(h_local)

    h = kernel32.OpenProcess(CALL_ACCESS, False, pid)
    if not h:
        raise OSError(f"OpenProcess failed: {ctypes.get_last_error()}")
    try:
        th = kernel32.CreateRemoteThread(
            h, None, 0,
            ctypes.c_void_p(target_base + offset),
            ctypes.c_void_p(param), 0, None)
        if not th:
            raise OSError(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
        kernel32.WaitForSingleObject(th, INFINITE)
        code = wintypes.DWORD(0)
        kernel32.GetExitCodeThread(th, ctypes.byref(code))
        kernel32.CloseHandle(th)
        if code.value != 0:
            hint = _ERR_HINTS.get(code.value)
            raise OSError(f"{func_name} failed in target process "
                          f"(Win32 error {code.value}"
                          f"{', ' + hint if hint else ''})")
    finally:
        kernel32.CloseHandle(h)


def remote_free_library(pid, module_handle):
    k32_local = kernel32.GetModuleHandleW("kernel32.dll")
    free_lib_local = kernel32.GetProcAddress(k32_local, b"FreeLibrary")
    if not free_lib_local:
        raise OSError("GetProcAddress(FreeLibrary) failed")
    offset = free_lib_local - k32_local
    k32_target = find_module_base(pid, "kernel32.dll")
    if not k32_target:
        raise OSError("kernel32 not found in target process")
    free_lib_remote = k32_target + offset
    h = kernel32.OpenProcess(CALL_ACCESS, False, pid)
    if not h:
        raise OSError(f"OpenProcess failed: {ctypes.get_last_error()}")
    try:
        th = kernel32.CreateRemoteThread(
            h, None, 0,
            ctypes.c_void_p(free_lib_remote),
            ctypes.c_void_p(module_handle), 0, None)
        if not th:
            raise OSError(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
        kernel32.WaitForSingleObject(th, INFINITE)
        code = wintypes.DWORD(0)
        kernel32.GetExitCodeThread(th, ctypes.byref(code))
        kernel32.CloseHandle(th)
        if code.value == 0:
            raise OSError("FreeLibrary failed in target process")
    finally:
        kernel32.CloseHandle(h)


def detach_dll(pid, dll_name, dll_path):
    for _ in range(16):
        base = find_module_base(pid, dll_name)
        if not base:
            return True
        try:
            remote_free_library(pid, base)
        except Exception:
            pass
        time.sleep(0.1)
    return find_module_base(pid, dll_name) is None


# ─────────────────────── Constants ───────────────────────

DLL_NAME    = "GhostWindow.dll"
DLL_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), DLL_NAME)
HOTKEY_TEXT = "Ctrl+Shift+F1"


# ─────────────────────── Stylesheet ───────────────────────

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

QSizeGrip {
    background: transparent;
    width: 14px;
    height: 14px;
}
"""


# ─────────────────────── TitleBar ───────────────────────

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


# ─────────────────────── Picker overlay ───────────────────────

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


# ─────────────────────── Main window ───────────────────────

class GhostWindow(QWidget):
    exitSignal       = Signal()
    pickSignal       = Signal(object)
    uiSignal         = Signal(str, str)
    # qint64: HWND does not always fit into a 32-bit C++ int
    registerSignal   = Signal('qint64', 'qint64', str)
    markVisibleSignal = Signal('qint64', 'qint64')
    removeSignal     = Signal('qint64', 'qint64')
    refreshSignal    = Signal()

    def __init__(self):
        super().__init__()

        self.setObjectName("MainWindow")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(720, 600)
        self.resize(780, 680)
        self.setWindowTitle("GhostWindow")

        hide_console()

        self.target_hwnd  = None
        self.target_pid   = None
        self.target_title = ""
        self.injected     = []      # ONLY touched from the GUI thread
        self._exiting     = False
        self._picker      = None

        self.exitSignal.connect(self._on_exit_now)
        self.pickSignal.connect(self._on_pick_done)
        self.uiSignal.connect(self._on_ui_update)
        self.registerSignal.connect(self._register_injected)
        self.markVisibleSignal.connect(self._mark_visible)
        self.removeSignal.connect(self._remove_entry)
        self.refreshSignal.connect(self.refresh_list)

        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._auto_refresh)
        self.refresh_timer.start(2000)

        if not os.path.exists(DLL_PATH):
            self._set_status(f"{DLL_NAME} not found next to the script", "err")
        else:
            self._set_status("Ready", "info")

    # ─── UI ───

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(TitleBar(self))

        content = QWidget()
        content.setObjectName("Content")
        main.addWidget(content, 1)

        cl = QVBoxLayout(content)
        cl.setContentsMargins(24, 20, 24, 16)
        cl.setSpacing(16)

        # Description
        header = QLabel("Hide any window from OBS / Zoom / Discord, "
                        "remove it from the taskbar, keep it always on top")
        header.setObjectName("Header")
        header.setWordWrap(True)
        cl.addWidget(header)

        # ─── Target selection ───
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.btn_pick = QPushButton("Pick a window")
        self.btn_pick.setObjectName("PrimaryBtn")
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.btn_pick.setMinimumHeight(38)
        self.btn_pick.clicked.connect(self.pick)
        top_row.addWidget(self.btn_pick, 1)

        self.btn_hide_self = QPushButton("Hide GhostWindow")
        self.btn_hide_self.setCursor(Qt.PointingHandCursor)
        self.btn_hide_self.setMinimumHeight(38)
        self.btn_hide_self.clicked.connect(self.hide_self)
        top_row.addWidget(self.btn_hide_self, 1)

        cl.addLayout(top_row)

        # Target info
        self.info_lbl = QLabel("No window selected")
        self.info_lbl.setObjectName("TargetInfo")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setMinimumHeight(48)
        cl.addWidget(self.info_lbl)

        # Target actions
        act_row = QHBoxLayout()
        act_row.setSpacing(10)

        self.btn_hide = QPushButton("Hide")
        self.btn_hide.setCursor(Qt.PointingHandCursor)
        self.btn_hide.setMinimumHeight(36)
        self.btn_hide.setEnabled(False)
        self.btn_hide.clicked.connect(self.hide_target)
        act_row.addWidget(self.btn_hide, 1)

        self.btn_show = QPushButton("Show")
        self.btn_show.setCursor(Qt.PointingHandCursor)
        self.btn_show.setMinimumHeight(36)
        self.btn_show.setEnabled(False)
        self.btn_show.clicked.connect(self.show_target)
        act_row.addWidget(self.btn_show, 1)

        self.btn_restore = QPushButton("Bring to front")
        self.btn_restore.setCursor(Qt.PointingHandCursor)
        self.btn_restore.setMinimumHeight(36)
        self.btn_restore.setEnabled(False)
        self.btn_restore.clicked.connect(self.restore_target)
        act_row.addWidget(self.btn_restore, 1)

        cl.addLayout(act_row)

        # Status
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("Status")
        self.status_lbl.setWordWrap(True)
        cl.addWidget(self.status_lbl)

        # ─── List ───
        sec = QLabel("HIDDEN WINDOWS")
        sec.setObjectName("SectionTitle")
        cl.addWidget(sec)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["PROCESS", "PID", "WINDOW", "STATE"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(34)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(3, 120)

        cl.addWidget(self.table, 1)

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_list)
        bottom.addWidget(self.btn_refresh)

        self.btn_return = QPushButton("Restore")
        self.btn_return.setCursor(Qt.PointingHandCursor)
        self.btn_return.clicked.connect(self.detach_selected)
        bottom.addWidget(self.btn_return)

        self.btn_remove = QPushButton("Forget")
        self.btn_remove.setCursor(Qt.PointingHandCursor)
        self.btn_remove.setToolTip("Remove from the list only — "
                                   "the window STAYS hidden")
        self.btn_remove.clicked.connect(self.remove_from_list)
        bottom.addWidget(self.btn_remove)

        bottom.addStretch()

        self.btn_exit = QPushButton("Quit")
        self.btn_exit.setObjectName("DangerBtn")
        self.btn_exit.setCursor(Qt.PointingHandCursor)
        self.btn_exit.clicked.connect(self.quit_app)
        bottom.addWidget(self.btn_exit)

        cl.addLayout(bottom)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setFixedSize(14, 14)
        grip_row.addWidget(grip, 0, Qt.AlignRight | Qt.AlignBottom)
        cl.addLayout(grip_row)

    # ─── show / hide self ───

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(60, lambda: apply_stealth_to_hwnd(int(self.winId())))

    def closeEvent(self, event):
        # Alt+F4 must not kill the app while windows are still hidden.
        if self._exiting:
            event.accept()
            return
        event.ignore()
        self.hide_self()

    def show_self(self):
        if self._exiting:
            return
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(60, lambda: apply_stealth_to_hwnd(int(self.winId())))
        # Qt's activateWindow() is often ignored by Windows for background
        # processes — nudge the window forward via WinAPI once it's realized.
        QTimer.singleShot(30, self._force_foreground_now)

    def _force_foreground_now(self):
        try:
            force_foreground(int(self.winId()))
        except Exception:
            pass

    def hide_self(self):
        if self._exiting:
            return
        self.hide()

    def toggle_self(self):
        if self.isVisible() and not self.isMinimized():
            self.hide_self()
        else:
            self.show_self()

    def on_hotkey(self):
        if self._exiting:
            return
        if self._picker is not None:
            self._picker.cancel()      # cancel picking
            return
        self.toggle_self()

    # ─── status ───

    def _set_status(self, text, kind="info"):
        colors = {
            "info": "#6d7280",
            "ok":   "#4ade80",
            "err":  "#f87171",
            "busy": "#60a5fa",
        }
        color = colors.get(kind, "#6d7280")
        self.status_lbl.setStyleSheet(f"QLabel#Status {{ color: {color}; }}")
        self.status_lbl.setText(text)

    def _on_ui_update(self, text, kind):
        self._set_status(text, kind)

    def _on_exit_now(self):
        QApplication.instance().quit()

    # ─── list entry mutations (GUI thread only, via signals) ───

    def _register_injected(self, pid, hwnd, title):
        for e in self.injected:
            if e["pid"] == pid and e["hwnd"] == hwnd:
                e["state"] = "hidden"
                e["title"] = title
                e["visible"] = False
                self.refresh_list()
                return
        self.injected.append({
            "pid":    pid,
            "hwnd":   hwnd,
            "name":   get_process_name(pid),
            "title":  title,
            "state":  "hidden",
            "visible": False,          # False = re-hide watchdog is allowed
        })
        self.refresh_list()

    def _mark_visible(self, pid, hwnd):
        for e in self.injected:
            if e["pid"] == pid and e["hwnd"] == hwnd:
                e["visible"] = True
                break
        self.refresh_list()

    def _remove_entry(self, pid, hwnd):
        self.injected = [x for x in self.injected
                         if not (x["pid"] == pid and x["hwnd"] == hwnd)]
        self.refresh_list()

    # ─── auto-refresh ───

    def _auto_refresh(self):
        if self._exiting:
            return
        try:
            changed = False
            now = time.monotonic()
            rehide = []

            for e in list(self.injected):
                pid, hwnd = e["pid"], e["hwnd"]
                if not is_process_alive(pid) or not user32.IsWindow(hwnd):
                    changed = True
                    continue

                new_state = ("hidden" if find_module_base(pid, DLL_NAME)
                             else "detached")
                if e.get("state") != new_state:
                    e["state"] = new_state
                    changed = True

                # Watchdog: the target app reset capture exclusion
                # (window recreated / style cleared) — re-apply StealthHide.
                if (new_state == "hidden"
                        and not e.get("visible")
                        and not stealth_is_active(hwnd)
                        and now - e.get("last_rehide", 0.0) >= 5.0):
                    e["last_rehide"] = now
                    rehide.append((pid, hwnd))

            if changed:
                self.refresh_list()

            for pid, hwnd in rehide:
                self._rehide_async(pid, hwnd)
        except Exception:
            pass

    def _rehide_async(self, pid, hwnd):
        def job():
            try:
                call_export(pid, DLL_NAME, DLL_PATH, "StealthHide", hwnd)
                self.registerSignal.emit(pid, hwnd, get_title(hwnd) or "hidden")
            except Exception:
                pass
        threading.Thread(target=job, daemon=True).start()

    # ─── picking a window ───

    def pick(self):
        self.hide()
        self._picker = PickerOverlay()
        self._picker.finished.connect(self.pickSignal.emit)
        self._picker.start()

    def _on_pick_done(self, hwnd):
        self._picker = None
        self.show_self()

        if not hwnd or not user32.IsWindow(hwnd):
            self._set_status("Picking cancelled — no window identified", "err")
            return
        if hwnd == get_root(int(self.winId())):
            self._set_status("That is GhostWindow itself", "err")
            return

        self.target_hwnd  = hwnd
        self.target_pid   = get_pid(hwnd)
        self.target_title = get_title(hwnd) or "(untitled)"

        self.info_lbl.setStyleSheet(
            "QLabel#TargetInfo {"
            "  background-color: #16161c;"
            "  border: 1px solid #30303c;"
            "  border-radius: 6px;"
            "  padding: 10px 14px;"
            "  color: #f0f0f5;"
            "}"
        )
        self.info_lbl.setText(
            f"<b>{self.target_title}</b><br>"
            f"<span style='color:#6d7280; font-size: 9pt;'>"
            f"{get_process_name(self.target_pid)} &nbsp;·&nbsp; "
            f"PID {self.target_pid} &nbsp;·&nbsp; HWND {hwnd:#x}"
            f"</span>"
        )
        self.btn_hide.setEnabled(True)
        self.btn_show.setEnabled(True)
        self.btn_restore.setEnabled(True)
        self._set_status("Window selected", "ok")

    # ─── target actions ───

    def hide_target(self):
        if not self.target_pid or not self.target_hwnd:
            return
        pid, hwnd, title = self.target_pid, self.target_hwnd, self.target_title
        # Snapshot on the GUI thread: is the DLL already serving other
        # windows of this process? If yes — never detach on failure.
        dll_already_serves = any(x["pid"] == pid for x in self.injected)

        def job():
            try:
                self.uiSignal.emit("Injecting…", "busy")
                if not find_module_base(pid, DLL_NAME):
                    inject_dll(pid, DLL_PATH)
                call_export(pid, DLL_NAME, DLL_PATH, "StealthHide", hwnd)
                self.registerSignal.emit(pid, hwnd, title)
                self.uiSignal.emit("Window hidden", "ok")
            except Exception as ex:
                if not dll_already_serves:
                    # The DLL was loaded but the hide failed — don't leave
                    # an orphaned module in the target process.
                    try:
                        detach_dll(pid, DLL_NAME, DLL_PATH)
                    except Exception:
                        pass
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    def show_target(self):
        if not self.target_pid or not self.target_hwnd:
            return
        pid, hwnd = self.target_pid, self.target_hwnd

        def job():
            try:
                if find_module_base(pid, DLL_NAME):
                    call_export(pid, DLL_NAME, DLL_PATH, "StealthShow", hwnd)
                _restore_window(hwnd)
                self.markVisibleSignal.emit(pid, hwnd)   # stop the watchdog
                self.uiSignal.emit("Window is visible again", "ok")
            except Exception as ex:
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    def restore_target(self):
        hwnd = self.target_hwnd
        if not hwnd or not user32.IsWindow(hwnd):
            self._set_status("Window is already closed", "err")
            return
        if _restore_window(hwnd):
            self._set_status("Window brought to front", "ok")
        else:
            self._set_status("Failed to activate the window", "err")

    # ─── list ───

    def refresh_list(self):
        selected = self._selected_entry()

        alive = []
        for e in self.injected:
            if not is_process_alive(e["pid"]) or not user32.IsWindow(e["hwnd"]):
                continue
            t = get_title(e["hwnd"])
            if t:
                e["title"] = t
            e["state"] = ("hidden" if find_module_base(e["pid"], DLL_NAME)
                          else "detached")
            alive.append(e)
        self.injected = alive

        self.table.setRowCount(len(self.injected))
        for i, e in enumerate(self.injected):
            it_name  = QTableWidgetItem(e["name"])
            it_pid   = QTableWidgetItem(str(e["pid"]))
            it_pid.setTextAlignment(Qt.AlignCenter)
            it_title = QTableWidgetItem(e["title"])

            state_txt = e["state"]
            it_state = QTableWidgetItem(state_txt)
            if state_txt == "hidden":
                it_state.setForeground(QColor("#4ade80"))
            else:
                it_state.setForeground(QColor("#fbbf24"))

            self.table.setItem(i, 0, it_name)
            self.table.setItem(i, 1, it_pid)
            self.table.setItem(i, 2, it_title)
            self.table.setItem(i, 3, it_state)

        # Preserve the selection across rebuilds
        if selected is not None:
            for i, e in enumerate(self.injected):
                if e["pid"] == selected["pid"] and e["hwnd"] == selected["hwnd"]:
                    self.table.selectRow(i)
                    break

    def _selected_entry(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.injected):
            return None
        return self.injected[row]

    def detach_selected(self):
        e = self._selected_entry()
        if not e:
            QMessageBox.information(self, "No selection",
                                    "Select a window in the list first.")
            return

        pid, hwnd = e["pid"], e["hwnd"]
        name, title = e["name"], e["title"]

        if not is_process_alive(pid) or not user32.IsWindow(hwnd):
            self.refresh_list()
            return

        ans = QMessageBox.question(
            self, "Restore window",
            f"Restore window \"{title}\" from {name} (PID {pid})?\n\n"
            f"It will become visible to OBS/Zoom again and return to the taskbar.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if ans != QMessageBox.Yes:
            return

        # Snapshot on the GUI thread: does the DLL serve other windows here?
        others_same_pid = any(x["pid"] == pid and x["hwnd"] != hwnd
                              for x in self.injected)

        self._set_status("Restoring…", "busy")

        def job():
            try:
                ok = True
                if find_module_base(pid, DLL_NAME):
                    try:
                        call_export(pid, DLL_NAME, DLL_PATH, "StealthShow", hwnd)
                    except Exception as ex:
                        ok = False
                        self.uiSignal.emit(str(ex), "err")
                _restore_window(hwnd)
                if not others_same_pid:
                    detach_dll(pid, DLL_NAME, DLL_PATH)
                self.removeSignal.emit(pid, hwnd)
                if ok:
                    self.uiSignal.emit(f"Window \"{title}\" restored", "ok")
            except Exception as ex:
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    def remove_from_list(self):
        e = self._selected_entry()
        if not e:
            return
        ans = QMessageBox.question(
            self, "Forget window",
            f"Remove \"{e['title']}\" from the list?\n\n"
            "The window will STAY hidden and the DLL will remain loaded "
            "in the target process. Use this only if you no longer need "
            "to control it from here.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ans != QMessageBox.Yes:
            return
        self._remove_entry(e["pid"], e["hwnd"])

    # ─── quit ───

    def quit_app(self):
        if self._exiting:
            return

        if self.injected:
            ans = QMessageBox.question(
                self, "Quit",
                f"There are still {len(self.injected)} hidden windows in the list.\n\n"
                f"Restore them and detach the DLL before quitting?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if ans != QMessageBox.Yes:
                return

        self._exiting = True
        self._set_status("Shutting down…", "busy")

        # Frozen snapshot — the worker thread must not touch live state.
        entries = list(self.injected)
        pids = {e["pid"] for e in entries}

        def job():
            for e in entries:
                pid, hwnd = e["pid"], e["hwnd"]
                if not is_process_alive(pid):
                    continue
                try:
                    if user32.IsWindow(hwnd) and find_module_base(pid, DLL_NAME):
                        call_export(pid, DLL_NAME, DLL_PATH, "StealthShow", hwnd)
                except Exception:
                    pass

            for pid in pids:
                if is_process_alive(pid):
                    try:
                        detach_dll(pid, DLL_NAME, DLL_PATH)
                    except Exception:
                        pass

            self.exitSignal.emit()

        threading.Thread(target=job, daemon=True).start()


# ─────────────────────── Entry point ───────────────────────

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