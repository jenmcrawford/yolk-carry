import pytest

from yolk.db.connection import connect, create_schema


@pytest.fixture
def db():
    conn = connect(":memory:")
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def person(db):
    """Person 1, used by every person-scoped test."""
    cur = db.execute("INSERT INTO people (name) VALUES ('Jen')")
    db.commit()
    return cur.lastrowid
