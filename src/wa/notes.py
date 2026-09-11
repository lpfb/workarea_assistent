"""Domain logic for project notes (.md files).

Notes live inside the project's own directory (<DIR>/notes/), not wa's XDG
data dir, so they travel with the project's own git history (see spec
section 4). Deliberately free of typer/rich imports, like wa/projects.py.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import List

from wa.errors import WaError
from wa.schema import Project

NOTES_SUBDIR = "notes"

# No dots/slashes allowed -- names become filenames, so this also blocks
# path traversal (e.g. "../../etc/passwd").
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_FALLBACK_EDITORS = ("nano", "vi", "vim", "nvim")


def default_note_name() -> str:
    """Name used for `wa notes edit` when none is given: note-DD-MM-YYYY (today)."""
    return date.today().strftime("note-%d-%m-%Y")


def _validate_name(name: str, kind: str = "name") -> None:
    if not _NAME_RE.match(name):
        raise WaError(
            f"Invalid {kind} '{name}': use letters, numbers, '-' or '_', "
            "starting with a letter or number."
        )


def get_notes_dir(project: Project) -> Path:
    notes_dir = Path(project.vars["DIR"]) / NOTES_SUBDIR
    notes_dir.mkdir(parents=True, exist_ok=True)
    return notes_dir


def resolve_note_path(project: Project, name: str) -> Path:
    _validate_name(name, "note name")
    return get_notes_dir(project) / f"{name}.md"


def list_notes(project: Project) -> List[Path]:
    """All .md notes in the project."""
    return sorted(get_notes_dir(project).glob("*.md"))


def remove_note(project: Project, name: str) -> Path:
    path = resolve_note_path(project, name)
    if not path.is_file():
        raise WaError(f"Note '{name}' not found.")
    path.unlink()
    return path


def resolve_editor_command() -> List[str]:
    """Resolve the $EDITOR command, falling back to a common terminal editor."""
    editor = os.environ.get("EDITOR")
    if editor:
        return shlex.split(editor)
    for candidate in _FALLBACK_EDITORS:
        if shutil.which(candidate):
            return [candidate]
    raise WaError("No editor available. Set $EDITOR (e.g. export EDITOR=nano).")


def open_in_editor(path: Path) -> int:
    """Open `path` in the user's editor, inheriting the terminal. Returns its exit code."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    command = resolve_editor_command() + [str(path)]
    result = subprocess.run(command)
    return result.returncode


def edit_text_in_editor(initial_text: str) -> str:
    """Round-trip arbitrary text through the user's editor via a throwaway temp file.

    Used for editing values (like a command's script) that don't have a
    permanent file of their own, unlike notes.
    """
    import tempfile

    command = resolve_editor_command()
    fd, temp_name = tempfile.mkstemp(suffix=".sh", text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(initial_text)
        subprocess.run(command + [str(temp_path)])
        return temp_path.read_text(encoding="utf-8").rstrip("\n")
    finally:
        temp_path.unlink(missing_ok=True)
