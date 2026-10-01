import pytest

from yolk.cli import main
from yolk.db.connection import connect


@pytest.fixture
def db_path(monkeypatch, tmp_path):
    path = tmp_path / "yolk.db"
    monkeypatch.setenv("YOLK_DB", str(path))
    return path


def test_init_creates_a_migrated_database(db_path, capsys):
    assert main(["init"]) == 0
    assert db_path.is_file()

    conn = connect(db_path)
    names = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "foods" in names
    assert "schema_version" in names
    conn.close()


def test_init_twice_is_a_no_op(db_path):
    assert main(["init"]) == 0
    assert main(["init"]) == 0


def test_init_with_seed_creates_the_plan(db_path):
    assert main(["init", "--seed"]) == 0
    conn = connect(db_path)
    row = conn.execute("SELECT name FROM day_plans").fetchone()
    assert row["name"] == "Keto Meal Plan A"
    conn.close()


def test_seeding_an_already_seeded_database_is_refused(db_path, capsys):
    main(["init", "--seed"])
    assert main(["init", "--seed"]) == 1
    assert "already has" in capsys.readouterr().err


def test_export_then_import_into_a_fresh_database(db_path, tmp_path, monkeypatch):
    main(["init", "--seed"])
    out = tmp_path / "export"
    assert main(["export", "--out", str(out)]) == 0
    assert (out / "foods.json").is_file()

    second = tmp_path / "second.db"
    monkeypatch.setenv("YOLK_DB", str(second))
    assert main(["init"]) == 0
    assert main(["import", "--from", str(out)]) == 0

    conn = connect(second)
    assert conn.execute("SELECT count(*) AS n FROM foods").fetchone()["n"] > 0
    conn.close()


def test_a_command_on_a_missing_database_explains_itself(db_path, capsys):
    assert main(["export"]) == 1
    assert "yolk init" in capsys.readouterr().err


def test_migrate_subcommand_reports_up_to_date(db_path, capsys):
    """The only subcommand with no prior coverage, and the one that will run
    against the real, unrecreatable database once migration 0002 lands."""
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["migrate"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_import_with_malformed_json_fails_cleanly_instead_of_a_traceback(
    db_path, tmp_path, monkeypatch, capsys
):
    main(["init", "--seed"])
    out = tmp_path / "export"
    main(["export", "--out", str(out)])
    (out / "foods.json").write_text("{not valid json", encoding="utf-8")

    second = tmp_path / "second.db"
    monkeypatch.setenv("YOLK_DB", str(second))
    main(["init"])

    # main() returning cleanly (rather than the test failing on an uncaught
    # json.JSONDecodeError propagating out of main) is the assertion here.
    assert main(["import", "--from", str(out)]) == 1
    assert capsys.readouterr().err.strip() != ""


def test_serve_binds_to_localhost_and_uses_the_resolved_database(
    db_path, monkeypatch, capsys
):
    calls = []
    monkeypatch.setattr(
        "yolk.cli.uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs))
    )
    assert main(["serve", "--port", "8123"]) == 0
    [(app, kwargs)] = calls
    assert kwargs == {"host": "127.0.0.1", "port": 8123}
    assert app.state.db_path == db_path
    assert "http://127.0.0.1:8123" in capsys.readouterr().out


def test_serve_defaults_to_port_8000(db_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "yolk.cli.uvicorn.run", lambda app, **kwargs: calls.append(kwargs)
    )
    main(["serve"])
    assert calls == [{"host": "127.0.0.1", "port": 8000}]
