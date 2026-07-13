"""Domain logic for managing projects: init, add, remove, vars, cmds, context.

Deliberately free of typer/rich/questionary imports -- this module is the
"core engine"; wa/cli.py is the only place that talks to the user.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from wa.constants import ACTIVE_PROJ_DIR_ENV, CONFIG_DIR
from wa.errors import WaError
from wa.schema import Project, Registry

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# Stricter than _NAME_RE: variable names become `export NAME=value`, so they
# must be valid shell identifiers (no dashes, can't start with a digit).
_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IMMUTABLE_VARS = {"DIR"}


def init_workspace() -> bool:
    """Ensure wa's XDG config/data directories and the registry file exist.

    Returns True on first-time setup, False if wa was already initialized.
    Safe to call repeatedly -- never touches existing data.
    """
    from wa.constants import REGISTRY_FILE

    already_initialized = REGISTRY_FILE.exists()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    Registry.load()  # side effect: creates DATA_DIR + projects.json if missing
    return not already_initialized


def validate_project_name(name: str, registry: Registry) -> None:
    if not _NAME_RE.match(name):
        raise WaError(
            f"Invalid project name '{name}': use letters, numbers, '-' or '_', "
            "starting with a letter or number."
        )
    if name in registry.projects:
        raise WaError(f"Project '{name}' already exists.")


def detect_git_remote(directory: Path) -> Optional[str]:
    """Best-effort detection of the 'origin' remote for a directory. None on any failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def add_project(
    name: str,
    directory: str,
    git: Optional[str] = None,
    doc: Optional[str] = None,
    ssh: Optional[str] = None,
) -> Project:
    """Validate inputs, persist a new project, and scaffold its notes/ directory."""
    registry = Registry.load()
    validate_project_name(name, registry)

    resolved_dir = Path(directory).expanduser().resolve()
    if not resolved_dir.is_dir():
        raise WaError(f"Directory does not exist: {resolved_dir}")

    project_vars = {"DIR": str(resolved_dir)}
    if git:
        project_vars["GIT"] = git
    if doc:
        project_vars["DOC"] = doc
    if ssh:
        project_vars["SSH"] = ssh

    (resolved_dir / "notes").mkdir(exist_ok=True)

    project = Project(name=name, vars=project_vars)
    registry.projects[name] = project
    registry.save()
    return project


def remove_project(name: str, delete_files: bool = False) -> Project:
    """Remove a project from the registry, optionally deleting its directory on disk."""
    registry = Registry.load()
    if name not in registry.projects:
        raise WaError(f"Project '{name}' not found.")

    project = registry.projects.pop(name)
    registry.save()

    if delete_files:
        directory = project.vars.get("DIR")
        if directory:
            _safe_rmtree(Path(directory))

    return project


def _safe_rmtree(directory: Path) -> None:
    """Delete a project directory, refusing anything that looks like a mistake."""
    if not directory.is_dir():
        return
    home = Path.home()
    if directory == Path("/") or directory == home or len(directory.parts) <= 2:
        raise WaError(f"Refusing to delete suspicious path: {directory}")
    shutil.rmtree(directory)


def get_project(name: str) -> Project:
    """Look up a project by name, or raise WaError if it doesn't exist."""
    registry = Registry.load()
    if name not in registry.projects:
        raise WaError(f"Project '{name}' not found.")
    return registry.projects[name]


def get_active_project() -> Project:
    """Resolve the project bound to this shell session's ACTIVE_PROJ_DIR.

    ACTIVE_PROJ_DIR is set by `wa open` (see wa/cli.py + wa/shell.py) and is
    per-shell-session -- there is no global "active project" in the registry.
    """
    active_dir = os.environ.get(ACTIVE_PROJ_DIR_ENV)
    if not active_dir:
        raise WaError("No active project in this shell. Run 'wa open <project>' first.")

    resolved = str(Path(active_dir).resolve())
    registry = Registry.load()
    for project in registry.projects.values():
        if project.vars.get("DIR") == resolved:
            return project

    raise WaError(
        f"{ACTIVE_PROJ_DIR_ENV} ({active_dir}) doesn't match any known project "
        "(it may have been removed or renamed). Run 'wa open <project>' again."
    )


def add_var(name: str, value: str) -> Project:
    """Add or update an environment variable on the active project."""
    if not _VAR_NAME_RE.match(name):
        raise WaError(f"Invalid variable name '{name}': must be a valid env var identifier.")
    if name in _IMMUTABLE_VARS:
        raise WaError(f"'{name}' is managed internally and cannot be changed with 'wa var'.")

    project = get_active_project()
    registry = Registry.load()
    registry.projects[project.name].vars[name] = value
    registry.save()
    return registry.projects[project.name]


def remove_var(name: str) -> Project:
    """Remove an environment variable from the active project."""
    if name in _IMMUTABLE_VARS:
        raise WaError(f"'{name}' is managed internally and cannot be removed.")

    project = get_active_project()
    registry = Registry.load()
    if name not in registry.projects[project.name].vars:
        raise WaError(f"Variable '{name}' not set on project '{project.name}'.")
    del registry.projects[project.name].vars[name]
    registry.save()
    return registry.projects[project.name]


def add_command(name: str, script: str) -> Project:
    """Add or overwrite a custom command (run via `wa run <name>`) on the active project."""
    if not _NAME_RE.match(name):
        raise WaError(
            f"Invalid command name '{name}': use letters, numbers, '-' or '_', "
            "starting with a letter or number."
        )

    project = get_active_project()
    registry = Registry.load()
    registry.projects[project.name].cmds[name] = script
    registry.save()
    return registry.projects[project.name]


def remove_command(name: str) -> Project:
    """Remove a custom command from the active project."""
    project = get_active_project()
    registry = Registry.load()
    if name not in registry.projects[project.name].cmds:
        raise WaError(f"Command '{name}' not found on project '{project.name}'.")
    del registry.projects[project.name].cmds[name]
    registry.save()
    return registry.projects[project.name]
