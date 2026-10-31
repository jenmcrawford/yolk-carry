import pytest
from fastapi.testclient import TestClient

from yolk.db.connection import connect, create_schema
from yolk.seed import seed_keto_plan_a
from yolk.web.app import create_app


@pytest.fixture
def db():
    conn = connect(":memory:")
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def person(db):
    """Person 1, used by every person-scoped test."""
    row = db.execute(
        "INSERT INTO people (name) VALUES ('Jen') RETURNING id"
    ).fetchone()
    db.commit()
    return row["id"]


@pytest.fixture
def seeded(tmp_path):
    """A seeded database file, for tests that go through the app.

    The app opens its own connection per request by path, so these tests use
    a file under tmp_path rather than :memory:.
    """
    path = tmp_path / "yolk.db"
    conn = connect(path)
    create_schema(conn)
    plan_id, spec = seed_keto_plan_a(conn)
    conn.close()
    return path, plan_id, spec


@pytest.fixture
def client(seeded):
    return TestClient(
        create_app(seeded[0]),
        base_url="http://127.0.0.1",
        headers={"origin": "http://127.0.0.1"},
    )


def _columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


@pytest.fixture
def keto_a_into_old_schema():
    """Fill a database at an older schema version with Keto Plan A.

    The library always writes the latest schema, so it cannot seed an old
    database directly. This seeds a fresh latest database and copies every
    row across, keeping only the columns the old tables have. Returns the
    plan id, which is the same in both.
    """

    def fill(old_conn):
        latest = connect(":memory:")
        create_schema(latest)
        plan_id, _ = seed_keto_plan_a(latest)
        old_tables = {
            row["name"]
            for row in old_conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        from yolk.snapshot import TABLES

        for table in TABLES:
            if table not in old_tables:
                continue
            shared = [c for c in _columns(old_conn, table) if c in _columns(latest, table)]
            names = ", ".join(shared)
            marks = ", ".join("?" for _ in shared)
            for row in latest.execute(f"SELECT {names} FROM {table}"):
                old_conn.execute(
                    f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row)
                )
        old_conn.commit()
        latest.close()
        return plan_id

    return fill
