import pytest

from yolk.db.connection import connect
from yolk.people import create_person, create_profile
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate


def _with_conn(path, work):
    conn = connect(path)
    try:
        return work(conn)
    finally:
        conn.close()


def _start_draft(client, plan_id) -> int:
    response = client.post(f"/plans/{plan_id}/draft", follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def _profile_id(path, plan_id):
    return _with_conn(path, lambda c: c.execute(
        "SELECT profile_id FROM day_plans WHERE id = ?", (plan_id,)
    ).fetchone()["profile_id"])


def _new_plan(client, path, plan_id, name="Rest day"):
    return client.post(
        "/plans", data={"name": name, "profile_id": _profile_id(path, plan_id)},
        follow_redirects=False,
    )


def _double_first_entry(path, draft):
    def work(conn):
        entry = conn.execute(
            "SELECT id, qty, unit FROM day_plan_entries WHERE day_plan_id = ? "
            "ORDER BY slot_no, sort_order, id", (draft,),
        ).fetchone()
        drafts.update_entry(conn, entry["id"], qty=entry["qty"] * 2, unit=entry["unit"])
        return evaluate(conn, draft).totals
    return _with_conn(path, work)


def _totals(path, plan_id):
    return _with_conn(path, lambda c: evaluate(c, plan_id).totals)


def test_edit_or_copy_opens_a_draft_of_the_plan(client, seeded):
    _, plan_id, spec = seeded
    assert 'action="/plans/%d/draft"' % plan_id in client.get(f"/plans/{plan_id}").text
    draft = _start_draft(client, plan_id)
    text = client.get(f"/drafts/{draft}").text
    assert f"{spec['plan_name']} (draft)" in text
    assert "Save over" in text
    assert spec["slots"][0]["entries"][0]["food"] in text


def test_edit_twice_opens_the_same_draft(client, seeded):
    _, plan_id, _ = seeded
    assert _start_draft(client, plan_id) == _start_draft(client, plan_id)


def test_new_plan_starts_a_blank_draft_with_every_slot(client, seeded):
    path, plan_id, spec = seeded
    response = _new_plan(client, path, plan_id)
    assert response.status_code == 303
    text = client.get(response.headers["location"]).text
    for slot in spec["slots"]:
        assert slot["name"] in text
    assert text.count("Nothing planned for this meal.") == len(spec["slots"])
    assert "Save over" not in text


def test_new_plan_with_a_taken_name_says_so(client, seeded):
    path, plan_id, spec = seeded
    response = _new_plan(client, path, plan_id, name=spec["plan_name"])
    assert response.status_code == 422
    assert "You already have a plan called" in response.text


def test_the_plan_list_shows_drafts_in_progress(client, seeded):
    _, plan_id, _ = seeded
    draft = _start_draft(client, plan_id)
    text = client.get("/plans").text
    assert "In progress" in text
    assert f'href="/drafts/{draft}"' in text


def test_save_as_new_turns_a_blank_draft_into_a_saved_plan(client, seeded):
    path, plan_id, _ = seeded
    location = _new_plan(client, path, plan_id).headers["location"]
    draft = int(location.rsplit("/", 1)[1])

    def add_pork(conn):
        food = conn.execute("SELECT id FROM foods WHERE name = 'Pork Rinds'").fetchone()["id"]
        drafts.add_entry_to_draft(conn, draft, slot_no=1, food_id=food, qty=50, unit="g")
    _with_conn(path, add_pork)

    response = client.post(
        f"/drafts/{draft}/save-as-new", data={"name": "Rest day"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/plans/{draft}"
    listing = client.get("/plans").text
    assert "Rest day" in listing
    assert "In progress" not in listing


def test_save_over_replaces_the_saved_plan(client, seeded):
    path, plan_id, _ = seeded
    draft = _start_draft(client, plan_id)
    draft_totals = _double_first_entry(path, draft)
    response = client.post(f"/drafts/{draft}/save-over", follow_redirects=False)
    assert response.headers["location"] == f"/plans/{plan_id}"
    assert _totals(path, plan_id) == draft_totals


def test_discard_leaves_the_saved_plan_exactly_as_it_was(client, seeded):
    path, plan_id, _ = seeded
    before = _totals(path, plan_id)
    draft = _start_draft(client, plan_id)
    _double_first_entry(path, draft)
    response = client.post(f"/drafts/{draft}/discard", follow_redirects=False)
    assert response.headers["location"] == f"/plans/{plan_id}"
    assert _totals(path, plan_id) == before
    assert client.get(f"/drafts/{draft}").status_code == 404


def test_a_draft_that_cannot_be_measured_cannot_be_saved(client, seeded):
    path, plan_id, _ = seeded
    draft = _start_draft(client, plan_id)

    def add_bad(conn):
        food = conn.execute("SELECT id FROM foods WHERE name = 'Pork Rinds'").fetchone()["id"]
        drafts.add_entry_to_draft(conn, draft, slot_no=1, food_id=food, qty=1, unit="handful")
    _with_conn(path, add_bad)

    response = client.post(f"/drafts/{draft}/save-over", follow_redirects=False)
    assert response.status_code == 422
    assert "handful" in response.text
    assert client.get(f"/drafts/{draft}").status_code == 200


def test_the_draft_page_shows_the_change_against_the_saved_plan(client, seeded):
    path, plan_id, _ = seeded
    draft = _start_draft(client, plan_id)
    _double_first_entry(path, draft)  # Buff Chick Coffee, 80 kcal, doubled
    text = client.get(f"/drafts/{draft}").text
    assert "vs saved" in text
    assert "+80" in text


def test_another_persons_draft_is_not_found(client, seeded):
    def sams_draft(conn):
        sam = create_person(conn, "Sam")
        profile = create_profile(
            conn, sam, name="rest", effective_on="2026-07-14",
            kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
        )
        return drafts.start_blank_draft(conn, sam, profile, "Sam plan")
    draft = _with_conn(seeded[0], sams_draft)
    assert client.get(f"/drafts/{draft}").status_code == 404


@pytest.mark.parametrize(
    "route, data",
    [
        ("save-as-new", {"name": "Stolen"}),
        ("discard", {}),
        ("save-over", {}),
        ("entries", {"slot_no": "1", "food_id": "FOOD"}),
    ],
)
def test_another_persons_draft_cannot_be_posted_to(client, seeded, route, data):
    path, _, _ = seeded

    def make_sam_draft(conn):
        sam = create_person(conn, "Sam")
        profile = create_profile(
            conn, sam, name="rest", effective_on="2026-07-14",
            kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
        )
        food = conn.execute("SELECT id FROM foods LIMIT 1").fetchone()["id"]
        return drafts.start_blank_draft(conn, sam, profile, "Sam draft"), food

    sam_draft, food = _with_conn(path, make_sam_draft)
    data = {k: str(food) if v == "FOOD" else v for k, v in data.items()}

    response = client.post(f"/drafts/{sam_draft}/{route}", data=data, follow_redirects=False)

    assert response.status_code == 404
    still_there = _with_conn(path, lambda c: (
        c.execute("SELECT status FROM day_plans WHERE id = ?", (sam_draft,)).fetchone(),
        c.execute(
            "SELECT count(*) AS n FROM day_plan_entries WHERE day_plan_id = ?",
            (sam_draft,),
        ).fetchone()["n"],
    ))
    assert still_there[0]["status"] == "draft"
    assert still_there[1] == 0
