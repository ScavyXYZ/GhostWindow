// GhostWindow.cpp
//
// Build (x64 Native Tools Command Prompt for VS):
//   cl /nologo /LD /O2 /EHsc /W4 GhostWindow.cpp /Fe:GhostWindow.dll /link /DEF:GhostWindow.def
// MinGW-w64:
//   g++ -O2 -shared -o GhostWindow.dll GhostWindow.cpp GhostWindow.def -luser32 -static
//
// Exports (GhostWindow.def does not need to change):
//   GhostVersion, StealthHide, StealthShow, StealthPin, StealthUnpin

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

static const wchar_t PROP_ORIG_STYLE[]   = L"GW_OrigExStyle";
static const wchar_t PROP_SAVED[]        = L"GW_Saved";
static const wchar_t PROP_ORIG_PROC[]    = L"GW_OrigProc";
static const wchar_t PROP_PROC_HOOKED[]  = L"GW_ProcHooked";
static const wchar_t PROP_LOCK_OFF[]     = L"GW_LockOff";

// Pin props
static const wchar_t PROP_PINNED[]       = L"GW_Pinned";
static const wchar_t PROP_WAS_TOP[]      = L"GW_WasTopmost";

// FIX: per-root ownership of one g_lockRefCount reference, independent of
// PROP_PROC_HOOKED (which can stay set after a "pass-through" unhook).
static const wchar_t PROP_HOLDS_REF[]    = L"GW_HoldsRef";

// Watchdog props
static const wchar_t PROP_TIMER[]        = L"GW_Timer";
static const wchar_t PROP_TICK_PENDING[] = L"GW_TickPending";

static const DWORD WATCHDOG_MS = 30;

// ===========================================================================
// Cursor lock
// ===========================================================================
// Goal: while the window is hidden, the cursor over it is always the plain
// arrow (no I-beam, no resize borders, no hand), so stream viewers never
// see the cursor change over an "empty" area.
//
// Layers:
//  1) WM_SETCURSOR interception on the root window AND every child
//     (the message is sent to the deepest window under the cursor).
//  2) Re-assert the arrow after mouse messages: some apps call SetCursor()
//     directly inside WM_MOUSEMOVE handlers, bypassing WM_SETCURSOR.
//  3) WATCHDOG: a timer-queue timer posts a private message to the root
//     every WATCHDOG_MS. The root's wndproc (= the window's own thread,
//     the only thread whose SetCursor() has any effect) re-asserts the
//     arrow if the mouse is over the window. This covers SetCursor() calls
//     made outside of mouse messages (programmatic setCursor, widget
//     show/hide, layout changes under a stationary mouse, ...).
//     The same tick also subclasses child windows created after hiding,
//     so we no longer depend on the WinEvent hook for that.
//  4) Child windows created AFTER hiding are additionally subclassed
//     through an in-process SetWinEventHook (best effort; see note at
//     AcquireNewWindowHook).
// ===========================================================================

// --- forward declarations ---------------------------------------------------

static LRESULT CALLBACK CursorLockProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);
static void ReleaseNewWindowHook();
static void StopWatchdog(HWND root);

// --- misc helpers -----------------------------------------------------------

static HCURSOR GetArrowCursor()
{
    static HCURSOR arrow = LoadCursorW(nullptr, IDC_ARROW); // thread-safe init
    return arrow;
}

static UINT GetTickMsg()
{
    static UINT m = RegisterWindowMessageW(L"GhostWindow_CursorTick");
    return m;
}

// Resolve this DLL's own module handle (for SetWinEventHook's hmodule
// argument) without touching its reference count. We deliberately do NOT
// pin the module here: StealthShow always removes every hook and stops the
// watchdog before the app calls FreeLibrary (see injection.py:detach_dll),
// so by the time unload happens nothing of ours is left subclassed. Pinning
// would make the DLL permanently un-unloadable for the life of the process,
// which breaks that detach flow (Restore / Quit) outright.
static HMODULE GetSelfModule()
{
    HMODULE self = nullptr;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&CursorLockProc), &self);
    return self;
}

static bool CursorOverRoot(HWND root)
{
    POINT pt;
    if (!GetCursorPos(&pt))
        return false;
    HWND h = WindowFromPoint(pt);
    return h && GetAncestor(h, GA_ROOT) == root;
}

// --- subclassing helpers (declared early: the proc uses them) ---------------

// rearm == true  : called from StealthHide path -> a window that was left in
//                  pass-through mode (LOCK_OFF) gets its lock switched back on.
// rearm == false : called from watchdog / WinEvent path -> never touches an
//                  existing hook.
static void HookSingleWindow(HWND hwnd, bool rearm = false)
{
    if (!hwnd || !IsWindow(hwnd))
        return;

    if (GetPropW(hwnd, PROP_PROC_HOOKED)) {
        // FIX: already hooked, but maybe in pass-through mode after an
        // earlier StealthShow where someone had subclassed on top of us.
        // Without this the lock never came back on the next StealthHide.
        if (rearm)
            RemovePropW(hwnd, PROP_LOCK_OFF);
        return;
    }

    SetLastError(0);
    LONG_PTR orig = SetWindowLongPtrW(
        hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(CursorLockProc));
    if (orig == 0 && GetLastError() != 0)
        return;                                  // protected class, etc.

    SetPropW(hwnd, PROP_ORIG_PROC,   reinterpret_cast<HANDLE>(orig));
    SetPropW(hwnd, PROP_PROC_HOOKED, reinterpret_cast<HANDLE>(1));
}

static BOOL CALLBACK HookChildrenCallback(HWND child, LPARAM rearm)
{
    HookSingleWindow(child, rearm != 0);
    return TRUE;
    // EnumChildWindows already enumerates ALL descendants
    // (children of children included) - no manual recursion needed.
}

// --- the window procedure ---------------------------------------------------

static LRESULT CALLBACK CursorLockProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    BOOL lock_active = GetPropW(hwnd, PROP_LOCK_OFF) == nullptr;

    // Watchdog tick (posted by TickTimerProc to the root window only).
    if (msg == GetTickMsg()) {
        RemovePropW(hwnd, PROP_TICK_PENDING);
        if (lock_active) {
            EnumChildWindows(hwnd, HookChildrenCallback, 0);  // late children
            if (CursorOverRoot(hwnd))
                SetCursor(GetArrowCursor());
        }
        return 0;                                // our private message, consume
    }

    if (msg == WM_SETCURSOR && lock_active) {
        SetCursor(GetArrowCursor());
        return TRUE;   // handled -> DefWindowProc / parent chain never runs
    }

    WNDPROC orig = reinterpret_cast<WNDPROC>(GetPropW(hwnd, PROP_ORIG_PROC));

    if (msg == WM_NCDESTROY) {
        // Window dies while locked: stop its watchdog, give back the
        // refcount, and don't leave props behind.
        StopWatchdog(hwnd);
        if (RemovePropW(hwnd, PROP_HOLDS_REF))
            ReleaseNewWindowHook();

        LRESULT r = orig
            ? CallWindowProcW(orig, hwnd, msg, wp, lp)
            : DefWindowProcW(hwnd, msg, wp, lp);

        RemovePropW(hwnd, PROP_ORIG_PROC);
        RemovePropW(hwnd, PROP_PROC_HOOKED);
        RemovePropW(hwnd, PROP_LOCK_OFF);
        return r;
    }

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

// --- install / remove -------------------------------------------------------

static void InstallCursorLock(HWND hwnd)
{
    if (!hwnd || !IsWindow(hwnd))
        return;
    HookSingleWindow(hwnd, /*rearm=*/true);
    EnumChildWindows(hwnd, HookChildrenCallback, /*rearm=*/1);
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
        // the app - instead just switch our layer to pass-through mode.
        // (HookSingleWindow(rearm=true) switches it back on at next hide.)
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

// --- watchdog ---------------------------------------------------------------

static VOID CALLBACK TickTimerProc(PVOID param, BOOLEAN)
{
    // Runs on a timer-queue thread. SetCursor() from here would do nothing,
    // so we only bounce a message to the window's own thread.
    HWND hwnd = static_cast<HWND>(param);
    if (!IsWindow(hwnd))
        return;
    if (GetPropW(hwnd, PROP_TICK_PENDING))
        return;                                  // coalesce if UI thread is busy
    SetPropW(hwnd, PROP_TICK_PENDING, reinterpret_cast<HANDLE>(1));
    if (!PostMessageW(hwnd, GetTickMsg(), 0, 0))
        RemovePropW(hwnd, PROP_TICK_PENDING);
}

static void StartWatchdog(HWND root)
{
    if (GetPropW(root, PROP_TIMER))
        return;                                  // already running
    HANDLE timer = nullptr;
    if (CreateTimerQueueTimer(&timer, nullptr, TickTimerProc, root,
                              WATCHDOG_MS, WATCHDOG_MS,
                              WT_EXECUTEINTIMERTHREAD))
        SetPropW(root, PROP_TIMER, timer);
}

static void StopWatchdog(HWND root)
{
    HANDLE timer = RemovePropW(root, PROP_TIMER);
    if (timer) {
        // NULL completion event -> returns immediately; a callback that is
        // already running just posts one last harmless message.
        DeleteTimerQueueTimer(nullptr, timer, nullptr);
    }
    RemovePropW(root, PROP_TICK_PENDING);
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
    // Skip roots that are in pass-through mode.
    if (root && GetPropW(root, PROP_PROC_HOOKED) && !GetPropW(root, PROP_LOCK_OFF))
        HookSingleWindow(hwnd);
}

// NOTE: a WinEvent hook is bound to the thread that installed it and is
// removed by the system when that thread exits. If StealthHide is called
// from a short-lived (e.g. remote) thread, this hook may silently vanish;
// that is why the watchdog tick above also subclasses new child windows.
static void AcquireNewWindowHook()
{
    if (InterlockedIncrement(&g_lockRefCount) == 1) {
        HMODULE self = GetSelfModule();

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
    return 4;   // 4: fixed re-arm/refcount, cursor watchdog (no permanent pin)
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

    InstallCursorLock(hwnd);

    // FIX: the refcount reference is owned per root window and taken
    // exactly once, no matter what state PROP_PROC_HOOKED is in.
    if (!GetPropW(hwnd, PROP_HOLDS_REF)) {
        SetPropW(hwnd, PROP_HOLDS_REF, reinterpret_cast<HANDLE>(1));
        AcquireNewWindowHook();
    }

    StartWatchdog(hwnd);

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

    StopWatchdog(hwnd);

    if (GetPropW(hwnd, PROP_PROC_HOOKED))
        RemoveCursorLock(hwnd);

    // FIX: release exactly the reference this root took in StealthHide.
    if (RemovePropW(hwnd, PROP_HOLDS_REF))
        ReleaseNewWindowHook();

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

    // If the user pinned the window separately (StealthPin), keep topmost.
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

// --- pin / unpin ------------------------------------------------------------

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