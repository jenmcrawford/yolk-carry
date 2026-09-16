import sqlite3

import pytest

from yolk.db.connection import connect, create_schema
from yolk.db.migrate import (
    MIGRATIONS_DIR,
    MigrationError,
    apply_migrations,
    available,
    latest_version,
)


def test_baseline_is_discovered():
    versions = [version for version, _ in available()]
    assert versions == sorted(versions)
    assert versions[0] == 1


def test_latest_version_matches_the_highest_file():
    assert latest_version() == max(v for v, _ in available())


def test_migrations_create_every_table():
    conn = connect(":memory:")
    apply_migrations(conn)
    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    expected = {
        "people", "tags", "food_tags", "foods", "food_units", "food_components",
        "protocols", "protocol_rules", "person_protocols",
        "macro_profiles", "slot_templates", "slot_template_roles",
        "day_plans", "day_plan_entries", "inventory",
    }
    assert expected <= names
    conn.close()


def test_migrations_record_what_they_applied():
    conn = connect(":memory:")
    applied_now = apply_migrations(conn)
    assert applied_now == [version for version, _ in available()]
    recorded = {
        row["version"] for row in conn.execute("SELECT version FROM schema_version")
    }
    assert recorded == set(applied_now)
    conn.close()


def test_applying_twice_is_a_no_op():
    conn = connect(":memory:")
    apply_migrations(conn)
    assert apply_migrations(conn) == []
    conn.close()


def test_badly_named_migration_is_rejected(tmp_path):
    (tmp_path / "nope.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    with pytest.raises(ValueError, match="0001_name.sql"):
        available(tmp_path)


def test_create_schema_still_builds_a_usable_database(db):
    """The existing conftest fixture must keep working unchanged."""
    db.execute("INSERT INTO people (name) VALUES ('Jen')")
    assert db.execute("SELECT count(*) AS n FROM people").fetchone()["n"] == 1


REBUILD_SQL = """
CREATE TABLE parent_new (
    id      INTEGER PRIMARY KEY,
    label   TEXT NOT NULL CHECK (label IN ('a', 'b', 'c'))
);
INSERT INTO parent_new (id, label) SELECT id, label FROM parent;
DROP TABLE parent;
ALTER TABLE parent_new RENAME TO parent;
"""


def _two_table_database(tmp_path):
    """A parent and a child, one row each, built by migration 0001."""
    (tmp_path / "0001_baseline.sql").write_text(
        "CREATE TABLE parent (\n"
        "    id    INTEGER PRIMARY KEY,\n"
        "    label TEXT NOT NULL CHECK (label IN ('a', 'b'))\n"
        ");\n"
        "CREATE TABLE child (\n"
        "    id        INTEGER PRIMARY KEY,\n"
        "    parent_id INTEGER NOT NULL REFERENCES parent(id) ON DELETE CASCADE\n"
        ");\n",
        encoding="utf-8",
    )
    conn = connect(":memory:")
    apply_migrations(conn, tmp_path)
    conn.execute("INSERT INTO parent (id, label) VALUES (1, 'a')")
    conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 1)")
    conn.commit()
    return conn


def test_rebuild_keeps_every_row_in_the_rebuilt_table(tmp_path):
    conn = _two_table_database(tmp_path)
    (tmp_path / "0002_widen_label.sql").write_text(REBUILD_SQL, encoding="utf-8")

    assert apply_migrations(conn, tmp_path) == [2]

    assert conn.execute("SELECT label FROM parent WHERE id = 1").fetchone()["label"] == "a"
    conn.execute("INSERT INTO parent (id, label) VALUES (2, 'c')")
    conn.close()


def test_rebuild_does_not_cascade_delete_the_children(tmp_path):
    """Dropping the old parent table must not take the child rows with it."""
    conn = _two_table_database(tmp_path)
    (tmp_path / "0002_widen_label.sql").write_text(REBUILD_SQL, encoding="utf-8")

    apply_migrations(conn, tmp_path)

    assert conn.execute("SELECT count(*) AS n FROM child").fetchone()["n"] == 1
    conn.close()


def test_a_migration_that_orphans_rows_is_rolled_back(tmp_path):
    """Losing a parent row leaves the child dangling, so nothing may commit."""
    conn = _two_table_database(tmp_path)
    (tmp_path / "0002_drop_a_row.sql").write_text(
        "DELETE FROM parent WHERE id = 1;", encoding="utf-8"
    )

    with pytest.raises(MigrationError, match="rolled back"):
        apply_migrations(conn, tmp_path)

    assert conn.execute("SELECT count(*) AS n FROM parent").fetchone()["n"] == 1
    versions = {row["version"] for row in conn.execute("SELECT version FROM schema_version")}
    assert versions == {1}
    conn.close()


def test_foreign_keys_are_enforced_again_after_a_migration(tmp_path):
    conn = _two_table_database(tmp_path)
    (tmp_path / "0002_widen_label.sql").write_text(REBUILD_SQL, encoding="utf-8")

    apply_migrations(conn, tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO child (id, parent_id) VALUES (2, 999)")
    conn.close()
