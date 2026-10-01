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
