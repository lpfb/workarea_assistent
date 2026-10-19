"""wa command line entry point.

Only rich/questionary-heavy imports (and the projects/errors domain modules)
are deferred into command bodies -- the top-level module stays cheap so
`wa --help` and completion stay instant.
"""
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from wa import shell

app = typer.Typer(
    help="Workflow Assistant: manage project workspaces, env vars, scripts and notes.",
    no_args_is_help=True,
    # Typer's default rich-based help formatter unconditionally imports
    # rich.markdown -> markdown_it/pygments, adding ~200ms to every
    # invocation just to render --help. Disabling it falls back to Click's
    # plain formatter for help/usage text; our own commands still use rich
    # (lazily imported) for their actual output.
    rich_markup_mode=None,
)


def _print_error(console, message: object) -> None:
    """Print a user-facing error, escaping any dynamic content it may carry.

    Project names, custom var/script values and note/task text are all
    user-supplied and may legally contain '[' -- without escaping, Rich
    would parse that as markup instead of displaying it literally.
    """
    from rich.markup import escape

    console.print(f"[red]Error:[/red] {escape(str(message))}")


def _print_info(console, message: str) -> None:
    """Print a neutral status message (e.g. 'nothing here yet') -- dim, not red/green."""
    console.print(f"[dim]{message}[/dim]")


# Dynamic shell-completion callables (see 'wa --install-completion').
#
# These only run when a shell is actually completing a command line (a
# separate `_WA_COMPLETE=...` invocation, not the normal command dispatch),
# so their lazy imports don't affect regular startup time. Each one fails
# silently (returns no completions) rather than raising -- a completion
# source that can crash the user's shell tab-press is worse than one that's
# occasionally empty, e.g. when no project/list is active yet.
#
# Signature is `(ctx, args, incomplete)` (the `args` list is unused) rather
# than the newer click 8 `(ctx, param, incomplete)` -- this Typer version
# only supports the `autocompletion=` param and warns that `shell_complete=`
# is deprecated, so we follow what it actually wants.


def _complete_project_names(ctx: typer.Context, args, incomplete: str):
    from wa.schema import Registry

    try:
        registry = Registry.load()
    except Exception:
        return []
    return [name for name in registry.projects if name.startswith(incomplete)]


def _complete_active_project_vars(ctx: typer.Context, args, incomplete: str):
    from wa import projects

    try:
        project = projects.get_active_project()
    except Exception:
        return []
    return [name for name in project.vars if name.startswith(incomplete)]


def _complete_active_project_cmds(ctx: typer.Context, args, incomplete: str):
    from wa import projects

    try:
        project = projects.get_active_project()
    except Exception:
        return []
    return [name for name in project.cmds if name.startswith(incomplete)]


def _complete_tmux_windows(ctx: typer.Context, args, incomplete: str):
    from wa import projects

    try:
        project = projects.get_active_project()
    except Exception:
        return []
    return [w["name"] for w in project.tmux_windows or [] if w["name"].startswith(incomplete)]


def _complete_note_names(ctx: typer.Context, args, incomplete: str):
    from wa import notes, projects

    try:
        project = projects.get_active_project()
    except Exception:
        return []
    return [p.stem for p in notes.list_notes(project) if p.stem.startswith(incomplete)]


@app.command("help")
def show_help(ctx: typer.Context) -> None:
    """List available commands and descriptions."""
    typer.echo(ctx.parent.get_help())


def _complete_shell_names(ctx: typer.Context, args, incomplete: str):
    return [name for name in shell.SUPPORTED_SHELLS if name.startswith(incomplete)]


@app.command("shell-init")
def shell_init(
    shell_name: str = typer.Argument(
        ..., help="Target shell: bash or zsh", autocompletion=_complete_shell_names
    ),
) -> None:
    """Print the shell function wa needs for cd/export integration.

    Add this to your shell rc file:

        eval "$(wa shell-init bash)"
    """
    typer.echo(shell.generate_shell_init(shell_name))


@app.command()
def init() -> None:
    """Initialize wa's configuration and data directories (XDG paths)."""
    from rich.console import Console

    from wa import projects
    from wa.constants import CONFIG_DIR, DATA_DIR

    console = Console()
    first_time = projects.init_workspace()
    if first_time:
        console.print("[green]wa initialized.[/green]")
    else:
        _print_info(console, "wa is already initialized.")
    console.print(f"  config: {CONFIG_DIR}")
    console.print(f"  data:   {DATA_DIR}")


project_app = typer.Typer(help="Manage registered projects (add/remove/list).")
app.add_typer(project_app, name="prj")


@project_app.command("add")
def project_add(
    name: str = typer.Argument(..., help="Project name (unique identifier)."),
    dir: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Project root directory. Defaults to the current directory."
    ),
    git: Optional[str] = typer.Option(None, "--git", "-g", help="Git remote URL."),
    doc: Optional[str] = typer.Option(None, "--doc", help="Docs path or URL."),
    ssh: Optional[str] = typer.Option(None, "--ssh", help="SSH connection string."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip interactive prompts; use flags/defaults only."
    ),
) -> None:
    """Register a new project with wa."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    target_dir = dir or os.getcwd()

    if not yes:
        import questionary

        target_dir = questionary.path("Project directory:", default=target_dir).ask()
        if target_dir is None:
            raise typer.Exit(1)
        if git is None:
            detected = projects.detect_git_remote(os.path.abspath(target_dir))
            git = questionary.text("Git remote (optional):", default=detected or "").ask() or None
        if doc is None:
            doc = questionary.text("Docs path or URL (optional):", default="").ask() or None
        if ssh is None:
            ssh = questionary.text("SSH connection (optional):", default="").ask() or None

    try:
        project = projects.add_project(name, target_dir, git=git, doc=doc, ssh=ssh)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    from rich.markup import escape

    console.print(f"[green]Added project '{project.name}'[/green]")
    for key, value in project.vars.items():
        console.print(f"  {key} = {escape(value)}")


@project_app.command("remove")
def project_remove(
    name: str = typer.Argument(
        ..., help="Project name to remove.", autocompletion=_complete_project_names
    ),
    delete_files: bool = typer.Option(
        False, "--delete-files", "-f", help="Also permanently delete the project's directory."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
) -> None:
    """Remove a project from wa (optionally deleting its files)."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()

    if not yes:
        import questionary

        if not questionary.confirm(f"Remove project '{name}' from wa?", default=False).ask():
            raise typer.Exit(0)
        if delete_files:
            delete_files = bool(
                questionary.confirm(
                    "This will PERMANENTLY DELETE the project's directory. Are you sure?",
                    default=False,
                ).ask()
            )

    try:
        # Close first: the session's panes live in DIR, which --delete-files removes.
        _close_project(console, projects.get_project(name), yes)
        project = projects.remove_project(name, delete_files=delete_files)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    message = f"[green]Removed project '{project.name}'[/green]"
    if delete_files:
        message += " and deleted its files"
    console.print(message)


@project_app.command("list")
def project_list() -> None:
    """List all registered projects."""
    from rich.console import Console
    from rich.table import Table

    from wa import projects
    from wa.constants import ACTIVE_PROJ_DIR_ENV

    console = Console()
    all_projects = projects.list_projects()
    if not all_projects:
        _print_info(
            console, "No projects registered yet. Use 'wa prj add <name>' to create one."
        )
        return

    active_dir = os.environ.get(ACTIVE_PROJ_DIR_ENV)
    active_resolved = str(Path(active_dir).resolve()) if active_dir else None

    from rich.markup import escape

    table = Table(show_header=True)
    table.add_column("")
    table.add_column("Name")
    table.add_column("DIR")
    table.add_column("GIT")
    for project in sorted(all_projects, key=lambda p: p.name):
        marker = "●" if project.vars.get("DIR") == active_resolved else ""
        table.add_row(
            marker,
            project.name,
            escape(project.vars.get("DIR", "")),
            escape(project.vars.get("GIT", "")),
        )
    console.print(table)


@app.command("open")
def open_project(
    name: str = typer.Argument(
        ..., help="Project name to open.", autocompletion=_complete_project_names
    ),
    no_tmux: bool = typer.Option(
        False, "--no-tmux", help="Only cd/export in this shell; don't open the tmux session."
    ),
) -> None:
    """Open a project: its tmux session (created from its layout if needed), or,
    inside that session or with --no-tmux, just export its variables, set
    ACTIVE_PROJ_DIR, and cd into its directory."""
    from rich.console import Console

    from wa import projects, tmux
    from wa.errors import WaError

    from rich.markup import escape

    console = Console()
    try:
        project = projects.get_project(name)
        directory = project.vars.get("DIR")
        if not directory:
            raise WaError(f"Project '{name}' has no DIR set.")
        if not Path(directory).is_dir():
            raise WaError(
                f"Project '{name}' DIR does not exist or is not accessible "
                f"on this machine: {directory}"
            )
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    session = tmux.session_name(project.name)
    # Inside the project's own session this is the `wa open` typed into each
    # window at creation -- plain cd/export, or the windows would recurse.
    if no_tmux or tmux.current_session() == session or not _ensure_tmux_available(console):
        _emit_open(project, directory)
        console.print(f"[green]Opened '{name}'[/green] -> {escape(directory)}")
        return

    try:
        windows = projects.ensure_tmux_windows(project)
        created = tmux.ensure_session(session, directory, project.name, windows)
        if os.environ.get("TMUX"):
            tmux.switch_client(session)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    verb = "Created" if created else "Resumed"
    console.print(f"[green]{verb} tmux session '{session}'[/green] -> {escape(directory)}")
    if not os.environ.get("TMUX"):
        # Also open the project in this shell, so it's there after detaching.
        _emit_open(project, directory)
        tmux.attach(session)


def _emit_open(project, directory: str) -> None:
    for key, value in project.vars.items():
        shell.emit_export(key, value)
    shell.emit_export("ACTIVE_PROJ_DIR", directory)
    shell.emit_cd(directory)


def _stdin_is_interactive() -> bool:
    return sys.stdin.isatty()


def _ensure_tmux_available(console) -> bool:
    """True if tmux can be used, offering to install it first when it's missing.

    Never fails `wa open`: when tmux is unavailable (declined, no TTY to ask
    on, unknown package manager, failed install) it warns and returns False
    so the caller falls back to a plain cd/export.
    """
    import subprocess

    from wa import tmux

    if tmux.is_installed():
        return True

    command = tmux.install_command()
    fallback = "opening without a tmux session (use --no-tmux to skip this check)."
    if command is None:
        console.print(f"[yellow]tmux is not installed[/yellow] and no known package manager was found; {fallback}")
        return False
    command_text = " ".join(command)
    if not _stdin_is_interactive():
        console.print(f"[yellow]tmux is not installed[/yellow] (install it with '{command_text}'); {fallback}")
        return False

    import questionary

    if not questionary.confirm(
        f"tmux is not installed. Install it now with '{command_text}'?", default=False
    ).ask():
        console.print(f"[yellow]Skipped tmux install[/yellow]; {fallback}")
        return False

    result = subprocess.run(command)
    if result.returncode != 0 or not tmux.is_installed():
        console.print(f"[yellow]tmux install failed[/yellow] (exit code {result.returncode}); {fallback}")
        return False
    console.print("[green]tmux installed.[/green]")
    return True


@app.command("close")
def close_project(
    name: Optional[str] = typer.Argument(
        None,
        help="Project name to close. Defaults to the active project.",
        autocompletion=_complete_project_names,
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Kill the tmux session without asking."
    ),
) -> None:
    """Close a project: kill its tmux session and, if it's active in this shell, unset its variables."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_project(name) if name else projects.get_active_project()
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    if not _close_project(console, project, yes):
        _print_info(console, f"Project '{project.name}' isn't open; nothing to close.")


def _close_project(console, project, yes: bool) -> bool:
    """Undo `wa open`: unset the project's variables if it's active in this
    shell, and kill its tmux session if it's running (asking first, unless
    `yes` -- that kills whatever runs in it). Returns False if neither applied.

    Only unsets when *this* project is the active one: other projects share
    variable names (DIR, GIT, ...), so unsetting them would clobber the
    project this shell actually has open.
    """
    from wa import tmux
    from wa.constants import ACTIVE_PROJ_DIR_ENV
    from wa.errors import WaError

    active_dir = os.environ.get(ACTIVE_PROJ_DIR_ENV)
    is_active = bool(active_dir) and str(Path(active_dir).resolve()) == project.vars["DIR"]
    session = _running_session(project)
    if not is_active and not session:
        return False

    if session and not yes:
        import questionary

        if not questionary.confirm(
            f"Kill tmux session '{session}'? Anything running in it will be killed.",
            default=False,
        ).ask():
            _print_info(console, f"Left tmux session '{session}' running.")
            session = None

    if is_active:
        for key in project.vars:
            shell.emit_unset(key)
        shell.emit_unset(ACTIVE_PROJ_DIR_ENV)
        console.print(f"[green]Closed '{project.name}'[/green] in this shell (variables unset)")

    if session:
        console.print(f"[green]Killed tmux session '{session}'[/green]")
        # Last: when run from inside the session, this kills wa's own shell too.
        try:
            tmux.kill_session(session)
        except WaError as exc:
            _print_error(console, exc)
            raise typer.Exit(1)
    return True


@app.command()
def goto(
    var_name: Optional[str] = typer.Argument(
        None,
        help="Variable to jump to (e.g. DOC). Omit to go to the project root (DIR).",
        autocompletion=_complete_active_project_vars,
    ),
) -> None:
    """cd into the active project's root, or into a path stored in one of its variables."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        path = projects.resolve_goto_path(project, var_name)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    from rich.markup import escape

    shell.emit_cd(str(path))
    console.print(f"[green]Requested cd[/green] -> {escape(str(path))}")


@app.command()
def run(
    command_name: str = typer.Argument(
        ...,
        help="Name of a custom command saved with 'wa cmd add'.",
        autocompletion=_complete_active_project_cmds,
    ),
) -> None:
    """Run a custom command saved for the active project, streaming its output live."""
    import subprocess

    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        if command_name not in project.cmds:
            available = ", ".join(sorted(project.cmds)) or "(none)"
            raise WaError(
                f"No command '{command_name}' in project '{project.name}'. "
                f"Available: {available}"
            )
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    script = project.cmds[command_name]
    env = {**os.environ, **project.vars}
    result = subprocess.run(script, shell=True, cwd=project.vars.get("DIR"), env=env)
    raise typer.Exit(result.returncode)


cmd_app = typer.Typer(help="Manage custom commands (run via 'wa run <name>') on the active project.")
app.add_typer(cmd_app, name="cmd")


@cmd_app.command("add")
def cmd_add(
    name: str = typer.Argument(..., help="Command name."),
    script: str = typer.Argument(..., help="Shell command/script to run."),
) -> None:
    """Add or overwrite a custom command on the active project."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.add_command(name, script)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)
    console.print(f"[green]Saved command '{name}'[/green] on project '{project.name}'")


@cmd_app.command("edit")
def cmd_edit(
    name: str = typer.Argument(
        ..., help="Command name to edit.", autocompletion=_complete_active_project_cmds
    ),
) -> None:
    """Edit an existing command's script in $EDITOR (fails if it isn't set yet)."""
    from rich.console import Console

    from wa import notes, projects
    from wa.errors import WaError

    console = Console()
    try:
        current_script = projects.get_command_script(name)
        new_script = notes.edit_text_in_editor(current_script)
        project = projects.add_command(name, new_script)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    console.print(f"[green]Updated command '{name}'[/green] on project '{project.name}'")


@cmd_app.command("remove")
def cmd_remove(
    name: str = typer.Argument(
        ..., help="Command name to remove.", autocompletion=_complete_active_project_cmds
    ),
) -> None:
    """Remove a custom command from the active project."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.remove_command(name)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)
    console.print(f"[green]Removed command '{name}'[/green] from project '{project.name}'")


@cmd_app.command("list")
def cmd_list() -> None:
    """List custom commands registered on the active project."""
    from rich.console import Console
    from rich.table import Table

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    if not project.cmds:
        console.print(
            f"No custom commands on project '{project.name}'. Use 'wa cmd add <name> <script>'."
        )
        return

    from rich.markup import escape

    table = Table(show_header=True)
    table.add_column("Name")
    table.add_column("Script")
    for cmd_name, script in sorted(project.cmds.items()):
        table.add_row(cmd_name, escape(script))
    console.print(table)


var_app = typer.Typer(help="Manage environment variables on the active project.")
app.add_typer(var_app, name="var")


@var_app.command("add")
def var_add(
    name: str = typer.Argument(..., help="Variable name (env var identifier)."),
    value: str = typer.Argument(..., help="Variable value."),
) -> None:
    """Add or update an environment variable on the active project."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.add_var(name, value)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    from rich.markup import escape

    shell.emit_export(name, value)  # apply immediately if this shell has the project open
    console.print(f"[green]Set {name}={escape(value)}[/green] on project '{project.name}'")


@var_app.command("edit")
def var_edit(
    name: str = typer.Argument(
        ..., help="Variable name to edit.", autocompletion=_complete_active_project_vars
    ),
    value: Optional[str] = typer.Argument(
        None, help="New value. Omit to edit interactively, pre-filled with the current value."
    ),
) -> None:
    """Edit an existing environment variable's value (fails if it isn't set yet)."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.require_existing_var(name)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    if value is None:
        import questionary

        value = questionary.text(f"{name} =", default=project.vars[name]).ask()
        if value is None:
            raise typer.Exit(0)

    try:
        project = projects.add_var(name, value)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    from rich.markup import escape

    shell.emit_export(name, value)  # apply immediately if this shell has the project open
    console.print(f"[green]Updated {name}={escape(value)}[/green] on project '{project.name}'")


@var_app.command("remove")
def var_remove(
    name: str = typer.Argument(
        ..., help="Variable name to remove.", autocompletion=_complete_active_project_vars
    ),
) -> None:
    """Remove an environment variable from the active project."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.remove_var(name)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    shell.emit_unset(name)
    console.print(f"[green]Removed {name}[/green] from project '{project.name}'")


@var_app.command("list")
def var_list() -> None:
    """List environment variables set on the active project."""
    from rich.console import Console
    from rich.table import Table

    from wa import projects
    from wa.errors import WaError
    from wa.projects import IMMUTABLE_VARS

    console = Console()
    try:
        project = projects.get_active_project()
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    if not project.vars:
        _print_info(console, f"No variables set on project '{project.name}'.")
        return

    from rich.markup import escape

    table = Table(show_header=True)
    table.add_column("Name")
    table.add_column("Value")
    table.add_column("")
    for var_name, value in sorted(project.vars.items()):
        note = "(immutable)" if var_name in IMMUTABLE_VARS else ""
        table.add_row(var_name, escape(value), note)
    console.print(table)


tmux_app = typer.Typer(
    help="Manage the active project's tmux layout (the windows 'wa open' creates)."
)
app.add_typer(tmux_app, name="tmux")


def _running_session(project) -> Optional[str]:
    """The project's tmux session name if it's running right now, else None."""
    from wa import tmux

    if not tmux.is_installed():
        return None
    session = tmux.session_name(project.name)
    return session if tmux.has_session(session) else None


@tmux_app.command("add")
def tmux_add(
    name: str = typer.Argument(..., help="Window name."),
    command: str = typer.Argument(
        "", help="Command to run in the window after 'wa open'. Omit for a plain shell."
    ),
    at: Optional[int] = typer.Option(
        None, "--at", help="0-based position in the layout. Defaults to the end."
    ),
) -> None:
    """Add a window to the layout (and to the project's session, if it's running)."""
    from rich.console import Console

    from wa import projects, tmux
    from wa.errors import WaError

    console = Console()
    try:
        project, index = projects.add_tmux_window(name, command, at)
        session = _running_session(project)
        if session:
            following = [w["name"] for w in project.tmux_windows[index + 1:]]
            tmux.insert_window(
                session, project.vars["DIR"], project.name, project.tmux_windows[index], following
            )
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    from rich.markup import escape

    message = f"[green]Added tmux window '{escape(name)}'[/green] at position {index} on project '{project.name}'"
    if session:
        message += f" and opened it in session '{session}'"
    console.print(message)


@tmux_app.command("remove")
def tmux_remove(
    name: str = typer.Argument(
        ..., help="Window name to remove.", autocompletion=_complete_tmux_windows
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Close the window in the running session without asking."
    ),
) -> None:
    """Remove a window from the layout (and close it in the running session)."""
    from rich.console import Console
    from rich.markup import escape

    from wa import projects, tmux
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.remove_tmux_window(name)
        session = _running_session(project)
        window_id = tmux.find_window(session, name) if session else None
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    console.print(f"[green]Removed tmux window '{escape(name)}'[/green] from project '{project.name}'")
    if not window_id:
        return

    if not yes:
        import questionary

        if not questionary.confirm(
            f"Window '{name}' is open in session '{session}'. Close it now? "
            "Anything running in it will be killed.",
            default=False,
        ).ask():
            _print_info(console, f"Left window '{escape(name)}' open; it won't be created next time.")
            return

    try:
        tmux.kill_window(window_id)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)
    console.print(f"Closed it in session '{session}'.")


@tmux_app.command("edit")
def tmux_edit(
    name: str = typer.Argument(
        ..., help="Window name to edit.", autocompletion=_complete_tmux_windows
    ),
    command: Optional[str] = typer.Argument(
        None, help="New command ('' for a plain shell). Omit to edit interactively."
    ),
) -> None:
    """Change a window's startup command (takes effect next time the session is created)."""
    from rich.console import Console
    from rich.markup import escape

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        if command is None:
            import questionary

            command = questionary.text(
                f"{name} command:", default=projects.get_tmux_window_cmd(name)
            ).ask()
            if command is None:
                raise typer.Exit(0)
        project = projects.edit_tmux_window(name, command)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    console.print(
        f"[green]Updated tmux window '{escape(name)}'[/green] on project '{project.name}'"
    )


@tmux_app.command("list")
def tmux_list() -> None:
    """List the windows 'wa open' creates for the active project, in order."""
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        windows = projects.ensure_tmux_windows(project)
        session = _running_session(project)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    table = Table(show_header=True)
    table.add_column("#")
    table.add_column("Window")
    table.add_column("Command")
    for index, window in enumerate(windows):
        table.add_row(str(index), escape(window["name"]), escape(window["cmd"]) or "[dim](shell)[/dim]")
    console.print(table)
    if session:
        _print_info(console, f"Session '{session}' is running.")


notes_app = typer.Typer(help="Manage markdown notes on the active project.")
app.add_typer(notes_app, name="notes")


@notes_app.command("edit")
def notes_edit(
    name: Optional[str] = typer.Argument(
        None,
        help="Note name (without .md). Defaults to 'note-DD-MM-YYYY' (today) if omitted.",
        autocompletion=_complete_note_names,
    ),
) -> None:
    """Open a note in $EDITOR, creating it first if it doesn't exist yet."""
    from rich.console import Console

    from wa import notes, projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        path = notes.resolve_note_path(project, name or notes.default_note_name())
        notes.open_in_editor(path)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)


@notes_app.command("list")
def notes_list() -> None:
    """List the active project's notes."""
    from datetime import datetime

    from rich.console import Console
    from rich.table import Table

    from wa import notes, projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    paths = notes.list_notes(project)
    if not paths:
        _print_info(console, f"No notes on project '{project.name}'. Use 'wa notes edit <name>'.")
        return

    table = Table(show_header=True)
    table.add_column("Name")
    table.add_column("Modified")
    for path in paths:
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        table.add_row(path.stem, modified)
    console.print(table)


@notes_app.command("remove")
def notes_remove(
    name: str = typer.Argument(
        ..., help="Note name to delete.", autocompletion=_complete_note_names
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a note file."""
    from rich.console import Console

    from wa import notes, projects
    from wa.errors import WaError

    console = Console()
    if not yes:
        import questionary

        if not questionary.confirm(f"Delete note '{name}'?", default=False).ask():
            raise typer.Exit(0)

    try:
        project = projects.get_active_project()
        notes.remove_note(project, name)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)
    console.print(f"[green]Removed note '{name}'[/green]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
