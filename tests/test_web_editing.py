from yolk.db.connection import connect

HTMX = {"HX-Request": "true"}


def _with_conn(path, work):
    conn = connect(path)
    try:
        return work(conn)
    finally:
        conn.close()


def _draft_and_first_entry(client, seeded):
    path, plan_id, _ = seeded
    response = client.post(f"/plans/{plan_id}/draft", follow_redirects=False)
    draft = int(response.headers["location"].rsplit("/", 1)[1])
    entry = _with_conn(path, lambda c: dict(c.execute(
        "SELECT id, slot_no, qty, unit, food_id FROM day_plan_entries "
        "WHERE day_plan_id = ? ORDER BY slot_no, sort_order, id", (draft,),
    ).fetchone()))
    return path, draft, entry


def _entry(path, entry_id):
    row = _with_conn(path, lambda c: c.execute(
        "SELECT food_id, qty, unit FROM day_plan_entries WHERE id = ?", (entry_id,)
    ).fetchone())
    return None if row is None else dict(row)


def _food(path, name):
    return _with_conn(path, lambda c: c.execute(
        "SELECT id FROM foods WHERE name = ?", (name,)
    ).fetchone()["id"])


def test_changing_an_amount_answers_with_the_slot_and_totals(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    response = client.post(
        f"/drafts/{draft}/entries/{entry['id']}",
        data={"qty": "2", "unit": entry["unit"]}, headers=HTMX,
    )
    assert response.status_code == 200
    assert f'id="slot-{entry["slot_no"]}"' in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert _entry(path, entry["id"])["qty"] == 2


def test_changing_an_amount_without_htmx_redirects_back(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    response = client.post(
        f"/drafts/{draft}/entries/{entry['id']}",
        data={"qty": "3", "unit": entry["unit"]}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/drafts/{draft}")
    assert _entry(path, entry["id"])["qty"] == 3


def test_a_bad_amount_shows_on_its_row_and_changes_nothing(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    url = f"/drafts/{draft}/entries/{entry['id']}"
    response = client.post(url, data={"qty": "abc", "unit": entry["unit"]}, headers=HTMX)
    assert response.status_code == 200
    assert "Amount must be a number" in response.text
    response = client.post(url, data={"qty": "0", "unit": entry["unit"]}, headers=HTMX)
    assert "greater than 0" in response.text
    assert _entry(path, entry["id"])["qty"] == entry["qty"]


def test_a_bad_amount_without_htmx_shows_the_page_with_the_message(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    response = client.post(
        f"/drafts/{draft}/entries/{entry['id']}",
        data={"qty": "", "unit": entry["unit"]}, follow_redirects=False,
    )
    assert response.status_code == 422
    assert "Amount must be a number" in response.text


def test_remove_takes_the_entry_out(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    response = client.post(f"/drafts/{draft}/entries/{entry['id']}/remove", headers=HTMX)
    assert response.status_code == 200
    assert _entry(path, entry["id"]) is None


def test_adding_a_food_uses_its_usual_portion(client, seeded):
    path, draft, _ = _draft_and_first_entry(client, seeded)
    for name, expected in [("Buff Chick Coffee", (1, "packet")), ("Pork Rinds", (100, "g"))]:
        response = client.post(
            f"/drafts/{draft}/entries",
            data={"slot_no": "1", "food_id": str(_food(path, name))}, headers=HTMX,
        )
        assert response.status_code == 200
        added = _with_conn(path, lambda c: c.execute(
            "SELECT qty, unit FROM day_plan_entries WHERE day_plan_id = ? "
            "ORDER BY id DESC", (draft,),
        ).fetchone())
        assert (added["qty"], added["unit"]) == expected


def test_swap_replaces_the_food_in_place(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    pork = _food(path, "Pork Rinds")
    client.post(
        f"/drafts/{draft}/entries/{entry['id']}/swap",
        data={"food_id": str(pork)}, headers=HTMX,
    )
    assert _entry(path, entry["id"]) == {"food_id": pork, "qty": 100, "unit": "g"}


def test_the_picker_lists_foods_with_add_buttons(client, seeded):
    _, draft, _ = _draft_and_first_entry(client, seeded)
    response = client.get(
        "/foods/search", params={"draft": draft, "slot": 1, "q": "pork"}, headers=HTMX
    )
    assert response.status_code == 200
    assert "Pork Rinds" in response.text
    assert f'action="/drafts/{draft}/entries"' in response.text
    assert 'name="slot_no" value="1"' in response.text
    assert "hx-post=" in response.text
    assert 'hx-get="/foods/search"' in response.text
    assert "<html" not in response.text


def test_the_picker_without_htmx_is_a_full_page_of_plain_forms(client, seeded):
    _, draft, _ = _draft_and_first_entry(client, seeded)
    response = client.get("/foods/search", params={"draft": draft, "slot": 1})
    assert "<html" in response.text
    assert "Back to" in response.text
    assert f'action="/drafts/{draft}/entries"' in response.text
    assert "hx-post=" not in response.text
    assert "hx-get=" not in response.text


def test_an_entry_from_another_plan_is_not_found(client, seeded):
    path, plan_id, _ = seeded
    _, draft, _ = _draft_and_first_entry(client, seeded)
    saved_entry = _with_conn(path, lambda c: c.execute(
        "SELECT id FROM day_plan_entries WHERE day_plan_id = ?", (plan_id,)
    ).fetchone()["id"])
    response = client.post(
        f"/drafts/{draft}/entries/{saved_entry}/remove", follow_redirects=False
    )
    assert response.status_code == 404


def test_htmx_is_served_from_the_app_itself(client):
    assert '<script src="/static/htmx.min.js"' in client.get("/plans").text
    script = client.get("/static/htmx.min.js")
    assert script.status_code == 200
    assert "htmx" in script.text[:2000]


def test_adding_or_swapping_an_unknown_food_is_not_found(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    before = _entry(path, entry["id"])
    for url, data in (
        (f"/drafts/{draft}/entries", {"slot_no": "1", "food_id": "999999"}),
        (f"/drafts/{draft}/entries/{entry['id']}/swap", {"food_id": "999999"}),
    ):
        response = client.post(url, data=data, headers=HTMX)
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")
    assert _entry(path, entry["id"]) == before
