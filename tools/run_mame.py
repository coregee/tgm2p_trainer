"""Launch MAME with this workspace's bridge (also used by VS Code tasks)."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from tgmtrainer.config import find_mame_exe
from tgmtrainer.launcher import Launcher


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mame", type=Path, default=find_mame_exe())
    parser.add_argument("--interpreter", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--seconds", type=int)
    args = parser.parse_args()
    if args.mame is None:
        parser.error("select MAME in the trainer, set TGM2_MAME_EXE, or pass --mame")
    extra = ["-nodrc" if args.interpreter else "-drc"]
    if args.headless:
        extra += ["-video", "none", "-sound", "none"]
    if args.seconds:
        extra += ["-seconds_to_run", str(args.seconds)]
    launcher = Launcher(args.mame)
    print("Starting MAME with workspace bridge", flush=True)
    process = launcher.launch(extra)
    print(f"MAME started (PID {process.pid}); log: {launcher.log_path}", flush=True)
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()


if __name__ == "__main__":
    sys.exit(main())
