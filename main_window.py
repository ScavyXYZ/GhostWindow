import os
import time
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QSizeGrip,
    QAbstractItemView, QMenu, QCheckBox,
)

from winapi import user32
from constants import DLL_NAME, DLL_PATH
from helpers import (
    get_root, get_pid, get_title, is_process_alive, get_process_name,
    find_module_base, stealth_is_active, _restore_window, force_foreground,
    apply_stealth_to_hwnd, hide_console,
    is_pinned, set_pinned,
    enum_process_windows,
)
from injection import inject_dll, call_export, detach_dll
from titlebar import TitleBar
from picker import PickerOverlay
import cursor_lock


class GhostWindow(QWidget):
    exitSignal        = Signal()
    pickSignal        = Signal(object)
    uiSignal          = Signal(str, str)
    registerSignal    = Signal('qint64', 'qint64', str)
    markVisibleSignal = Signal('qint64', 'qint64')
    removeSignal      = Signal('qint64', 'qint64')
    refreshSignal     = Signal()
    pinChangedSignal  = Signal('qint64', 'qint64', bool)

    def __init__(self):
        super().__init__()

        self.setObjectName("MainWindow")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(720, 640)
        self.resize(780, 720)
        self.setWindowTitle("GhostWindow")

        hide_console()

        self.target_hwnd  = None
        self.target_pid   = None
        self.target_title = ""
        self.injected     = []
        self._exiting     = False
        self._picker      = None

        self.exitSignal.connect(self._on_exit_now)
        self.pickSignal.connect(self._on_pick_done)
        self.uiSignal.connect(self._on_ui_update)
        self.registerSignal.connect(self._register_injected)
        self.markVisibleSignal.connect(self._mark_visible)
        self.removeSignal.connect(self._remove_entry)
        self.refreshSignal.connect(self.refresh_list)
        self.pinChangedSignal.connect(self._on_pin_changed)

        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._auto_refresh)
        self.refresh_timer.start(2000)

        if not os.path.exists(DLL_PATH):
            self._set_status(f"{DLL_NAME} not found next to the script", "err")
        else:
            self._set_status("Ready", "info")

    # ------------------------------------------------------------------ UI
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
        cl.setSpacing(14)

        header = QLabel("Hide any window from OBS / Zoom / Discord, "
                        "remove it from the taskbar, keep it always on top")
        header.setObjectName("Header")
        header.setWordWrap(True)
        cl.addWidget(header)

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

        self.info_lbl = QLabel("No window selected")
        self.info_lbl.setObjectName("TargetInfo")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setMinimumHeight(48)
        cl.addWidget(self.info_lbl)

        # NEW: чекбокс «ховати всі вікна процесу»
        self.chk_children = QCheckBox("Hide all windows of the same process")
        self.chk_children.setChecked(True)
        self.chk_children.setCursor(Qt.PointingHandCursor)
        self.chk_children.setToolTip(
            "Ховає не лише вибране вікно, а всі top-level вікна того ж PID\n"
            "(діалоги, popup-и, вкладки). Нові вікна ховаються автоматично."
        )
        cl.addWidget(self.chk_children)

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

        self.btn_pin = QPushButton("Pin on top")
        self.btn_pin.setCursor(Qt.PointingHandCursor)
        self.btn_pin.setMinimumHeight(36)
        self.btn_pin.setCheckable(True)
        self.btn_pin.setEnabled(False)
        self.btn_pin.clicked.connect(self.toggle_pin_target)
        act_row.addWidget(self.btn_pin, 1)

        cl.addLayout(act_row)

        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("Status")
        self.status_lbl.setWordWrap(True)
        cl.addWidget(self.status_lbl)

        sec = QLabel("HIDDEN WINDOWS")
        sec.setObjectName("SectionTitle")
        cl.addWidget(sec)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["PROCESS", "PID", "WINDOW", "STATE", "PIN"])
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
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 50)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.doubleClicked.connect(self._on_row_double_click)

        cl.addWidget(self.table, 1)

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

    # ------------------------------------------------------------- window
    def _install_cursor_lock(self):
        h = int(self.winId())
        apply_stealth_to_hwnd(h)
        try:
            cursor_lock.install(h)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(60, self._install_cursor_lock)

    def closeEvent(self, event):
        if self._exiting:
            try:
                cursor_lock.uninstall(int(self.winId()))
            except Exception:
                pass
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
        QTimer.singleShot(60, self._install_cursor_lock)
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
            self._picker.cancel()
            return
        self.toggle_self()

    def on_hotkey_pin(self):
        if self._exiting or self._picker is not None:
            return
        if not self.target_hwnd:
            self._set_status("Спочатку виберіть вікно", "err")
            return
        self.btn_pin.setChecked(not self.btn_pin.isChecked())
        self.toggle_pin_target()

    # --------------------------------------------------------------- status
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

    # ---------------------------------------------------------- list update
    def _register_injected(self, pid, hwnd, title):
        for e in self.injected:
            if e["pid"] == pid and e["hwnd"] == hwnd:
                e["state"] = "hidden"
                e["title"] = title
                e["visible"] = False
                self.refresh_list()
                return
        self.injected.append({
            "pid":     pid,
            "hwnd":    hwnd,
            "name":    get_process_name(pid),
            "title":   title,
            "state":   "hidden",
            "visible": False,
            "pinned":  is_pinned(hwnd),
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

    def _on_pin_changed(self, pid, hwnd, pinned):
        for e in self.injected:
            if e["pid"] == pid and e["hwnd"] == hwnd:
                e["pinned"] = pinned
                break
        if self.target_hwnd == hwnd and self.target_pid == pid:
            self.btn_pin.setChecked(pinned)
            self._update_pin_label()
        self.refresh_list()

    def _auto_refresh(self):
        if self._exiting:
            return
        try:
            changed = False
            now = time.monotonic()
            rehide = []
            newly_hidden = []

            hidden_pids = {e["pid"] for e in self.injected
                           if e.get("state") == "hidden"}
            known_hwnds = {(e["pid"], e["hwnd"]) for e in self.injected}

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

                new_pinned = is_pinned(hwnd)
                if e.get("pinned") != new_pinned:
                    e["pinned"] = new_pinned
                    changed = True

                if (new_state == "hidden"
                        and not e.get("visible")
                        and not stealth_is_active(hwnd)
                        and now - e.get("last_rehide", 0.0) >= 5.0):
                    e["last_rehide"] = now
                    rehide.append((pid, hwnd))

            # NEW: пошук нових top-level вікон того ж PID
            if self.chk_children.isChecked() and hidden_pids:
                for pid in hidden_pids:
                    if not find_module_base(pid, DLL_NAME):
                        continue
                    for h in enum_process_windows(pid):
                        if (pid, h) in known_hwnds:
                            continue
                        if not stealth_is_active(h):
                            newly_hidden.append(
                                (pid, h, get_title(h) or "(popup)"))

            if changed:
                self.refresh_list()

            for pid, hwnd in rehide:
                self._rehide_async(pid, hwnd)

            for pid, hwnd, title in newly_hidden:
                self._hide_new_async(pid, hwnd, title)

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

    def _hide_new_async(self, pid, hwnd, title):
        def job():
            try:
                call_export(pid, DLL_NAME, DLL_PATH, "StealthHide", hwnd)
                self.registerSignal.emit(pid, hwnd, title)
            except Exception:
                pass
        threading.Thread(target=job, daemon=True).start()

    # ---------------------------------------------------------------- pick
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

        self.btn_pin.setEnabled(True)
        self.btn_pin.setChecked(is_pinned(hwnd))
        self._update_pin_label()

        self._set_status("Window selected", "ok")

    # ------------------------------------------------------------ hide/show
    def hide_target(self):
        if not self.target_pid or not self.target_hwnd:
            return

        pid  = self.target_pid
        root = get_root(self.target_hwnd)
        title = self.target_title
        dll_already_serves = any(x["pid"] == pid for x in self.injected)
        hide_children = self.chk_children.isChecked()

        targets = [root]
        if hide_children:
            for h in enum_process_windows(pid):
                if h != root:
                    targets.append(h)

        def job():
            try:
                self.uiSignal.emit("Injecting…", "busy")
                if not find_module_base(pid, DLL_NAME):
                    inject_dll(pid, DLL_PATH)

                hidden = 0
                for h in targets:
                    if not user32.IsWindow(h):
                        continue
                    try:
                        call_export(pid, DLL_NAME, DLL_PATH, "StealthHide", h)
                        self.registerSignal.emit(
                            pid, h, get_title(h) or title)
                        hidden += 1
                    except Exception:
                        pass

                if hidden == 0:
                    raise OSError("Жодне вікно не вдалося приховати")

                msg = (f"Hidden {hidden} window(s)" if hidden > 1
                       else "Window hidden")
                self.uiSignal.emit(msg, "ok")
            except Exception as ex:
                if not dll_already_serves:
                    try:
                        detach_dll(pid, DLL_NAME, DLL_PATH)
                    except Exception:
                        pass
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    def show_target(self):
        if not self.target_pid:
            return
        pid = self.target_pid

        siblings = [e["hwnd"] for e in self.injected if e["pid"] == pid]
        if self.target_hwnd and self.target_hwnd not in siblings:
            siblings.append(self.target_hwnd)

        def job():
            try:
                shown = 0
                for h in siblings:
                    if not user32.IsWindow(h):
                        continue
                    try:
                        if find_module_base(pid, DLL_NAME):
                            call_export(pid, DLL_NAME, DLL_PATH,
                                        "StealthShow", h)
                        _restore_window(h)
                        self.markVisibleSignal.emit(pid, h)
                        shown += 1
                    except Exception:
                        pass
                if shown == 0:
                    self.uiSignal.emit("Nothing to show", "err")
                else:
                    self.uiSignal.emit(
                        f"Restored {shown} window(s)" if shown > 1
                        else "Window is visible again",
                        "ok")
            except Exception as ex:
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    # --------------------------------------------------------- bring to front
    def _bring_to_front_hwnd(self, hwnd):
        if not hwnd or not user32.IsWindow(hwnd):
            self._set_status("Window is already closed", "err")
            return
        if _restore_window(hwnd):
            self._set_status("Window brought to front", "ok")
        else:
            self._set_status("Failed to activate the window", "err")

    def restore_target(self):
        self._bring_to_front_hwnd(self.target_hwnd)

    # ------------------------------------------------------------------ pin
    def _update_pin_label(self):
        self.btn_pin.setText("Unpin" if self.btn_pin.isChecked()
                             else "Pin on top")

    def toggle_pin_target(self):
        if not self.target_pid or not self.target_hwnd:
            return
        if not user32.IsWindow(self.target_hwnd):
            self._set_status("Window is already closed", "err")
            return

        want_pin = self.btn_pin.isChecked()
        pid, hwnd = self.target_pid, self.target_hwnd
        self._update_pin_label()

        def job():
            try:
                if find_module_base(pid, DLL_NAME):
                    fn = "StealthPin" if want_pin else "StealthUnpin"
                    call_export(pid, DLL_NAME, DLL_PATH, fn, hwnd)
                else:
                    if not set_pinned(hwnd, want_pin):
                        raise OSError("SetWindowPos failed — "
                                      "можливо, потрібні права адміністратора")
                self.pinChangedSignal.emit(pid, hwnd, want_pin)
                self.uiSignal.emit(
                    "Pinned on top" if want_pin else "Unpinned", "ok")
            except Exception as ex:
                self.pinChangedSignal.emit(pid, hwnd, is_pinned(hwnd))
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    def _pin_entry(self, entry, want_pin):
        pid, hwnd = entry["pid"], entry["hwnd"]
        if not user32.IsWindow(hwnd):
            self.refresh_list()
            return

        def job():
            try:
                if find_module_base(pid, DLL_NAME):
                    fn = "StealthPin" if want_pin else "StealthUnpin"
                    call_export(pid, DLL_NAME, DLL_PATH, fn, hwnd)
                else:
                    set_pinned(hwnd, want_pin)
                self.pinChangedSignal.emit(pid, hwnd, want_pin)
                self.uiSignal.emit(
                    "Pinned on top" if want_pin else "Unpinned", "ok")
            except Exception as ex:
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    # -------------------------------------------------------------- table
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
            e["pinned"] = is_pinned(e["hwnd"])
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

            pinned = bool(e.get("pinned"))
            it_pin = QTableWidgetItem("📌" if pinned else "")
            it_pin.setTextAlignment(Qt.AlignCenter)
            if pinned:
                it_pin.setForeground(QColor("#60a5fa"))
                it_pin.setToolTip("Pinned on top — ПКМ → Unpin")

            self.table.setItem(i, 0, it_name)
            self.table.setItem(i, 1, it_pid)
            self.table.setItem(i, 2, it_title)
            self.table.setItem(i, 3, it_state)
            self.table.setItem(i, 4, it_pin)

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

    def _table_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self.injected):
            return
        e = self.injected[row]

        menu = QMenu(self)
        pinned = bool(e.get("pinned"))
        act_pin = menu.addAction("Unpin" if pinned else "Pin on top")
        menu.addSeparator()
        act_bring  = menu.addAction("Bring to front")
        act_show   = menu.addAction("Show this only")
        act_show_all = menu.addAction("Show all of this process")
        act_hide_all = menu.addAction("Hide all of this process")
        menu.addSeparator()
        act_restore = menu.addAction("Restore (detach DLL)")
        act_forget = menu.addAction("Forget")
        menu.addSeparator()
        act_copy_hwnd = menu.addAction(f"Copy HWND ({e['hwnd']:#x})")
        act_copy_pid  = menu.addAction(f"Copy PID ({e['pid']})")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == act_pin:
            self._pin_entry(e, not pinned)
        elif chosen == act_bring:
            self._bring_to_front_hwnd(e["hwnd"])
        elif chosen == act_show:
            self._show_entry(e)
        elif chosen == act_show_all:
            self._show_process(e["pid"])
        elif chosen == act_hide_all:
            self._hide_process(e)
        elif chosen == act_restore:
            self.table.selectRow(row)
            self.detach_selected()
        elif chosen == act_forget:
            self.table.selectRow(row)
            self.remove_from_list()
        elif chosen == act_copy_hwnd:
            QApplication.clipboard().setText(f"{e['hwnd']:#x}")
            self._set_status("HWND copied", "ok")
        elif chosen == act_copy_pid:
            QApplication.clipboard().setText(str(e["pid"]))
            self._set_status("PID copied", "ok")

    def _show_entry(self, e):
        pid, hwnd = e["pid"], e["hwnd"]
        if not user32.IsWindow(hwnd):
            self.refresh_list()
            return

        def job():
            try:
                if find_module_base(pid, DLL_NAME):
                    call_export(pid, DLL_NAME, DLL_PATH, "StealthShow", hwnd)
                _restore_window(hwnd)
                self.markVisibleSignal.emit(pid, hwnd)
                self.uiSignal.emit("Window is visible again", "ok")
            except Exception as ex:
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    def _show_process(self, pid):
        hwnds = [e["hwnd"] for e in self.injected if e["pid"] == pid]
        if not hwnds:
            return

        def job():
            try:
                shown = 0
                for h in hwnds:
                    if not user32.IsWindow(h):
                        continue
                    try:
                        if find_module_base(pid, DLL_NAME):
                            call_export(pid, DLL_NAME, DLL_PATH,
                                        "StealthShow", h)
                        _restore_window(h)
                        self.markVisibleSignal.emit(pid, h)
                        shown += 1
                    except Exception:
                        pass
                if shown:
                    self.uiSignal.emit(f"Restored {shown} window(s)", "ok")
            except Exception as ex:
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    def _hide_process(self, entry):
        pid = entry["pid"]
        root = get_root(entry["hwnd"])
        targets = [root]
        for h in enum_process_windows(pid):
            if h != root:
                targets.append(h)

        def job():
            try:
                if not find_module_base(pid, DLL_NAME):
                    inject_dll(pid, DLL_PATH)
                hidden = 0
                for h in targets:
                    if not user32.IsWindow(h):
                        continue
                    try:
                        call_export(pid, DLL_NAME, DLL_PATH, "StealthHide", h)
                        self.registerSignal.emit(pid, h, get_title(h) or "(hidden)")
                        hidden += 1
                    except Exception:
                        pass
                self.uiSignal.emit(f"Hidden {hidden} window(s)", "ok")
            except Exception as ex:
                self.uiSignal.emit(str(ex), "err")

        threading.Thread(target=job, daemon=True).start()

    def _on_row_double_click(self, index):
        row = index.row()
        if not (0 <= row < len(self.injected)):
            return
        e = self.injected[row]
        self._bring_to_front_hwnd(e["hwnd"])

    # --------------------------------------------------------- detach/forget
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

    # ----------------------------------------------------------------- quit
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