from fastapi.testclient import TestClient

from yolk.db.connection import connect
from yolk.people import create_person, create_profile
from yolk.planning.evaluate import create_day_plan
from yolk.web.app import create_app


def _bare_client(path):
    return TestClient(create_app(path), base_url="http://127.0.0.1")


def test_a_post_from_another_site_is_refused(client):
    response = client.post(
        "/person", data={"person_id": 1},
        headers={"origin": "http://evil.example"}, follow_redirects=False,
    )
    assert response.status_code == 403
    assert "Refused" in response.text
    assert "set-cookie" not in response.headers


def test_a_post_with_neither_origin_nor_referer_is_refused(seeded):
    response = _bare_client(seeded[0]).post(
        "/person", data={"person_id": 1}, follow_redirects=False
    )
    assert response.status_code == 403


def test_a_post_with_a_same_machine_referer_is_allowed(seeded):
    response = _bare_client(seeded[0]).post(
        "/person", data={"person_id": 1},
        headers={"referer": "http://127.0.0.1/plans"}, follow_redirects=False,
    )
    assert response.status_code == 303


def test_a_post_from_another_local_port_is_refused(client):
    response = client.post(
        "/person", data={"person_id": 1},
        headers={"origin": "http://127.0.0.1:3000"}, follow_redirects=False,
    )
    assert response.status_code == 403


def test_a_post_with_a_null_origin_is_refused(client):
    response = client.post(
        "/person", data={"person_id": 1},
        headers={"origin": "null"}, follow_redirects=False,
    )
    assert response.status_code == 403


def test_an_unknown_address_gets_the_html_error_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Not Found" in response.text


def test_a_malformed_plan_id_gets_the_html_error_page(client):
    response = client.get("/plans/not-a-number")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")


def test_another_persons_plan_is_not_found(client, seeded):
    conn = connect(seeded[0])
    sam = create_person(conn, "Sam")
    profile = create_profile(
        conn, sam, name="rest", effective_on="2026-07-14",
        kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
    )
    sam_plan = create_day_plan(conn, sam, profile, name="Sam plan")
    conn.close()
    assert client.get(f"/plans/{sam_plan}").status_code == 404
