import pytest

from yolk.db.connection import connect, create_schema
from yolk.db.migrate import (
    MIGRATIONS_DIR,
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
