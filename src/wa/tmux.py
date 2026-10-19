"""tmux integration: one session per project, one window per layout entry.

`wa open <proj>` (see wa/cli.py) creates the project's session from its
layout (wa/projects.py `ensure_tmux_windows`) and attaches to it. Every
window starts in the project's DIR and gets `wa open <proj>` typed into it
(plus the window's own command, if any), so the shell function exports the
project's vars there too. Inside the project's own session, `wa open` just
does the plain cd/export -- that is what stops the windows from recursing.

Windows are always addressed by their tmux id (@N), never by index, so the
user's base-index setting doesn't matter. Every tmux invocation goes
through `_run`, the single seam tests replace with a fake.

Deliberately free of typer/rich/questionary imports, like wa/projects.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple

from wa import shell
from wa.constants import ACTIVE_PROJ_DIR_ENV, SHELL_PIPE_ENV
from wa.errors import WaError

# (package manager binary, install command), in detection order.
_INSTALLERS: Sequence[Tuple[str, List[str]]] = (
    ("pacman", ["pacman", "-S", "--needed", "tmux"]),
    ("apt-get", ["apt-get", "install", "-y", "tmux"]),
    ("dnf", ["dnf", "install", "-y", "tmux"]),
    ("zypper", ["zypper", "install", "-y", "tmux"]),
    ("apk", ["apk", "add", "tmux"]),
    ("brew", ["brew", "install", "tmux"]),
)


def is_installed() -> bool:
    return shutil.which("tmux") is not None


def install_command() -> Optional[List[str]]:
    """The command that would install tmux with this system's package manager, or None.

    Prefixed with sudo unless already root -- except for brew, which refuses to run as root.
    """
    for binary, command in _INSTALLERS:
        if shutil.which(binary) is None:
            continue
        if binary != "brew" and os.geteuid() != 0:
            return ["sudo", *command]
        return list(command)
    return None


def session_name(project_name: str) -> str:
    """tmux session name for a project (':' and '.' are target separators in tmux)."""
    return project_name.replace(":", "_").replace(".", "_")


def _run(args: Sequence[str]) -> str:
    """Run `tmux <args>`, returning stdout; raises WaError on failure.

    wa's own shell-integration vars are stripped: if this call starts the
    tmux server, its environment is what every pane inherits.
    """
    env = {k: v for k, v in os.environ.items() if k not in (SHELL_PIPE_ENV, ACTIVE_PROJ_DIR_ENV)}
    try:
        result = subprocess.run(["tmux", *args], capture_output=True, text=True, env=env)
    except OSError as exc:
        raise WaError(f"Could not run tmux: {exc}") from exc
    if result.returncode != 0:
        raise WaError(f"tmux {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _exact(session: str) -> str:
    # '=' makes tmux match the session name exactly instead of by prefix.
    return f"={session}"


def has_session(session: str) -> bool:
    try:
        _run(["has-session", "-t", _exact(session)])
    except WaError:
        return False
    return True


def current_session() -> Optional[str]:
    """Name of the tmux session this shell runs in, or None outside tmux."""
    if not os.environ.get("TMUX"):
        return None
    args = ["display-message", "-p"]
    pane = os.environ.get("TMUX_PANE")
    if pane:
        args += ["-t", pane]
    try:
        return _run([*args, "#{session_name}"]) or None
    except WaError:
        return None


def startup_line(project_name: str, cmd: str) -> str:
    """What gets typed into each window: open the project, then its command (if any)."""
    line = f"wa open {shell.quote(project_name)}"
    return f"{line} && {cmd}" if cmd.strip() else line


def _start_window(window_id: str, project_name: str, cmd: str) -> None:
    _run(["send-keys", "-t", window_id, "-l", startup_line(project_name, cmd)])
    _run(["send-keys", "-t", window_id, "Enter"])


def list_windows(session: str) -> List[Tuple[str, str]]:
    """(window id, name) for each window of a session, in tmux order."""
    output = _run(["list-windows", "-t", _exact(session), "-F", "#{window_id}\t#{window_name}"])
    return [tuple(line.split("\t", 1)) for line in output.splitlines() if line]


def create_session(
    session: str, directory: str, project_name: str, windows: List[Dict[str, str]]
) -> None:
    """Create a detached session with one window per layout entry, in order."""
    if not windows:
        raise WaError(f"Project '{project_name}' has no tmux windows configured.")
    first, *rest = windows
    first_id = _run([
        "new-session", "-d", "-s", session, "-c", directory, "-n", first["name"],
        "-P", "-F", "#{window_id}",
    ])
    _start_window(first_id, project_name, first["cmd"])

    previous_id = first_id
    for window in rest:
        previous_id = _run([
            "new-window", "-d", "-a", "-t", previous_id, "-c", directory, "-n", window["name"],
            "-P", "-F", "#{window_id}",
        ])
        _start_window(previous_id, project_name, window["cmd"])
    _run(["select-window", "-t", first_id])


def ensure_session(
    session: str, directory: str, project_name: str, windows: List[Dict[str, str]]
) -> bool:
    """Create the session unless it already exists. Returns True if it was created.

    An existing session is left untouched -- reopening a project resumes it.
    """
    if has_session(session):
        return False
    create_session(session, directory, project_name, windows)
    return True


def attach(session: str) -> None:
    """Attach the terminal to a session.

    With shell integration, the attach is handed to the parent shell via the
    side channel, so no wa process lingers while you work. Without it, wa
    runs tmux in the foreground until you detach.
    """
    if os.environ.get(SHELL_PIPE_ENV):
        shell.emit(f"tmux attach-session -t {shell.quote(_exact(session))}")
    else:
        _run_foreground(["attach-session", "-t", _exact(session)])


def _run_foreground(args: Sequence[str]) -> None:
    """Run tmux attached to this terminal (for attach without shell integration)."""
    subprocess.run(["tmux", *args])


def kill_session(session: str) -> None:
    _run(["kill-session", "-t", _exact(session)])


def switch_client(session: str) -> None:
    _run(["switch-client", "-t", _exact(session)])


def insert_window(
    session: str,
    directory: str,
    project_name: str,
    window: Dict[str, str],
    following_names: Sequence[str],
) -> None:
    """Add a window to a running session at the position matching the layout.

    `following_names` are the layout's window names after the new one; it is
    placed before the first of those that is open, or after the last window
    if none are (the live session may have drifted from the layout).
    """
    live = list_windows(session)
    live_ids = {name: window_id for window_id, name in reversed(live)}
    placement = ["-a", "-t", live[-1][0]] if live else ["-t", f"{_exact(session)}:"]
    for name in following_names:
        if name in live_ids:
            placement = ["-b", "-t", live_ids[name]]
            break
    window_id = _run([
        "new-window", "-d", *placement, "-c", directory, "-n", window["name"],
        "-P", "-F", "#{window_id}",
    ])
    _start_window(window_id, project_name, window["cmd"])


def find_window(session: str, name: str) -> Optional[str]:
    """Id of the first window with this name in a running session, or None."""
    for window_id, window_name in list_windows(session):
        if window_name == name:
            return window_id
    return None


def kill_window(window_id: str) -> None:
    _run(["kill-window", "-t", window_id])
