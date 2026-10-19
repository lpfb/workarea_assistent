"""Functional tests: drive the actual Typer app end-to-end via CliRunner.

Unlike tests/test_projects.py etc. (which call domain functions directly),
these exercise argument parsing, the active-project context rules,
shell-pipe emission, and rich output -- the things that only show up at
the CLI layer.
"""
import pytest
from typer.testing import CliRunner

from wa.cli import app

runner = CliRunner()


@pytest.fixture
def active_project(monkeypatch, project_dir):
    """Register a project and mark it active in this shell session, like `wa open` would."""
    from wa import projects

    project = projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))
    return project


def test_init_first_time_reports_success():
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "initialized" in result.output


def test_init_second_time_reports_already_initialized():
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "already initialized" in result.output


def test_project_add_registers_project(project_dir):
    result = runner.invoke(app, ["prj", "add", "demo", "--dir", str(project_dir), "--yes"])
    assert result.exit_code == 0
    assert "Added project 'demo'" in result.output


def test_project_add_rejects_duplicate(project_dir):
    runner.invoke(app, ["prj", "add", "demo", "--dir", str(project_dir), "--yes"])
    result = runner.invoke(app, ["prj", "add", "demo", "--dir", str(project_dir), "--yes"])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_project_list_empty_shows_hint():
    result = runner.invoke(app, ["prj", "list"])
    assert result.exit_code == 0
    assert "No projects registered" in result.output


def test_project_list_marks_active_project(monkeypatch, project_dir):
    runner.invoke(app, ["prj", "add", "demo", "--dir", str(project_dir), "--yes"])
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    result = runner.invoke(app, ["prj", "list"])
    assert "demo" in result.output
    assert "●" in result.output


def test_open_emits_cd_and_exports(project_dir, shell_pipe):
    from wa import projects

    projects.add_project("demo", str(project_dir), git="git@x:y.git")
    result = runner.invoke(app, ["open", "demo", "--no-tmux"])

    assert result.exit_code == 0
    assert "Opened 'demo'" in result.output

    pipe_content = shell_pipe.read_text()
    assert f"cd '{project_dir.resolve()}'" in pipe_content
    assert "export ACTIVE_PROJ_DIR=" in pipe_content
    assert "export GIT='git@x:y.git'" in pipe_content


def test_open_unknown_project_errors():
    result = runner.invoke(app, ["open", "nope"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "not found" in result.output


def test_project_remove_without_delete_files_keeps_directory(project_dir):
    runner.invoke(app, ["prj", "add", "demo", "--dir", str(project_dir), "--yes"])
    result = runner.invoke(app, ["prj", "remove", "demo", "--yes"])

    assert result.exit_code == 0
    assert project_dir.is_dir()


def test_project_remove_with_delete_files_removes_directory(project_dir):
    runner.invoke(app, ["prj", "add", "demo", "--dir", str(project_dir), "--yes"])
    result = runner.invoke(app, ["prj", "remove", "demo", "--delete-files", "--yes"])

    assert result.exit_code == 0
    assert not project_dir.exists()


def test_goto_root_emits_cd(active_project, shell_pipe):
    result = runner.invoke(app, ["goto"])
    assert result.exit_code == 0
    assert f"cd '{active_project.vars['DIR']}'" in shell_pipe.read_text()


def test_goto_without_active_project_errors():
    result = runner.invoke(app, ["goto"])
    assert result.exit_code == 1
    assert "No active project" in result.output


def test_var_add_list_remove_round_trip(active_project, shell_pipe):
    add_result = runner.invoke(app, ["var", "add", "FOO", "bar baz"])
    assert add_result.exit_code == 0
    assert "export FOO='bar baz'" in shell_pipe.read_text()

    list_result = runner.invoke(app, ["var", "list"])
    assert "FOO" in list_result.output
    assert "bar baz" in list_result.output
    assert "(immutable)" in list_result.output  # DIR row

    remove_result = runner.invoke(app, ["var", "remove", "FOO"])
    assert remove_result.exit_code == 0

    final_list = runner.invoke(app, ["var", "list"])
    assert "FOO" not in final_list.output


def test_var_edit_with_value_arg_updates_and_exports(active_project, shell_pipe):
    runner.invoke(app, ["var", "add", "FOO", "bar"])

    result = runner.invoke(app, ["var", "edit", "FOO", "baz"])
    assert result.exit_code == 0
    assert "Updated FOO=baz" in result.output
    assert "export FOO='baz'" in shell_pipe.read_text()


def test_var_edit_missing_var_errors(active_project):
    result = runner.invoke(app, ["var", "edit", "NOPE", "value"])
    assert result.exit_code == 1
    assert "not set" in result.output


def test_var_edit_rejects_immutable_dir(active_project):
    result = runner.invoke(app, ["var", "edit", "DIR", "/somewhere"])
    assert result.exit_code == 1
    assert "managed internally" in result.output


def test_var_add_rejects_immutable_dir(active_project):
    result = runner.invoke(app, ["var", "add", "DIR", "/somewhere"])
    assert result.exit_code == 1
    assert "managed internally" in result.output


def test_var_add_escapes_bracket_content(active_project):
    """Regression: rich must not swallow literal '[...]' in a var value."""
    result = runner.invoke(app, ["var", "add", "TAG", "release[1.2.3]"])
    assert result.exit_code == 0
    assert "release[1.2.3]" in result.output


def test_cmd_add_list_remove_round_trip(active_project):
    runner.invoke(app, ["cmd", "add", "build", "make all"])

    list_result = runner.invoke(app, ["cmd", "list"])
    assert "build" in list_result.output
    assert "make all" in list_result.output

    runner.invoke(app, ["cmd", "remove", "build"])
    final_list = runner.invoke(app, ["cmd", "list"])
    assert "No custom commands" in final_list.output


def test_cmd_edit_updates_script(active_project, monkeypatch):
    runner.invoke(app, ["cmd", "add", "build", "make all"])
    monkeypatch.setattr("wa.notes.resolve_editor_command", lambda: ["true"])

    result = runner.invoke(app, ["cmd", "edit", "build"])
    assert result.exit_code == 0
    assert "Updated command 'build'" in result.output

    from wa import projects

    assert projects.get_command_script("build") == "make all"


def test_cmd_edit_missing_command_errors(active_project, monkeypatch):
    monkeypatch.setattr("wa.notes.resolve_editor_command", lambda: ["true"])
    result = runner.invoke(app, ["cmd", "edit", "nope"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_run_executes_command_and_propagates_exit_code(active_project):
    runner.invoke(app, ["cmd", "add", "fail", "exit 7"])
    result = runner.invoke(app, ["run", "fail"])
    assert result.exit_code == 7


def test_run_unknown_command_errors(active_project):
    result = runner.invoke(app, ["run", "nope"])
    assert result.exit_code == 1
    assert "No command 'nope'" in result.output


def test_notes_edit_creates_file_without_opening_real_editor(active_project, monkeypatch):
    monkeypatch.setenv("EDITOR", "true")
    result = runner.invoke(app, ["notes", "edit", "mynote"])
    assert result.exit_code == 0

    from wa import notes

    path = notes.resolve_note_path(active_project, "mynote")
    assert path.is_file()


def test_notes_edit_defaults_to_dated_name(active_project, monkeypatch):
    monkeypatch.setenv("EDITOR", "true")
    runner.invoke(app, ["notes", "edit"])

    from wa import notes

    expected = notes.resolve_note_path(active_project, notes.default_note_name())
    assert expected.is_file()


def test_notes_list_and_remove(active_project, monkeypatch):
    monkeypatch.setenv("EDITOR", "true")
    runner.invoke(app, ["notes", "edit", "mynote"])

    list_result = runner.invoke(app, ["notes", "list"])
    assert "mynote" in list_result.output

    remove_result = runner.invoke(app, ["notes", "remove", "mynote", "--yes"])
    assert remove_result.exit_code == 0

    final_list = runner.invoke(app, ["notes", "list"])
    assert "No notes" in final_list.output


def test_no_active_project_error_shared_across_commands(project_dir):
    for args in (["run", "x"], ["var", "list"], ["cmd", "list"], ["notes", "list"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 1, args
        assert "No active project" in result.output, args
