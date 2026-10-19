"""tmux integration: layout storage, session creation on `wa open`, live
updates from `wa tmux add/remove`, and the tmux-missing fallback.

Every test runs against conftest's FakeTmux -- never a real tmux server.
"""
import json

import pytest
from typer.testing import CliRunner

from wa import projects
from wa.cli import app
from wa.project_data import load_project_data, save_project_data

runner = CliRunner()


@pytest.fixture
def active_project(monkeypatch, project_dir):
    project = projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))
    return project


def _layout(project_dir):
    return load_project_data(project_dir).tmux_windows


# --- layout storage -------------------------------------------------------


def test_add_project_materializes_default_layout(project_dir):
    projects.add_project("demo", str(project_dir))
    assert _layout(project_dir) == [
        {"name": "git", "cmd": ""},
        {"name": "edit", "cmd": ""},
        {"name": "deploy", "cmd": ""},
    ]


def test_add_project_uses_configured_defaults(project_dir):
    import wa.constants as constants

    constants.CONFIG_FILE.parent.mkdir(parents=True)
    constants.CONFIG_FILE.write_text(
        json.dumps({"tmux": {"default_windows": ["code", {"name": "logs", "cmd": "tail -f x"}]}})
    )
    projects.add_project("demo", str(project_dir))
    assert _layout(project_dir) == [{"name": "code", "cmd": ""}, {"name": "logs", "cmd": "tail -f x"}]


def test_project_layout_is_independent_of_later_default_changes(project_dir):
    import wa.constants as constants

    projects.add_project("demo", str(project_dir))
    constants.CONFIG_FILE.parent.mkdir(parents=True)
    constants.CONFIG_FILE.write_text(json.dumps({"tmux": {"default_windows": ["other"]}}))
    assert [w["name"] for w in _layout(project_dir)] == ["git", "edit", "deploy"]


def test_legacy_project_gets_defaults_on_first_use(active_project, project_dir):
    data = load_project_data(project_dir)
    data.tmux_windows = None
    save_project_data(project_dir, data)

    result = runner.invoke(app, ["tmux", "list"])
    assert result.exit_code == 0
    assert [w["name"] for w in _layout(project_dir)] == ["git", "edit", "deploy"]


def test_init_writes_editable_config_file():
    import wa.constants as constants

    runner.invoke(app, ["init"])
    config = json.loads(constants.CONFIG_FILE.read_text())
    assert [w["name"] for w in config["tmux"]["default_windows"]] == ["git", "edit", "deploy"]


# --- wa tmux add/remove/edit/list ----------------------------------------


def test_tmux_add_appends_by_default(active_project, project_dir):
    result = runner.invoke(app, ["tmux", "add", "logs", "tail -f app.log"])
    assert result.exit_code == 0
    assert _layout(project_dir)[-1] == {"name": "logs", "cmd": "tail -f app.log"}


def test_tmux_add_at_position(active_project, project_dir):
    result = runner.invoke(app, ["tmux", "add", "build", "--at", "1"])
    assert result.exit_code == 0
    assert [w["name"] for w in _layout(project_dir)] == ["git", "build", "edit", "deploy"]


def test_tmux_add_at_past_end_appends(active_project, project_dir):
    runner.invoke(app, ["tmux", "add", "build", "--at", "99"])
    assert [w["name"] for w in _layout(project_dir)][-1] == "build"


def test_tmux_add_rejects_negative_position(active_project):
    result = runner.invoke(app, ["tmux", "add", "build", "--at", "-1"])
    assert result.exit_code == 1


def test_tmux_add_rejects_duplicate(active_project):
    result = runner.invoke(app, ["tmux", "add", "git"])
    assert result.exit_code == 1
    assert "already exists" in result.output


@pytest.mark.parametrize("bad_name", ["", "a:b", "a.b"])
def test_tmux_add_rejects_invalid_names(active_project, bad_name):
    result = runner.invoke(app, ["tmux", "add", bad_name])
    assert result.exit_code == 1


def test_tmux_add_accepts_names_with_spaces(active_project, project_dir):
    result = runner.invoke(app, ["tmux", "add", "my logs"])
    assert result.exit_code == 0
    assert _layout(project_dir)[-1]["name"] == "my logs"


def test_tmux_remove(active_project, project_dir):
    result = runner.invoke(app, ["tmux", "remove", "deploy"])
    assert result.exit_code == 0
    assert [w["name"] for w in _layout(project_dir)] == ["git", "edit"]


def test_tmux_remove_unknown_errors(active_project):
    result = runner.invoke(app, ["tmux", "remove", "nope"])
    assert result.exit_code == 1


def test_tmux_remove_refuses_last_window(active_project):
    runner.invoke(app, ["tmux", "remove", "deploy"])
    runner.invoke(app, ["tmux", "remove", "edit"])
    result = runner.invoke(app, ["tmux", "remove", "git"])
    assert result.exit_code == 1
    assert "only window" in result.output


def test_tmux_edit_with_value(active_project, project_dir):
    result = runner.invoke(app, ["tmux", "edit", "git", "lazygit"])
    assert result.exit_code == 0
    assert _layout(project_dir)[0] == {"name": "git", "cmd": "lazygit"}


def test_tmux_edit_unknown_errors(active_project):
    result = runner.invoke(app, ["tmux", "edit", "nope", "x"])
    assert result.exit_code == 1


def test_tmux_list_shows_layout(active_project):
    runner.invoke(app, ["tmux", "edit", "git", "lazygit"])
    result = runner.invoke(app, ["tmux", "list"])
    assert result.exit_code == 0
    for text in ("git", "lazygit", "edit", "deploy"):
        assert text in result.output


def test_tmux_commands_require_active_project():
    result = runner.invoke(app, ["tmux", "list"])
    assert result.exit_code == 1
    assert "No active project" in result.output


def test_tmux_layout_survives_var_and_cmd_changes(active_project, project_dir):
    runner.invoke(app, ["tmux", "add", "logs"])
    runner.invoke(app, ["var", "add", "FOO", "bar"])
    runner.invoke(app, ["cmd", "add", "build", "make"])
    assert _layout(project_dir)[-1]["name"] == "logs"


# --- wa open ---------------------------------------------------------------


def test_open_outside_tmux_creates_session_and_attaches(project_dir, shell_pipe, fake_tmux):
    projects.add_project("demo", str(project_dir))
    projects_dir = str(project_dir.resolve())

    result = runner.invoke(app, ["open", "demo"])
    assert result.exit_code == 0
    assert "Created tmux session 'demo'" in result.output

    windows = fake_tmux.sessions["demo"]
    assert [w["name"] for w in windows] == ["git", "edit", "deploy"]
    assert all(w["dir"] == projects_dir for w in windows)
    assert all(w["keys"] == ["wa open 'demo'", "Enter"] for w in windows)

    pipe = shell_pipe.read_text()
    assert f"cd '{projects_dir}'" in pipe
    assert pipe.rstrip().endswith("tmux attach-session -t '=demo'")


def test_open_runs_window_commands_after_wa_open(project_dir, shell_pipe, fake_tmux, monkeypatch):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))
    runner.invoke(app, ["tmux", "edit", "git", "cd git"])
    monkeypatch.delenv("ACTIVE_PROJ_DIR")

    runner.invoke(app, ["open", "demo"])
    assert fake_tmux.sessions["demo"][0]["keys"][0] == "wa open 'demo' && cd git"


def test_open_resumes_existing_session(project_dir, shell_pipe, fake_tmux):
    projects.add_project("demo", str(project_dir))
    runner.invoke(app, ["open", "demo"])
    sent_before = sum(1 for c in fake_tmux.calls if c[0] == "send-keys")

    result = runner.invoke(app, ["open", "demo"])
    assert "Resumed tmux session 'demo'" in result.output
    assert sum(1 for c in fake_tmux.calls if c[0] == "send-keys") == sent_before


def test_open_inside_own_session_is_plain_open(project_dir, shell_pipe, fake_tmux, monkeypatch):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake_tmux.current = "demo"

    result = runner.invoke(app, ["open", "demo"])
    assert "Opened 'demo'" in result.output
    assert "new-session" not in [c[0] for c in fake_tmux.calls]
    assert "attach-session" not in shell_pipe.read_text()


def test_open_inside_other_session_switches_client(project_dir, shell_pipe, fake_tmux, monkeypatch):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake_tmux.current = "other"

    result = runner.invoke(app, ["open", "demo"])
    assert result.exit_code == 0
    assert "demo" in fake_tmux.sessions
    assert fake_tmux.switched == ["demo"]
    assert not shell_pipe.exists() or "attach-session" not in shell_pipe.read_text()


def test_open_without_shell_integration_attaches_in_foreground(project_dir, fake_tmux):
    projects.add_project("demo", str(project_dir))
    result = runner.invoke(app, ["open", "demo"])
    assert result.exit_code == 0
    assert fake_tmux.attached == [["attach-session", "-t", "=demo"]]


def test_open_no_tmux_flag_skips_tmux(project_dir, shell_pipe, fake_tmux):
    projects.add_project("demo", str(project_dir))
    result = runner.invoke(app, ["open", "demo", "--no-tmux"])
    assert "Opened 'demo'" in result.output
    assert fake_tmux.calls == []


# --- tmux not installed ----------------------------------------------------


def test_open_without_tmux_non_interactive_falls_back(project_dir, shell_pipe, fake_tmux):
    fake_tmux.installed = False
    projects.add_project("demo", str(project_dir))

    result = runner.invoke(app, ["open", "demo"])
    assert result.exit_code == 0
    assert "tmux is not installed" in result.output
    assert "Opened 'demo'" in result.output
    assert fake_tmux.calls == []


def test_open_without_tmux_declined_install_falls_back(project_dir, shell_pipe, fake_tmux, monkeypatch):
    import questionary

    import wa.cli as cli
    import wa.tmux as tmux

    fake_tmux.installed = False
    projects.add_project("demo", str(project_dir))
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    monkeypatch.setattr(tmux, "install_command", lambda: ["sudo", "pacman", "-S", "tmux"])
    monkeypatch.setattr(
        questionary, "confirm", lambda *a, **k: type("Q", (), {"ask": lambda self: False})()
    )

    result = runner.invoke(app, ["open", "demo"])
    assert "Skipped tmux install" in result.output
    assert "Opened 'demo'" in result.output


def test_open_without_tmux_accepted_install_opens_session(project_dir, shell_pipe, fake_tmux, monkeypatch):
    import subprocess

    import questionary

    import wa.cli as cli
    import wa.tmux as tmux

    fake_tmux.installed = False
    projects.add_project("demo", str(project_dir))
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    monkeypatch.setattr(tmux, "install_command", lambda: ["sudo", "pacman", "-S", "tmux"])
    monkeypatch.setattr(
        questionary, "confirm", lambda *a, **k: type("Q", (), {"ask": lambda self: True})()
    )
    ran = []

    def fake_install(command):
        ran.append(command)
        fake_tmux.installed = True
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_install)

    result = runner.invoke(app, ["open", "demo"])
    assert ran == [["sudo", "pacman", "-S", "tmux"]]
    assert "Created tmux session 'demo'" in result.output


def test_install_command_uses_sudo_for_system_managers(monkeypatch):
    import wa.tmux as tmux

    monkeypatch.setattr(tmux.shutil, "which", lambda b: "/usr/bin/pacman" if b == "pacman" else None)
    monkeypatch.setattr(tmux.os, "geteuid", lambda: 1000)
    assert tmux.install_command() == ["sudo", "pacman", "-S", "--needed", "tmux"]


def test_install_command_none_without_known_manager(monkeypatch):
    import wa.tmux as tmux

    monkeypatch.setattr(tmux.shutil, "which", lambda b: None)
    assert tmux.install_command() is None


def test_tmux_layout_commands_work_without_tmux(active_project, project_dir, fake_tmux):
    fake_tmux.installed = False
    result = runner.invoke(app, ["tmux", "add", "logs"])
    assert result.exit_code == 0
    assert fake_tmux.calls == []


# --- live updates to a running session -------------------------------------


@pytest.fixture
def running_session(active_project, shell_pipe, fake_tmux, monkeypatch):
    monkeypatch.delenv("ACTIVE_PROJ_DIR")
    runner.invoke(app, ["open", "demo"])
    monkeypatch.setenv("ACTIVE_PROJ_DIR", active_project.vars["DIR"])
    return fake_tmux


def test_tmux_add_opens_window_in_running_session(running_session):
    result = runner.invoke(app, ["tmux", "add", "logs", "tail -f x"])
    assert "opened it in session 'demo'" in " ".join(result.output.split())
    assert running_session.window_names("demo") == ["git", "edit", "deploy", "logs"]
    assert running_session.sessions["demo"][-1]["keys"][0] == "wa open 'demo' && tail -f x"


def test_tmux_add_at_inserts_in_matching_live_position(running_session):
    runner.invoke(app, ["tmux", "add", "build", "--at", "1"])
    assert running_session.window_names("demo") == ["git", "build", "edit", "deploy"]


def test_tmux_remove_with_yes_closes_live_window(running_session):
    result = runner.invoke(app, ["tmux", "remove", "edit", "--yes"])
    assert result.exit_code == 0
    assert running_session.window_names("demo") == ["git", "deploy"]


def test_tmux_remove_declined_keeps_live_window(running_session, project_dir, monkeypatch):
    import questionary

    monkeypatch.setattr(
        questionary, "confirm", lambda *a, **k: type("Q", (), {"ask": lambda self: False})()
    )
    result = runner.invoke(app, ["tmux", "remove", "edit"])
    assert result.exit_code == 0
    assert running_session.window_names("demo") == ["git", "edit", "deploy"]
    assert [w["name"] for w in _layout(project_dir)] == ["git", "deploy"]


# --- wa close / prj remove -----------------------------------------------


def _answer(monkeypatch, value):
    import questionary

    monkeypatch.setattr(
        questionary, "confirm", lambda *a, **k: type("Q", (), {"ask": lambda self: value})()
    )


def test_close_active_project_kills_session_and_unsets_vars(running_session, shell_pipe):
    runner.invoke(app, ["var", "add", "FOO", "bar"])
    shell_pipe.write_text("")

    result = runner.invoke(app, ["close", "--yes"])
    assert result.exit_code == 0
    assert "demo" not in running_session.sessions
    pipe = shell_pipe.read_text().splitlines()
    for name in ("DIR", "FOO", "ACTIVE_PROJ_DIR"):
        assert f"unset {name}" in pipe


def test_close_by_name_from_other_project_keeps_this_shells_vars(
    running_session, shell_pipe, tmp_path, monkeypatch
):
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    projects.add_project("other", str(other_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(other_dir))
    shell_pipe.write_text("")

    result = runner.invoke(app, ["close", "demo", "--yes"])
    assert result.exit_code == 0
    assert "demo" not in running_session.sessions
    assert "unset" not in shell_pipe.read_text()


def test_close_asks_and_declined_keeps_session_but_unsets(running_session, shell_pipe, monkeypatch):
    _answer(monkeypatch, False)
    shell_pipe.write_text("")

    result = runner.invoke(app, ["close"])
    assert result.exit_code == 0
    assert "demo" in running_session.sessions
    assert "Left tmux session 'demo' running" in result.output
    assert "unset ACTIVE_PROJ_DIR" in shell_pipe.read_text()


def test_close_active_project_without_session_only_unsets(active_project, shell_pipe, fake_tmux):
    result = runner.invoke(app, ["close"])
    assert result.exit_code == 0
    assert "unset ACTIVE_PROJ_DIR" in shell_pipe.read_text()
    assert "kill-session" not in [c[0] for c in fake_tmux.calls]


def test_close_project_not_open_is_a_no_op(project_dir, shell_pipe):
    projects.add_project("demo", str(project_dir))
    result = runner.invoke(app, ["close", "demo"])
    assert result.exit_code == 0
    assert "nothing to close" in result.output
    assert not shell_pipe.exists()


def test_close_without_name_or_active_project_errors():
    result = runner.invoke(app, ["close"])
    assert result.exit_code == 1
    assert "No active project" in result.output


def test_close_without_tmux_still_unsets(active_project, shell_pipe, fake_tmux):
    fake_tmux.installed = False
    result = runner.invoke(app, ["close"])
    assert result.exit_code == 0
    assert "unset ACTIVE_PROJ_DIR" in shell_pipe.read_text()
    assert fake_tmux.calls == []


def test_prj_remove_closes_running_session(running_session, shell_pipe):
    result = runner.invoke(app, ["prj", "remove", "demo", "--yes"])
    assert result.exit_code == 0
    assert "demo" not in running_session.sessions
    assert "unset ACTIVE_PROJ_DIR" in shell_pipe.read_text()


def test_prj_remove_with_delete_files_kills_session_first(running_session, project_dir):
    result = runner.invoke(app, ["prj", "remove", "demo", "--delete-files", "--yes"])
    assert result.exit_code == 0
    assert "demo" not in running_session.sessions
    assert not project_dir.exists()


def test_prj_remove_declined_session_close_still_removes(running_session, monkeypatch):
    answers = iter([True, False])  # "Remove project?" yes, "Kill session?" no
    import questionary

    monkeypatch.setattr(
        questionary, "confirm",
        lambda *a, **k: type("Q", (), {"ask": lambda self: next(answers)})(),
    )
    result = runner.invoke(app, ["prj", "remove", "demo"])
    assert result.exit_code == 0
    assert "Removed project 'demo'" in result.output
    assert "demo" in running_session.sessions
