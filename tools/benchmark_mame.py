"""DRC benchmark: stock, connected disabled hooks, and enabled overrides."""

import argparse
import copy
import json
import re
import shutil
import socket
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMPTY = {"players": [{}, {}], "global": {}}
# Slow gravity keeps both players active. These profiles deliberately change
# gameplay; comparisons include changes in work, not just trampoline overhead.
PLAYER = {
    "gravity": 1024,
    "are": 25,
    "line_are": 25,
    "line_clear": 40,
    "lock": 30,
    "das": 14,
    "invisible": 0,
    "freeze_level": 1,
    "bypass_torikan": 1,
    "ghost": 1,
    "mroll": 1,
    "big": 1,
    "items": 1,
}
VISIBLE = {
    "players": [copy.deepcopy(PLAYER), copy.deepcopy(PLAYER)],
    "global": {"music": 1},
}
HIDDEN = copy.deepcopy(VISIBLE)
for player in HIDDEN["players"]:
    player["effective_gravity"] = player.pop("gravity")
    player["invisible"] = 1
PROFILES = {
    "stock": None,
    "connected_disabled": EMPTY,
    "base_visible": VISIBLE,
    "effective_hidden": HIDDEN,
}


def observe(proc, settings):
    """Publish once, drain telemetry, and verify that settings writes stop."""
    sock = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            sock = socket.create_connection(("127.0.0.1", 50575), 0.1)
            break
        except OSError:
            time.sleep(0.01)
    assert sock, "bridge did not listen"
    counts, active, big_pieces = [], [0, 0], [0, 0]
    ack, last_diagnostic = False, -500
    with sock:
        sock.settimeout(0.2)

        def send(**message):
            sock.sendall((json.dumps(message) + "\n").encode())

        send(t="hello")
        send(t="sync", id=1, settings=settings)
        buffer = b""
        deadline = time.monotonic() + 120
        while proc.poll() is None:
            assert time.monotonic() < deadline, "MAME benchmark stalled"
            try:
                chunk = sock.recv(65536)
            except TimeoutError:
                continue
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                m = json.loads(line)
                assert m["t"] != "error" and not m.get("error"), m
                if m["t"] == "hello":
                    assert m["protocol"] == 3 and m["compatible"], m
                elif m["t"] == "ack" and "settings" in m:
                    assert m["settings"] == settings, m
                    ack = True
                elif m["t"] == "status" and m.get("ready") and m["revision"] == 1:
                    counts.append((m["parameter_writes"], m["action_writes"]))
                elif m["t"] == "state":
                    assert m["settings"] == settings, m
                    for p, state in enumerate(m["players"]):
                        if state["play_state"] == 2:
                            active[p] += 1
                            big_pieces[p] += bool(state["active_piece"] & 0x200)
                    if m["frame"] >= last_diagnostic + 500:
                        send(t="diagnostics")
                        last_diagnostic = m["frame"]
    assert ack and len(counts) > 2, (ack, counts)
    assert len(set(counts)) == 1, f"writes continued after application: {counts}"
    assert min(active) > 30, f"insufficient two-player gameplay: {active}"
    if settings["players"][0]:
        assert min(big_pieces) > 0, f"BIG handoff not observed: {big_pieces}"
    return {
        "steady_write_counts": counts[0],
        "diagnostic_samples": len(counts),
        "active_samples": active,
        "big_pieces_active_samples": big_pieces,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mame", type=Path)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    exe = args.mame.resolve()
    assert args.runs > 0 and args.seconds >= 70, (
        "need positive repeats and >=70 seconds for boot + gameplay"
    )
    results = {name: [] for name in PROFILES}
    version = subprocess.check_output([str(exe), "-version"], text=True).strip()
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        plugins = folder / "plugins"
        shutil.copytree(ROOT / "plugin", plugins / "tgm2p-trainer")
        for run in range(args.runs):
            names = list(PROFILES)
            shift = run % len(names)  # Rotate measurement order.
            for variant in names[shift:] + names[:shift]:
                state = folder / f"{variant}-{run}"
                command = [
                    str(exe),
                    "tgm2p",
                    "-video",
                    "none",
                    "-sound",
                    "auto",
                    "-volume",
                    "-32",
                    "-nothrottle",
                    "-drc",
                    "-seconds_to_run",
                    str(args.seconds),
                    "-skip_gameinfo",
                    "-autoboot_delay",
                    "0",
                    "-autoboot_script",
                    str(ROOT / "tools/gameplay_probe.lua"),
                    "-cfg_directory",
                    str(state / "cfg"),
                    "-nvram_directory",
                    str(state / "nvram"),
                ]
                settings = PROFILES[variant]
                if settings is not None:
                    command += [
                        "-plugins",
                        "-plugin",
                        "tgm2p-trainer",
                        "-pluginspath",
                        f"{plugins};{exe.parent / 'plugins'}",
                    ]
                else:
                    command += ["-noplugins"]
                with (folder / "mame.log").open("w+") as log:
                    proc = subprocess.Popen(
                        command, cwd=exe.parent, stdout=log, stderr=subprocess.STDOUT
                    )
                    try:
                        verification = (
                            observe(proc, settings) if settings is not None else {}
                        )
                        proc.wait(timeout=120)
                    finally:
                        if proc.poll() is None:
                            proc.terminate()
                            proc.wait(timeout=10)
                    log.seek(0)
                    output = log.read()
                assert proc.returncode == 0, output[-4000:]
                match = re.search(r"Average speed: ([\d.]+)%", output)
                assert match, output[-4000:]
                speed = float(match[1]) / 100
                results[variant].append({"speed": speed, **verification})
                print(f"{variant} run {run + 1}: {speed:.2f}x real time", flush=True)
    medians = {k: statistics.median(r["speed"] for r in v) for k, v in results.items()}
    for name, median in medians.items():
        speeds = [r["speed"] for r in results[name]]
        print(
            f"{name}: median {median:.2f}x, range {min(speeds):.2f}..{max(speeds):.2f}x; "
            f"execution-time ratio vs stock {medians['stock'] / median:.4f}x"
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "mame": version,
                    "seconds_per_run": args.seconds,
                    "runs": args.runs,
                    "profiles": PROFILES,
                    "results": results,
                    "medians": medians,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
