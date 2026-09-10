"""Live native-patch integration test; requires a local MAME + tgm2p ROM."""

import argparse
import json
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mame", type=Path)
    ap.add_argument("--interpreter", action="store_true")
    args = ap.parse_args()
    exe = args.mame.resolve()
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        plugins = folder / "plugins"
        shutil.copytree(ROOT / "plugin", plugins / "tgm2p-trainer")
        logpath = Path(tempfile.gettempdir()) / "tgm2p-trainer/native-live.log"
        logpath.parent.mkdir(parents=True, exist_ok=True)
        log = logpath.open("w+")
        proc = subprocess.Popen(
            [
                str(exe),
                "tgm2p",
                "-video",
                "none",
                "-sound",
                "auto",
                "-volume",
                "-32",
                "-speed",
                "4",
                "-seconds_to_run",
                "150",
                "-nodrc" if args.interpreter else "-drc",
                "-plugins",
                "-plugin",
                "tgm2p-trainer",
                "-pluginspath",
                f"{plugins};{exe.parent / 'plugins'}",
                "-skip_gameinfo",
                "-autoboot_delay",
                "0",
                "-autoboot_script",
                str(ROOT / "tools/gameplay_probe.lua"),
                "-cfg_directory",
                str(folder / "cfg"),
                "-nvram_directory",
                str(folder / "nvram"),
            ],
            cwd=exe.parent,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        sock = None
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and proc.poll() is None:
                try:
                    sock = socket.create_connection(("127.0.0.1", 50575), 0.2)
                    break
                except OSError:
                    time.sleep(0.05)
            assert sock, "bridge did not listen"
            sock.settimeout(3)
            buf = b""
            settings = {"players": [{}, {"gravity": 0, "lock": 45}], "global": {}}

            def send(**m):
                sock.sendall((json.dumps(m) + "\n").encode())

            send(t="hello")
            send(t="sync", id=1, settings=settings)
            lastframe = 0
            phase = 0
            target = 0
            checks = set()
            baseline = None
            revision = 1
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and proc.poll() is None:
                data = sock.recv(65536)
                assert data, "bridge closed"
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    m = json.loads(line)
                    assert m["t"] != "error", m
                    if m["t"] == "status":
                        assert not m.get("error"), m
                        if m.get("ready"):
                            checks.add("signatures + installation")
                            if phase == 4:
                                baseline = m["parameter_writes"]
                                target = lastframe + 360
                                phase = 5
                            elif phase == 6:
                                assert m["parameter_writes"] == baseline, m
                                checks.add("no parameter writes during steady gameplay")
                                send(t="reset_machine")
                                reset_frame = lastframe
                                phase = 7
                            elif phase == 7 and m.get("installs", 0) >= 2:
                                phase = 8
                    if m["t"] == "hello":
                        assert m["protocol"] == 3 and m["compatible"], m
                        checks.add("protocol 3")
                    if m["t"] != "state":
                        continue
                    p = m["players"][0]
                    f = m["frame"]
                    lastframe = f
                    if phase == 0 and f >= 3000 and p["play_state"] == 2:
                        settings["players"][0] = {
                            "gravity": 0,
                            "lock": 90,
                            "das": 5,
                            "are": 8,
                            "line_are": 9,
                            "line_clear": 10,
                            "freeze_level": 1,
                            "ghost": 0,
                            "mroll": 1,
                            "big": 1,
                            "items": 1,
                            "bypass_torikan": 1,
                        }
                        revision += 1
                        send(t="sync", id=revision, settings=settings)
                        send(t="action", action="level", player=0, value=100)
                        target = f + 60
                        phase = 1
                    elif phase == 1 and f >= target:
                        y = p["active_y"]
                        target = f + 120
                        phase = 2
                        assert p["gravity"] == 0, (p, phase)
                    elif phase == 2:
                        assert p["active_y"] == y and p["play_state"] == 2, (
                            phase,
                            p,
                            y,
                        )
                        assert p["level"] == 100, p
                        assert p["next_piece"] & 0x200, p
                        assert p["game_mode"] & 0x200 and not p["game_mode"] & 0x40, p
                        if f >= target:
                            checks.add("0G stationary for 120 frames")
                            settings["players"][0]["gravity"] = 20 * 65536
                            send(t="sync", id=3, settings=settings)
                            target = f + 180
                            phase = 3
                            dropped = False
                            duration = False
                            big_active = False
                    elif phase == 3:
                        dropped |= p["active_y"] < y
                        duration |= p["lock_duration"] == 90
                        big_active |= bool(p["active_piece"] & 0x200)
                        assert p["level"] == 100, p
                        if f >= target:
                            assert dropped, "20G did not drop"
                            assert (
                                m["players"][1]["play_state"] == 2
                                and m["players"][1]["gravity"] == 0
                            ), m["players"][1]
                            checks.add("independent P2 gravity")
                            assert duration, "lock duration was not loaded"
                            assert big_active, "queued BIG did not reach active piece"
                            checks.update(
                                [
                                    "20G moves piece",
                                    "lock reload override",
                                    "frozen level across piece progression",
                                    "BIG queued-to-active handoff without game-mode cheat bit",
                                ]
                            )
                            settings["players"][0] = {
                                "effective_gravity": 0,
                                "invisible": 1,
                            }
                            settings["global"] = {"music": 3}
                            send(t="sync", id=4, settings=settings)
                            send(t="diagnostics")
                            phase = 4
                    elif phase == 5:
                        if f < target - 240:
                            effective_y = p["active_y"]
                        else:
                            assert (
                                p["play_state"] == 2 and p["active_y"] == effective_y
                            ), p
                        if f >= target:
                            assert m["music_scene"] == 3, m
                            checks.update(
                                [
                                    "effective 0G stationary",
                                    "music director selected requested scene",
                                ]
                            )
                            send(t="diagnostics")
                            phase = 6
                    elif (
                        phase == 8 and f >= reset_frame + 2700 and p["play_state"] == 2
                    ):
                        y = p["active_y"]
                        target = f + 120
                        phase = 9
                    elif phase == 9:
                        assert p["play_state"] == 2 and p["active_y"] == y, m
                        assert m["music_scene"] == 3, m
                        if f >= target:
                            checks.add(
                                "soft reset: fresh game retains effective 0G and selected music scene"
                            )
                            print("PASS: " + "; ".join(sorted(checks)), flush=True)
                            return
            raise AssertionError(
                f"Incomplete phase={phase} checks={checks}; log={logpath}"
            )
        finally:
            if sock:
                sock.close()
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
            log.flush()
            log.seek(0)
            output = log.read()
            log.close()
            if "Error" in output or "error" in output:
                print(output[-4000:])


if __name__ == "__main__":
    main()
