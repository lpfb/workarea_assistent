"""wa command line entry point.

Only rich/questionary-heavy imports (and the projects/errors domain modules)
are deferred into command bodies -- the top-level module stays cheap so
`wa --help` and completion stay instant.
"""
import os
from pathlib import Path
from typing import Optional

import typer

from wa import shell

app = typer.Typer(
    help="Workflow Assistant: manage project workspaces, env vars, scripts, notes and tasks.",
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


@app.command("help")
def show_help(ctx: typer.Context) -> None:
    """List available commands and descriptions."""
    typer.echo(ctx.parent.get_help())


@app.command("shell-init")
def shell_init(
    shell_name: str = typer.Argument(..., help="Target shell: bash or zsh"),
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
        console.print("wa is already initialized.")
    console.print(f"  config: {CONFIG_DIR}")
    console.print(f"  data:   {DATA_DIR}")


@app.command()
def add(
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


@app.command()
def remove(
    name: str = typer.Argument(..., help="Project name to remove."),
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
        project = projects.remove_project(name, delete_files=delete_files)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    message = f"[green]Removed project '{project.name}'[/green]"
    if delete_files:
        message += " and deleted its files"
    console.print(message)


project_app = typer.Typer(help="Manage registered projects.")
app.add_typer(project_app, name="project")


@project_app.command("list")
def project_list() -> None:
    """List all registered projects."""
    from rich.console import Console
    from rich.table import Table

    from wa.constants import ACTIVE_PROJ_DIR_ENV
    from wa.schema import Registry

    console = Console()
    registry = Registry.load()
    if not registry.projects:
        console.print("No projects registered yet. Use 'wa add <name>' to create one.")
        return

    active_dir = os.environ.get(ACTIVE_PROJ_DIR_ENV)
    active_resolved = str(Path(active_dir).resolve()) if active_dir else None

    from rich.markup import escape

    table = Table(show_header=True)
    table.add_column("")
    table.add_column("Name")
    table.add_column("DIR")
    table.add_column("GIT")
    for name, project in sorted(registry.projects.items()):
        marker = "●" if project.vars.get("DIR") == active_resolved else ""
        table.add_row(
            marker, name, escape(project.vars.get("DIR", "")), escape(project.vars.get("GIT", ""))
        )
    console.print(table)


@app.command("open")
def open_project(name: str = typer.Argument(..., help="Project name to open.")) -> None:
    """Export a project's variables, set ACTIVE_PROJ_DIR, and cd into its directory."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    from rich.markup import escape

    console = Console()
    try:
        project = projects.get_project(name)
        directory = project.vars.get("DIR")
        if not directory or not Path(directory).is_dir():
            raise WaError(f"Project '{name}' has no valid DIR to open.")
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    for key, value in project.vars.items():
        shell.emit_export(key, value)
    shell.emit_export("ACTIVE_PROJ_DIR", directory)
    shell.emit_cd(directory)

    console.print(f"[green]Opened '{name}'[/green] -> {escape(directory)}")


@app.command()
def goto(
    var_name: Optional[str] = typer.Argument(
        None,
        help="Variable to jump to (e.g. DOC). Omit to go to the project root (DIR).",
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
        ..., help="Name of a custom command saved with 'wa cmd add'."
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


@cmd_app.command("remove")
def cmd_remove(name: str = typer.Argument(..., help="Command name to remove.")) -> None:
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


@var_app.command("remove")
def var_remove(name: str = typer.Argument(..., help="Variable name to remove.")) -> None:
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

    shell.emit(f"unset {name}")
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
        console.print(f"No variables set on project '{project.name}'.")
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


notes_app = typer.Typer(help="Manage markdown notes on the active project.")
app.add_typer(notes_app, name="notes")


@notes_app.command("edit")
def notes_edit(
    name: Optional[str] = typer.Argument(
        None,
        help="Note name (without .md). Defaults to 'note-DD-MM-YYYY' (today) if omitted.",
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
        console.print(f"No notes on project '{project.name}'. Use 'wa notes edit <name>'.")
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
    name: str = typer.Argument(..., help="Note name to delete."),
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


todo_app = typer.Typer(help="Manage the active project's todo lists.")
app.add_typer(todo_app, name="todo")


def _print_todo_items(console, items) -> None:
    from rich.markup import escape

    if not items:
        console.print("(empty)")
        return
    for i, item in enumerate(items, start=1):
        text = escape(item.text)
        if item.checked:
            console.print(f"{i}. [green]{escape('[x]')}[/green] [strike]{text}[/strike]")
        else:
            console.print(f"{i}. {escape('[ ]')} {text}")


@todo_app.command("add")
def todo_add(
    text_or_name: Optional[str] = typer.Argument(
        None,
        help=(
            "No list open (see 'wa todo open'): name of a new list to create "
            "(defaults to todo-DD-MM-YYYY). List open: task text to add to it."
        ),
    ),
) -> None:
    """Create a new todo list, or add a task to the currently open one."""
    from rich.console import Console

    from wa import notes, projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        active_list = notes.get_active_todo_list()

        if active_list is None:
            list_name = text_or_name or notes.default_todo_name()
            notes.create_todo_list(project, list_name)
        else:
            if not text_or_name:
                raise WaError('Task text is required, e.g. \'wa todo add "fix bug"\'.')
            notes.add_todo(project, active_list, text_or_name)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    from rich.markup import escape

    if active_list is None:
        console.print(
            f"[green]Created todo list '{escape(list_name)}'[/green]. "
            f"Use 'wa todo open {list_name}' to open it."
        )
    else:
        console.print(f"[green]Added[/green] to '{active_list}': {escape(text_or_name)}")


@todo_app.command("list")
def todo_list() -> None:
    """List all todo lists on the active project."""
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

    paths = notes.list_todo_lists(project)
    if not paths:
        console.print(f"No todo lists on project '{project.name}'. Use 'wa todo add [name]'.")
        return

    active_list = notes.get_active_todo_list()
    table = Table(show_header=True)
    table.add_column("")
    table.add_column("Name")
    for path in paths:
        marker = "●" if path.stem == active_list else ""
        table.add_row(marker, path.stem)
    console.print(table)


@todo_app.command("open")
def todo_open(
    name: str = typer.Argument(..., help="Todo list name to open (see 'wa todo list')."),
) -> None:
    """Select a todo list for this shell session and show its content."""
    from rich.console import Console
    from rich.markup import escape

    from wa import notes, projects
    from wa.constants import ACTIVE_TODO_LIST_ENV
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        path = notes.resolve_todo_list_path(project, name)
        if not path.is_file():
            raise WaError(f"Todo list '{name}' not found. Use 'wa todo add {name}' to create it.")
        items = notes.parse_todo(project, name)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    shell.emit_export(ACTIVE_TODO_LIST_ENV, name)

    console.print(f"[green]Opened todo list '{escape(name)}'[/green]")
    _print_todo_items(console, items)


@todo_app.command("close")
def todo_close() -> None:
    """Close the currently open todo list in this shell session."""
    from rich.console import Console

    from wa import notes
    from wa.constants import ACTIVE_TODO_LIST_ENV
    from wa.errors import WaError

    console = Console()
    active_list = notes.get_active_todo_list()
    if active_list is None:
        _print_error(console, WaError("No todo list open."))
        raise typer.Exit(1)

    shell.emit(f"unset {ACTIVE_TODO_LIST_ENV}")
    console.print(f"[green]Closed todo list '{active_list}'[/green]")


@todo_app.command("show")
def todo_show() -> None:
    """Show the content of the currently open todo list."""
    from rich.console import Console

    from wa import notes, projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        active_list = notes.get_active_todo_list()
        if active_list is None:
            raise WaError("No todo list open. Run 'wa todo open <name>' first.")
        items = notes.parse_todo(project, active_list)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    console.print(f"[green]{active_list}[/green]")
    _print_todo_items(console, items)


@todo_app.command("toggle")
def todo_toggle(
    position: int = typer.Argument(..., help="Task number (see 'wa todo open <name>')."),
) -> None:
    """Toggle a task's checked state in the currently open todo list."""
    from rich.console import Console
    from rich.markup import escape

    from wa import notes, projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        active_list = notes.get_active_todo_list()
        if active_list is None:
            raise WaError("No todo list open. Run 'wa todo open <name>' first.")
        item = notes.toggle_todo(project, active_list, position)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    marker = escape("[x]") if item.checked else escape("[ ]")
    console.print(f"[green]{marker}[/green] {escape(item.text)}")


@todo_app.command("remove")
def todo_remove(
    position: int = typer.Argument(..., help="Task number (see 'wa todo open <name>')."),
) -> None:
    """Delete a task from the currently open todo list."""
    from rich.console import Console
    from rich.markup import escape

    from wa import notes, projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_active_project()
        active_list = notes.get_active_todo_list()
        if active_list is None:
            raise WaError("No todo list open. Run 'wa todo open <name>' first.")
        item = notes.remove_todo(project, active_list, position)
    except WaError as exc:
        _print_error(console, exc)
        raise typer.Exit(1)

    console.print(f"[green]Removed[/green]: {escape(item.text)}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
