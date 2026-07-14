"""Domain logic for project notes (.md files) and the todo checklist.

Both live inside the project's own directory (<DIR>/notes/), not wa's XDG
data dir, so they travel with the project's own git history (see spec
section 4). Deliberately free of typer/rich imports, like wa/projects.py.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional

from wa.constants import ACTIVE_TODO_LIST_ENV
from wa.errors import WaError
from wa.schema import Project

NOTES_SUBDIR = "notes"
TODO_SUBDIR = "todo"  # <DIR>/notes/todo/<list-name>.md -- kept separate from
# regular notes so `wa notes list` never has to guess which .md files are
# todo lists.

# No dots/slashes allowed -- names become filenames, so this also blocks
# path traversal (e.g. "../../etc/passwd"). Shared by notes and todo lists.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_TODO_LINE_RE = re.compile(r"^- \[([ xX])\] (.*)$")
_FALLBACK_EDITORS = ("nano", "vi", "vim")


def default_note_name() -> str:
    """Name used for `wa notes edit` when none is given: note-DD-MM-YYYY (today)."""
    return date.today().strftime("note-%d-%m-%Y")


def default_todo_name() -> str:
    """Name used for `wa todo add` (list-creation mode) when none is given: todo-DD-MM-YYYY."""
    return date.today().strftime("todo-%d-%m-%Y")


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
    """All .md notes in the project (todo lists live under notes/todo/, not here)."""
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


@dataclass
class TodoItem:
    line_index: int  # 0-based index into the todo file's lines, for in-place rewrites
    checked: bool
    text: str


def get_todo_dir(project: Project) -> Path:
    todo_dir = get_notes_dir(project) / TODO_SUBDIR
    todo_dir.mkdir(parents=True, exist_ok=True)
    return todo_dir


def resolve_todo_list_path(project: Project, name: str) -> Path:
    _validate_name(name, "todo list name")
    return get_todo_dir(project) / f"{name}.md"


def list_todo_lists(project: Project) -> List[Path]:
    """All todo lists that exist for this project."""
    return sorted(get_todo_dir(project).glob("*.md"))


def create_todo_list(project: Project, name: str) -> Path:
    """Create a new, empty todo list. Raises if one with that name already exists."""
    path = resolve_todo_list_path(project, name)
    if path.exists():
        raise WaError(f"Todo list '{name}' already exists.")
    path.touch()
    return path


def get_active_todo_list() -> Optional[str]:
    """The todo list name selected by `wa todo open` in this shell session, if any."""
    return os.environ.get(ACTIVE_TODO_LIST_ENV)


def _read_lines(path: Path) -> List[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _write_lines(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines)
    if content:
        content += "\n"
    path.write_text(content, encoding="utf-8")


def parse_todo(project: Project, name: str) -> List[TodoItem]:
    """Parse a checklist; only well-formed '- [ ]'/'- [x]' lines become items.

    Other lines (headers, free text) are preserved on disk but not indexed,
    so they don't shift the numbering `wa todo` commands show the user.
    """
    lines = _read_lines(resolve_todo_list_path(project, name))
    items = []
    for i, line in enumerate(lines):
        match = _TODO_LINE_RE.match(line)
        if match:
            items.append(
                TodoItem(line_index=i, checked=match.group(1).lower() == "x", text=match.group(2))
            )
    return items


def add_todo(project: Project, name: str, text: str) -> TodoItem:
    text = text.strip()
    if not text:
        raise WaError("Todo text cannot be empty.")
    path = resolve_todo_list_path(project, name)
    lines = _read_lines(path)
    lines.append(f"- [ ] {text}")
    _write_lines(path, lines)
    return TodoItem(line_index=len(lines) - 1, checked=False, text=text)


def _get_item_by_position(project: Project, name: str, position: int) -> TodoItem:
    """`position` is 1-based, matching what `wa todo open`/`list` displays."""
    items = parse_todo(project, name)
    if position < 1 or position > len(items):
        raise WaError(f"No todo item #{position}. There are {len(items)} item(s).")
    return items[position - 1]


def toggle_todo(project: Project, name: str, position: int) -> TodoItem:
    item = _get_item_by_position(project, name, position)
    path = resolve_todo_list_path(project, name)
    lines = _read_lines(path)
    new_checked = not item.checked
    lines[item.line_index] = f"- [{'x' if new_checked else ' '}] {item.text}"
    _write_lines(path, lines)
    return TodoItem(line_index=item.line_index, checked=new_checked, text=item.text)


def remove_todo(project: Project, name: str, position: int) -> TodoItem:
    item = _get_item_by_position(project, name, position)
    path = resolve_todo_list_path(project, name)
    lines = _read_lines(path)
    del lines[item.line_index]
    _write_lines(path, lines)
    return item
