"""SQLite connection management and schema creation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql to an empty database."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # executescript issues an implicit COMMIT that resets the pragma
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
