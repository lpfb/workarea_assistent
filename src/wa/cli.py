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
)


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
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[green]Added project '{project.name}'[/green]")
    for key, value in project.vars.items():
        console.print(f"  {key} = {value}")


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
        console.print(f"[red]Error:[/red] {exc}")
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

    table = Table(show_header=True)
    table.add_column("")
    table.add_column("Name")
    table.add_column("DIR")
    table.add_column("GIT")
    for name, project in sorted(registry.projects.items()):
        marker = "●" if project.vars.get("DIR") == active_resolved else ""
        table.add_row(marker, name, project.vars.get("DIR", ""), project.vars.get("GIT", ""))
    console.print(table)


@app.command("open")
def open_project(name: str = typer.Argument(..., help="Project name to open.")) -> None:
    """Export a project's variables, set ACTIVE_PROJ_DIR, and cd into its directory."""
    from rich.console import Console

    from wa import projects
    from wa.errors import WaError

    console = Console()
    try:
        project = projects.get_project(name)
    except WaError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    directory = project.vars.get("DIR")
    if not directory or not Path(directory).is_dir():
        console.print(f"[red]Error:[/red] Project '{name}' has no valid DIR to open.")
        raise typer.Exit(1)

    for key, value in project.vars.items():
        shell.emit_export(key, value)
    shell.emit_export("ACTIVE_PROJ_DIR", directory)
    shell.emit_cd(directory)

    console.print(f"[green]Opened '{name}'[/green] -> {directory}")


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
        console.print(f"[red]Error:[/red] {exc}")
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
        console.print(f"[red]Error:[/red] {exc}")
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
        console.print(f"[red]Error:[/red] {exc}")
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
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not project.cmds:
        console.print(
            f"No custom commands on project '{project.name}'. Use 'wa cmd add <name> <script>'."
        )
        return

    table = Table(show_header=True)
    table.add_column("Name")
    table.add_column("Script")
    for cmd_name, script in sorted(project.cmds.items()):
        table.add_row(cmd_name, script)
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
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    shell.emit_export(name, value)  # apply immediately if this shell has the project open
    console.print(f"[green]Set {name}={value}[/green] on project '{project.name}'")


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
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    shell.emit(f"unset {name}")
    console.print(f"[green]Removed {name}[/green] from project '{project.name}'")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
