"""Game-independent desired settings and profile validation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .config import bundled_plugin_dir


def empty_settings():
    return {"players": [{}, {}], "global": {}}


def load_catalog():
    folder = bundled_plugin_dir()
    if folder is None:
        raise FileNotFoundError("The bundled native trainer plugin is missing")
    return json.loads((folder / "catalog.json").read_text())


def validate(settings, catalog):
    if not isinstance(settings, dict) or set(settings) != {"players", "global"}:
        raise ValueError("A profile must contain players and global settings")
    players = settings["players"]
    if not isinstance(players, list) or len(players) != 2:
        raise ValueError("A profile must contain exactly two players")
    for player in players:
        if not isinstance(player, dict):
            raise ValueError("Player settings must be objects")  # noqa: TRY004 -- public validation contract
        for key, value in player.items():
            spec = catalog["controls"].get(key)
            if (
                spec is None
                or type(value) is not int
                or not spec["min"] <= value <= spec["max"]
            ):
                raise ValueError(f"Invalid setting: {key}")
        if "gravity" in player and "effective_gravity" in player:
            raise ValueError("Choose base gravity or effective gravity, not both")
    global_settings = settings["global"]
    if not isinstance(global_settings, dict):
        raise ValueError("Global settings must be an object")  # noqa: TRY004 -- public validation contract
    for key, value in global_settings.items():
        if key != "music" or type(value) is not int or not 0 <= value <= 10:
            raise ValueError("Invalid music scene")
    return copy.deepcopy(settings)


def load_profile(path, catalog):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 3:
        raise ValueError("This profile uses an unsupported version")
    settings = copy.deepcopy(data.get("settings"))
    if isinstance(settings, dict) and isinstance(settings.get("players"), list):
        for player in settings["players"]:
            if isinstance(player, dict):
                player.pop("transform", None)
                if "hold_level" in player:
                    player.pop("hold_level")
                    player["freeze_level"] = 1
    settings = validate(settings, catalog)
    # Keep saved values, but restore the game's soft/sonic-drop handling.
    for player in settings["players"]:
        if "effective_gravity" in player:
            player["gravity"] = player.pop("effective_gravity")
    return settings


def save_profile(path, settings, catalog):
    data = {"version": 3, "settings": validate(settings, catalog)}
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
