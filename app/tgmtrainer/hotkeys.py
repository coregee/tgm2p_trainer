from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def _settings_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    folder = Path(base) if base else Path.home() / ".tgm2trainer"
    return folder / "hotkeys.json"


def load_bindings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: v for k, v in data.items()
        if isinstance(v, dict) and isinstance(v.get("token"), str)
    }


def save_bindings(bindings: dict):
    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(bindings, fh, indent=2)
    except OSError:
        pass
