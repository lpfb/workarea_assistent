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
