"""XDG Base Directory locations used by wa.

Config (small, user-editable settings) and data (project registry, the
thing wa actually manages) are kept separate per the XDG spec, even though
today only one file lives in each directory.
"""
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wa"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "wa"

CONFIG_FILE = CONFIG_DIR / "config.json"
REGISTRY_FILE = DATA_DIR / "projects.json"

# Env var names used for shell integration and command execution context.
SHELL_PIPE_ENV = "WA_SHELL_PIPE"
ACTIVE_PROJ_DIR_ENV = "ACTIVE_PROJ_DIR"
ACTIVE_TODO_LIST_ENV = "ACTIVE_TODO_LIST"
