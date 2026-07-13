"""JSON persistence layer for wa's project registry.

Design: a single registry file (projects.json) under XDG_DATA_HOME holds
metadata for every project wa knows about. Notes/todos are intentionally
NOT stored here -- they live as .md files inside each project's own
directory (see spec section 4, `notes`/`todo`), so they travel with the
project's own git history instead of wa's private state.
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

SCHEMA_VERSION = 1


@dataclass
class Project:
    """One managed project. `vars` always carries DIR/GIT/DOC/SSH once `add` runs."""

    name: str
    vars: Dict[str, str] = field(default_factory=dict)
    cmds: Dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        return cls(
            name=data["name"],
            vars=dict(data.get("vars", {})),
            cmds=dict(data.get("cmds", {})),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class Registry:
    """The full set of projects known to wa.

    Deliberately has no "active project" field: which project is open is a
    per-shell-session concept (two terminals can have two different projects
    open at once), tracked entirely via the ACTIVE_PROJ_DIR env var -- never
    persisted globally here.
    """

    version: int = SCHEMA_VERSION
    projects: Dict[str, Project] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Registry":
        """Load the registry from disk, transparently creating an empty one on first run."""
        if not REGISTRY_FILE.exists():
            registry = cls()
            registry.save()
            return registry

        raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        projects = {
            name: Project.from_dict(data) for name, data in raw.get("projects", {}).items()
        }
        return cls(
            version=raw.get("version", SCHEMA_VERSION),
            projects=projects,
        )

    def save(self) -> None:
        """Persist the registry atomically (write to tmp file + os.replace).

        Avoids leaving a half-written projects.json if wa is killed mid-save.
        """
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "projects": {name: p.to_dict() for name, p in self.projects.items()},
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
