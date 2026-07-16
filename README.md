# wa — Workflow Assistant CLI

`wa` is a command-line tool for developers who juggle multiple projects in
the terminal. It centralizes project workspaces, environment variables,
custom scripts, notes, and todo lists — all addressable by project name
instead of remembered paths and one-off shell aliases.

```
~/anywhere ❯ wa open blogapi
Opened 'blogapi' -> /home/user/projects/blog-api
~/projects/blog-api ❯ wa run build
~/projects/blog-api ❯ wa todo add "fix the flaky auth test"
```

## Features

- **Project registry** — register any directory as a named project (`wa add`),
  then jump into it from anywhere with `wa open <name>`.
- **Real `cd` from a subprocess** — `wa open`/`wa goto` actually change your
  shell's working directory, via a small shell-function wrapper installed
  once during setup (see [How it works](#how-it-works)).
- **Per-project environment variables** — attach arbitrary vars (`DOC`,
  `SSH`, or anything else) to a project; `wa open` exports them into your
  shell automatically.
- **Custom commands** — save a shell command against a project (`wa cmd add`)
  and run it with `wa run <name>`, with live streamed output and exit code
  propagation.
- **Notes and todo lists** — per-project markdown notes (opened in `$EDITOR`)
  and lightweight, session-scoped todo lists, stored alongside the project
  itself so they travel with its git history.
- **Tab completion** — project names, variable names, command names, note
  names, and todo list names all complete dynamically, not just the static
  command structure.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

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
| `wa add <name> [--dir DIR] [--git URL] [--doc PATH] [--ssh STR] [--yes]` | Register a new project. Prompts interactively unless `--yes` is passed. |
| `wa remove <name> [--delete-files] [--yes]` | Unregister a project, optionally deleting its directory too. |
| `wa project list` | List all registered projects, marking the active one. |
| `wa open <name>` | Export the project's variables, set `ACTIVE_PROJ_DIR`, and `cd` into it. |
| `wa goto [var]` | `cd` into the active project's root (`DIR`), or into the path stored in a given variable (e.g. `wa goto DOC`). |

### Environment variables

| Command | Description |
|---|---|
| `wa var add <name> <value>` | Add or update a variable on the active project; applied to the current shell immediately. |
| `wa var remove <name>` | Remove a variable from the active project. |
| `wa var list` | List the active project's variables (`DIR` is always immutable). |

### Custom commands

| Command | Description |
|---|---|
| `wa cmd add <name> <script>` | Save a shell command/script on the active project. |
| `wa cmd remove <name>` | Remove a saved command. |
| `wa cmd list` | List commands saved on the active project. |
| `wa run <name>` | Run a saved command, streaming output live; `wa`'s exit code matches the command's. |

### Notes

| Command | Description |
|---|---|
| `wa notes edit [name]` | Open a markdown note in `$EDITOR`, creating it if needed. Defaults to `note-DD-MM-YYYY` (today) if `name` is omitted. |
| `wa notes list` | List the active project's notes. |
| `wa notes remove <name> [--yes]` | Delete a note. |

### Todo lists

Todo lists are named and scoped to a project; one list can be "open" per
shell session (`wa todo open`), after which `add`/`toggle`/`remove`/`show`
act on it without repeating the name.

| Command | Description |
|---|---|
| `wa todo add [name-or-text]` | No list open: create a new list (defaults to `todo-DD-MM-YYYY`). List open: add a task. |
| `wa todo open <name>` | Open a list for this shell session and show its tasks. |
| `wa todo close` | Close the currently open list in this shell session. |
| `wa todo show` | Show the currently open list's tasks. |
| `wa todo toggle <n>` | Toggle a task's checked state. |
| `wa todo remove <n>` | Delete a task. |
| `wa todo list` | List all todo lists on the active project, marking the open one. |

### Misc

| Command | Description |
|---|---|
| `wa help` | Alias for `wa --help`. |
| `wa shell-init <bash\|zsh>` | Print the shell function used for the rc-file integration above. |

## How it works

A subprocess can't change its parent shell's working directory or export
variables into it directly. `wa shell-init` prints a small shell function
(`wa() { ... }`) that shadows the `wa` binary: it runs the real command,
then reads any `cd`/`export`/`unset` lines the command wrote to a temporary
side-channel file (`$WA_SHELL_PIPE`) and `eval`s them in the current shell.
This is how `wa open` and `wa goto` are able to actually move you between
directories.

"Active project" (`ACTIVE_PROJ_DIR`) and "active todo list"
(`ACTIVE_TODO_LIST`) are both per-shell-session environment variables, never
persisted to disk — two terminals can have different projects or todo lists
open at the same time without conflict.

Data is stored following the XDG Base Directory spec: configuration in
`~/.config/wa/`, and the project registry in `~/.local/share/wa/`. Notes and
todo lists live inside each project's own directory (`<DIR>/notes/`), so
they're versioned alongside the project's code.

## Development

```bash
pip install -e ".[dev]"
pytest
```

See `CHANGELOG.md` for the full history of what has landed.
