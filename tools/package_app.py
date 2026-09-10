"""Package the trainer without collecting unrelated DLLs from the host PATH."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = os.environ.copy()
    if sys.platform == "win32":
        # GUI/media tools can put old UCRT DLLs on PATH. PyInstaller otherwise
        # bundles those copies, causing QtWidgets to fail at import time.
        windows = Path(env.get("SystemRoot", "C:/Windows"))
        env["PATH"] = os.pathsep.join(
            map(
                str,
                [
                    Path(sys.executable).parent,
                    Path(sys.base_prefix),
                    windows / "System32",
                    windows,
                ],
            )
        )
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "tgm2p-trainer",
            "--paths",
            str(ROOT / "app"),
            "--collect-submodules",
            "tgmtrainer",
            "--add-data",
            f"{ROOT / 'plugin'}{os.pathsep}plugin",
            "--distpath",
            str(ROOT / "app/dist"),
            "--workpath",
            str(ROOT / "app/build"),
            str(ROOT / "app/run_app.py"),
        ],
        cwd=ROOT,
        env=env,
    )


if __name__ == "__main__":
    sys.exit(main())
