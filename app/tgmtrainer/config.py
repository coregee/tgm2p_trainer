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
    "9", "8", "7", "6", "5",
    "4", "4",
    "3", "3",
    "2", "2", "2",
    "1", "1", "1",
    "S1", "S1", "S1",
    "S2",
    "S3",
    "S4", "S4", "S4",
    "S5", "S5",
    "S6", "S6",
    "S7", "S7",
    "S8", "S8",
    "S9",
]


def _relative_grade_names(names: list[str]) -> list[str]:
    """Grade to sub-grade name."""
    out: list[str] = []
    i = 0
    letters = ['a', 'b', 'c']
    while i < len(names):
        j = i
        while j < len(names) and names[j] == names[i]:
            j += 1
        run = j - i
        if run == 1: # simple grade
            out.append(names[i])
        else:
            for k in range(run):
                suffix = (run - k - 1)
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
    "Level 1",   # 0
    "Level 2",   # 1
    "Level 3",   # 2
    "Level 4",   # 3
    "Versus",    # 4
    "Credits",   # 5
    "Result",    # 6
    "Select",    # 7
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


def addresses_path(mame_dir: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if mame_dir is None:
        exe = find_mame_exe()
        mame_dir = exe.parent if exe else None
    if mame_dir:
        candidates.append(mame_dir / "plugins" / "tgm2p-trainer" / "addresses.json")
    # MAME's per-user plugin folder on Linux/macOS (and some Windows setups)
    candidates.append(Path.home() / ".mame" / "plugins" / "tgm2p-trainer" / "addresses.json")
    base = _base_dir()
    for up in (base.parents[1] if len(base.parents) >= 2 else base,
               base.parent, Path.cwd()):
        candidates.append(up / "plugin" / "addresses.json")
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "addresses.json")
    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


class Config:
    def __init__(self, data: dict, source: Path | None = None):
        self.data = data
        self.source = source

    @classmethod
    def load(cls, mame_dir: Path | None = None) -> "Config":
        path = addresses_path(mame_dir)
        if not path:
            raise FileNotFoundError(
                "addresses.json not found. Install the plugin in MAME's "
                "plugins folder, or set the TGM2_MAME_DIR / TGM2_MAME_EXE "
                "environment variable."
            )
        with open(path, "r", encoding="utf-8") as fh:
            return cls(json.load(fh), path)

    @property
    def port(self) -> int:
        return int(self.data.get("meta", {}).get("port", 50575))

    @property
    def addresses(self) -> dict:
        return self.data.get("addresses", {})

    @property
    def timing_presets(self) -> dict:
        presets = self.data.get("presets", {}).get("timings", {})
        return {k: v for k, v in presets.items() if not k.startswith("_")}

    @property
    def timing_members(self) -> list[str]:
        return self.data.get("composites", {}).get("timings", {}).get(
            "members", ["are", "line_are", "das", "lock_delay", "line_clear"]
        )

    @property
    def grade_max(self) -> int:
        return len(GRADE_NAMES) - 1

    @property
    def grade_relative_names(self) -> list[str]:
        return GRADE_NAMES_RELATIVE

    def grade_relative_name(self, index) -> str:
        """Internal grade index -> disambiguated label, with the relative suffix
        when the displayed grade spans multiple internal grades, e.g. internal
        21 -> 'S4-2'."""
        try:
            return GRADE_NAMES_RELATIVE[int(index)]
        except (ValueError, TypeError, IndexError):
            return "?"

    def play_state_name(self, value) -> str:
        try:
            return PLAY_STATES.get(int(value), str(value))
        except (ValueError, TypeError):
            return "?"

    @property
    def music_track_names(self) -> list[str]:
        return MUSIC_TRACKS

    @property
    def music_none_id(self) -> int:
        return MUSIC_NONE

    def music_track_name(self, value) -> str:
        try:
            i = int(value)
        except (ValueError, TypeError):
            return "--"
        if i == MUSIC_NONE:
            return "(None)"
        if 0 <= i < len(MUSIC_TRACKS):
            return MUSIC_TRACKS[i]
        return "--"

    def music_track_scene(self, track) -> int:
        try:
            t = int(track)
        except (ValueError, TypeError):
            return SONG_TO_SCENE[0]
        if t == MUSIC_NONE:
            return MUSIC_STOP_SCENE
        try:
            return SONG_TO_SCENE[t]
        except IndexError:
            return SONG_TO_SCENE[0]
