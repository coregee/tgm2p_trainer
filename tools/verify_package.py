"""Windows packaged-app startup test against a local bridge fixture."""

import argparse
import json
import os
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "executable", type=Path, nargs="?", default=ROOT / "app/dist/tgm2p-trainer.exe"
    )
    args = ap.parse_args()
    manifest = json.loads((ROOT / "plugin/native.json").read_text())
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 50575))
        listener.listen()
        listener.settimeout(20)
        proc = subprocess.Popen(
            [str(args.executable.resolve())],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        )
        try:
            client, _ = listener.accept()
            with client, client.makefile("rb") as stream:
                client.settimeout(5)
                assert json.loads(stream.readline()) == {"t": "hello"}
                hello = {
                    "t": "hello",
                    "protocol": 3,
                    "rom": "tgm2p",
                    "compatible": True,
                    "patch_id": manifest["sha256"],
                }
                client.sendall((json.dumps(hello) + "\n").encode())
                kinds = set()
                while not {"sync", "bindings"} <= kinds:
                    m = json.loads(stream.readline())
                    kinds.add(m["t"])
                    if m["t"] == "sync":
                        assert m["settings"] == {"players": [{}, {}], "global": {}}, m
                assert proc.poll() is None
                print(
                    "PASS: frozen app starts, loads matching embedded manifest, builds Qt window and publishes settings + hotkeys"
                )
        finally:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
