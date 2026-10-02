// GhostWindow.cpp
//
// Build (x64 Native Tools Command Prompt for VS):
//   cl /nologo /LD /O2 /EHsc /W4 GhostWindow.cpp /Fe:GhostWindow.dll /link /DEF:GhostWindow.def
// MinGW-w64:
//   g++ -O2 -shared -o GhostWindow.dll GhostWindow.cpp GhostWindow.def -luser32 -static

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <Windows.h>

#pragma comment(lib, "user32.lib")

#ifndef WDA_EXCLUDEFROMCAPTURE
#define WDA_EXCLUDEFROMCAPTURE 0x00000011
#endif
#ifndef WDA_MONITOR
#define WDA_MONITOR 0x00000001
#endif
#ifndef WDA_NONE
#define WDA_NONE 0x00000000
#endif

static const wchar_t PROP_ORIG_STYLE[]  = L"GW_OrigExStyle";
static const wchar_t PROP_SAVED[]       = L"GW_Saved";
static const wchar_t PROP_ORIG_PROC[]   = L"GW_OrigProc";
static const wchar_t PROP_PROC_HOOKED[] = L"GW_ProcHooked";
static const wchar_t PROP_LOCK_OFF[]    = L"GW_LockOff";

// NEW: pin props
static const wchar_t PROP_PINNED[]      = L"GW_Pinned";
static const wchar_t PROP_WAS_TOP[]     = L"GW_WasTopmost";

// ===========================================================================
// Cursor lock
// ===========================================================================
// Goal: while the window is hidden, the cursor over it is always the plain
// arrow (no I-beam, no resize borders, no hand), so stream viewers never
// see the cursor change over an "empty" area.
//
// Three layers:
//  1) WM_SETCURSOR interception on the root window AND every child
//     (the message is sent to the deepest window under the cursor).
//  2) Re-assert the arrow after mouse messages: some apps call SetCursor()
//     directly inside WM_MOUSEMOVE handlers, bypassing WM_SETCURSOR.
//  3) Child windows created AFTER hiding are auto-subclassed through an
//     in-process SetWinEventHook (EVENT_OBJECT_CREATE / EVENT_OBJECT_SHOW).
// ===========================================================================

static HCURSOR GetArrowCursor()
{
    static HCURSOR arrow = LoadCursorW(nullptr, IDC_ARROW); // thread-safe init
    return arrow;
}

static LRESULT CALLBACK CursorLockProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    BOOL lock_active = GetPropW(hwnd, PROP_LOCK_OFF) == nullptr;

    if (msg == WM_SETCURSOR && lock_active) {
        SetCursor(GetArrowCursor());
        return TRUE;   // handled -> DefWindowProc / parent chain never runs
    }

    WNDPROC orig = reinterpret_cast<WNDPROC>(GetPropW(hwnd, PROP_ORIG_PROC));
    LRESULT res = orig
        ? CallWindowProcW(orig, hwnd, msg, wp, lp)
        : DefWindowProcW(hwnd, msg, wp, lp);

    // Defeat direct SetCursor() calls inside the app's mouse handlers:
    // the last SetCursor wins, so we set the arrow after the app did.
    if (lock_active) {
        switch (msg) {
            case WM_MOUSEMOVE:     case WM_NCMOUSEMOVE:
            case WM_LBUTTONDOWN:   case WM_LBUTTONUP:   case WM_LBUTTONDBLCLK:
            case WM_RBUTTONDOWN:   case WM_RBUTTONUP:   case WM_RBUTTONDBLCLK:
            case WM_MBUTTONDOWN:   case WM_MBUTTONUP:   case WM_MBUTTONDBLCLK:
            case WM_NCLBUTTONDOWN: case WM_NCLBUTTONUP:
            case WM_NCRBUTTONDOWN: case WM_NCRBUTTONUP:
                SetCursor(GetArrowCursor());
                break;
            default:
                break;
        }
    }
    return res;
}

// --- subclassing helpers ----------------------------------------------------

static void HookSingleWindow(HWND hwnd)
{
    if (!hwnd || !IsWindow(hwnd))
        return;
    if (GetPropW(hwnd, PROP_PROC_HOOKED))
        return;                                  // already hooked

    SetLastError(0);
    LONG_PTR orig = SetWindowLongPtrW(
        hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(CursorLockProc));
    if (orig == 0 && GetLastError() != 0)
        return;                                  // protected class, etc.

    SetPropW(hwnd, PROP_ORIG_PROC,   reinterpret_cast<HANDLE>(orig));
    SetPropW(hwnd, PROP_PROC_HOOKED, reinterpret_cast<HANDLE>(1));
}

static BOOL CALLBACK HookChildrenCallback(HWND child, LPARAM)
{
    HookSingleWindow(child);
    return TRUE;
    // EnumChildWindows already enumerates ALL descendants
    // (children of children included) — no manual recursion needed.
}

static void InstallCursorLock(HWND hwnd)
{
    if (!hwnd || !IsWindow(hwnd))
        return;
    HookSingleWindow(hwnd);
    EnumChildWindows(hwnd, HookChildrenCallback, 0);
}

static void UnhookSingleWindow(HWND hwnd)
{
    if (!GetPropW(hwnd, PROP_PROC_HOOKED))
        return;

    LONG_PTR orig = reinterpret_cast<LONG_PTR>(GetPropW(hwnd, PROP_ORIG_PROC));
    LONG_PTR cur  = GetWindowLongPtrW(hwnd, GWLP_WNDPROC);

    if (orig && cur == reinterpret_cast<LONG_PTR>(CursorLockProc)) {
        // Our hook is still on top of the chain -> safe to restore.
        SetWindowLongPtrW(hwnd, GWLP_WNDPROC, orig);
        RemovePropW(hwnd, PROP_ORIG_PROC);
        RemovePropW(hwnd, PROP_PROC_HOOKED);
        RemovePropW(hwnd, PROP_LOCK_OFF);
    } else {
        // The app made its own subclass on top of ours while hidden.
        // Restoring now would rip its procedure out of the chain and break
        // the app — instead just switch our layer to pass-through mode.
        SetPropW(hwnd, PROP_LOCK_OFF, reinterpret_cast<HANDLE>(1));
    }
}

static BOOL CALLBACK UnhookChildrenCallback(HWND child, LPARAM)
{
    UnhookSingleWindow(child);
    return TRUE;
}

static void RemoveCursorLock(HWND hwnd)
{
    if (!hwnd || !IsWindow(hwnd))
        return;
    UnhookSingleWindow(hwnd);
    EnumChildWindows(hwnd, UnhookChildrenCallback, 0);
}

// --- auto-hook windows created while hidden ---------------------------------

static volatile LONG g_lockRefCount = 0;
static HWINEVENTHOOK g_newWndHook   = nullptr;

static void CALLBACK NewWindowEvent(HWINEVENTHOOK, DWORD event, HWND hwnd,
                                    LONG idObject, LONG idChild,
                                    DWORD, DWORD)
{
    if (!hwnd || idObject != OBJID_WINDOW || idChild != 0)
        return;
    if (event != EVENT_OBJECT_CREATE && event != EVENT_OBJECT_SHOW)
        return;

    HWND root = GetAncestor(hwnd, GA_ROOT);
    if (root && GetPropW(root, PROP_PROC_HOOKED))
        HookSingleWindow(hwnd);
}

static void AcquireNewWindowHook()
{
    if (InterlockedIncrement(&g_lockRefCount) == 1) {
        HMODULE self = nullptr;
        GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
            GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(&CursorLockProc), &self);

        g_newWndHook = SetWinEventHook(
            EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW,
            self, NewWindowEvent,
            GetCurrentProcessId(), 0,
            WINEVENT_INCONTEXT);
    }
}

static void ReleaseNewWindowHook()
{
    if (InterlockedDecrement(&g_lockRefCount) == 0 && g_newWndHook) {
        UnhookWinEvent(g_newWndHook);
        g_newWndHook = nullptr;
    }
}

// ===========================================================================
// Exports
// ===========================================================================

extern "C" __declspec(dllexport) DWORD WINAPI GhostVersion(void)
{
    return 3;   // NEW: bump — тепер підтримується pin
}

extern "C" __declspec(dllexport) DWORD WINAPI StealthHide(LPVOID param)
{
    HWND hwnd = reinterpret_cast<HWND>(param);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    hwnd = GetAncestor(hwnd, GA_ROOT);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    if (!SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE) &&
        !SetWindowDisplayAffinity(hwnd, WDA_MONITOR))
    {
        DWORD err = GetLastError();
        return err ? err : 2;
    }

    if (!GetPropW(hwnd, PROP_SAVED)) {
        LONG_PTR ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        SetPropW(hwnd, PROP_ORIG_STYLE, reinterpret_cast<HANDLE>(ex));
        SetPropW(hwnd, PROP_SAVED, reinterpret_cast<HANDLE>(1));
    }

    LONG_PTR ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
    ex |= WS_EX_TOOLWINDOW;
    ex &= ~WS_EX_APPWINDOW;
    SetLastError(0);
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex);
    DWORD err = GetLastError();

    SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED);

    BOOL already_locked = GetPropW(hwnd, PROP_PROC_HOOKED) != nullptr;
    InstallCursorLock(hwnd);
    if (!already_locked)
        AcquireNewWindowHook();

    return err;
}

extern "C" __declspec(dllexport) DWORD WINAPI StealthShow(LPVOID param)
{
    HWND hwnd = reinterpret_cast<HWND>(param);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    hwnd = GetAncestor(hwnd, GA_ROOT);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    if (GetPropW(hwnd, PROP_PROC_HOOKED)) {
        RemoveCursorLock(hwnd);
        ReleaseNewWindowHook();
    }

    SetWindowDisplayAffinity(hwnd, WDA_NONE);

    LONG_PTR ex;
    BOOL was_topmost = FALSE;
    const bool have_saved = GetPropW(hwnd, PROP_SAVED) != nullptr;

    if (have_saved) {
        ex = reinterpret_cast<LONG_PTR>(GetPropW(hwnd, PROP_ORIG_STYLE));
        was_topmost = (ex & WS_EX_TOPMOST) ? TRUE : FALSE;
    } else {
        ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        ex |= WS_EX_APPWINDOW;
        ex &= ~WS_EX_TOOLWINDOW;
    }

    SetLastError(0);
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex);
    DWORD err = GetLastError();

    // NEW: якщо користувач окремо закріпив вікно (StealthPin), не скидаємо topmost
    BOOL pinned = GetPropW(hwnd, PROP_PINNED) != nullptr;

    SetWindowPos(hwnd,
                 (pinned || was_topmost) ? HWND_TOPMOST : HWND_NOTOPMOST,
                 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED);

    if (have_saved) {
        RemovePropW(hwnd, PROP_ORIG_STYLE);
        RemovePropW(hwnd, PROP_SAVED);
    }
    return err;
}

// --- NEW: pin / unpin -------------------------------------------------------

extern "C" __declspec(dllexport) DWORD WINAPI StealthPin(LPVOID param)
{
    HWND hwnd = reinterpret_cast<HWND>(param);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    hwnd = GetAncestor(hwnd, GA_ROOT);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    if (!GetPropW(hwnd, PROP_PINNED)) {
        LONG_PTR ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        BOOL was_top = (ex & WS_EX_TOPMOST) ? TRUE : FALSE;
        SetPropW(hwnd, PROP_WAS_TOP, reinterpret_cast<HANDLE>(was_top));
        SetPropW(hwnd, PROP_PINNED,  reinterpret_cast<HANDLE>(1));
    }

    if (!SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))
        return GetLastError();

    return 0;
}

extern "C" __declspec(dllexport) DWORD WINAPI StealthUnpin(LPVOID param)
{
    HWND hwnd = reinterpret_cast<HWND>(param);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    hwnd = GetAncestor(hwnd, GA_ROOT);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    BOOL was_top = FALSE;
    if (GetPropW(hwnd, PROP_PINNED)) {
        was_top = reinterpret_cast<LONG_PTR>(
                      GetPropW(hwnd, PROP_WAS_TOP)) ? TRUE : FALSE;
        RemovePropW(hwnd, PROP_WAS_TOP);
        RemovePropW(hwnd, PROP_PINNED);
    }

    if (!SetWindowPos(hwnd, was_top ? HWND_TOPMOST : HWND_NOTOPMOST,
                      0, 0, 0, 0,
                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))
        return GetLastError();

    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(hModule);
    return TRUE;
}