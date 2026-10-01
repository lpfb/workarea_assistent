"""JSON persistence layer for wa's project registry.

Design: a single registry file (projects.json) under XDG_DATA_HOME holds
only a pointer per project -- its name and directory (ProjectRef).
Everything else about a project (vars, cmds) lives in <DIR>/.wa/data.json
(see wa/project_data.py), and notes live in <DIR>/notes/ (see wa/notes.py);
both travel with the project's own directory/git history instead of wa's
private state.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from wa.constants import DATA_DIR, REGISTRY_FILE
from wa.project_data import ProjectData, save_project_data

SCHEMA_VERSION = 2


@dataclass
class ProjectRef:
    """Where a registered project lives -- the only thing the central registry stores."""

    name: str
    dir: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectRef":
        return cls(
            name=data["name"],
            dir=data["dir"],
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class Project:
    """Merged, in-memory view of a project: its pointer plus its local vars/cmds.

    Never persisted directly -- wa/projects.py assembles this from a
    ProjectRef (central) and a ProjectData (local), and splits it back
    apart when saving. `vars` always carries DIR once assembled.
    """

    name: str
    vars: Dict[str, str] = field(default_factory=dict)
    cmds: Dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Registry:
    """The full set of projects wa knows about -- just their names and directories.

    Deliberately has no "active project" field: which project is open is a
    per-shell-session concept (two terminals can have two different projects
    open at once), tracked entirely via the ACTIVE_PROJ_DIR env var -- never
    persisted globally here.
    """

    version: int = SCHEMA_VERSION
    projects: Dict[str, ProjectRef] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Registry":
        """Load the registry from disk, transparently creating an empty one on first run.

        Also transparently migrates schema v1 registries (which stored vars/
        cmds inline) by moving that data out to each project's own
        <DIR>/.wa/data.json -- see `_migrate_legacy_project`.
        """
        if not REGISTRY_FILE.exists():
            registry = cls()
            registry.save()
            return registry

        raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        on_disk_version = raw.get("version", SCHEMA_VERSION)

        projects: Dict[str, ProjectRef] = {}
        migrated = False
        for name, data in raw.get("projects", {}).items():
            if "dir" in data:
                projects[name] = ProjectRef.from_dict({"name": name, **data})
            else:
                projects[name] = _migrate_legacy_project(name, data)
                migrated = True

        registry = cls(version=SCHEMA_VERSION, projects=projects)
        if migrated or on_disk_version != SCHEMA_VERSION:
            registry.save()
        return registry

    def save(self) -> None:
        """Persist the registry atomically (write to tmp file + os.replace).

        Avoids leaving a half-written projects.json if wa is killed mid-save.
        """
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "projects": {name: ref.to_dict() for name, ref in self.projects.items()},
        }
        fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, prefix=".projects_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, REGISTRY_FILE)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise


def _migrate_legacy_project(name: str, data: dict) -> ProjectRef:
    """One-time upgrade from schema v1, where vars/cmds lived inline in the registry.

    Moves everything except DIR into <DIR>/.wa/data.json (if the directory
    still exists -- if it doesn't, there's nowhere to put the data, so it's
    dropped) and returns the ProjectRef that replaces the old inline entry.
    """
    legacy_vars = dict(data.get("vars", {}))
    directory = legacy_vars.pop("DIR", None)
    if not directory:
        raise ValueError(f"Legacy project '{name}' has no DIR; cannot migrate.")

    if Path(directory).is_dir():
        local_data = ProjectData(vars=legacy_vars, cmds=dict(data.get("cmds", {})))
        save_project_data(Path(directory), local_data)

    return ProjectRef(
        name=name,
        dir=directory,
        created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
    )
