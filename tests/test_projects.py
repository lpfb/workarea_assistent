import pytest

from wa import projects
from wa.errors import WaError
from wa.schema import Registry


def test_add_project_persists_dir_and_scaffolds_notes(project_dir):
    project = projects.add_project("demo", str(project_dir))

    assert project.vars["DIR"] == str(project_dir.resolve())
    assert (project_dir / "notes").is_dir()

    reloaded = projects.get_project("demo")
    assert reloaded.vars["DIR"] == str(project_dir.resolve())


def test_add_project_rejects_duplicate_name(project_dir):
    projects.add_project("demo", str(project_dir))
    with pytest.raises(WaError, match="already exists"):
        projects.add_project("demo", str(project_dir))


def test_add_project_rejects_invalid_name(project_dir):
    with pytest.raises(WaError, match="Invalid project name"):
        projects.add_project("../etc", str(project_dir))


def test_add_project_rejects_nonexistent_dir(tmp_path):
    with pytest.raises(WaError, match="does not exist"):
        projects.add_project("demo", str(tmp_path / "does-not-exist"))


def test_add_project_stores_optional_vars(project_dir):
    project = projects.add_project(
        "demo", str(project_dir), git="git@x:y.git", doc="/docs", ssh="user@host"
    )
    assert project.vars["GIT"] == "git@x:y.git"
    assert project.vars["DOC"] == "/docs"
    assert project.vars["SSH"] == "user@host"


def test_remove_project_removes_from_registry_but_keeps_files_by_default(project_dir):
    projects.add_project("demo", str(project_dir))
    projects.remove_project("demo")

    assert project_dir.is_dir()
    with pytest.raises(WaError, match="not found"):
        projects.get_project("demo")


def test_remove_project_with_delete_files_removes_directory(project_dir):
    projects.add_project("demo", str(project_dir))
    projects.remove_project("demo", delete_files=True)

    assert not project_dir.exists()


def test_remove_project_missing_raises():
    with pytest.raises(WaError, match="not found"):
        projects.remove_project("nope")


def test_safe_rmtree_refuses_home_directory():
    from pathlib import Path

    # The real $HOME is used deliberately: it's guaranteed to exist and to
    # equal Path.home(), and the guard must raise before any rmtree call --
    # if it didn't, this test would be actively destructive.
    with pytest.raises(WaError, match="Refusing"):
        projects._safe_rmtree(Path.home())
    assert Path.home().is_dir()


def test_safe_rmtree_refuses_shallow_path():
    from pathlib import Path

    # len(parts) <= 2 matches paths like "/tmp" -- a plausible fat-finger
    # target one directory level short of something real. Real /tmp is used
    # here (guaranteed to exist) since the guard raises before any rmtree call.
    with pytest.raises(WaError, match="Refusing"):
        projects._safe_rmtree(Path("/tmp"))
    assert Path("/tmp").is_dir()


def test_get_active_project_requires_env_var():
    with pytest.raises(WaError, match="No active project"):
        projects.get_active_project()


def test_get_active_project_resolves_from_env(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    project = projects.get_active_project()
    assert project.name == "demo"


def test_get_active_project_errors_when_dir_matches_no_project(monkeypatch, tmp_path):
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(tmp_path))
    with pytest.raises(WaError, match="doesn't match any known project"):
        projects.get_active_project()


def test_resolve_goto_path_defaults_to_dir(project_dir):
    project = projects.add_project("demo", str(project_dir))
    path = projects.resolve_goto_path(project)
    assert path == project_dir.resolve()


def test_resolve_goto_path_rejects_non_directory_var(project_dir):
    project = projects.add_project("demo", str(project_dir), git="git@x:y.git")
    with pytest.raises(WaError, match="is not a directory"):
        projects.resolve_goto_path(project, "GIT")


def test_resolve_goto_path_rejects_unknown_var(project_dir):
    project = projects.add_project("demo", str(project_dir))
    with pytest.raises(WaError, match="not set"):
        projects.resolve_goto_path(project, "NOPE")


def test_add_var_and_remove_var_round_trip(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    projects.add_var("FOO", "bar")
    assert projects.get_project("demo").vars["FOO"] == "bar"

    projects.remove_var("FOO")
    assert "FOO" not in projects.get_project("demo").vars


def test_add_var_rejects_immutable_dir(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    with pytest.raises(WaError, match="managed internally"):
        projects.add_var("DIR", "/somewhere/else")


def test_remove_var_rejects_immutable_dir(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    with pytest.raises(WaError, match="managed internally"):
        projects.remove_var("DIR")


def test_add_var_rejects_invalid_identifier(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    with pytest.raises(WaError, match="Invalid variable name"):
        projects.add_var("not-an-identifier", "value")


def test_remove_var_missing_raises(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    with pytest.raises(WaError, match="not set"):
        projects.remove_var("NOPE")


def test_add_command_and_remove_command_round_trip(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    projects.add_command("build", "make all")
    assert projects.get_project("demo").cmds["build"] == "make all"

    projects.remove_command("build")
    assert "build" not in projects.get_project("demo").cmds


def test_remove_command_missing_raises(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    with pytest.raises(WaError, match="not found"):
        projects.remove_command("nope")


def test_get_command_script_returns_current_script(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))
    projects.add_command("build", "make all")

    assert projects.get_command_script("build") == "make all"


def test_get_command_script_missing_raises(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    with pytest.raises(WaError, match="not found"):
        projects.get_command_script("nope")


def test_require_existing_var_returns_project(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))
    projects.add_var("FOO", "bar")

    project = projects.require_existing_var("FOO")
    assert project.vars["FOO"] == "bar"


def test_require_existing_var_missing_raises(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    with pytest.raises(WaError, match="not set"):
        projects.require_existing_var("NOPE")


def test_require_existing_var_rejects_immutable_dir(monkeypatch, project_dir):
    projects.add_project("demo", str(project_dir))
    monkeypatch.setenv("ACTIVE_PROJ_DIR", str(project_dir))

    with pytest.raises(WaError, match="managed internally"):
        projects.require_existing_var("DIR")
