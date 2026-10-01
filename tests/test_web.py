from fastapi.testclient import TestClient

from yolk.db.connection import connect, create_schema
from yolk.db.migrate import applied
from yolk.web.app import create_app


def test_the_root_redirects_to_the_plan_list(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/plans"


def test_the_plan_list_shows_the_seeded_plan(client, seeded):
    _, plan_id, spec = seeded
    response = client.get("/plans")
    assert response.status_code == 200
    assert spec["plan_name"] in response.text
    assert spec["profile"]["name"] in response.text
    assert f'href="/plans/{plan_id}"' in response.text
    assert "Within tolerance" in response.text


def test_a_missing_database_says_to_run_init_and_is_not_created(tmp_path):
    path = tmp_path / "absent.db"
    response = TestClient(create_app(path), base_url="http://127.0.0.1").get("/plans")
    assert response.status_code == 503
    assert "uv run python -m yolk init --seed" in response.text
    assert not path.exists()


def test_a_database_behind_on_migrations_says_to_run_migrate(tmp_path):
    path = tmp_path / "old.db"
    conn = connect(path)
    applied(conn)  # creates the bookkeeping table, applies nothing
    conn.close()
    response = TestClient(create_app(path), base_url="http://127.0.0.1").get("/plans")
    assert response.status_code == 503
    assert "uv run python -m yolk migrate" in response.text


def test_a_database_with_nobody_in_it_says_to_seed(tmp_path):
    path = tmp_path / "empty.db"
    conn = connect(path)
    create_schema(conn)
    conn.close()
    response = TestClient(create_app(path), base_url="http://127.0.0.1").get("/plans")
    assert response.status_code == 503
    assert "uv run python -m yolk init --seed" in response.text


def test_an_unexpected_error_renders_a_plain_page(seeded, monkeypatch):
    def explode(conn, person_id):
        raise RuntimeError("boom")

    monkeypatch.setattr("yolk.web.routes.plans.plan_summaries", explode)
    client = TestClient(create_app(seeded[0]), base_url="http://127.0.0.1", raise_server_exceptions=False)
    response = client.get("/plans")
    assert response.status_code == 500
    assert "Something went wrong" in response.text
    assert "boom" not in response.text


def test_a_request_for_another_host_is_refused(client):
    assert client.get("/plans").status_code == 200
    response = client.get("/plans", headers={"host": "evil.example"})
    assert response.status_code == 400
