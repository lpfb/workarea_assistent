# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added (Etapa 1 — Arquitetura e Estrutura de Dados)
- Project skeleton and packaging (`pyproject.toml`, `src/wa` layout, entry point `wa`).
- XDG-compliant path resolution: config in `~/.config/wa/`, data in `~/.local/share/wa/`.
- JSON registry schema (`Project`, `Registry`) with atomic load/save.
- Shell integration technique: `wa shell-init <bash|zsh>` prints a shell function that
  wires up a side-channel temp file (`WA_SHELL_PIPE`) so `cd`/`export` can propagate
  to the parent shell, without disturbing normal stdout/stderr.

### Added (Etapa 2 — Core Engine e CLI)
- `wa init`: idempotently creates the XDG config/data directories and the registry file.
- `wa add <name>`: registers a project (`DIR`/`GIT`/`DOC`/`SSH`), validates the name and
  that `DIR` exists, auto-detects the git remote when possible, scaffolds `<DIR>/notes/`.
  Interactive prompts (questionary) by default, or fully flag-driven with `--yes`.
- `wa remove <name>`: removes a project from the registry, with an opt-in
  `--delete-files` that permanently deletes its directory (guarded against deleting
  `$HOME`, `/`, or other suspiciously shallow paths).
- `wa help`: explicit alias for the root `--help` output.
- New `wa/projects.py` (domain logic, no CLI/rich coupling) and `wa/errors.py`
  (`WaError` for user-facing failures).

### Added (Etapa 3 — Sistema de Variáveis e Comandos Customizados)
- `wa open <name>`: exports the project's vars, sets `ACTIVE_PROJ_DIR`, and `cd`s into
  its directory (via the Etapa 1 shell wrapper).
- `wa run <name>`: runs a custom command saved on the active project, output streamed
  live (not buffered), process exit code propagated as `wa`'s own exit code.
- `wa cmd add/remove <name> [script]`: manage custom commands on the active project.
- `wa var add/remove <name> [value]`: manage extra environment variables on the active
  project; `DIR` is immutable. Changes apply immediately to the current shell session
  (`export`/`unset`) in addition to being persisted.
- `wa/projects.py`: `get_project`, `get_active_project` (resolves the active project
  from `ACTIVE_PROJ_DIR`, per shell session).

### Changed
- **Architecture fix**: removed the global `active_project` field from the registry
  schema (Etapa 1). "Active project" is a per-shell-session concept — two terminals
  can have different projects open at once — so it is tracked exclusively via the
  `ACTIVE_PROJ_DIR` env var, never persisted to `projects.json`. Verified two
  concurrent shells can each have a different active project without conflict.
- Removed the Etapa 1 `_poc_cd` hidden proof-of-concept command, superseded by the
  real `wa open`.

### Added (fora do roadmap sequencial, a pedido)
- `wa project list`: lists all registered projects (name, DIR, GIT), marking the one
  matching this shell's `ACTIVE_PROJ_DIR` with `●`.
- `wa cmd list`: lists the custom commands saved on the active project.
- `wa goto [var]`: cd's into the active project's root (`DIR`) with no argument, or
  into the path stored in a given variable (e.g. `wa goto DOC`); rejects variables
  that aren't an existing directory (e.g. `GIT`).
- `wa var list`: lists the active project's variables, flagging `DIR` as immutable.
  `wa/projects.IMMUTABLE_VARS` made public (was `_IMMUTABLE_VARS`) since the CLI
  layer now needs to read it too.

### Added (Etapa 4 — Motor de Gestão de Notas e Tarefas)
- New `wa/notes.py`: domain logic for notes and the todo checklist, both stored
  inside `<DIR>/notes/` (travels with the project's own git history).
- `wa notes edit [name]`: opens `<DIR>/notes/<name>.md` in `$EDITOR`, creating the
  file first if needed. Falls back to `nano`/`vi`/`vim` (via `shutil.which`) when
  `$EDITOR` is unset. If `name` is omitted, defaults to `note-DD-MM-YYYY` (today's
  date) instead of a fixed generic name, so repeated `wa notes edit` calls the same
  day land in the same daily note.
- `wa notes list` / `wa notes remove <name>`: list and delete note files. Note names
  are restricted to a safe filename pattern, which also blocks path traversal
  (e.g. `wa notes edit ../../etc/passwd` is rejected).
- All todo commands require an active project (`get_active_project`), same context
  rule as `run`/`cmd`/`var`.

### Changed — redesigned `wa todo` around named lists + an "open" list (twice, as the UX evolved)
- Todo lists now live under `<DIR>/notes/todo/<name>.md`, a subfolder kept separate
  from `wa notes` so the two features never need filename heuristics to tell each
  other's files apart.
- `wa todo add [name-or-text]` is now contextual, matching how the rest of the app
  works (`wa open <project>` sets context that later commands act on):
  - **No todo list open in this shell**: the argument is a list name to create
    (`wa todo add sprint42`), or if omitted, defaults to `todo-DD-MM-YYYY` (today).
    Only creates the (empty) list -- it does not open it.
  - **A todo list is open** (via `wa todo open`): the argument is task text, added
    to that list (`wa todo add "fix bug"`).
- `wa todo open <name>`: selects a list for the shell session (`ACTIVE_TODO_LIST`
  env var, same per-session pattern as `ACTIVE_PROJ_DIR`/`wa open`) and prints its
  current tasks.
- `wa todo list`: now lists the todo list *files* themselves (not one list's tasks),
  marking the currently open one with `●` -- symmetric with `wa project list`.
- `wa todo show`: reprints the currently open list's tasks without re-selecting it
  (errors the same way as `toggle`/`remove` if none is open).
- `wa todo close`: clears the currently open list (`unset`s `ACTIVE_TODO_LIST` in this
  shell session) so a subsequent `wa todo open <name>` starts from a clean slate.
  Note that `wa todo open <name>` already overwrites whichever list was open, so this
  isn't required to switch lists -- it's for explicitly returning to "no list open".
  Errors the same way as `toggle`/`remove`/`show` if none is open.
- `wa todo toggle <n>` / `wa todo remove <n>`: act on whichever list is open; error
  clearly ("Run 'wa todo open <name>' first") if none is.
- Superseded the earlier `--list`/`-l` flag design (added, then replaced, in the
  same session) once it became clear typing `--list` on every single todo command
  wasn't practical. No migration path from either previous format -- pre-release,
  no real data depends on it yet.

### Fixed
- **Rich markup injection in output**: `wa todo list`/`toggle` were silently
  swallowing task text like `- [x] this` because Rich parses literal `[...]` in any
  printed string as markup, not just in hardcoded `[green]...[/green]` tags. Fixed
  by escaping all user-supplied strings (project var values, cmd scripts, todo/note
  text) with `rich.markup.escape()` before they reach `console.print`/table cells.
  Centralized error printing into a `_print_error()` helper in `cli.py` so this is
  applied consistently instead of at each of the ~19 call sites individually.

### Performance
- Set `rich_markup_mode=None` on the Typer app. Typer's default rich-based help
  formatter unconditionally imports `rich.markdown` (which pulls in `markdown_it`
  and `pygments`), adding ~200ms to *every* invocation just to be able to render
  `--help` with colored panels -- independent of how many commands `wa` has (a
  minimal one-command Typer app pays the same cost). Disabling it drops `wa --help`
  from ~0.40s back to ~0.20s; help/usage text now renders as plain Click-style text
  instead of Rich panels. Our own commands are unaffected -- they still use
  `rich.console.Console`, lazily imported per-command, for their actual output.
