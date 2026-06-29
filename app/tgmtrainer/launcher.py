from __future__ import annotations

import subprocess
from pathlib import Path

LAUNCH_ARGS = [
    "tgm2p",
    "-window",
    "-skip_gameinfo",
    "-plugins",
    "-plugin", "tgm2p-trainer",
]

class Launcher:
    def __init__(self, mame_dir: Path):
        self.mame_dir = Path(mame_dir)

    @property
    def mame_exe(self) -> Path:
        return self.mame_dir / "mame.exe"

    def available(self) -> bool:
        return self.mame_exe.is_file()

    def is_running(self, proc: subprocess.Popen | None) -> bool:
        return proc is not None and proc.poll() is None

    def launch(self) -> subprocess.Popen:
        if not self.available():
            raise FileNotFoundError(f"mame.exe not found in {self.mame_dir}")
        return subprocess.Popen(
            [str(self.mame_exe), *LAUNCH_ARGS],
            cwd=str(self.mame_dir),
        )
