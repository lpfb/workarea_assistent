"""User-facing errors raised by wa's domain logic (wa/projects.py etc.).

Kept separate from typer/rich so the domain layer stays presentation-agnostic
-- the CLI layer decides how a WaError gets displayed.
"""


class WaError(Exception):
    """A recoverable, user-facing error (bad input, missing project, ...)."""
