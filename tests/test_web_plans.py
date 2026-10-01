from yolk.db.connection import connect
from yolk.planning.evaluate import add_entry, evaluate


def _add_entry_to_seeded_plan(path, plan_id, *, slot_no, unit):
    conn = connect(path)
    food_id = conn.execute(
        "SELECT food_id FROM day_plan_entries WHERE day_plan_id = ? ORDER BY id",
        (plan_id,),
    ).fetchone()["food_id"]
    add_entry(conn, plan_id, slot_no=slot_no, food_id=food_id, qty=1, unit=unit)
    conn.close()


def test_the_plan_page_shows_every_slot_name_and_the_day_kcal_total(client, seeded):
    path, plan_id, spec = seeded
    conn = connect(path)
    kcal = evaluate(conn, plan_id).totals.kcal
    conn.close()

    response = client.get(f"/plans/{plan_id}")
    assert response.status_code == 200
    for slot in spec["slots"]:
        assert slot["name"] in response.text
    assert f"{kcal:.0f}" in response.text


def test_the_plan_page_shows_each_entry_with_its_quantity(client, seeded):
    _, plan_id, spec = seeded
    first = spec["slots"][0]["entries"][0]
    response = client.get(f"/plans/{plan_id}")
    assert first["food"] in response.text
    assert f"{first['qty']:g} {first['unit']}" in response.text


def test_the_seeded_plan_is_marked_within_tolerance_on_every_macro(client, seeded):
    _, plan_id, _ = seeded
    response = client.get(f"/plans/{plan_id}")
    assert response.text.count("Within") == 4
    assert "Outside" not in response.text


def test_a_slot_without_a_template_is_titled_by_number(client, seeded):
    path, plan_id, _ = seeded
    _add_entry_to_seeded_plan(path, plan_id, slot_no=7, unit="g")
    response = client.get(f"/plans/{plan_id}")
    assert "Slot 7" in response.text


def test_an_unknown_unit_renders_inline_not_as_a_500(client, seeded):
    path, plan_id, spec = seeded
    _add_entry_to_seeded_plan(path, plan_id, slot_no=1, unit="handful")
    response = client.get(f"/plans/{plan_id}")
    assert response.status_code == 200
    assert spec["plan_name"] in response.text
    assert "handful" in response.text
    assert "Something went wrong" not in response.text


def test_an_unknown_plan_is_a_404(client):
    response = client.get("/plans/999")
    assert response.status_code == 404
    assert "There is no plan 999" in response.text
