from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import bundled_plugin_dir

LAUNCH_ARGS = [
    "tgm2p",
    "-window",
    "-skip_gameinfo",
    "-drc",  # Native hooks retain the SH-2 dynamic recompiler.
    "-plugins",
    "-plugin",
    "tgm2p-trainer",
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

    def launch(self, extra_args: list[str] | None = None) -> subprocess.Popen:
        if not self.available():
            raise FileNotFoundError(f"MAME executable not found: {self.mame_exe}")
        source = bundled_plugin_dir()
        if source is None:
            raise FileNotFoundError(
                "The matching trainer plugin is missing; reinstall the trainer app"
            )
        files = sorted(p for p in source.iterdir() if p.suffix in {".lua", ".json"})
        digest = hashlib.sha256(
            b"".join(p.name.encode() + p.read_bytes() for p in files)
        ).hexdigest()[:16]
        plugin_root = Path(tempfile.gettempdir()) / "tgm2p-trainer" / digest / "plugins"
        target = plugin_root / "tgm2p-trainer"
        target.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copy2(path, target / path.name)
        log_path = plugin_root.parent / "mame.log"
        self.log_path = log_path
        with log_path.open("w", encoding="utf-8") as log:
            return subprocess.Popen(
                [
                    str(self.mame_exe),
                    *LAUNCH_ARGS,
                    "-pluginspath",
                    f"{plugin_root};{self.mame_dir / 'plugins'}",
                    *(extra_args or []),
                ],
                cwd=str(self.mame_dir),
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0,
            )
