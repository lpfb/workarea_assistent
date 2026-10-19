"""Shared test fixtures.

The most important thing here is isolation: without it, tests would read
and write the developer's real ~/.config/wa and ~/.local/share/wa (or
worse, run `--delete-files` against a real directory), and would inherit
whatever ACTIVE_PROJ_DIR happens to be set in the shell pytest was
launched from.

wa.constants computes CONFIG_DIR/DATA_DIR/REGISTRY_FILE once at import
time, and wa.schema/wa.projects each bind their own copies of the names
they need via `from wa.constants import ...`. Patching wa.constants alone
would not reach those already-bound copies, so each consuming module's
names are patched individually.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    import wa.constants as constants
    import wa.projects as projects
    import wa.schema as schema

    config_dir = tmp_path / "config" / "wa"
    data_dir = tmp_path / "data" / "wa"
    registry_file = data_dir / "projects.json"

    monkeypatch.setattr(constants, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(constants, "DATA_DIR", data_dir)
    monkeypatch.setattr(constants, "CONFIG_FILE", config_dir / "config.json")
    monkeypatch.setattr(constants, "REGISTRY_FILE", registry_file)

    monkeypatch.setattr(schema, "DATA_DIR", data_dir)
    monkeypatch.setattr(schema, "REGISTRY_FILE", registry_file)

    monkeypatch.setattr(projects, "CONFIG_DIR", config_dir)

    for var in ("ACTIVE_PROJ_DIR", "WA_SHELL_PIPE"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def project_dir(tmp_path):
    """A real directory to use as a project's DIR (add_project requires it to exist)."""
    directory = tmp_path / "myproject"
    directory.mkdir()
    return directory


@pytest.fixture
def shell_pipe(tmp_path, monkeypatch):
    """A WA_SHELL_PIPE file wired up so tests can assert on emitted cd/export lines."""
    pipe_path = tmp_path / "wa_shell_pipe"
    monkeypatch.setenv("WA_SHELL_PIPE", str(pipe_path))
    return pipe_path


class FakeTmux:
    """In-memory stand-in for the tmux binary, wired into wa.tmux's `_run` seam.

    Models just enough (sessions holding ordered windows with ids) to verify
    what wa asks tmux to do, without ever touching a real tmux server.
    """

    def __init__(self):
        self.installed = True
        self.sessions = {}  # name -> list of {"id", "name", "dir", "keys"}
        self.calls = []
        self.attached = []
        self.switched = []
        self.current = None  # session name reported by display-message
        self._next_id = 0

    def _new_window(self, name, directory):
        self._next_id += 1
        return {"id": f"@{self._next_id}", "name": name, "dir": directory, "keys": []}

    def _locate(self, window_id):
        for windows in self.sessions.values():
            for index, window in enumerate(windows):
                if window["id"] == window_id:
                    return windows, index
        raise AssertionError(f"unknown window {window_id}")

    def window_names(self, session):
        return [w["name"] for w in self.sessions[session]]

    def run(self, args):
        from wa.errors import WaError

        args = list(args)
        self.calls.append(args)
        cmd, opts = args[0], args[1:]

        def opt(flag):
            return opts[opts.index(flag) + 1] if flag in opts else None

        target = (opt("-t") or "").lstrip("=").rstrip(":")
        if cmd == "has-session":
            if target not in self.sessions:
                raise WaError("can't find session")
            return ""
        if cmd == "display-message":
            if self.current is None:
                raise WaError("no current session")
            return self.current
        if cmd == "new-session":
            window = self._new_window(opt("-n"), opt("-c"))
            self.sessions[opt("-s")] = [window]
            return window["id"]
        if cmd == "new-window":
            window = self._new_window(opt("-n"), opt("-c"))
            if target in self.sessions:
                self.sessions[target].append(window)
            else:
                windows, index = self._locate(target)
                windows.insert(index if "-b" in opts else index + 1, window)
            return window["id"]
        if cmd == "send-keys":
            windows, index = self._locate(opt("-t"))
            windows[index]["keys"].append(opts[-1])
            return ""
        if cmd == "list-windows":
            return "\n".join(f"{w['id']}\t{w['name']}" for w in self.sessions[target])
        if cmd == "kill-window":
            windows, index = self._locate(opt("-t"))
            del windows[index]
            return ""
        if cmd == "kill-session":
            del self.sessions[target]
            return ""
        if cmd == "switch-client":
            self.switched.append(target)
            return ""
        if cmd == "select-window":
            return ""
        raise AssertionError(f"unexpected tmux call: {args}")


@pytest.fixture(autouse=True)
def fake_tmux(monkeypatch):
    import wa.tmux as tmux

    fake = FakeTmux()
    monkeypatch.setattr(tmux, "_run", fake.run)
    monkeypatch.setattr(tmux, "is_installed", lambda: fake.installed)
    monkeypatch.setattr(tmux, "_run_foreground", lambda args: fake.attached.append(args))
    for var in ("TMUX", "TMUX_PANE"):
        monkeypatch.delenv(var, raising=False)
    return fake
