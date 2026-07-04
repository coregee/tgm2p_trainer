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
    def __init__(self, mame_exe: Path):
        self.mame_exe = Path(mame_exe)

    @property
    def mame_dir(self) -> Path:
        return self.mame_exe.parent

    def available(self) -> bool:
        return self.mame_exe.is_file()

    def is_running(self, proc: subprocess.Popen | None) -> bool:
        return proc is not None and proc.poll() is None

    def launch(self) -> subprocess.Popen:
        if not self.available():
            raise FileNotFoundError(f"MAME executable not found: {self.mame_exe}")
        return subprocess.Popen(
            [str(self.mame_exe), *LAUNCH_ARGS],
            cwd=str(self.mame_dir),
        )
