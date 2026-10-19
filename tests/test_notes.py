import pytest

from wa import notes, projects
from wa.errors import WaError


@pytest.fixture
def project(project_dir):
    return projects.add_project("demo", str(project_dir))


def test_default_note_name_matches_expected_pattern():
    import re

    assert re.match(r"^note-\d{2}-\d{2}-\d{4}$", notes.default_note_name())


def test_resolve_note_path_rejects_path_traversal(project):
    with pytest.raises(WaError, match="Invalid note name"):
        notes.resolve_note_path(project, "../../etc/passwd")


def test_resolve_note_path_rejects_slash_in_name(project):
    with pytest.raises(WaError, match="Invalid note name"):
        notes.resolve_note_path(project, "sub/dir")


def test_open_in_editor_creates_file_if_missing(project, monkeypatch):
    monkeypatch.setattr(notes, "resolve_editor_command", lambda: ["true"])
    path = notes.resolve_note_path(project, "mynote")

    assert not path.exists()
    notes.open_in_editor(path)
    assert path.is_file()


def test_edit_text_in_editor_returns_unchanged_text_when_editor_is_noop(monkeypatch):
    monkeypatch.setattr(notes, "resolve_editor_command", lambda: ["true"])
    assert notes.edit_text_in_editor("make all") == "make all"


def test_edit_text_in_editor_returns_editors_new_content(monkeypatch, tmp_path):
    script_path = tmp_path / "fake_editor.sh"
    script_path.write_text('#!/bin/sh\necho "edited content" > "$1"\n')
    script_path.chmod(0o755)
    monkeypatch.setattr(notes, "resolve_editor_command", lambda: [str(script_path)])

    assert notes.edit_text_in_editor("original") == "edited content"


def test_list_notes_only_returns_notes_dir_md_files(project):
    notes_dir = notes.get_notes_dir(project)
    (notes_dir / "a.md").touch()
    (notes_dir / "b.md").touch()
    (notes_dir / "c.txt").touch()

    result = {p.name for p in notes.list_notes(project)}
    assert result == {"a.md", "b.md"}


def test_remove_note_missing_raises(project):
    with pytest.raises(WaError, match="not found"):
        notes.remove_note(project, "missing")


def test_remove_note_deletes_file(project):
    path = notes.resolve_note_path(project, "mynote")
    path.touch()
    notes.remove_note(project, "mynote")
    assert not path.exists()


def test_resolve_editor_command_uses_editor_env(monkeypatch):
    monkeypatch.setenv("EDITOR", "myeditor --flag")
    assert notes.resolve_editor_command() == ["myeditor", "--flag"]


def test_resolve_editor_command_falls_back_when_editor_unset(monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr(notes.shutil, "which", lambda name: "/usr/bin/nano" if name == "nano" else None)
    assert notes.resolve_editor_command() == ["nano"]


def test_resolve_editor_command_raises_when_nothing_available(monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr(notes.shutil, "which", lambda name: None)
    with pytest.raises(WaError, match="No editor available"):
        notes.resolve_editor_command()
