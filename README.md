# GhostWindow

**GhostWindow** — a Windows utility that hides any window from screen capture (OBS, Zoom, Discord, etc.), removes it from the taskbar and Alt+Tab, and keeps it on top of other windows.

Works by injecting a DLL into the target process and using `SetWindowDisplayAffinity` (Windows 10 2004+).

---

## Features

- Hide a window from screen capture (OBS, Zoom, Discord, Teams, etc.)
- Remove from taskbar and Alt+Tab
- Keep on top of other windows
- Hotkeys — show/hide GhostWindow, pin/unpin target, bring to front
- Pick mode with countdown timer to select a window under the cursor
- Watchdog — automatically re-hides if the target process resets window styles
- Cursor lock — forces the default arrow cursor on hidden windows (prevents custom cursors from appearing)
- Restore windows individually or all at once on exit

---

## Requirements

- Windows 10 2004+ or Windows 11
- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/)
- Administrator rights (for injecting into elevated or other-user processes)

---

## Installation

```bash
git clone https://github.com/yourusername/GhostWindow.git
cd GhostWindow
pip install PySide6
```

---

## Building GhostWindow.dll

The DLL is already built and included in the repository. To rebuild:

### Visual Studio (MSVC)

```bat
:: x64 Native Tools Command Prompt for VS
cl /nologo /LD /O2 /EHsc /W4 GhostWindow.cpp /Fe:GhostWindow.dll /link /DEF:GhostWindow.def
```

### MinGW-w64

```bash
g++ -O2 -shared -o GhostWindow.dll GhostWindow.cpp GhostWindow.def -luser32 -static
```

---

## Usage

### Running

```bash
:: Run as administrator (recommended)
python ghostwindow.py
```

### Hiding a window

1. Click **"Pick a window"** — a 5-second countdown appears
2. Point your cursor at the target window during the countdown
3. After selection, click **"Hide"**
4. The window disappears from the taskbar, screen capture, and Alt+Tab

### Showing a window again

- Select it in the **"HIDDEN WINDOWS"** list and click **"Show"** or **"Restore"**
- Or click **"Restore"** in the bottom bar to restore all windows

### Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+F3` | Show/hide the GhostWindow window |
| `Ctrl+Shift+F4` | Pin/unpin the selected window (toggle always-on-top) |
| `Ctrl+Shift+F5` | Bring the selected window to front |

- During pick mode, `Ctrl+Shift+F3` cancels the selection

### Buttons

| Button | Action |
|--------|--------|
| **Pick a window** | Select a window under the cursor |
| **Hide GhostWindow** | Hide GhostWindow itself |
| **Hide** | Hide the selected window |
| **Show** | Show the selected window |
| **Bring to front** | Activate the selected window |
| **Refresh** | Refresh the hidden windows list |
| **Restore** | Restore the selected window (un-hide) |
| **Forget** | Remove from the list (window stays hidden) |
| **Quit** | Exit, restoring all windows |

---

## Project Structure

```
GhostWindow/
├── ghostwindow.py    — entry point
├── main_window.py    — main window, UI, logic
├── winapi.py         — WinAPI constants, ctypes declarations
├── helpers.py        — window/process helper functions
├── injection.py      — DLL injection and remote export calling
├── constants.py      — constants and styles
├── hotkey.py         — global hotkey filter
├── titlebar.py       — custom title bar widget
├── picker.py         — picker overlay for window selection
├── cursor_lock.py    — in-process cursor lock (forces arrow cursor)
├── GhostWindow.cpp   — DLL source
├── GhostWindow.def   — DLL exports
└── GhostWindow.dll   — built DLL
```

---

## How It Works

1. **Injection** — `LoadLibraryW` via `CreateRemoteThread` with the DLL path
2. **StealthHide** — the DLL calls:
   - `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` — exclude from capture
   - `WS_EX_TOOLWINDOW` — remove from taskbar
   - `HWND_TOPMOST` — keep on top
3. **StealthShow** — restore the original state (styles are saved in window properties)
4. **Cursor Lock** — `cursor_lock.py` hooks `WM_SETCURSOR` and mouse messages on the target window and all its children, forcing the default arrow cursor. A watchdog timer (~30 ms) re-applies the cursor if Qt or the target app changes it programmatically.

---

## Known Limitations

- Some anti-cheats may block DLL injection
- UWP/Store apps may not support `SetWindowDisplayAffinity`
- Administrator rights are required to inject into elevated processes

---

## License

MIT
