"""
DLL injection and remote export calling.
"""

import os
import time
import ctypes
from ctypes import wintypes

from winapi import (
    kernel32,
    INJECT_ACCESS, CALL_ACCESS,
    MEM_COMMIT, MEM_RESERVE, MEM_RELEASE, PAGE_READWRITE,
    INFINITE,
)


_ERR_HINTS = {
    5:    "access denied",
    87:   "invalid parameter",
    1400: "invalid window handle",
}


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


def call_export(pid, dll_name, dll_path, func_name, param=0):
    """Call an exported DWORD WINAPI f(LPVOID) inside the target process.

    Raises OSError if the remote export returned a non-zero error code.
    """
    from helpers import find_module_base

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
    from helpers import find_module_base

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
    from helpers import find_module_base

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
