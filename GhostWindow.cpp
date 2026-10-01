// GhostWindow.cpp
//
// DLL, що ін'єктується в цільовий процес.
// Експорти (всі повертають 0 при успіху або Win32-код помилки):
//   GhostVersion()    — версія DLL (перевірка з інжектора)
//   StealthHide(hwnd) — приховати вікно з захоплення екрана, таскбару,
//                       тримати поверх. Оригінальний стиль зберігається
//                       у window properties для точного відновлення.
//   StealthShow(hwnd) — відновити початковий стан вікна.
//
// Збірка (x64 Native Tools Command Prompt for VS):
//   cl /nologo /LD /O2 /EHsc /W4 GhostWindow.cpp /Fe:GhostWindow.dll /link /DEF:GhostWindow.def
//
// MinGW-w64:
//   g++ -O2 -shared -o GhostWindow.dll GhostWindow.cpp GhostWindow.def -luser32 -static

#include <Windows.h>

#pragma comment(lib, "user32.lib")

#ifndef WDA_EXCLUDEFROMCAPTURE
#define WDA_EXCLUDEFROMCAPTURE 0x00000011   // Win10 2004+
#endif
#ifndef WDA_MONITOR
#define WDA_MONITOR 0x00000001              // fallback: чорний прямокутник у захопленні
#endif
#ifndef WDA_NONE
#define WDA_NONE 0x00000000
#endif

static const wchar_t PROP_ORIG_STYLE[] = L"GW_OrigExStyle";
static const wchar_t PROP_SAVED[]      = L"GW_Saved";

extern "C" __declspec(dllexport) DWORD WINAPI GhostVersion(void)
{
    return 1;
}

extern "C" __declspec(dllexport) DWORD WINAPI StealthHide(LPVOID param)
{
    HWND hwnd = reinterpret_cast<HWND>(param);
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    hwnd = GetAncestor(hwnd, GA_ROOT);          // страховка від child-hwnd
    if (!hwnd || !IsWindow(hwnd))
        return 1;

    // 1. Виключити з захоплення екрана.
    if (!SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE) &&
        !SetWindowDisplayAffinity(hwnd, WDA_MONITOR))
    {
        DWORD err = GetLastError();
        return err ? err : 2;
    }

    // 2. Зберегти оригінальний стан ОДИН РАЗ (ідемпотентність).
    if (!GetPropW(hwnd, PROP_SAVED)) {
        LONG_PTR ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        SetPropW(hwnd, PROP_ORIG_STYLE, reinterpret_cast<HANDLE>(ex));
        SetPropW(hwnd, PROP_SAVED, reinterpret_cast<HANDLE>(1));
    }

    // 3. Прибрати з таскбару / Alt-Tab.
    LONG_PTR ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
    ex |= WS_EX_TOOLWINDOW;
    ex &= ~WS_EX_APPWINDOW;
    SetLastError(0);
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex);
    DWORD err = GetLastError();

    // 4. Поверх; FRAMECHANGED змушує таскбар перемалюватися.
    SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED);

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

    SetWindowDisplayAffinity(hwnd, WDA_NONE);

    LONG_PTR ex;
    BOOL was_topmost = FALSE;
    const bool have_saved = GetPropW(hwnd, PROP_SAVED) != nullptr;

    if (have_saved) {
        ex = reinterpret_cast<LONG_PTR>(GetPropW(hwnd, PROP_ORIG_STYLE));
        was_topmost = (ex & WS_EX_TOPMOST) ? TRUE : FALSE;
    } else {
        // Приховано старим білдом без збереженого стану — best effort.
        ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        ex |= WS_EX_APPWINDOW;
        ex &= ~WS_EX_TOOLWINDOW;
    }

    SetLastError(0);
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex);
    DWORD err = GetLastError();

    SetWindowPos(hwnd,
                 was_topmost ? HWND_TOPMOST : HWND_NOTOPMOST,
                 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED);

    if (have_saved) {
        RemovePropW(hwnd, PROP_ORIG_STYLE);
        RemovePropW(hwnd, PROP_SAVED);
    }
    return err;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(hModule);
    return TRUE;
}