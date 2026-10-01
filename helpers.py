import os
import ctypes
from ctypes import wintypes

from winapi import (
    kernel32, user32,
    PROCESS_QUERY_LIMITED, GA_ROOT, WDA_EXCLUDEFROMCAPTURE, WDA_MONITOR,
    SW_RESTORE, SW_SHOW, GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW,
    SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED,
    TH32CS_SNAPMODULE, TH32CS_SNAPMODULE32, MODULEENTRY32W,
    POINT, VK_MENU, KEYEVENTF_KEYUP,
)


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
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)

        user32.keybd_event(VK_MENU, 0, 0, None)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)

        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def apply_stealth_to_hwnd(hwnd):
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
            user32.ShowWindow(hwnd, 0)
    except Exception:
        pass