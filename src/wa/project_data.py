"""Per-project local data (vars, cmds) stored inside the project's own directory.

Kept at <DIR>/.wa/data.json instead of wa's central registry, so a
project's custom vars and commands travel with it when the directory is
cloned, copied or moved -- the same rationale notes/ already follows (see
wa/notes.py). Machine-local by default: the .wa/ folder gets its own
self-contained .gitignore ("*"), so it's excluded from git even if nobody
remembers to add it to the project's own .gitignore.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

LOCAL_DIR_NAME = ".wa"
LOCAL_DATA_FILENAME = "data.json"
DATA_SCHEMA_VERSION = 1


@dataclass
class ProjectData:
    """A project's local vars/cmds -- everything about it except where it lives."""

    vars: Dict[str, str] = field(default_factory=dict)
    cmds: Dict[str, str] = field(default_factory=dict)


def local_dir(directory: Path) -> Path:
    return Path(directory) / LOCAL_DIR_NAME


def _data_path(directory: Path) -> Path:
    return local_dir(directory) / LOCAL_DATA_FILENAME


def load_project_data(directory: Path) -> ProjectData:
    """Read <directory>/.wa/data.json, or an empty ProjectData if it doesn't exist yet."""
    path = _data_path(directory)
    if not path.is_file():
        return ProjectData()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ProjectData(vars=dict(raw.get("vars", {})), cmds=dict(raw.get("cmds", {})))


def save_project_data(directory: Path, data: ProjectData) -> None:
    """Persist `data` atomically to <directory>/.wa/data.json, creating the folder if needed."""
    wa_dir = local_dir(directory)
    wa_dir.mkdir(parents=True, exist_ok=True)
    _ensure_self_gitignore(wa_dir)

    payload = {"version": DATA_SCHEMA_VERSION, "vars": data.vars, "cmds": data.cmds}
    fd, tmp_path = tempfile.mkstemp(dir=wa_dir, prefix=".data_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, _data_path(directory))
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _ensure_self_gitignore(wa_dir: Path) -> None:
    """Make .wa/ ignore itself, so it's excluded from git regardless of the
    project's own .gitignore -- never overwritten once it exists."""
    gitignore = wa_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
