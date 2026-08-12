import sqlite3

import pytest


def test_schema_creates_expected_tables(db):
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    expected = {
        "people", "tags", "food_tags", "foods", "food_units", "food_components",
        "protocols", "protocol_rules", "person_protocols",
        "macro_profiles", "slot_templates", "slot_template_roles",
        "day_plans", "day_plan_entries", "inventory",
    }
    assert expected <= names


def test_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO food_units (food_id, unit, grams) VALUES (9999, 'tbsp', 14.0)"
        )


def test_item_requires_macros(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO foods (kind, name, role, source) "
            "VALUES ('item', 'Mystery', 'protein', 'manual')"
        )
