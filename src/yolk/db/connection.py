"""SQLite connection management and schema creation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yolk.db import Connection
from yolk.db.migrate import apply_migrations


def connect(path: str | Path, *, check_same_thread: bool = True) -> Connection:
    """Open a connection with row access by name and foreign keys enforced.

    The web app passes check_same_thread=False: FastAPI may open a request's
    connection on one threadpool thread and use it on another. A connection
    there belongs to exactly one request and is never used concurrently, so
    sqlite3's same-thread guard protects nothing. Everything else keeps it.
    """
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: Connection) -> None:
    """Bring a database up to the latest schema by applying every migration."""
    apply_migrations(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
