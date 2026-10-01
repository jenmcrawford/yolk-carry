from yolk.db.connection import connect
from yolk.people import create_person, create_profile
from yolk.planning.evaluate import create_day_plan


def _add_sam(path) -> int:
    conn = connect(path)
    sam = create_person(conn, "Sam")
    profile = create_profile(
        conn, sam, name="rest", effective_on="2026-07-14",
        kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
    )
    create_day_plan(conn, sam, profile, name="Sam plan")
    conn.close()
    return sam


def test_with_one_person_there_is_no_picker(client):
    assert 'action="/person"' not in client.get("/plans").text


def test_with_two_people_the_picker_lists_both(client, seeded):
    _add_sam(seeded[0])
    text = client.get("/plans").text
    assert 'action="/person"' in text
    assert "Jen" in text and "Sam" in text


def test_picking_a_person_shows_their_plans(client, seeded):
    path, _, spec = seeded
    sam = _add_sam(path)
    response = client.post("/person", data={"person_id": sam})
    assert response.status_code == 200  # after following the redirect
    assert "Sam plan" in response.text
    assert spec["plan_name"] not in response.text


def test_picking_an_unknown_person_changes_nothing(client, seeded):
    path, _, spec = seeded
    _add_sam(path)
    response = client.post("/person", data={"person_id": 999})
    assert spec["plan_name"] in response.text
    assert "Sam plan" not in response.text
