from __future__ import annotations

import random
import subprocess
import time
from collections import namedtuple
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QKeySequence, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPushButton, QSizePolicy,
    QSlider, QSpinBox, QStyle, QStyleOptionSlider, QToolButton, QVBoxLayout,
    QWidget,
)

from .bridge import Bridge
from .config import Config, find_mame_dir, save_mame_dir
from .hotkeys import load_bindings, save_bindings
from .keymap import mame_token, mod_names
from .launcher import Launcher

HotkeyAction = namedtuple(
    "HotkeyAction",
    "id label press tap hold",
    defaults=(None, None, None)
)

def _preset_labels(keys) -> dict:
    parsed = {}
    starts_by_mode = {}
    for key in keys:
        mode, sep, num = key.partition("_")
        start = None
        if sep:
            try:
                start = int(num)
            except ValueError:
                start = None
        parsed[key] = (mode, start)
        if start is not None:
            starts_by_mode.setdefault(mode, []).append(start)
    labels = {}
    for key, (mode, start) in parsed.items():
        if start is None:
            labels[key] = key
            continue
        higher = [s for s in starts_by_mode[mode] if s > start]
        end = (min(higher) - 1) if higher else 999
        labels[key] = f"{mode.capitalize()}: {start:03d}-{end:03d}"
    return labels


G_UNIT = 256
GRAV_FINE_STEP = 4
GRAV_COARSE_STEP = G_UNIT // 4
GRAV_MAX = 20 * G_UNIT
GRAV_FINE_TICKS = G_UNIT // GRAV_FINE_STEP
GRAV_COARSE_TICKS = (GRAV_MAX - G_UNIT) // GRAV_COARSE_STEP


class GravitySlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        super().setRange(0, GRAV_FINE_TICKS + GRAV_COARSE_TICKS)
        self.setSingleStep(1)
        self.setPageStep(4)

    @staticmethod
    def gravity_for_pos(pos: int) -> int:
        if pos <= GRAV_FINE_TICKS:
            return pos * GRAV_FINE_STEP
        return G_UNIT + (pos - GRAV_FINE_TICKS) * GRAV_COARSE_STEP

    @staticmethod
    def pos_for_gravity(value: int) -> int:
        if value <= G_UNIT:
            return round(value / GRAV_FINE_STEP)
        pos = GRAV_FINE_TICKS + round((value - G_UNIT) / GRAV_COARSE_STEP)
        return min(pos, GRAV_FINE_TICKS + GRAV_COARSE_TICKS)

    def gravity(self) -> int:
        return self.gravity_for_pos(self.value())

    def setGravity(self, value: int):
        value = max(0, min(GRAV_MAX, value))
        self.setValue(self.pos_for_gravity(value))

    def paintEvent(self, event):
        super().paintEvent(event)
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        groove = style.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        span = groove.width() - handle.width()
        xoff = QStyle.sliderPositionFromValue(
            self.minimum(), self.maximum(), GRAV_FINE_TICKS, span, opt.upsideDown
        )
        center = QPointF(groove.x() + handle.width() / 2 + xoff, groove.center().y())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self.palette().color(QPalette.Highlight))
        p.drawEllipse(center, 3.0, 3.0)


class CollapsibleBox(QWidget):
    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; padding: 4px 2px;"
            " text-align: left; }"
        )
        self.header.toggled.connect(self._on_toggled)
        outer.addWidget(self.header)
        self.content = QWidget()
        self.content.setVisible(expanded)
        outer.addWidget(self.content)

    def setContentLayout(self, layout):
        layout.setContentsMargins(10, 2, 6, 8)
        self.content.setLayout(layout)

    def _on_toggled(self, expanded: bool):
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)
        win = self.window()
        if win is None:
            return
        win.setMinimumHeight(0)
        target = -1
        for _ in range(8):
            QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
            h = win.sizeHint().height()
            if h == target:
                break
            target = h
        win.resize(win.width(), target)


class TriToggle(QWidget):
    def __init__(self, key: str, bridge: Bridge, on_change=None,
                 states=None, off_clears=False):
        super().__init__()
        self.key = key
        self.bridge = bridge
        self._on_change = on_change
        self._off_clears = off_clears
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self._buttons = {}
        for label, mode in (states or (("Off", "off"), ("On", "on"), ("Game", "game"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedWidth(52)
            b.clicked.connect(lambda _checked, m=mode: self._on_click(m))
            self.group.addButton(b)
            self._buttons[mode] = b
            lay.addWidget(b)
        self._buttons["game" if "game" in self._buttons else "off"].setChecked(True)

    def _on_click(self, mode: str):
        if self._on_change is not None:
            self._on_change(mode)
            return
        if mode == "on":
            self.bridge.set_override(self.key, 1)
        elif mode == "off" and not self._off_clears:
            self.bridge.set_override(self.key, 0)
        else:
            self.bridge.clear_override(self.key)

    def _current_mode(self) -> str:
        return next((m for m, b in self._buttons.items() if b.isChecked()), "off")

    def _set_mode(self, mode: str):
        if mode not in self._buttons:
            mode = "off"
        self._buttons[mode].setChecked(True)
        self._on_click(mode)

    def toggle_on_off(self):
        self._set_mode("off" if self._current_mode() == "on" else "on")

    def reset_to_game(self):
        self._set_mode("game" if "game" in self._buttons else "off")


class ConfigDialog(QDialog):
    MOD_KEYS = {
        Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr,
    }

    def __init__(self, actions, bindings, probe, mame_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Config")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.bindings = bindings 
        self._probe = probe
        self.mame_dir = Path(mame_dir) if mame_dir else None
        self._capturing: str | None = None
        self._rows = {} 

        outer = QVBoxLayout(self)

        path_box = QGroupBox("MAME")
        path_row = QHBoxLayout(path_box)
        path_row.addWidget(QLabel("mame.exe:"))
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("(Unset)")
        self.path_edit.setMinimumWidth(280)
        path_row.addWidget(self.path_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_mame)
        path_row.addWidget(browse)
        outer.addWidget(path_box)
        self._refresh_path()

        hk_box = QGroupBox("Hotkeys")
        hk_outer = QVBoxLayout(hk_box)
        hint = QLabel(
            "Click Assign, then press the desired hotkey."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        hk_outer.addWidget(hint)

        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setHorizontalSpacing(8)
        hk_outer.addLayout(grid)
        outer.addWidget(hk_box)
        for r, (aid, label) in enumerate(actions):
            grid.addWidget(QLabel(label), r, 0)
            key_lbl = QLabel()
            key_lbl.setAlignment(Qt.AlignCenter)
            key_lbl.setStyleSheet("font-weight: bold;")
            key_lbl.setMinimumWidth(120)
            grid.addWidget(key_lbl, r, 1)
            assign = QPushButton("Assign")
            assign.clicked.connect(lambda _, a=aid: self._start_capture(a))
            grid.addWidget(assign, r, 2)
            clear = QPushButton("Clear")
            clear.clicked.connect(lambda _, a=aid: self._clear(a))
            grid.addWidget(clear, r, 3)
            self._rows[aid] = (key_lbl, assign)
            self._refresh_row(aid)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        outer.addWidget(buttons)

    def _refresh_path(self):
        self.path_edit.setText(str(self.mame_dir / "mame.exe") if self.mame_dir else "")

    def _browse_mame(self):
        start = str(self.mame_dir) if self.mame_dir else ""
        fn, _ = QFileDialog.getOpenFileName(
            self, "Locate mame.exe", start,
            "MAME executable (mame*.exe);;Executables (*.exe);;All files (*)",
        )
        if fn:
            self.mame_dir = Path(fn).resolve().parent
            self._refresh_path()

    def _refresh_row(self, aid: str):
        key_lbl, assign = self._rows[aid]
        if self._capturing == aid:
            key_lbl.setText("Press any key…")
            assign.setText("Cancel")
        else:
            b = self.bindings.get(aid)
            key_lbl.setText(b["text"] if b else "—")
            assign.setText("Assign")

    def _start_capture(self, aid: str):
        if self._capturing == aid:
            self._cancel_capture()
            return
        prev, self._capturing = self._capturing, aid
        if prev is not None:
            self._refresh_row(prev)
        self._refresh_row(aid)
        self.grabKeyboard()

    def _cancel_capture(self):
        aid, self._capturing = self._capturing, None
        self.releaseKeyboard()
        if aid is not None:
            self._refresh_row(aid)

    def _clear(self, aid: str):
        if self._capturing == aid:
            self._cancel_capture()
        self.bindings.pop(aid, None)
        self._refresh_row(aid)

    def keyPressEvent(self, event):
        if self._capturing is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in self.MOD_KEYS:
            return
        if key == Qt.Key_Escape and event.modifiers() == Qt.NoModifier:
            self._cancel_capture()
            return
        token = mame_token(key)
        mods = mod_names(event.modifiers())
        text = QKeySequence(event.keyCombination()).toString() or "(key)"
        if not token or not self._probe(token):
            key_lbl, _ = self._rows[self._capturing]
            key_lbl.setText("Can't bind this key.")
            return
        aid = self._capturing
        for other, b in list(self.bindings.items()):
            if other != aid and b.get("token") == token and b.get("mods") == mods:
                self.bindings.pop(other)
                self._refresh_row(other)
        self.bindings[aid] = {"token": token, "mods": mods, "text": text}
        self._capturing = None
        self.releaseKeyboard()
        self._refresh_row(aid)

    def closeEvent(self, event):
        if self._capturing is not None:
            self._cancel_capture()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TGM2 Trainer")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.mame_dir = find_mame_dir()
        self.launcher: Launcher | None = Launcher(self.mame_dir) if self.mame_dir else None
        self.mame_proc: subprocess.Popen | None = None
        self._gravity_active = False
        self._timings_active = False
        self._level_val: int | None = None
        self._grade_idx: int | None = None
        self._grade_pts: int | None = None
        self._game_mode: int | None = None
        self._level_frozen = False
        self._music_val: int | None = None
        self._music_frozen = False
        self.tri_toggles: dict[str, TriToggle] = {}

        try:
            self.config = Config.load(self.mame_dir)
            self._config_error = None
        except FileNotFoundError as exc:
            self.config = Config({})
            self._config_error = str(exc)

        self.bridge = Bridge(port=self.config.port)
        self._build_ui()
        self._wire_bridge()
        self._setup_hotkeys()
        self.bridge.start()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_text = QLabel("Disconnected")
        self._set_status(False)
        header.addWidget(self.status_dot)
        header.addWidget(self.status_text, 1)
        self.config_btn = QPushButton("Config")
        self.config_btn.setToolTip("Set your MAME .exe path and shortcut hotkeys.")
        self.config_btn.clicked.connect(self._open_config)
        header.addWidget(self.config_btn)
        self.launch_btn = QPushButton("Launch MAME")
        self.launch_btn.clicked.connect(self._launch)
        if not self.launcher or not self.launcher.available():
            self.launch_btn.setEnabled(False)
            self.launch_btn.setToolTip(self._config_error or "mame.exe not found")
        header.addWidget(self.launch_btn)
        root.addLayout(header)

        prow = QHBoxLayout()
        lbl = QLabel("Apply to:")
        prow.addWidget(lbl)
        self.p1_btn = QPushButton("P1")
        self.p2_btn = QPushButton("P2")
        for b in (self.p1_btn, self.p2_btn):
            b.setCheckable(True)
            b.setMaximumWidth(46)
            b.toggled.connect(self._players_changed)
        self.p1_btn.setChecked(True)
        prow.addWidget(self.p1_btn)
        prow.addWidget(self.p2_btn)
        prow.addStretch(1)
        self.reset_btn = QPushButton("Restart Game")
        self.reset_btn.setToolTip(
            "Restart the current game for the player(s)."
        )
        self.reset_btn.clicked.connect(self._reset_game)
        prow.addWidget(self.reset_btn)
        root.addLayout(prow)

        self._build_adjust_panel(root)

        tg = CollapsibleBox("Toggles")
        grid = QGridLayout()

        _onoff = (("Off", "off"), ("On", "on"))
        self._add_tri(grid, 0, "Invisible", "invisible", states=_onoff, off_clears=True,
                      tip="Enable/disable Invisible mode. Does not affect M-roll.")
        self._add_tri(grid, 1, "BIG", "big_mode", states=_onoff, off_clears=True,
                      tip="Enable/disable BIG mode.")
        
        self._add_tri(grid, 2, "Ghost piece", "ghost", on_change=self._ghost_changed,
                      tip="Configure ghost piece/TLS behaviour. Off/On override, or default to Game behaviour.")
        self._add_tri(grid, 3, "Item mode", "item_mode",
                      tip="Enable/disable Item mode.")
        self._add_tri(grid, 4, "Always TRANS FORM", "trans_form", states=_onoff, off_clears=True,
                      tip="Force the TRANS FORM modifier on all active pieces.")

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        grid.addWidget(sep, 5, 0, 1, 2)

        self.grade_chk = QCheckBox("Force grade S9 + M-roll conditions")
        grade_tooltip = ("Bypass all checks for the M-roll in Master mode.")
        self.grade_chk.setToolTip(grade_tooltip)
        self.grade_chk.toggled.connect(self._toggle_grade)
        grid.addWidget(self.grade_chk, 6, 0, 1, 2)

        self.death_torikan_chk = QCheckBox("Bypass Death torikan")
        torikan_tip = ("Bypass the 3:25 torikan at level 500 in T.A. Death.")
        self.death_torikan_chk.setToolTip(torikan_tip)
        self.death_torikan_chk.toggled.connect(self._toggle_death_torikan)
        grid.addWidget(self.death_torikan_chk, 7, 0, 1, 2)

        self.debug_mode_chk = QCheckBox("Debug mode")
        debug_tip = ("Enable the built-in debug mode cheat.")
        self.debug_mode_chk.setToolTip(debug_tip)
        self.debug_mode_chk.toggled.connect(self._toggle_debug_mode)
        grid.addWidget(self.debug_mode_chk, 8, 0, 1, 2)

        tg.setContentLayout(grid)
        root.addWidget(tg)

        ss = CollapsibleBox("Speed Settings")
        ssl = QVBoxLayout()

        row = QHBoxLayout()
        self.gravity_chk = QCheckBox("Override Gravity")
        self.gravity_chk.setToolTip("Force a constant gravity value between 0 and 20G.")
        self.gravity_chk.toggled.connect(self._toggle_gravity)
        row.addWidget(self.gravity_chk)
        self.gravity_val = QLabel("256 (1.00G)")
        row.addWidget(self.gravity_val, 1, Qt.AlignRight)
        ssl.addLayout(row)
        self.gravity_slider = GravitySlider()
        self.gravity_slider.setGravity(256)
        self.gravity_slider.valueChanged.connect(self._gravity_changed)
        ssl.addWidget(self.gravity_slider)

        speed_sep = QFrame()
        speed_sep.setFrameShape(QFrame.HLine)
        speed_sep.setFrameShadow(QFrame.Sunken)
        ssl.addWidget(speed_sep)

        trow = QHBoxLayout()
        self.timings_chk = QCheckBox("Override Frame Times")
        self.timings_chk.setToolTip(
            "Force override frame timing values from the game's presets or a custom list.")
        self.timings_chk.toggled.connect(self._toggle_timings)
        trow.addWidget(self.timings_chk)
        self.preset_combo = QComboBox()
        preset_labels = _preset_labels(list(self.config.timing_presets))
        for key in self.config.timing_presets:
            self.preset_combo.addItem(preset_labels[key], key)
        self.preset_combo.addItem("Custom", None)
        trow.addWidget(self.preset_combo, 1)
        ssl.addLayout(trow)

        self.timing_table = QWidget()
        tgrid = QGridLayout(self.timing_table)
        tgrid.setContentsMargins(0, 4, 0, 0)
        tgrid.setHorizontalSpacing(4)
        self.timing_spins = {}
        labels = {
            "are": "ARE",
            "line_are": "Line ARE",
            "das": "DAS",
            "lock_delay": "Lock",
            "line_clear": "Clear",
        }
        tips = {
            "are": "Piece spawn delay (includes lock frames +2)",
            "line_are": "Piece spawn delay on line clear (includes lock frames +2)",
            "das": "Auto-shift delay",
            "lock_delay": "Lock delay",
            "line_clear": "Line-clear animation length",
        }
        for col, member in enumerate(self.config.timing_members):
            hdr = QLabel(labels.get(member, member))
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setToolTip(tips.get(member, member))
            hdr.setStyleSheet("color: #888; font-size: 11px;")
            tgrid.addWidget(hdr, 0, col)
            sp = QSpinBox()
            # game breaks below these values; are/line_are -= 2 (game logic excludes lock frames)
            sp.setRange({"are": 3, "line_are": 3, "line_clear": 1, "das": 3}.get(member, 0), 127)
            sp.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
            sp.setAlignment(Qt.AlignCenter)
            sp.setToolTip(tips.get(member, member))
            tgrid.addWidget(sp, 1, col)
            tgrid.setColumnStretch(col, 1)
            self.timing_spins[member] = sp
        ssl.addWidget(self.timing_table)

        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        for sp in self.timing_spins.values():
            sp.valueChanged.connect(self._custom_changed)
        self._preset_changed(self.preset_combo.currentIndex())
        ss.setContentLayout(ssl)
        root.addWidget(ss)

        root.addStretch(1)

        footer = QHBoxLayout()
        reload_btn = QPushButton("Reload config")
        reload_btn.clicked.connect(self.bridge.reload_config)
        footer.addWidget(reload_btn)
        self.notice = QLabel("")
        self.notice.setStyleSheet("color: #888;")
        footer.addWidget(self.notice, 1)
        root.addLayout(footer)

        self._set_gravity_editable(False)
        self._set_timings_editable(False)

        self.setMinimumWidth(340)

    def _build_adjust_panel(self, root: QVBoxLayout):
        box = CollapsibleBox("Adjust")
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 2)
        grid.setColumnStretch(6, 1)
        grid.setColumnMinimumWidth(1, 90)
        STEP_W = 48 

        cap_align = Qt.AlignRight | Qt.AlignVCenter

        grid.addWidget(QLabel("State:"), 0, 0, cap_align)
        self.lbl_state = QLabel("--")
        self.lbl_state.setStyleSheet("font-weight: bold;")
        self.lbl_state.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.lbl_state, 0, 1)

        grid.addWidget(QLabel("Level:"), 1, 0, cap_align)
        self.lbl_level = QLabel("---")
        self.lbl_level.setStyleSheet("font-weight: bold;")
        self.lbl_level.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.lbl_level, 1, 1)
        b_lvl_up = QPushButton("+100")
        b_lvl_up.setFixedWidth(STEP_W)
        b_lvl_up.clicked.connect(lambda: self._level_delta(100))
        grid.addWidget(b_lvl_up, 1, 2)
        b_lvl_dn = QPushButton("-100")
        b_lvl_dn.setFixedWidth(STEP_W)
        b_lvl_dn.clicked.connect(lambda: self._level_delta(-100))
        grid.addWidget(b_lvl_dn, 1, 3)
        self.level_set = QSpinBox()

        self.level_set.setRange(0, 998)
        self.level_set.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.level_set.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.level_set, 1, 4)
        set_lvl = QPushButton("Set")
        set_lvl.setFixedWidth(STEP_W)
        set_lvl.clicked.connect(self._level_set)
        grid.addWidget(set_lvl, 1, 5)
        self.level_freeze = QCheckBox("Freeze")
        self.level_freeze.toggled.connect(self._level_freeze_toggled)
        grid.addWidget(self.level_freeze, 1, 6)

        grid.addWidget(QLabel("Grade:"), 2, 0, cap_align)
        self.lbl_grade = QLabel("--")
        self.lbl_grade.setStyleSheet("font-weight: bold;")
        self.lbl_grade.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.lbl_grade, 2, 1)
        b_grd_up = QPushButton("+")     # no point in step down; grade doesn't refresh
        b_grd_up.setFixedWidth(STEP_W * 2 + grid.horizontalSpacing())
        b_grd_up.clicked.connect(lambda: self._grade_delta(1))
        grid.addWidget(b_grd_up, 2, 2, 1, 2)
        self.grade_set = QComboBox()

        self.grade_set.setEditable(True)
        self.grade_set.setInsertPolicy(QComboBox.NoInsert)
        self.grade_set.lineEdit().setReadOnly(True)
        self.grade_set.lineEdit().setAlignment(Qt.AlignCenter)
        self.grade_set.lineEdit().setFocusPolicy(Qt.NoFocus)
        for idx, name in enumerate(self.config.grade_relative_names):
            self.grade_set.addItem(name, idx)
            self.grade_set.setItemData(idx, Qt.AlignCenter, Qt.TextAlignmentRole)
        grid.addWidget(self.grade_set, 2, 4)
        set_grd = QPushButton("Set")
        set_grd.setFixedWidth(STEP_W)
        set_grd.clicked.connect(self._grade_set)
        grid.addWidget(set_grd, 2, 5)
        
        pts_cell = QWidget()
        pts_lay = QHBoxLayout(pts_cell)
        pts_lay.setContentsMargins(0, 0, 0, 0)
        pts_lay.setSpacing(4)
        self.lbl_grade_pts = QLabel("--")
        pts_font = self.lbl_grade_pts.font()
        pts_font.setBold(True)
        self.lbl_grade_pts.setFont(pts_font)
        self.lbl_grade_pts.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_grade_pts.setFixedWidth(self.lbl_grade_pts.fontMetrics().horizontalAdvance("100"))
        pts_lay.addWidget(self.lbl_grade_pts)
        pts_lay.addWidget(QLabel("/ 100"))
        pts_lay.addStretch(1)
        grid.addWidget(pts_cell, 2, 6)

        music_cap = QLabel("Music:")
        grid.addWidget(music_cap, 3, 0, cap_align)
        self.lbl_music = QLabel("--")
        self.lbl_music.setStyleSheet("font-weight: bold;")
        self.lbl_music.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.lbl_music, 3, 1)
        self.music_set = QComboBox()

        self.music_set.setEditable(True)
        self.music_set.setInsertPolicy(QComboBox.NoInsert)
        self.music_set.lineEdit().setReadOnly(True)
        self.music_set.lineEdit().setAlignment(Qt.AlignCenter)
        self.music_set.lineEdit().setFocusPolicy(Qt.NoFocus)
        for idx, name in enumerate(self.config.music_track_names):
            self.music_set.addItem(name, idx)
            self.music_set.setItemData(idx, Qt.AlignCenter, Qt.TextAlignmentRole)
        none_pos = self.music_set.count()
        self.music_set.addItem("(None)", self.config.music_none_id)
        self.music_set.setItemData(none_pos, Qt.AlignCenter, Qt.TextAlignmentRole)
        grid.addWidget(self.music_set, 3, 4)
        set_music = QPushButton("Set")
        set_music.setFixedWidth(STEP_W)
        set_music.clicked.connect(self._music_set)
        grid.addWidget(set_music, 3, 5)
        self.music_freeze = QCheckBox("Freeze")
        self.music_freeze.toggled.connect(self._music_freeze_toggled)
        grid.addWidget(self.music_freeze, 3, 6)

        box.setContentLayout(grid)
        root.addWidget(box)

    def _add_tri(self, grid: QGridLayout, row: int, label: str, key: str,
                 on_change=None, tip: str | None = None,
                 states=None, off_clears=False):
        lbl = QLabel(label)
        if tip:
            lbl.setToolTip(tip)
        grid.addWidget(lbl, row, 0)
        tri = TriToggle(key, self.bridge, on_change=on_change,
                        states=states, off_clears=off_clears)
        if tip:
            tri.setToolTip(tip)
        self.tri_toggles[key] = tri
        grid.addWidget(tri, row, 1)

    def _wire_bridge(self):
        self.bridge.connectionChanged.connect(self._set_status)
        self.bridge.stateReceived.connect(self._on_state)
        self.bridge.notice.connect(self._on_notice)
        self.bridge.hotkeyEvent.connect(self._on_hotkey)

    def _set_status(self, connected: bool):
        self.status_text.setText("Connected" if connected else "Disconnected")
        self.status_dot.setStyleSheet(
            "color: #2ecc40;" if connected else "color: #ff4136;"
        )

    def _reset_game(self):
        self.bridge.write("reset_game", 1)
        self._osd("Game reset")

    def _on_state(self, m: dict):
        if "level" in m:
            self._level_val = int(m["level"])
            if not self._level_frozen:
                self._refresh_level()
        if "internal_grade" in m:
            self._grade_idx = int(m["internal_grade"])
            self._refresh_grade()
        if "grade_points" in m:
            self._grade_pts = int(m["grade_points"])
            self._refresh_grade()
        if "game_mode" in m:
            self._game_mode = int(m["game_mode"])
        if "play_state" in m:
            self.lbl_state.setText(self.config.play_state_name(m["play_state"]))
        if "music" in m:
            self._music_val = int(m["music"])
            if not self._music_frozen:
                self._refresh_music()
        if "gravity" in m and not self._gravity_active:
            self._mirror_gravity(int(m["gravity"]))
        if not self._timings_active:
            self._mirror_timings()

    def _on_notice(self, text: str):
        self.notice.setText(text)

    def _refresh_level(self):
        v = self._level_val
        self.lbl_level.setText("---" if v is None else str(v))

    def _refresh_grade(self):
        gi = self._grade_idx
        self.lbl_grade.setText("--" if gi is None else self.config.grade_relative_name(gi))
        pts = self._grade_pts
        self.lbl_grade_pts.setText("--" if pts is None else str(pts))

    def _refresh_music(self):
        v = self._music_val
        self.lbl_music.setText("--" if v is None else self.config.music_track_name(v))

    def _apply_level(self):
        if self._level_val is None:
            return
        section = min(self._level_val // 100, 9)
        if self._level_frozen:
            self.bridge.set_override("section", section)
            self.bridge.set_override("section_count", section)
            self.bridge.set_override("level", self._level_val)
        else:
            self.bridge.write("section", section)
            self.bridge.write("section_count", section)
            self.bridge.write("level", self._level_val)

    def _level_delta(self, delta: int):
        base = self._level_val if self._level_val is not None else self.level_set.value()
        self._level_val = max(0, min(998, base + delta))
        self._refresh_level()
        self._apply_level()
        self._on_notice(f"level → {self._level_val}")

    def _level_set(self):
        self._level_val = self.level_set.value()
        self._refresh_level()
        self._apply_level()
        self._on_notice(f"level → {self._level_val}")

    def _level_freeze_toggled(self, checked: bool):
        self._level_frozen = checked
        if checked:
            if self._level_val is None:
                self._level_val = self.level_set.value()
            self._refresh_level()
            self._apply_level()
        else:
            self.bridge.clear_override("level")
            self.bridge.clear_override("section")
            self.bridge.clear_override("section_count")
            self._refresh_level()
        self._on_notice(f"level freeze {'on' if checked else 'off'}")

    def _grade_delta(self, delta: int):
        base = self._grade_idx if self._grade_idx is not None else int(self.grade_set.currentData())
        self._grade_idx = max(0, min(self.config.grade_max, base + delta))
        self._refresh_grade()
        self.bridge.write("internal_grade", self._grade_idx)
        self._on_notice(
            f"grade → {self.config.grade_relative_name(self._grade_idx)} ({self._grade_idx})"
        )

    def _grade_set(self):
        self._grade_idx = int(self.grade_set.currentData())
        self._refresh_grade()
        self.bridge.write("internal_grade", self._grade_idx)
        self._on_notice(
            f"grade → {self.config.grade_relative_name(self._grade_idx)} ({self._grade_idx})"
        )

    def _music_set(self):
        track = int(self.music_set.currentData())
        if self.music_freeze.isChecked():
            scene = self.config.music_track_scene(track)
            self._music_val = track
            self.bridge.set_override("music_scene", scene)
        else:
            self.music_freeze.setChecked(True)
        self._on_notice(f"music → {self.config.music_track_name(track)}")

    def _music_freeze_toggled(self, checked: bool):
        self._music_frozen = checked
        if checked:
            track = int(self.music_set.currentData())
            scene = self.config.music_track_scene(track)
            self._music_val = track
            self._refresh_music()
            self.bridge.set_override("music_scene", scene)
        else:
            self.bridge.clear_override("music_scene")
            self._refresh_music()
        self._on_notice(f"music freeze {'on' if checked else 'off'}")

    def _launch(self):
        if not self.launcher:
            return
        if self.launcher.is_running(self.mame_proc):
            self._on_notice("MAME already running")
            return
        try:
            self.mame_proc = self.launcher.launch()
            self._on_notice("Launched MAME; connecting...")
        except OSError as exc:
            self._on_notice(f"launch failed: {exc}")

    def _toggle_grade(self, checked: bool):
        if checked:
            self.bridge.set_override("grade_mroll", True)
        else:
            self.bridge.clear_override("grade_mroll")

    def _ghost_changed(self, mode: str):
        if mode == "on":
            self.bridge.clear_override("ghost_render")
            self.bridge.set_override("ghost", 1)
            self.bridge.write("ghost_render", 1)
        elif mode == "off":
            self.bridge.clear_override("ghost")
            self.bridge.set_override("ghost_render", 0)
        else:  # game
            self.bridge.clear_override("ghost")
            self.bridge.clear_override("ghost_render")
            self.bridge.write("ghost_render", 1)

    def _toggle_death_torikan(self, checked: bool):
        if checked:
            self.bridge.set_override("death_torikan", 1)
        else:
            self.bridge.clear_override("death_torikan")

    def _toggle_debug_mode(self, checked: bool):
        if checked:
            self.bridge.set_override("debug_mode", 1)
        else:
            self.bridge.clear_override("debug_mode")

    def _players_changed(self, _checked: bool):
        if not self.p1_btn.isChecked() and not self.p2_btn.isChecked():
            btn = self.sender()
            if btn is not None:
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
        players = [i for i, b in enumerate((self.p1_btn, self.p2_btn)) if b.isChecked()]
        self.bridge.set_players(players or [0])

    def _toggle_gravity(self, checked: bool):
        self._gravity_active = checked
        self._set_gravity_editable(checked)
        if checked:
            self.bridge.set_override("gravity_force", self.gravity_slider.gravity())
        else:
            self.bridge.set_override("gravity_force", -1)

    def _set_gravity_editable(self, on: bool):
        self.gravity_slider.setEnabled(on)

    def _mirror_gravity(self, value: int):
        self.gravity_slider.setGravity(value)

    def _gravity_changed(self, _pos: int):
        value = self.gravity_slider.gravity()
        self.gravity_val.setText(f"{value} ({value / 256:.2f}G)")
        if self._gravity_active:
            self.bridge.set_override("gravity_force", value)

    _TIMING_TABLES = {  # wiki values for ARE/DAS are +2 compared to game logic
        "are": ("are_force", -2),
        "line_are": ("line_are_force", -2),
        "line_clear": ("line_clear_force", 0),
        "lock_delay": ("lock_force", 0),
        "das": ("das_force", -2)}

    def _send_timings(self, active: bool):
        v = self._current_timings()
        for member, (key, off) in self._TIMING_TABLES.items():
            if active and member in v:
                self.bridge.set_override(key, v[member] + off)
            else:
                self.bridge.set_override(key, -1)
        self.bridge.clear_override("lock_delay")

    def _toggle_timings(self, checked: bool):
        self._timings_active = checked
        self._set_timings_editable(checked)
        self._send_timings(checked)

    def _set_timings_editable(self, on: bool):
        self.preset_combo.setEnabled(on)
        for sp in self.timing_spins.values():
            sp.setEnabled(on)

    def _mirror_timings(self):
        if self._level_val is None or self._game_mode is None:
            return
        key = self._current_preset_key(self._level_val, self._game_mode)
        if key is None:
            return
        idx = self.preset_combo.findData(key)
        if idx >= 0 and idx != self.preset_combo.currentIndex():
            self.preset_combo.setCurrentIndex(idx)

    def _current_preset_key(self, level: int, game_mode: int) -> str | None:
        if game_mode & 0x80:    # tgm+ doesn't use 500+ master timings
            return "master_000"
        mode = "death" if (game_mode & 0x1000) else "master"
        best, best_start = None, -1
        for key in self.config.timing_presets:
            m, sep, num = key.partition("_")
            if m != mode or not sep:
                continue
            try:
                start = int(num)
            except ValueError:
                continue
            if best_start < start <= level:
                best, best_start = key, start
        return best

    def _preset_changed(self, _index: int):
        key = self.preset_combo.currentData()
        if key is not None:
            preset = self.config.timing_presets.get(key, {})
            for member, sp in self.timing_spins.items():
                if member in preset:
                    sp.blockSignals(True)
                    sp.setValue(int(preset[member]))
                    sp.blockSignals(False)
        if self._timings_active:
            self._send_timings(True)

    def _custom_changed(self, _value: int):
        values = self._current_timings()
        key = self._matching_preset(values)
        target = (self.preset_combo.count() - 1 if key is None
                  else self.preset_combo.findData(key))
        if target >= 0 and target != self.preset_combo.currentIndex():
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(target)
            self.preset_combo.blockSignals(False)
        if self._timings_active:
            self._send_timings(True)

    def _matching_preset(self, values: dict) -> str | None:
        for key, preset in self.config.timing_presets.items():
            if all(int(preset.get(m, -1)) == values.get(m) for m in values):
                return key
        return None

    def _current_timings(self) -> dict:
        return {member: sp.value() for member, sp in self.timing_spins.items()}

    def _osd(self, text: str):
        self.bridge.osd(text)
        self._on_notice(text)

    def _setup_hotkeys(self):
        def osd_chk(checkbox, name):
            def run():
                checkbox.toggle()
                self._osd(f"{name}: {'ON' if checkbox.isChecked() else 'OFF'}")
            return run

        def osd_level(delta):
            def run():
                self._level_delta(delta)
                self._osd(f"Level → {self._level_val}")
            return run

        def osd_grade(delta):
            def run():
                self._grade_delta(delta)
                self._osd(f"Grade → {self.config.grade_relative_name(self._grade_idx)}")
            return run

        def osd_tap(t, name):
            def run():
                t.toggle_on_off()
                self._osd(f"{name}: {'ON' if t._current_mode() == 'on' else 'OFF'}")
            return run

        def osd_hold(t, name):
            def run():
                t.reset_to_game()
                # two-state toggles (no Game button) release to Off instead
                self._osd(f"{name}: {'Game' if t._current_mode() == 'game' else 'Off'}")
            return run

        inv, big, gho, itm = (self.tri_toggles["invisible"], self.tri_toggles["big_mode"],
                              self.tri_toggles["ghost"], self.tri_toggles["item_mode"])
        trans = self.tri_toggles["trans_form"]
        self._hotkey_actions = [
            HotkeyAction("level_up",     "Level +100", press=osd_level(100)),
            HotkeyAction("level_down",   "Level -100", press=osd_level(-100)),
            HotkeyAction("level_freeze", "Toggle Level Freeze", press=osd_chk(self.level_freeze, "Level Freeze")),
            HotkeyAction("grade_up",     "Grade +1", press=osd_grade(1)),
            HotkeyAction("reset_game",   "Reset Game", press=self._reset_game),
            HotkeyAction("invisible",    "Invisible — tap: On/Off", tap=osd_tap(inv, "Invisible"), hold=osd_hold(inv, "Invisible")),
            HotkeyAction("big_mode",     "BIG — tap: On/Off", tap=osd_tap(big, "BIG"), hold=osd_hold(big, "BIG")),
            HotkeyAction("ghost",        "Ghost — tap: On/Off · hold: Game", tap=osd_tap(gho, "Ghost"), hold=osd_hold(gho, "Ghost")),
            HotkeyAction("item_mode",    "Item mode — tap: On/Off · hold: Game", tap=osd_tap(itm, "Item mode"), hold=osd_hold(itm, "Item mode")),
            HotkeyAction("trans_form",   "Trans form — tap: On/Off", tap=osd_tap(trans, "TRANS FORM"), hold=osd_hold(trans, "TRANS FORM")),
        ]
        self._hotkey_by_id = {a.id: a for a in self._hotkey_actions}
        self.hotkey_bindings = load_bindings()
        self._apply_hotkeys()

    def _apply_hotkeys(self):
        payload = []
        for aid, b in self.hotkey_bindings.items():
            act = self._hotkey_by_id.get(aid)
            token = b.get("token") if act else None
            if not token:
                continue
            payload.append({
                "action": aid,
                "token": token,
                "mods": b.get("mods", []),
                "kind": "taphold" if (act.tap or act.hold) else "press",
            })
        self.bridge.set_hotkeys(payload)

    def _on_hotkey(self, action: str, event: str):
        act = self._hotkey_by_id.get(action)
        if act is None:
            return
        cb = {"press": act.press, "tap": act.tap, "hold": act.hold}.get(event)
        if cb:
            cb()

    def _open_config(self):
        dlg = ConfigDialog(
            [(a.id, a.label) for a in self._hotkey_actions],
            dict(self.hotkey_bindings),
            probe=lambda token: bool(token),
            mame_dir=self.mame_dir,
            parent=self,
        )
        dlg.exec()
        self.hotkey_bindings = dlg.bindings
        save_bindings(self.hotkey_bindings)
        self._apply_hotkeys()
        if dlg.mame_dir != self.mame_dir:
            self._set_mame_dir(dlg.mame_dir)

    def _set_mame_dir(self, mame_dir: Path | None):
        save_mame_dir(mame_dir)
        self.mame_dir = mame_dir
        self.launcher = Launcher(mame_dir) if mame_dir else None
        ready = bool(self.launcher and self.launcher.available())
        self.launch_btn.setEnabled(ready)
        self.launch_btn.setToolTip("" if ready else "mame.exe not found")
        if not self.config.data:
            try:
                self.config = Config.load(mame_dir)
                self._config_error = None
            except FileNotFoundError as exc:
                self._config_error = str(exc)
        self._on_notice(
            f"MAME path set to {mame_dir}" if mame_dir else "MAME path cleared"
        )

    def closeEvent(self, event):
        self.bridge.stop()
        super().closeEvent(event)
