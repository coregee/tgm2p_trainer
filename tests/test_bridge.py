import copy
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from itertools import pairwise
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSlider, QApplication, QPushButton
from tgmtrainer.bridge import Bridge, split_lines
from tgmtrainer.config import bundled_plugin_dir
from tgmtrainer.controls import ONE_G, GravityControl
from tgmtrainer.launcher import LAUNCH_ARGS
from tgmtrainer.model import (
    empty_settings,
    load_catalog,
    load_profile,
    save_profile,
    validate,
)
from tgmtrainer.ui import MainWindow


class TrainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_framing_and_size_limit(self):
        rest, msgs = split_lines(b'null\n[]\n42\n{"t":"state"}\n{"text":"\xe3')
        self.assertEqual(msgs, [{"t": "state"}])
        rest, msgs = split_lines(rest + b'\x81\x82"}\n')
        self.assertEqual(msgs, [{"text": "\u3042"}])
        self.assertEqual(rest, b"")
        with self.assertRaises(ValueError):
            split_lines(b"x" * 65537)

    def test_full_snapshot_on_reconnect_including_offline_release(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(4)
        bridge = Bridge(port=listener.getsockname()[1])
        settings = empty_settings()
        settings["players"][1] = {"gravity": 0}
        bridge.replace_settings(settings)
        errors = []
        snapshots = []
        offline = threading.Event()
        cleared = threading.Event()

        def server():
            try:
                for attempt in range(2):
                    client, _ = listener.accept()
                    with client:
                        client.settimeout(3)
                        with client.makefile("rb") as file:
                            self.assertEqual(
                                json.loads(file.readline()), {"t": "hello"}
                            )
                            client.sendall(
                                b'{"t":"hello","protocol":3,"rom":"tgm2p","compatible":true}\n'
                            )
                            while True:
                                m = json.loads(file.readline())
                                if m.get("t") == "sync":
                                    snapshots.append(m)
                                    break
                    if attempt == 0:
                        offline.set()
                        self.assertTrue(cleared.wait(3))
            except BaseException as exc:  # noqa: BLE001 -- transfer worker failures to the test thread
                errors.append(exc)

        worker = threading.Thread(target=server)
        worker.start()
        bridge.start()
        try:
            self.assertTrue(offline.wait(3))
            bridge.replace_settings(empty_settings())
            cleared.set()
            worker.join(6)
            self.assertFalse(worker.is_alive())
            if errors:
                raise errors[0]
            self.assertEqual(snapshots[0]["settings"]["players"][1], {"gravity": 0})
            self.assertEqual(snapshots[1]["settings"], empty_settings())
            self.assertGreater(snapshots[1]["id"], snapshots[0]["id"])
        finally:
            bridge.stop()
            listener.close()

    def test_profiles_are_validated_before_import(self):
        catalog = load_catalog()
        s = empty_settings()
        s["players"][0] = {"gravity": 65536, "lock": 17}
        s["players"][1] = {"gravity": 0, "invisible": 2}
        s["global"] = {"music": 3}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "profile.json"
            save_profile(p, s, catalog)
            self.assertEqual(load_profile(p, catalog), s)
            legacy = copy.deepcopy(s)
            legacy["players"][1] = {"effective_gravity": 32768}
            save_profile(p, legacy, catalog)
            self.assertEqual(load_profile(p, catalog)["players"][1], {"gravity": 32768})
        bad = copy.deepcopy(s)
        bad["players"][1]["gravity"] = False
        with self.assertRaises(ValueError):
            validate(bad, catalog)
        bad = copy.deepcopy(s)
        bad["players"][0]["effective_gravity"] = 0
        with self.assertRaises(ValueError):
            validate(bad, catalog)
        bad = copy.deepcopy(s)
        bad["players"][0]["poke"] = 0
        with self.assertRaises(ValueError):
            validate(bad, catalog)
        self.assertEqual(s["players"][0], {"gravity": 65536, "lock": 17})

    def test_offline_practice_actions_are_silent_and_not_queued(self):
        bridge = Bridge()
        notices = []
        bridge.notice.connect(notices.append)
        bridge._send = Mock()
        for action, value in (
            ("level", 486),
            ("section", 1),
            ("grade", 12),
            ("restart", None),
        ):
            bridge.action(action, 0, value)
        bridge._send.assert_not_called()
        self.assertEqual(notices, [])
        bridge._compatible = True
        bridge._sync()
        self.assertTrue(
            all(call.args[0]["t"] == "sync" for call in bridge._send.call_args_list)
        )
        bridge._send.reset_mock()
        bridge.action("level", 1, 123)
        bridge._send.assert_called_once_with(
            {"t": "action", "action": "level", "player": 1, "value": 123}
        )

    def test_practice_controls_stay_enabled_through_title_and_readiness_updates(self):
        w = MainWindow()
        w.bridge.stop()
        try:
            state = dict.fromkeys(
                (
                    "next_piece",
                    "game_mode",
                    "play_state",
                    "gravity",
                    "level",
                    "section",
                    "lock_remaining",
                    "lock_duration",
                    "das_charge",
                    "delay_remaining",
                ),
                0,
            )
            for connected, ready, playing in (
                (False, False, False),
                (True, False, False),
                (True, True, False),
                (True, True, True),
                (True, True, False),
                (False, False, False),
            ):
                w.on_connection(connected)
                w.on_ready(ready)
                w.on_state(
                    {
                        "players": [state, state],
                        "settings": empty_settings(),
                        "playing": playing,
                    }
                )
                # Heartbeats can arrive between title telemetry packets.
                w.on_ready(ready)
                for player, panel in enumerate(w.panels):
                    w.tabs.setCurrentIndex(player)
                    self.assertTrue(w.reset_player.isEnabled())
                    self.assertEqual(
                        w.reset_player.text(), f"Reset Player {player + 1}"
                    )
                    self.assertTrue(panel.level.isEnabled())
                    self.assertTrue(
                        all(
                            b.isEnabled()
                            for b in panel.actions.findChildren(QPushButton)
                        )
                    )
        finally:
            w.close()

    def test_ui_player_isolation_units_release_and_acknowledgement(self):
        w = MainWindow()
        w.bridge.stop()
        try:
            p1, p2 = w.panels
            self.assertNotIn("effective_gravity", p1.rows)
            self.assertNotIn("hold_level", p1.rows)
            self.assertNotIn("transform", w.catalog["controls"])
            p1.toggles["big"].setChecked(True)
            self.assertEqual(w.settings["players"][0]["big"], 1)
            p1.toggles["big"].setChecked(False)
            self.assertEqual(w.settings["players"][0]["big"], 0)
            p1.toggles["items"].setChecked(True)
            p1.toggles["freeze_level"].setChecked(True)
            self.assertEqual(w.settings["players"][0]["freeze_level"], 1)
            p1.toggles["freeze_level"].setChecked(False)
            self.assertNotIn("freeze_level", w.settings["players"][0])
            actions = []
            p1.action.connect(lambda *args: actions.append(args))
            QTest.keyClicks(p1.level, "486")
            p1.jump_level()
            self.assertEqual(actions[-1], ("level", 0, 486))
            p1.level.clear()
            QTest.keyClicks(p1.level, "999")
            p1.jump_level()
            self.assertEqual(actions[-1], ("level", 0, 999))
            p1.rows["gravity"].enabled.setChecked(True)
            p1.rows["gravity"].value.editor.setText("128/256")
            p1.rows["gravity"].value.editor.editingFinished.emit()
            self.assertEqual(w.settings["players"][0]["gravity"], 32768)
            self.assertEqual(w.settings["players"][1], {})
            self.assertNotIn("effective_gravity", w.settings["players"][0])
            are = p1.rows["are"]
            self.assertEqual(are.value.slider.minimum(), 3)
            are.enabled.setChecked(True)
            are.value.slider.setValue(3)
            self.assertEqual(are.value.editor.value(), 3)
            self.assertEqual(w.settings["players"][0]["are"], 1)
            are.value.editor.setValue(37)
            self.assertEqual(are.value.slider.value(), 37)
            self.assertEqual(w.settings["players"][0]["are"], 35)
            p2.rows["lock"].enabled.setChecked(True)
            p2.rows["lock"].value.setValue(17)
            self.assertEqual(w.settings["players"][1]["lock"], 17)
            visibility = p2.rows["invisible"]
            visibility.enabled.setChecked(True)
            visibility.value.setCurrentIndex(visibility.value.findText("Fading"))
            self.assertEqual(w.settings["players"][1]["invisible"], 2)
            w.on_connection(True)
            w.on_ready(True)
            self.assertIn("applying", w.connection.text())
            w.on_ack(w.revision)
            self.assertIn("applied", w.connection.text())
            w.release_all()
            self.assertEqual(w.settings, empty_settings())
            self.assertTrue(
                all(
                    not row.enabled.isChecked()
                    for p in w.panels
                    for row in p.rows.values()
                )
            )
        finally:
            w.close()

    def test_visibility_hotkey_reveals_without_releasing_override(self):
        w = MainWindow()
        w.bridge.stop()
        try:
            w.bridge.replace_settings = Mock(return_value=1)
            for player in range(2):
                w.tabs.setCurrentIndex(player)
                row = w.panels[player].rows["invisible"]
                other = copy.deepcopy(w.settings["players"][1 - player])
                for initial, expected in ((None, 1), (1, 0), (0, 1), (2, 0)):
                    with self.subTest(player=player, initial=initial):
                        row.set_raw(initial)
                        w.bridge.hotkeyEvent.emit("invisible", "tap")
                        self.assertTrue(row.enabled.isChecked())
                        self.assertEqual(row.raw(), expected)
                        self.assertEqual(
                            w.settings["players"][player]["invisible"], expected
                        )
                        self.assertEqual(w.settings["players"][1 - player], other)
                        w.bridge.replace_settings.assert_called_with(w.settings)
                w.bridge.hotkeyEvent.emit("invisible", "hold")
                self.assertFalse(row.enabled.isChecked())
                self.assertNotIn("invisible", w.settings["players"][player])
            self.assertEqual(w.HOTKEYS["invisible"], "Toggle visibility")
        finally:
            w.close()

    def test_gravity_slider_scale_fractional_entry_and_steps(self):
        control = GravityControl()
        slider = control.slider
        self.assertEqual(slider.gravity_for_pos(0), 0)
        self.assertEqual(slider.gravity_for_pos(slider.maximum() // 2), ONE_G)
        self.assertEqual(slider.gravity_for_pos(slider.maximum()), 20 * ONE_G)
        values = (
            list(range(0, ONE_G + 1, 256))
            + list(range(ONE_G, 5 * ONE_G + 1, 1024))
            + list(range(5 * ONE_G, 20 * ONE_G + 1, ONE_G // 4))
        )
        for raw in values:
            self.assertEqual(slider.gravity_for_pos(slider.pos_for_gravity(raw)), raw)
        control.editor.setText("128/256 G")
        control.editor.editingFinished.emit()
        self.assertEqual(control.raw(), ONE_G // 2)
        control.set_raw(5 * ONE_G)
        self.assertEqual(control.editor.text(), "5 G")
        slider.step(1)
        self.assertEqual(control.editor.text(), "5 + 64/256 G")
        slider.step(-1)
        self.assertEqual(control.raw(), 5 * ONE_G)
        slider.step(-1)
        self.assertEqual(control.raw(), 5 * ONE_G - 1024)
        control.editor.setText("1 + 4/256 G")
        control.editor.editingFinished.emit()
        self.assertEqual(control.raw(), ONE_G + 1024)
        self.assertEqual(control.editor.text(), "1 + 4/256 G")
        control.set_raw(ONE_G)
        slider.step(1)
        self.assertEqual(control.raw(), ONE_G + 1024)
        slider.step(-1)
        slider.step(-1)
        self.assertEqual(control.raw(), ONE_G - 256)
        control.editor.setText("7.25")
        control.editor.editingFinished.emit()
        self.assertEqual(control.raw(), 29 * ONE_G // 4)
        slider.triggerAction(QAbstractSlider.SliderPageStepAdd)
        self.assertGreater(control.raw(), 29 * ONE_G // 4)

    def test_bundle_and_generated_hook_regions(self):
        self.assertIn("-drc", LAUNCH_ARGS)
        self.assertNotIn("-nodrc", LAUNCH_ARGS)
        folder = bundled_plugin_dir()
        m = json.loads((folder / "native.json").read_text())
        regions = sorted((p["address"], p["address"] + p["size"]) for p in m["patches"])
        for a, b in pairwise(regions):
            self.assertLessEqual(a[1], b[0])
        for p in m["patches"]:
            self.assertEqual(len(bytes.fromhex(p["expected"])), p["size"])
            self.assertEqual(len(bytes.fromhex(p["bytes"])), p["size"])
        self.assertLess(m["base"] + len(bytes.fromhex(m["payload"])), m["parameters"])


if __name__ == "__main__":
    unittest.main()
