"""Native trainer UI: independent players, explicit overrides, acknowledged state."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIntValidator, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .bridge import Bridge
from .config import (
    GRADE_NAMES_RELATIVE,
    MUSIC_TRACKS,
    SONG_TO_SCENE,
    bundled_plugin_dir,
    find_mame_exe,
    save_mame_exe,
)
from .controls import GravityControl, NumericControl, gravity_text
from .hotkeys import load_bindings, save_bindings
from .keymap import mame_token, mod_names
from .launcher import Launcher
from .model import empty_settings, load_catalog, load_profile, save_profile


class ControlRow(QWidget):
    edited = Signal()

    def __init__(self, key, spec):
        super().__init__()
        self.key, self.spec = key, spec
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox(spec["label"])
        self.enabled.setMinimumWidth(170)
        self.enabled.setToolTip(spec["help"])
        layout.addWidget(self.enabled)
        kind = spec.get("kind")
        if kind in ("visibility", "flag", "toggle"):
            self.value = QComboBox()
            if kind == "visibility":
                self.value.addItem("Visible", 0)
                self.value.addItem("Invisible", 1)
                self.value.addItem("Fading", 2)
            elif kind == "toggle":
                self.value.addItem("Off", 0)
                self.value.addItem("On", 1)
            else:
                self.value.addItem("Enabled", 1)
            self.value.setCurrentIndex(self.value.findData(spec["default"]))
            self.value.currentIndexChanged.connect(self.edited)
        elif kind == "gravity":
            self.value = GravityControl()
            self.value.valueChanged.connect(self.edited)
        else:
            self.value = NumericControl(spec, " frames")
            self.value.valueChanged.connect(self.edited)
        self.value.setToolTip(spec["help"])
        self.value.setMinimumWidth(160)
        self.value.setEnabled(False)
        layout.addWidget(self.value)
        self.enabled.toggled.connect(self.value.setEnabled)
        self.enabled.toggled.connect(self.edited)

    def raw(self):
        if isinstance(self.value, QComboBox):
            return self.value.currentData()
        if self.spec.get("kind") == "gravity":
            return self.value.raw()
        return self.value.value() - self.spec.get("display_offset", 0)

    def set_raw(self, value):
        on = value is not None
        with QSignalBlocker(self.enabled), QSignalBlocker(self.value):
            self.enabled.setChecked(on)
            self.value.setEnabled(on)
            if on:
                if isinstance(self.value, QComboBox):
                    self.value.setCurrentIndex(self.value.findData(value))
                elif self.spec.get("kind") == "gravity":
                    self.value.set_raw(value)
                else:
                    self.value.setValue(value + self.spec.get("display_offset", 0))


class CollapsibleSection(QGroupBox):
    def __init__(self, title):
        super().__init__()
        self.section_title = title
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel(title), 1)
        self.toggle = QToolButton()
        self.toggle.setAutoRaise(True)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        header.addWidget(self.toggle)
        layout.addLayout(header)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self.set_expanded)
        self.set_expanded(True)

    def set_expanded(self, expanded):
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        action = "Collapse" if expanded else "Expand"
        self.toggle.setToolTip(f"{action} {self.section_title}")
        self.toggle.setAccessibleName(f"{action} {self.section_title}")


class PlayerPanel(QWidget):
    changed = Signal(int, str)
    action = Signal(str, int, object)

    def __init__(self, player, catalog):
        super().__init__()
        self.player = player
        self.rows = {}
        self.practice_settings = {}
        self.toggles = {}
        self.sections = {}
        layout = QVBoxLayout(self)

        def section(title):
            box = CollapsibleSection(title)
            self.sections[title] = box
            layout.addWidget(box)
            return box, box.content

        def control(target, key):
            row = ControlRow(key, catalog["controls"][key])
            self.rows[key] = row
            target.addWidget(row)
            row.edited.connect(lambda k=key: self.changed.emit(player, k))

        def toggle(target, key, label):
            button = QCheckBox(label)
            button.setToolTip(catalog["controls"][key]["help"])
            button.toggled.connect(
                lambda checked, k=key: self.toggle_practice(k, checked)
            )
            self.toggles[key] = button
            target.addWidget(button)

        _, timing = section("Timing")
        presetrow = QHBoxLayout()
        label = QLabel("Preset")
        label.setMinimumWidth(170)
        presetrow.addWidget(label)
        self.presets = QComboBox()
        for name in catalog["presets"]:
            if not name.startswith("_"):
                self.presets.addItem(name.replace("_", " ").title(), name)
        presetrow.addWidget(self.presets, 1)
        apply = QPushButton("Apply")
        apply.clicked.connect(lambda: self.apply_preset(catalog))
        presetrow.addWidget(apply)
        timing.addLayout(presetrow)
        for key in ("gravity", "are", "line_are", "line_clear", "lock", "das"):
            control(timing, key)

        _, modifiers = section("Modifiers")
        control(modifiers, "invisible")
        toggle(modifiers, "big", "BIG mode")
        toggle(modifiers, "items", "ITEM mode")
        control(modifiers, "ghost")

        self.actions, progression = section("Progression")
        toggle(progression, "freeze_level", "Freeze level")

        def action_row(label):
            row = QHBoxLayout()
            title = QLabel(label)
            title.setMinimumWidth(170)
            row.addWidget(title)
            progression.addLayout(row)
            return row

        self.level = QLineEdit()
        self.level.setValidator(QIntValidator(0, 999, self.level))
        self.level.setMaxLength(3)
        self.level.setPlaceholderText("000–999")
        setlevel = QPushButton("Jump to level")
        setlevel.clicked.connect(self.jump_level)
        self.level.returnPressed.connect(self.jump_level)
        row = action_row("Level")
        row.addWidget(self.level, 1)
        row.addWidget(setlevel)
        row = action_row("Section")
        for text, direction in [("↓ Previous", -1), ("↑ Next", 1)]:
            button = QPushButton(text)
            button.clicked.connect(
                lambda _, d=direction: self.action.emit("section", player, d)
            )
            row.addWidget(button, 1)
        grade = QComboBox()
        grade.addItems(GRADE_NAMES_RELATIVE)
        setgrade = QPushButton("Set internal grade")
        setgrade.clicked.connect(
            lambda: self.action.emit("grade", player, grade.currentIndex())
        )
        row = action_row("Grade")
        row.addWidget(grade, 1)
        row.addWidget(setgrade)
        control(progression, "mroll")
        control(progression, "bypass_torikan")
        _, status = section("Status")
        labels = (
            "State",
            "Level",
            "Section",
            "Gravity",
            "Lock remaining / duration",
            "DAS charge",
            "Delay remaining",
            "Mode",
        )
        self.telemetry = QTableWidget(len(labels), 2)
        self.telemetry.setHorizontalHeaderLabels(["Metric", "Current value"])
        self.telemetry.verticalHeader().hide()
        self.telemetry.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.telemetry.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.telemetry.setAlternatingRowColors(True)
        self.telemetry.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.telemetry.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for row, label in enumerate(labels):
            self.telemetry.setItem(row, 0, QTableWidgetItem(label))
            self.telemetry.setItem(
                row, 1, QTableWidgetItem("Waiting for game…" if row == 0 else "—")
            )
        self.telemetry.resizeRowsToContents()
        self.telemetry.setFixedHeight(
            self.telemetry.horizontalHeader().height()
            + sum(self.telemetry.rowHeight(row) for row in range(len(labels)))
            + 2 * self.telemetry.frameWidth()
        )
        status.addWidget(self.telemetry)
        layout.addStretch()

    def jump_level(self):
        if self.level.hasAcceptableInput():
            self.action.emit("level", self.player, int(self.level.text()))

    def toggle_practice(self, key, checked):
        if key == "freeze_level" and not checked:
            self.practice_settings.pop(key, None)
        else:
            self.practice_settings[key] = int(checked)
        self.changed.emit(self.player, key)

    def apply_preset(self, catalog):
        preset = catalog["presets"][self.presets.currentData()]
        for key in ("are", "line_are", "line_clear", "lock", "das"):
            row = self.rows[key]
            member = "lock_delay" if key == "lock" else key
            row.set_raw(preset[member] - row.spec.get("display_offset", 0))
        self.changed.emit(self.player, "preset")

    def read(self):
        return {
            **self.practice_settings,
            **{
                key: row.raw()
                for key, row in self.rows.items()
                if row.enabled.isChecked()
            },
        }

    def display(self, settings):
        self.practice_settings = {k: settings[k] for k in self.toggles if k in settings}
        for key, toggle in self.toggles.items():
            with QSignalBlocker(toggle):
                toggle.setChecked(bool(settings.get(key, 0)))
        for key, row in self.rows.items():
            row.set_raw(settings.get(key))

    def update_state(self, s, settings, playing=True):
        actual = {
            "big": bool(s["next_piece"] & 0x200),
            "items": bool(s["game_mode"] & 0x200),
        }
        for key, toggle in self.toggles.items():
            with QSignalBlocker(toggle):
                toggle.setChecked(bool(settings.get(key, actual.get(key, False))))
        state = {
            0: "Idle",
            1: "Starting",
            2: "Active",
            3: "Locking",
            4: "Line clear",
            5: "Entry",
            7: "Game over",
            10: "Menu",
            13: "Complete",
        }.get(s["play_state"], str(s["play_state"]))
        gravity = (
            settings.get("effective_gravity", s["gravity"]) if playing else s["gravity"]
        )
        values = (
            state,
            f"{s['level']:03d}",
            str(s["section"]),
            gravity_text(gravity),
            f"{s['lock_remaining']} / {s['lock_duration']} frames",
            f"{s['das_charge']} frames",
            f"{s['delay_remaining']} frames",
            f"0x{s['game_mode']:04X}",
        )
        for row, value in enumerate(values):
            item = self.telemetry.item(row, 1)
            if item.text() != value:
                item.setText(value)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TGM2+ Trainer")
        self.resize(660, 940)
        self.catalog = load_catalog()
        self.settings = empty_settings()
        self.mame_exe = find_mame_exe()
        self.process = None
        self.launcher = None
        self.connected = False
        self.ready = False
        self.revision = 0
        self.acked = -1
        manifest = json.loads((bundled_plugin_dir() / "native.json").read_text())
        self.bridge = Bridge(port=self.catalog["port"], patch_id=manifest["sha256"])
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        toolbar = QHBoxLayout()
        self.connection = QLabel("Disconnected")
        toolbar.addWidget(self.connection, 1)
        choose = QPushButton("Choose MAME…")
        choose.clicked.connect(self.choose_mame)
        toolbar.addWidget(choose)
        self.launch = QPushButton("Launch MAME")
        self.launch.clicked.connect(self.launch_mame)
        toolbar.addWidget(self.launch)
        layout.addLayout(toolbar)
        self.path = QLabel(
            str(self.mame_exe or "Choose your MAME executable to launch the game.")
        )
        self.path.setWordWrap(True)
        layout.addWidget(self.path)
        self.tabs = QTabWidget()
        self.panels = []
        for p in range(2):
            panel = PlayerPanel(p, self.catalog)
            self.panels.append(panel)
            panel.changed.connect(self.edited)
            panel.action.connect(self.bridge.action)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            self.tabs.addTab(scroll, f"Player {p + 1}")
        musicrow = QHBoxLayout()
        self.reset_player = QPushButton("Reset Player 1")
        self.reset_player.clicked.connect(
            lambda: self.panels[self.tabs.currentIndex()].action.emit(
                "restart", self.tabs.currentIndex(), None
            )
        )
        musicrow.addWidget(self.reset_player)
        self.tabs.currentChanged.connect(self.update_reset_player)
        musicrow.addWidget(QLabel("Music (shared):"))
        self.music = QComboBox()
        self.music.addItem("Follow game", None)
        self.music.addItem("Silence", 2)
        for name, scene in zip(MUSIC_TRACKS, SONG_TO_SCENE):
            self.music.addItem(name, scene)
        self.music.currentIndexChanged.connect(lambda: self.edited(-1, "music"))
        musicrow.addWidget(self.music, 1)
        self.playing = QLabel("")
        musicrow.addWidget(self.playing)
        layout.addLayout(musicrow)
        layout.addWidget(self.tabs, 1)
        buttons = QHBoxLayout()
        for title, callback in [
            ("Copy to other player", self.copy_player),
            ("Release all overrides", self.release_all),
            ("Load profile…", self.load),
            ("Save profile…", self.save),
        ]:
            b = QPushButton(title)
            b.clicked.connect(callback)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.notice = QLabel("Settings are sent only when changed.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.bridge.connectionChanged.connect(self.on_connection)
        self.bridge.readyChanged.connect(self.on_ready)
        self.bridge.stateReceived.connect(self.on_state)
        self.bridge.notice.connect(self.notice.setText)
        self.bridge.acknowledged.connect(self.on_ack)
        menu = self.menuBar().addMenu("Game")
        reset = QAction("Reset MAME", self)
        reset.triggered.connect(self.bridge.reset_machine)
        menu.addAction(reset)
        for label, value in [
            ("Enable game debug mode", 1),
            ("Disable game debug mode", 0),
        ]:
            action = QAction(label, self)
            action.triggered.connect(
                lambda _, v=value: self.bridge.action("debug", 0, v)
            )
            menu.addAction(action)
        release = QAction("Release all overrides", self)
        release.setShortcut(QKeySequence("Ctrl+Backspace"))
        release.triggered.connect(self.release_all)
        self.addAction(release)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_process)
        self.timer.start(500)
        self.hotkey_bindings = load_bindings()
        self.last_players = [{}, {}]
        self.bridge.hotkeyEvent.connect(self.on_hotkey)
        hotkeys = QAction("Hotkeys…", self)
        hotkeys.triggered.connect(self.edit_hotkeys)
        menu.addAction(hotkeys)
        self.send_hotkeys()
        self.bridge.start()
        self.refresh_status()

    def edited(self, p, key):
        self.settings = {
            "players": [panel.read() for panel in self.panels],
            "global": {},
        }
        if self.music.currentData() is not None:
            self.settings["global"]["music"] = self.music.currentData()
        self.revision = self.bridge.replace_settings(self.settings)
        self.refresh_status()

    def show_settings(self):
        for panel, settings in zip(self.panels, self.settings["players"]):
            panel.display(settings)
        with QSignalBlocker(self.music):
            self.music.setCurrentIndex(
                self.music.findData(self.settings["global"].get("music"))
            )
        self.edited(-1, "profile")

    def release_all(self):
        self.settings = empty_settings()
        self.show_settings()

    def copy_player(self):
        p = self.tabs.currentIndex()
        self.settings["players"][1 - p] = copy.deepcopy(self.settings["players"][p])
        self.show_settings()

    def on_connection(self, value):
        self.connected = value
        if not value:
            self.acked = -1
        self.refresh_status()

    def on_ready(self, value):
        self.ready = value
        self.refresh_status()

    def on_ack(self, revision):
        self.acked = revision
        self.refresh_status()

    def update_reset_player(self):
        player = self.tabs.currentIndex()
        self.reset_player.setText(f"Reset Player {player + 1}")

    def refresh_status(self):
        self.update_reset_player()
        self.connection.setText(
            "Disconnected — settings queued"
            if not self.connected
            else "Connected — waiting for game"
            if not self.ready
            else "Ready — settings applied"
            if self.acked == self.revision
            else "Ready — applying settings…"
        )
        self.launch.setEnabled(
            self.mame_exe is not None and self.process is None and not self.connected
        )

    def on_state(self, m):
        self.last_players = m["players"]
        if not m.get("playing", True):
            self.notice.setText(
                "Title / demo — overrides suspended. Your settings resume during gameplay."
            )
        elif self.notice.text().startswith("Title / demo"):
            self.notice.setText("Gameplay — overrides active.")
        for panel, s, settings in zip(
            self.panels, m["players"], m["settings"]["players"]
        ):
            panel.update_state(s, settings, m.get("playing", True))
        self.update_reset_player()
        scene = m.get("music_scene", -1)
        track = SONG_TO_SCENE.index(scene) if scene in SONG_TO_SCENE else -1
        self.playing.setText(
            "Scene: " + (MUSIC_TRACKS[track] if track >= 0 else "Silence")
        )

    def choose_mame(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose MAME executable", str(self.mame_exe or "")
        )
        if path:
            self.mame_exe = Path(path)
            save_mame_exe(self.mame_exe)
            self.path.setText(path)
            self.refresh_status()

    def launch_mame(self):
        try:
            self.launcher = Launcher(self.mame_exe)
            self.process = self.launcher.launch()
            self.refresh_status()
            self.notice.setText(
                "MAME is starting. The trainer waits for the game code before installing patches."
            )
        except (OSError, ValueError) as exc:
            self.notice.setText(str(exc))

    def poll_process(self):
        if self.process and self.process.poll() is not None:
            code = self.process.returncode
            self.process = None
            self.refresh_status()
            self.notice.setText(f"MAME exited ({code}). Log: {self.launcher.log_path}")

    def load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load trainer profile", "", "Trainer profiles (*.json)"
        )
        if path:
            try:
                self.settings = load_profile(path, self.catalog)
                self.show_settings()
                self.notice.setText("Profile loaded.")
            except (OSError, ValueError) as exc:
                self.notice.setText(str(exc))

    def save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save trainer profile", "practice.json", "Trainer profiles (*.json)"
        )
        if path:
            try:
                save_profile(path, self.settings, self.catalog)
                self.notice.setText("Profile saved.")
            except (OSError, ValueError) as exc:
                self.notice.setText(str(exc))

    HOTKEYS: ClassVar[dict[str, str]] = {
        "level_up": "Level +100",
        "level_down": "Level -100",
        "level_freeze": "Toggle freeze level",
        "grade_up": "Grade +1",
        "reset_game": "Restart player",
        "invisible": "Toggle invisible",
        "big_mode": "Toggle BIG",
        "ghost": "Toggle ghost",
        "item_mode": "Toggle items",
        "release_all": "Release all overrides",
    }

    def send_hotkeys(self):
        self.bridge.set_hotkeys(
            [
                {
                    "action": k,
                    "token": v["token"],
                    "mods": v.get("mods", []),
                    "kind": "taphold" if k in ("invisible", "ghost") else "press",
                }
                for k, v in self.hotkey_bindings.items()
                if k in self.HOTKEYS
            ]
        )

    def edit_hotkeys(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Practice hotkeys")
        layout = QFormLayout(dialog)
        layout.addRow(
            QLabel(
                "Hotkeys work while MAME has focus. Actions use the selected player tab."
            )
        )
        editors = {}
        for key, label in self.HOTKEYS.items():
            editor = QKeySequenceEdit(
                QKeySequence(self.hotkey_bindings.get(key, {}).get("text", ""))
            )
            editor.setMaximumSequenceLength(1)
            editors[key] = editor
            layout.addRow(label, editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        bindings = {}
        used = set()
        for key, editor in editors.items():
            sequence = editor.keySequence()
            if sequence.isEmpty():
                continue
            combination = sequence[0]
            token = mame_token(combination.key())
            mods = mod_names(combination.keyboardModifiers())
            signature = (token, tuple(mods))
            if not token or signature in used:
                self.notice.setText(
                    "Hotkeys were not saved: unsupported or duplicate key."
                )
                return
            used.add(signature)
            bindings[key] = {"token": token, "mods": mods, "text": sequence.toString()}
        self.hotkey_bindings = bindings
        save_bindings(bindings)
        self.send_hotkeys()

    def on_hotkey(self, action, event):
        p = self.tabs.currentIndex()
        state = self.last_players[p]
        key = {
            "level_freeze": "freeze_level",
            "big_mode": "big",
            "item_mode": "items",
        }.get(action, action)
        if key in self.panels[p].toggles:
            self.panels[p].toggles[key].toggle()
        elif key in self.panels[p].rows:
            row = self.panels[p].rows[key]
            if event == "hold" or row.enabled.isChecked():
                row.set_raw(None)
            else:
                row.set_raw(row.spec["default"])
            self.edited(p, key)
        elif action in ("level_up", "level_down"):
            self.bridge.action(
                "section",
                p,
                1 if action == "level_up" else -1,
            )
        elif action == "grade_up":
            self.bridge.action("grade", p, min(31, state.get("grade", 0) + 1))
        elif action == "reset_game":
            self.bridge.action("restart", p)
        elif action == "release_all":
            self.release_all()

    def closeEvent(self, event):
        # Closing the app leaves the user's game and selected native settings
        # running. Reopening publishes the new app's complete desired snapshot.
        self.bridge.stop()
        event.accept()
