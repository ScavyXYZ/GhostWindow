# GhostWindow

**GhostWindow** — утиліта для Windows, яка приховує будь-яке вікно від захоплення екрана (OBS, Zoom, Discord тощо), прибирає його з панелі задач і Alt+Tab, і тримає поверх інших вікон.

Працює через інжекцію DLL у цільовий процес і використання `SetWindowDisplayAffinity` (Windows 10 2004+).

---

## Можливості

- Приховування вікна від захоплення екрана (OBS, Zoom, Discord, Teams, тощо)
- Видалення з панелі задач і Alt+Tab
- Закріплення поверх інших вікон
- Гаряча клавіша `Ctrl+Shift+F1` — показати/сховати саму GhostWindow
- Вибір вікна під курсором (pick mode з таймером)
- Watchdog — автоматичне повторне приховування, якщо цільовий процес скидає стилі
- Відновлення вікон по одному або все разом при виході

---

## Вимоги

- Windows 10 2004+ або Windows 11
- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/)
- Права адміністратора (для інжекції в процеси інших користувачів / elevated)

---

## Встановлення

```bash
git clone https://github.com/yourusername/GhostWindow.git
cd GhostWindow
pip install PySide6
```

---

## Збірка GhostWindow.dll

DLL уже зібрана і лежить у репозиторії. Якщо потрібно перізбрати:

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

## Використання

### Запуск

```bash
:: Запуск від імені адміністратора (рекомендовано)
python ghostwindow.py
```

### Як приховати вікно

1. Натисніть **"Pick a window"** — з'явиться таймер на 5 секунд
2. Наведіть курсор на цільове вікно за цей час
3. Після вибору натисніть **"Hide"**
4. Вікно зникне з панелі задач, захоплення екрана та Alt+Tab

### Як показати вікно назад

- Виберіть його у списку **"HIDDEN WINDOWS"** і натисніть **"Show"** або **"Restore"**
- Або натисніть **"Restore"** у нижній панелі для відновлення всіх

### Гаряча клавіша

- `Ctrl+Shift+F1` — показати/сховати вікно GhostWindow
- Під час pick mode — скасувати вибір

### Кнопки

| Кнопка | Дія |
|--------|-----|
| **Pick a window** | Вибір вікна під курсором |
| **Hide GhostWindow** | Сховати саму GhostWindow |
| **Hide** | Приховати вибране вікно |
| **Show** | Показати вибране вікно |
| **Bring to front** | Активувати вибране вікно |
| **Refresh** | Оновити список прихованих вікон |
| **Restore** | Відновити вибране вікно (зняти з приховування) |
| **Forget** | Прибрати зі списку (вікно лишається прихованим) |
| **Quit** | Вийти, відновивши всі вікна |

---

## Структура проєкту

```
GhostWindow/
├── ghostwindow.py    — точка входу
├── main_window.py    — головне вікно, UI, логіка
├── winapi.py         — константи WinAPI, ctypes-декларації
├── helpers.py        — функції для роботи з вікнами та процесами
├── injection.py      — інжекція DLL та виклик експортів
├── constants.py      — константи та стилі
├── hotkey.py         — фільтр глобальної гарячої клавіші
├── titlebar.py       — кастомний заголовок вікна
├── picker.py         — оверлей для вибору вікна
├── GhostWindow.cpp   — джерело DLL
├── GhostWindow.def   — експорти DLL
└── GhostWindow.dll   — зібрана DLL
```

---

## Як це працює

1. **Інжекція** — `LoadLibraryW` через `CreateRemoteThread` зі шляхом до DLL
2. **StealthHide** — DLL викликає:
   - `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` — виключення з захоплення
   - `WS_EX_TOOLWINDOW` — прибирання з панелі задач
   - `HWND_TOPMOST` — закріплення поверх
3. **StealthShow** — відновлення оригінального стану (стилі зберігаються у window properties)

---

## Відомі обмеження

- Деякі антічіти можуть блокувати інжекцію DLL
- Вікна UWP/Store можуть не підтримувати `SetWindowDisplayAffinity`
- Для інжекції в elevated-процеси потрібні права адміністратора

---

## Ліцензія

MIT
