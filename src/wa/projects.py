"""Domain logic for managing projects: init, add, remove, vars, cmds, context.

A project's data is split across two layers (see wa/schema.py and
wa/project_data.py): the central registry only knows a project's name and
directory (ProjectRef); vars/cmds live in the project's own
<DIR>/.wa/data.json. This module is what assembles/splits the merged
`Project` view callers actually work with, so that split is invisible
outside this file.

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
from wa.project_data import ProjectData, load_project_data, save_project_data
from wa.schema import Project, ProjectRef, Registry

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# Stricter than _NAME_RE: variable names become `export NAME=value`, so they
# must be valid shell identifiers (no dashes, can't start with a digit).
_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
IMMUTABLE_VARS = {"DIR"}


def _load_project(ref: ProjectRef) -> Project:
    """Assemble the merged, in-memory Project view from its central pointer
    plus its local vars/cmds (see wa/project_data.py)."""
    data = load_project_data(Path(ref.dir))
    return Project(
        name=ref.name, vars={"DIR": ref.dir, **data.vars}, cmds=dict(data.cmds),
        created_at=ref.created_at,
    )


def _save_project_local(project: Project) -> None:
    """Persist a Project's vars/cmds back to its own <DIR>/.wa/data.json (DIR excluded --
    it's implicit in the file's own location, not user-editable data)."""
    directory = Path(project.vars["DIR"])
    local_vars = {k: v for k, v in project.vars.items() if k != "DIR"}
    save_project_data(directory, ProjectData(vars=local_vars, cmds=dict(project.cmds)))


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
    """Validate inputs, persist a new project, and scaffold its notes/ directory.

    If the directory already has local data from a previous registration
    (see wa/project_data.py) -- e.g. it was `remove`d without --delete-files
    and is now being re-`add`ed -- that data is preserved, not clobbered.
    """
    registry = Registry.load()
    validate_project_name(name, registry)

    resolved_dir = Path(directory).expanduser().resolve()
    if not resolved_dir.is_dir():
        raise WaError(f"Directory does not exist: {resolved_dir}")

    (resolved_dir / "notes").mkdir(exist_ok=True)

    local_data = load_project_data(resolved_dir)
    if git:
        local_data.vars["GIT"] = git
    if doc:
        local_data.vars["DOC"] = doc
    if ssh:
        local_data.vars["SSH"] = ssh
    if local_data.vars or local_data.cmds:
        save_project_data(resolved_dir, local_data)

    ref = ProjectRef(name=name, dir=str(resolved_dir))
    registry.projects[name] = ref
    registry.save()
    return _load_project(ref)


def remove_project(name: str, delete_files: bool = False) -> Project:
    """Remove a project from the registry, optionally deleting its directory on disk.

    Without --delete-files, the project's own <DIR>/.wa/data.json is left
    untouched -- only the central pointer is forgotten, so re-`add`ing the
    same directory later picks its vars/cmds back up.
    """
    registry = Registry.load()
    if name not in registry.projects:
        raise WaError(f"Project '{name}' not found.")

    ref = registry.projects.pop(name)
    project = _load_project(ref)
    registry.save()

    if delete_files:
        _safe_rmtree(Path(ref.dir))

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
    return _load_project(registry.projects[name])


def list_projects() -> list:
    """Every registered project, merged with its local vars/cmds, for `wa prj list`.

    A project whose directory is missing/unreadable still shows up (name +
    DIR from the central pointer), just without its local vars/cmds --
    listing shouldn't break because one project moved or was deleted.
    """
    registry = Registry.load()
    result = []
    for ref in registry.projects.values():
        try:
            result.append(_load_project(ref))
        except OSError:
            result.append(Project(name=ref.name, vars={"DIR": ref.dir}, created_at=ref.created_at))
    return result


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
    for ref in registry.projects.values():
        if ref.dir == resolved:
            return _load_project(ref)

    raise WaError(
        f"{ACTIVE_PROJ_DIR_ENV} ({active_dir}) doesn't match any known project "
        "(it may have been removed or renamed). Run 'wa open <project>' again."
    )


def resolve_goto_path(project: Project, var_name: Optional[str] = None) -> Path:
    """Resolve the directory `wa goto` should cd into.

    With no var_name, targets the project root (DIR). With one, looks it up
    among the project's vars (DIR/GIT/DOC/SSH/custom) and requires it to
    point at an existing directory -- GIT/SSH are typically not paths, so
    pointing `goto` at them fails with a clear error rather than a bad cd.
    """
    if var_name is None:
        var_name = "DIR"

    if var_name not in project.vars:
        available = ", ".join(sorted(project.vars)) or "(none)"
        raise WaError(
            f"Variable '{var_name}' not set on project '{project.name}'. Available: {available}"
        )

    target = project.vars[var_name]
    path = Path(target).expanduser()
    if not path.is_dir():
        raise WaError(f"{var_name} ('{target}') is not a directory.")
    return path.resolve()


def add_var(name: str, value: str) -> Project:
    """Add or update an environment variable on the active project."""
    if not _VAR_NAME_RE.match(name):
        raise WaError(f"Invalid variable name '{name}': must be a valid env var identifier.")
    if name in IMMUTABLE_VARS:
        raise WaError(f"'{name}' is managed internally and cannot be changed with 'wa var'.")

    project = get_active_project()
    project.vars[name] = value
    _save_project_local(project)
    return project


def remove_var(name: str) -> Project:
    """Remove an environment variable from the active project."""
    if name in IMMUTABLE_VARS:
        raise WaError(f"'{name}' is managed internally and cannot be removed.")

    project = get_active_project()
    if name not in project.vars:
        raise WaError(f"Variable '{name}' not set on project '{project.name}'.")
    del project.vars[name]
    _save_project_local(project)
    return project


def get_command_script(name: str) -> str:
    """Return the current script for `name` on the active project; raises if missing."""
    project = get_active_project()
    if name not in project.cmds:
        raise WaError(f"Command '{name}' not found on project '{project.name}'.")
    return project.cmds[name]


def require_existing_var(name: str) -> Project:
    """Resolve the active project and ensure `name` is already a set variable.

    Used by `wa var edit`, which -- unlike `add_var` -- should not silently
    create a new variable on a typo'd name.
    """
    if name in IMMUTABLE_VARS:
        raise WaError(f"'{name}' is managed internally and cannot be changed with 'wa var'.")
    project = get_active_project()
    if name not in project.vars:
        raise WaError(
            f"Variable '{name}' not set on project '{project.name}'. Use 'wa var add' to create it."
        )
    return project


def add_command(name: str, script: str) -> Project:
    """Add or overwrite a custom command (run via `wa run <name>`) on the active project."""
    if not _NAME_RE.match(name):
        raise WaError(
            f"Invalid command name '{name}': use letters, numbers, '-' or '_', "
            "starting with a letter or number."
        )

    project = get_active_project()
    project.cmds[name] = script
    _save_project_local(project)
    return project


def remove_command(name: str) -> Project:
    """Remove a custom command from the active project."""
    project = get_active_project()
    if name not in project.cmds:
        raise WaError(f"Command '{name}' not found on project '{project.name}'.")
    del project.cmds[name]
    _save_project_local(project)
    return project
