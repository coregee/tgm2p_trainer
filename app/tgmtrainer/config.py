from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

if sys.platform == "win32":
    MAME_EXE_NAMES = ("mame.exe", "mame64.exe")
else:
    MAME_EXE_NAMES = ("mame", "mame64")

GRADE_NAMES = [
    "9",
    "8",
    "7",
    "6",
    "5",
    "4",
    "4",
    "3",
    "3",
    "2",
    "2",
    "2",
    "1",
    "1",
    "1",
    "S1",
    "S1",
    "S1",
    "S2",
    "S3",
    "S4",
    "S4",
    "S4",
    "S5",
    "S5",
    "S6",
    "S6",
    "S7",
    "S7",
    "S8",
    "S8",
    "S9",
]


def _relative_grade_names(names: list[str]) -> list[str]:
    """Grade to sub-grade name."""
    out: list[str] = []
    i = 0
    letters = ["a", "b", "c"]
    while i < len(names):
        j = i
        while j < len(names) and names[j] == names[i]:
            j += 1
        run = j - i
        if run == 1:  # simple grade
            out.append(names[i])
        else:
            for k in range(run):
                suffix = run - k - 1
                out.append(f"{names[i]} {letters[suffix]}")
        i = j
    return out


GRADE_NAMES_RELATIVE = _relative_grade_names(GRADE_NAMES)

PLAY_STATES = {
    0: "NONE",
    1: "START",
    2: "ACTIVE",
    3: "LOCKING",
    4: "LINECLEAR",
    5: "ENTRY",
    7: "GAMEOVER",
    10: "IDLE",
    11: "FADING",
    13: "COMPLETION",
    71: "STARTUP",
}

MUSIC_TRACKS = [
    "Level 1",  # 0
    "Level 2",  # 1
    "Level 3",  # 2
    "Level 4",  # 3
    "Versus",  # 4
    "Credits",  # 5
    "Result",  # 6
    "Select",  # 7
]
MUSIC_NONE = -1
MUSIC_STOP_SCENE = 2
SONG_TO_SCENE = [1, 3, 5, 7, 10, 9, 8, 0]


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _settings_path() -> Path:
    from PySide6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    folder = Path(base) if base else Path.home() / ".tgm2trainer"
    return folder / "settings.json"


def mame_exe_in(directory: Path) -> Path | None:
    for name in MAME_EXE_NAMES:
        p = directory / name
        if p.is_file():
            return p
    return None


def load_mame_exe() -> Path | None:
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    p = data.get("mame_exe")
    if isinstance(p, str) and p:
        return Path(p)
    legacy = data.get("mame_dir")  # pre-0.2 settings stored the directory
    if isinstance(legacy, str) and legacy:
        return mame_exe_in(Path(legacy))
    return None


def save_mame_exe(mame_exe: Path | str | None):
    path = _settings_path()
    try:
        data = {}
        if path.is_file():
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
                data = loaded if isinstance(loaded, dict) else {}
        if mame_exe:
            data["mame_exe"] = str(mame_exe)
        else:
            data.pop("mame_exe", None)
        data.pop("mame_dir", None)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except (OSError, ValueError):
        pass


def find_mame_exe() -> Path | None:
    saved = load_mame_exe()
    try:
        if saved and saved.is_file():
            return saved.resolve()
    except OSError:
        pass
    env_exe = os.environ.get("TGM2_MAME_EXE")
    if env_exe and Path(env_exe).is_file():
        return Path(env_exe).resolve()
    dir_candidates: list[Path] = []
    env = os.environ.get("TGM2_MAME_DIR")
    if env:
        dir_candidates.append(Path(env))
    base = _base_dir()
    dir_candidates += [
        base.parents[1] / "mame" if len(base.parents) >= 2 else base / "mame",
        base / "mame",
        base.parent / "mame",
        Path.cwd() / "mame",
        Path.cwd(),
    ]
    for c in dir_candidates:
        try:
            exe = mame_exe_in(c)
        except (OSError, IndexError):
            continue
        if exe:
            return exe.resolve()
    which = shutil.which("mame")  # system installs (apt, pacman, Homebrew)
    return Path(which).resolve() if which else None


def bundled_plugin_dir() -> Path | None:
    """Prefer the plugin shipped with this app over an unrelated installed copy."""
    roots = [Path(__file__).resolve().parents[2] / "plugin"]
    if getattr(sys, "_MEIPASS", None):
        roots.insert(0, Path(sys._MEIPASS) / "plugin")
    for root in roots:
        if (root / "init.lua").is_file() and (root / "native.json").is_file():
            return root
    return None
