import json

import pytest

from yolk.db.connection import connect, create_schema
from yolk.seed import seed_keto_plan_a
from yolk.snapshot import (
    SnapshotError,
    export_database,
    import_database,
)


@pytest.fixture
def seeded(db):
    seed_keto_plan_a(db)
    return db


def _fresh():
    conn = connect(":memory:")
    create_schema(conn)
    return conn


def test_export_writes_one_file_per_table(seeded, tmp_path):
    written = export_database(seeded, tmp_path)
    names = {path.name for path in written}
    assert "foods.json" in names
    assert "day_plans.json" in names
    assert "schema_version.json" in names


def test_export_is_sorted_and_indented(seeded, tmp_path):
    export_database(seeded, tmp_path)
    text = (tmp_path / "people.json").read_text(encoding="utf-8")
    assert text.endswith("\n")
    rows = json.loads(text)
    assert rows[0] == {"id": 1, "name": "Jen"}
    assert list(rows[0]) == sorted(rows[0])


def test_export_is_deterministic(seeded, tmp_path):
    export_database(seeded, tmp_path)
    first = (tmp_path / "foods.json").read_text(encoding="utf-8")
    export_database(seeded, tmp_path)
    assert (tmp_path / "foods.json").read_text(encoding="utf-8") == first


def test_round_trip_is_byte_identical(seeded, tmp_path):
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    # A deliberately old applied_on. Without restoring it on import, the
    # fresh database's own migration run stamps today's date instead, and
    # the re-export only matches the first export within a 24-hour window.
    seeded.execute("UPDATE schema_version SET applied_on = '2020-01-01'")
    seeded.commit()
    export_database(seeded, out_a)

    restored = _fresh()
    import_database(restored, out_a)
    export_database(restored, out_b)

    for path in sorted(out_a.glob("*.json")):
        assert path.read_bytes() == (out_b / path.name).read_bytes(), path.name
    assert (
        json.loads((out_b / "schema_version.json").read_text())[0]["applied_on"]
        == "2020-01-01"
    )
    restored.close()


def test_import_restores_the_plan(seeded, tmp_path):
    export_database(seeded, tmp_path)
    restored = _fresh()
    counts = import_database(restored, tmp_path)

    assert counts["foods"] > 0
    original = seeded.execute("SELECT count(*) AS n FROM day_plan_entries").fetchone()["n"]
    assert restored.execute(
        "SELECT count(*) AS n FROM day_plan_entries"
    ).fetchone()["n"] == original
    restored.close()


def test_import_refuses_a_database_with_rows(seeded, tmp_path):
    export_database(seeded, tmp_path)
    with pytest.raises(SnapshotError, match="already has data"):
        import_database(seeded, tmp_path)


def test_import_refuses_a_version_mismatch(seeded, tmp_path):
    export_database(seeded, tmp_path)
    (tmp_path / "schema_version.json").write_text(
        json.dumps([{"applied_on": "2026-01-01", "version": 99}], indent=2) + "\n",
        encoding="utf-8",
    )
    restored = _fresh()
    with pytest.raises(SnapshotError, match="version"):
        import_database(restored, tmp_path)
    restored.close()


def test_import_refuses_a_database_that_lags_behind_the_export(seeded, tmp_path):
    """latest_version() only checks the export against the code on disk. A
    database that exists but was migrated to an older version must be caught
    here too, rather than failing deep in the insert loop with an opaque
    OperationalError about a missing column."""
    export_database(seeded, tmp_path)
    restored = _fresh()
    restored.execute("DELETE FROM schema_version")
    restored.execute(
        "INSERT INTO schema_version (version, applied_on) VALUES (0, '2020-01-01')"
    )
    restored.commit()

    with pytest.raises(SnapshotError, match="database is at"):
        import_database(restored, tmp_path)
    restored.close()
