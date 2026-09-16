"""Where things live on disk.

One function owns the database path so that nothing else has to guess, and so
that pointing at a copy is an environment change rather than a code change.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# src/yolk/config.py -> src/yolk -> src -> the repository root
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_NAME = "yolk.db"


def database_path() -> Path:
    """The SQLite file to use: $YOLK_DB if set, otherwise yolk.db in the repo."""
    load_dotenv()
    configured = os.environ.get("YOLK_DB")
    if configured:
        return Path(configured).expanduser()
    return REPO_ROOT / DEFAULT_DB_NAME
