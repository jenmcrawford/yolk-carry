from pathlib import Path

from yolk.config import DEFAULT_DB_NAME, REPO_ROOT, database_path


def test_default_path_is_the_repo_root(monkeypatch):
    monkeypatch.delenv("YOLK_DB", raising=False)
    assert database_path() == REPO_ROOT / DEFAULT_DB_NAME


def test_repo_root_contains_the_project_file():
    assert (REPO_ROOT / "pyproject.toml").is_file()


def test_environment_variable_wins(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.db"
    monkeypatch.setenv("YOLK_DB", str(target))
    assert database_path() == target


def test_a_user_path_is_expanded(monkeypatch):
    monkeypatch.setenv("YOLK_DB", "~/yolk.db")
    resolved = database_path()
    assert "~" not in str(resolved)
    assert resolved == Path.home() / "yolk.db"
