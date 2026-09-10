"""Exercise the actual Qt controls, bridge and staged launcher against MAME."""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from tgmtrainer.launcher import Launcher
from tgmtrainer.ui import MainWindow


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mame", type=Path)
    ap.add_argument("--screenshot", type=Path)
    args = ap.parse_args()
    app = QApplication([])
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    w = MainWindow()
    w.show()
    states = []
    w.bridge.stateReceived.connect(states.append)
    statuses, notices = [], []
    w.bridge.statusReceived.connect(statuses.append)
    w.bridge.notice.connect(notices.append)
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        launcher = Launcher(args.mame.resolve())
        proc = launcher.launch(
            [
                "-video",
                "none",
                "-sound",
                "auto",
                "-volume",
                "-32",
                "-speed",
                "4",
                "-seconds_to_run",
                "90",
                "-cfg_directory",
                str(folder / "cfg"),
                "-nvram_directory",
                str(folder / "nvram"),
                "-autoboot_delay",
                "0",
                "-autoboot_script",
                str(ROOT / "tools/gameplay_probe.lua"),
            ]
        )
        try:

            def until(predicate):
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline and proc.poll() is None:
                    app.processEvents()
                    if predicate():
                        return
                    time.sleep(0.005)
                raise AssertionError(
                    f"Timed out: {w.connection.text()}; {w.notice.text()}; log={launcher.log_path}"
                )

            until(lambda: states and states[-1]["frame"] >= 1200)
            assert not states[-1]["playing"], states[-1]
            notices.clear()
            for panel in w.panels:
                assert panel.level.isEnabled()
                for action, value in (
                    ("level", 486),
                    ("section", 1),
                    ("grade", 12),
                    ("restart", None),
                ):
                    panel.action.emit(action, panel.player, value)
            assert w.reset_player.isEnabled()
            w.bridge._send({"t": "diagnostics", "id": "title-actions"})
            until(lambda: any(s.get("id") == "title-actions" for s in statuses))
            status = next(s for s in statuses if s.get("id") == "title-actions")
            assert status["action_writes"] == 0, status
            assert not notices, notices
            print(
                "PASS: title actions are silently discarded through the live bridge; controls stay enabled"
            )
            until(
                lambda: (
                    states
                    and states[-1]["frame"] >= 3000
                    and states[-1]["players"][0]["play_state"] == 2
                )
            )
            row = w.panels[0].rows["gravity"]
            row.value.editor.setText("0/256")
            row.value.editor.editingFinished.emit()
            row.enabled.setChecked(True)
            until(
                lambda: (
                    w.acked == w.revision
                    and states[-1]["settings"]["players"][0].get("gravity") == 0
                )
            )
            y = states[-1]["players"][0]["active_y"]
            target = states[-1]["frame"] + 120
            until(lambda: states[-1]["frame"] >= target)
            assert states[-1]["players"][0]["active_y"] == y, states[-1]
            assert "applied" in w.connection.text(), w.connection.text()
            panel = w.panels[0]
            panel.toggles["freeze_level"].setChecked(True)
            panel.level.setText("486")
            panel.jump_level()
            until(lambda: states[-1]["players"][0]["level"] == 486)
            assert states[-1]["players"][0]["section"] == 4, states[-1]
            assert states[-1]["players"][0]["section_count"] == 4, states[-1]
            panel.action.emit("section", 0, 1)
            until(lambda: states[-1]["players"][0]["level"] == 500)
            assert states[-1]["players"][0]["section"] == 5, states[-1]
            panel.toggles["big"].setChecked(True)
            panel.toggles["items"].setChecked(True)
            until(
                lambda: (
                    states[-1]["players"][0]["next_piece"] & 0x200
                    and states[-1]["players"][0]["game_mode"] & 0x200
                )
            )
            panel.toggles["big"].setChecked(False)
            panel.toggles["items"].setChecked(False)
            until(
                lambda: (
                    not states[-1]["players"][0]["next_piece"] & 0x200
                    and not states[-1]["players"][0]["game_mode"] & 0x200
                )
            )
            if args.screenshot:
                assert w.grab().save(str(args.screenshot.resolve()))
            row.enabled.setChecked(False)
            until(
                lambda: (
                    w.acked == w.revision
                    and states[-1]["players"][0]["gravity"] > 0
                    and states[-1]["players"][0]["active_y"] < y
                )
            )
            print(
                "PASS: Qt 0G stops movement and release restores falling; frozen level jumps to 486 with section counters, section up reaches 500; BIG/ITEM toggles set and clear real flags; bundled plugin staged by launcher"
            )
        finally:
            w.close()
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
