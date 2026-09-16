"""Database access for yolk.

`Connection` is an alias rather than `sqlite3.Connection` used directly, so
that a later move to Postgres changes one line instead of every annotation in
the package.
"""

from __future__ import annotations

import sqlite3

Connection = sqlite3.Connection

__all__ = ["Connection"]
