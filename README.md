# wa — Workflow Assistant CLI

Centralizes the management of project workspaces, directory paths, custom
scripts, environment variables, and notes/tasks for Linux command-line
workflows.

## Status

Under active, staged development. See `CHANGELOG.md` for what has landed so
far.

## Development install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
eval "$(wa shell-init bash)"   # or zsh
```
