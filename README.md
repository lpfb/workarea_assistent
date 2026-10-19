# wa — Workflow Assistant CLI

`wa` is a command-line tool for developers who juggle multiple projects in
the terminal. It centralizes project workspaces, environment variables,
custom scripts, and notes — all addressable by project name instead of
remembered paths and one-off shell aliases.

```
~/anywhere ❯ wa open blogapi
Opened 'blogapi' -> /home/user/projects/blog-api
~/projects/blog-api ❯ wa run build
~/projects/blog-api ❯ wa notes edit
```

## Features

- **Project registry** — register any directory as a named project
  (`wa prj add`), then jump into it from anywhere with `wa open <name>`.
- **Real `cd` from a subprocess** — `wa open`/`wa goto` actually change your
  shell's working directory, via a small shell-function wrapper installed
  once during setup (see [How it works](#how-it-works)).
- **Per-project environment variables** — attach arbitrary vars (`DOC`,
  `SSH`, or anything else) to a project; `wa open` exports them into your
  shell automatically.
- **Custom commands** — save a shell command against a project (`wa cmd add`)
  and run it with `wa run <name>`, with live streamed output and exit code
  propagation.
- **tmux sessions** — `wa open` drops you into a per-project tmux session
  with your usual windows (`git`, `edit`, `deploy` by default), each one
  already inside the project with its variables exported, optionally
  running a startup command. Customize it per project with `wa tmux`.
- **Notes** — per-project markdown notes (opened in `$EDITOR`), stored
  alongside the project itself so they travel with its git history.
- **Tab completion** — project names, variable names, command names, and
  note names all complete dynamically, not just the static command
  structure.

## Installation

### Recommended: pipx

[pipx](https://pipx.pypa.io/) installs `wa` into its own isolated virtual
environment while still putting the `wa` command on your `PATH`, so it's
available in every shell without manually activating anything.

```bash
# install pipx first if you don't have it
python3 -m pip install --user pipx
pipx ensurepath

# from the project directory
pipx install .
```

To pick up code changes without reinstalling (useful if you're tracking a
local clone), use an editable install instead:

```bash
pipx install -e .
```

### Alternative: pip + virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

With this method `wa` is only on your `PATH` while the virtualenv is
activated, so you'd need to `source .venv/bin/activate` (or add
`.venv/bin` to `PATH`) in every new shell before using it.

### Shell integration

Then wire up shell integration by adding this to your `~/.bashrc` or
`~/.zshrc`:

```bash
command -v wa >/dev/null 2>&1 && eval "$(wa shell-init bash)"   # or zsh
```

Restart your shell (or `source` the rc file), then run `wa init` once to
create wa's config/data directories.

To enable tab completion:

```bash
wa --install-completion bash   # or zsh
```

## Command reference

### Projects

| Command | Description |
|---|---|
| `wa init` | Create wa's XDG config/data directories. |
| `wa prj add <name> [--dir DIR] [--git URL] [--doc PATH] [--ssh STR] [--yes]` | Register a new project. Prompts interactively unless `--yes` is passed. |
| `wa prj remove <name> [--delete-files] [--yes]` | Unregister a project, optionally deleting its directory too. Closes it first, like `wa close`. |
| `wa prj list` | List all registered projects, marking the active one. |
| `wa open <name> [--no-tmux]` | Open the project's tmux session (see [tmux sessions](#tmux-sessions)). Inside that session, or with `--no-tmux`: export the project's variables, set `ACTIVE_PROJ_DIR`, and `cd` into it. |
| `wa close [name] [--yes]` | Undo `wa open`: kill the project's tmux session (asks first; `--yes` skips) and, if it's the active project in this shell, unset its variables and `ACTIVE_PROJ_DIR`. Defaults to the active project. |
| `wa goto [var]` | `cd` into the active project's root (`DIR`), or into the path stored in a given variable (e.g. `wa goto DOC`). |

`open`/`close`/`goto`/`run` stay top-level (no `prj`/`cmd` prefix) because they're
the commands run most often, day to day; `add`/`remove`/`list` are setup-time
CRUD and live under their resource's namespace (`prj`, kept short since it's
typed often), same as `var`/`cmd`/`notes`.

### Environment variables

| Command | Description |
|---|---|
| `wa var add <name> <value>` | Add or update a variable on the active project; applied to the current shell immediately. |
| `wa var edit <name> [value]` | Edit an existing variable's value (fails if not set yet). Omit `value` for an interactive prompt pre-filled with the current value. |
| `wa var remove <name>` | Remove a variable from the active project. |
| `wa var list` | List the active project's variables (`DIR` is always immutable). |

### Custom commands

| Command | Description |
|---|---|
| `wa cmd add <name> <script>` | Save a shell command/script on the active project. |
| `wa cmd edit <name>` | Edit an existing command's script in `$EDITOR` (fails if not set yet). Handy for multi-line scripts. |
| `wa cmd remove <name>` | Remove a saved command. |
| `wa cmd list` | List commands saved on the active project. |
| `wa run <name>` | Run a saved command, streaming output live; `wa`'s exit code matches the command's. |

### tmux sessions

| Command | Description |
|---|---|
| `wa tmux add <name> [command] [--at N]` | Add a window to the active project's layout, at 0-based position `N` (default: the end). Without a command it's a plain shell. Also opens it in the running session. |
| `wa tmux remove <name> [--yes]` | Remove a window from the layout; if it's open in the running session, asks before closing it (`--yes` skips the question). |
| `wa tmux edit <name> [command]` | Change a window's startup command (`''` for a plain shell). Omit `command` for an interactive prompt pre-filled with the current one. Applies the next time the session is created. |
| `wa tmux list` | Show the layout, in order. |

Each project has one tmux session, named after it. `wa open <name>`:

- **outside tmux** — creates the session from the project's layout (or
  resumes it if it's already running) and attaches to it. Each window
  starts in `DIR` with `wa open <name> && <command>` typed into it, so the
  project's variables are exported there too. After you detach, the shell
  you came from is in the project as well.
- **inside another tmux session** — same, but switches to it instead of
  nesting sessions.
- **inside the project's own session** — just the plain `cd`/export.

The layout is stored per project in `<DIR>/.wa/data.json`. New projects
start with a copy of the defaults in `~/.config/wa/config.json` (created by
`wa init`), so editing the defaults only affects projects added afterwards:

```json
{
  "tmux": {
    "default_windows": [
      {"name": "git", "cmd": ""},
      {"name": "edit", "cmd": ""},
      {"name": "deploy", "cmd": ""}
    ]
  }
}
```

If tmux isn't installed, `wa open` offers to install it with your package
manager (showing the exact command first); if you decline — or there's no
terminal to ask on — it just does the plain `cd`/export.

### Notes

| Command | Description |
|---|---|
| `wa notes edit [name]` | Open a markdown note in `$EDITOR`, creating it if needed. Defaults to `note-DD-MM-YYYY` (today) if `name` is omitted. |
| `wa notes list` | List the active project's notes. |
| `wa notes remove <name> [--yes]` | Delete a note. |

### Misc

| Command | Description |
|---|---|
| `wa help` | Alias for `wa --help`. |
| `wa --version` | Print the installed version. |
| `wa shell-init <bash\|zsh>` | Print the shell function used for the rc-file integration above. |

## How it works

A subprocess can't change its parent shell's working directory or export
variables into it directly. `wa shell-init` prints a small shell function
(`wa() { ... }`) that shadows the `wa` binary: it runs the real command,
then reads any `cd`/`export`/`unset` lines the command wrote to a temporary
side-channel file (`$WA_SHELL_PIPE`) and `eval`s them in the current shell.
This is how `wa open` and `wa goto` are able to actually move you between
directories.

"Active project" (`ACTIVE_PROJ_DIR`) is a per-shell-session environment
variable, never persisted to disk — two terminals can have different
projects open at the same time without conflict.

Data is split across two layers. A central registry, following the XDG
Base Directory spec (configuration in `~/.config/wa/`, registry in
`~/.local/share/wa/`), holds only each project's name and directory --
enough to resolve `wa open <name>` before anything else is known. Its
variables, custom commands, and notes all live *inside* the project's own
directory instead (`<DIR>/.wa/data.json` -- vars, cmds and the tmux
layout -- and `<DIR>/notes/`), so they
travel with the project itself when it's moved, cloned, or copied,
independent of which machine or `$HOME` registered it. `<DIR>/.wa/` is
machine-local by default: `wa` drops a self-contained `.wa/.gitignore`
(`*`) the first time it writes there, so it's excluded from git even if
you never add it to the project's own `.gitignore`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

See `CHANGELOG.md` for the full history of what has landed.

### Releasing

Versions follow [SemVer](https://semver.org/) and come from git tags --
there's no version number to edit in `pyproject.toml`:

1. Move the `[Unreleased]` entries in `CHANGELOG.md` under a new
   `## [X.Y.Z] - YYYY-MM-DD` heading and commit.
2. `git tag -a vX.Y.Z -m "wa X.Y.Z"` and `git push origin main vX.Y.Z`.
3. Reinstall (`pip install -e .` / `pipx install --force .`) so
   `wa --version` reports the new tag -- installs read the version once,
   at install time.
