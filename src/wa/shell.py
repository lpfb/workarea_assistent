"""Shell integration: lets wa change the parent shell's cwd and export env vars.

A Python child process cannot mutate its parent shell's state directly --
any `os.chdir`/`os.environ` change dies with the process. The established
workaround (used by tools like zoxide, pyenv, direnv) is a two-channel design:

  1. stdout/stderr behave completely normally, so rich tables, prompts and
     errors display exactly as if wa were a plain program.
  2. A side channel -- a temp file whose path is passed via the
     WA_SHELL_PIPE env var -- is where wa writes raw shell statements
     (cd, export...). A shell function installed via
     `eval "$(wa shell-init bash)"` creates that temp file, runs the real
     `wa` binary with it wired up, then `eval`s the file's contents and
     deletes it.

This keeps the two concerns (what the user sees vs. what mutates their
shell) fully decoupled.
"""
from __future__ import annotations

import os
from pathlib import Path

from wa.constants import SHELL_PIPE_ENV

SUPPORTED_SHELLS = ("bash", "zsh")

# bash and zsh share the same POSIX-compatible function body today.
_SHELL_FUNCTION_TEMPLATE = """\
wa() {{
  local __wa_pipe
  __wa_pipe="$(mktemp "${{TMPDIR:-/tmp}}/wa.XXXXXX")"
  WA_SHELL_PIPE="$__wa_pipe" command {bin} "$@"
  local __wa_status=$?
  if [ -s "$__wa_pipe" ]; then
    eval "$(cat "$__wa_pipe")"
  fi
  rm -f "$__wa_pipe"
  return $__wa_status
}}
"""


def generate_shell_init(shell_name: str, bin_name: str = "wa") -> str:
    """Return the shell function definition for the given shell."""
    if shell_name not in SUPPORTED_SHELLS:
        raise ValueError(
            f"Unsupported shell: {shell_name!r} (expected one of {SUPPORTED_SHELLS})"
        )
    return _SHELL_FUNCTION_TEMPLATE.format(bin=bin_name)


def emit(line: str) -> None:
    """Append a raw shell statement to the side channel, if one is active.

    No-ops when wa is invoked without shell integration (WA_SHELL_PIPE unset),
    so the CLI still works standalone -- just without cd/export propagation.
    """
    pipe_path = os.environ.get(SHELL_PIPE_ENV)
    if not pipe_path:
        return
    with open(pipe_path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def emit_cd(path: "os.PathLike[str] | str") -> None:
    emit(f"cd {_quote(str(path))}")


def emit_export(name: str, value: str) -> None:
    emit(f"export {name}={_quote(value)}")


def _quote(value: str) -> str:
    """Single-quote a value for safe use in eval'd shell code (handles embedded quotes/spaces)."""
    return "'" + value.replace("'", "'\\''") + "'"
