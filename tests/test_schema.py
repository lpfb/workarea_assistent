import json

from wa.schema import Project, ProjectRef, Registry


def test_load_creates_empty_registry_on_first_run():
    registry = Registry.load()
    assert registry.projects == {}
    assert registry.version == 2


def test_load_creates_registry_file_on_disk():
    from wa.constants import REGISTRY_FILE

    assert not REGISTRY_FILE.exists()
    Registry.load()
    assert REGISTRY_FILE.exists()


def test_save_then_load_round_trips_project_ref():
    registry = Registry.load()
    registry.projects["demo"] = ProjectRef(name="demo", dir="/tmp/demo")
    registry.save()

    reloaded = Registry.load()
    assert set(reloaded.projects) == {"demo"}
    assert reloaded.projects["demo"].dir == "/tmp/demo"


def test_save_is_atomic_no_leftover_tmp_files():
    from wa.constants import DATA_DIR

    registry = Registry.load()
    registry.projects["demo"] = ProjectRef(name="demo", dir="/tmp/demo")
    registry.save()

    leftovers = list(DATA_DIR.glob(".projects_*.tmp"))
    assert leftovers == []


def test_project_ref_from_dict_defaults_missing_created_at():
    ref = ProjectRef.from_dict({"name": "demo", "dir": "/tmp/demo"})
    assert ref.dir == "/tmp/demo"
    assert ref.created_at


def test_load_migrates_legacy_v1_project_with_inline_vars_cmds(tmp_path):
    """Old registries stored vars/cmds inline; loading must migrate them out
    to <dir>/.wa/data.json, leaving only a pointer behind -- and persist that
    migration, not just apply it in memory."""
    from wa.constants import DATA_DIR, REGISTRY_FILE
    from wa.project_data import load_project_data

    project_dir = tmp_path / "legacy"
    project_dir.mkdir()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(
            {
                "version": 1,
                "projects": {
                    "demo": {
                        "name": "demo",
                        "vars": {"DIR": str(project_dir), "GIT": "git@x:y.git"},
                        "cmds": {"build": "make"},
                        "created_at": "2020-01-01T00:00:00+00:00",
                    }
                },
            }
        )
    )

    registry = Registry.load()
    assert registry.version == 2
    assert registry.projects["demo"].dir == str(project_dir)
    assert registry.projects["demo"].created_at == "2020-01-01T00:00:00+00:00"

    local_data = load_project_data(project_dir)
    assert local_data.vars == {"GIT": "git@x:y.git"}
    assert local_data.cmds == {"build": "make"}

    on_disk = json.loads(REGISTRY_FILE.read_text())
    assert on_disk["version"] == 2
    assert "vars" not in on_disk["projects"]["demo"]
    assert "cmds" not in on_disk["projects"]["demo"]


def test_load_migrates_legacy_project_whose_dir_no_longer_exists(tmp_path):
    """A legacy project whose directory was deleted still migrates to a
    ProjectRef (just without any local data to preserve)."""
    from wa.constants import DATA_DIR, REGISTRY_FILE

    missing_dir = tmp_path / "gone"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(
            {
                "version": 1,
                "projects": {
                    "demo": {
                        "name": "demo",
                        "vars": {"DIR": str(missing_dir)},
                        "cmds": {},
                    }
                },
            }
        )
    )

    registry = Registry.load()
    assert registry.projects["demo"].dir == str(missing_dir)


def test_project_is_a_plain_in_memory_dataclass():
    project = Project(name="demo", vars={"DIR": "/tmp/demo"}, cmds={"build": "make"})
    assert project.name == "demo"
    assert project.vars["DIR"] == "/tmp/demo"
    assert project.cmds["build"] == "make"
    assert project.created_at
