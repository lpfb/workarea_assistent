"""User-editable global settings, stored in CONFIG_FILE (~/.config/wa/config.json).

Today this only holds the default tmux layout -- the windows a new project
gets seeded with. It is a seed, not a live setting: once a project has its
own layout (in <DIR>/.wa/data.json), editing the defaults here no longer
affects it.

CONFIG_FILE is read through the `constants` module at call time (rather
than `from wa.constants import CONFIG_FILE`) so tests can redirect it.
"""
from __future__ import annotations

import json
from typing import Dict, List

import wa.constants as constants
from wa.errors import WaError

DEFAULT_TMUX_WINDOWS: List[Dict[str, str]] = [
    {"name": "git", "cmd": ""},
    {"name": "edit", "cmd": ""},
    {"name": "deploy", "cmd": ""},
]


def _default_config() -> dict:
    return {"tmux": {"default_windows": [dict(w) for w in DEFAULT_TMUX_WINDOWS]}}


def ensure_config_file() -> None:
    """Write a config.json with the built-in defaults if none exists, so there's
    an obvious file to edit -- never overwrites an existing one."""
    path = constants.CONFIG_FILE
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_default_config(), indent=2) + "\n", encoding="utf-8")


def load_default_tmux_windows() -> List[Dict[str, str]]:
    """The tmux windows new projects start with: config.json's list, or the built-ins.

    Each entry may be a {"name", "cmd"} object or just a window-name string.
    """
    path = constants.CONFIG_FILE
    if not path.is_file():
        return [dict(w) for w in DEFAULT_TMUX_WINDOWS]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WaError(f"Invalid JSON in {path}: {exc}") from exc

    entries = raw.get("tmux", {}).get("default_windows")
    if entries is None:
        return [dict(w) for w in DEFAULT_TMUX_WINDOWS]

    windows = []
    for entry in entries:
        if isinstance(entry, str):
            windows.append({"name": entry, "cmd": ""})
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            windows.append({"name": entry["name"], "cmd": str(entry.get("cmd", ""))})
        else:
            raise WaError(f"Invalid tmux.default_windows entry in {path}: {entry!r}")
    return windows
