"""SQLite connection management and schema creation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yolk.db import Connection
from yolk.db.migrate import apply_migrations


def connect(path: str | Path) -> Connection:
    """Open a connection with row access by name and foreign keys enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: Connection) -> None:
    """Bring a database up to the latest schema by applying every migration."""
    apply_migrations(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
