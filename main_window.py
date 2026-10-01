"""
GhostWindow — main window: UI, target actions, hidden-window list.
"""

import os
import time
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QSizeGrip,
    QAbstractItemView,
)

from winapi import user32
from constants import DLL_NAME, DLL_PATH
from helpers import (
    get_root, get_pid, get_title, is_process_alive, get_process_name,
    find_module_base, stealth_is_active, _restore_window, force_foreground,
    apply_stealth_to_hwnd, hide_console,
)
from injection import inject_dll, call_export, detach_dll
from titlebar import TitleBar
from picker import PickerOverlay


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
