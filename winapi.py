import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32   = ctypes.WinDLL("user32",   use_last_error=True)

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
WS_EX_TOPMOST    = 0x00000008
WS_EX_NOACTIVATE = 0x08000000      # NEW
WS_EX_LAYERED    = 0x00080000      # NEW

SWP_NOSIZE       = 0x0001
SWP_NOMOVE       = 0x0002
SWP_NOZORDER     = 0x0004
SWP_NOACTIVATE   = 0x0010
SWP_FRAMECHANGED = 0x0020

HWND_TOPMOST   = -1
HWND_NOTOPMOST = -2

WM_HOTKEY    = 0x0312
MOD_CONTROL  = 0x0002
MOD_SHIFT    = 0x0004
MOD_NOREPEAT = 0x4000
HOTKEY_ID       = 1
HOTKEY_ID_PIN   = 2
HOTKEY_ID_FRONT = 3

VK_F3           = 0x72
VK_F4           = 0x73
VK_F5           = 0x74
VK_MENU         = 0x12
KEYEVENTF_KEYUP = 0x0002

GW_OWNER = 4                       # NEW


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):      # NEW
    _fields_ = [("left",   ctypes.c_long),
                ("top",    ctypes.c_long),
                ("right",  ctypes.c_long),
                ("bottom", ctypes.c_long)]


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
user32.IsWindowVisible.argtypes      = [wintypes.HWND]     # NEW
user32.IsWindowVisible.restype       = wintypes.BOOL       # NEW
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

# NEW: для переліку вікон процесу
user32.EnumWindows.argtypes          = [ctypes.c_void_p, wintypes.LPARAM]
user32.EnumWindows.restype           = wintypes.BOOL
user32.GetWindow.argtypes            = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype             = wintypes.HWND
user32.GetWindowRect.argtypes        = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype         = wintypes.BOOL