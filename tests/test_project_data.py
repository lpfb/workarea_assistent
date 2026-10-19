from wa.project_data import ProjectData, load_project_data, save_project_data


def test_load_missing_file_returns_empty(tmp_path):
    data = load_project_data(tmp_path)
    assert data.vars == {}
    assert data.cmds == {}


def test_save_then_load_round_trips(tmp_path):
    save_project_data(tmp_path, ProjectData(vars={"GIT": "git@x:y.git"}, cmds={"build": "make"}))

    reloaded = load_project_data(tmp_path)
    assert reloaded.vars == {"GIT": "git@x:y.git"}
    assert reloaded.cmds == {"build": "make"}


def test_save_creates_hidden_dir_and_self_gitignore(tmp_path):
    save_project_data(tmp_path, ProjectData())

    wa_dir = tmp_path / ".wa"
    assert wa_dir.is_dir()
    assert (wa_dir / "data.json").is_file()
    assert (wa_dir / ".gitignore").read_text() == "*\n"


def test_save_does_not_overwrite_existing_gitignore(tmp_path):
    wa_dir = tmp_path / ".wa"
    wa_dir.mkdir()
    (wa_dir / ".gitignore").write_text("custom\n")

    save_project_data(tmp_path, ProjectData())

    assert (wa_dir / ".gitignore").read_text() == "custom\n"


def test_save_is_atomic_no_leftover_tmp_files(tmp_path):
    save_project_data(tmp_path, ProjectData())

    leftovers = list((tmp_path / ".wa").glob(".data_*.tmp"))
    assert leftovers == []
