import pytest

from yolk.errors import DuplicatePlanNameError, NotADraftError, UnknownUnitError
from yolk.people import create_person
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate
from yolk.seed import seed_keto_plan_a


@pytest.fixture
def keto(db):
    plan_id, _ = seed_keto_plan_a(db)
    return plan_id


def _entries(db, plan_id):
    return [
        tuple(row)
        for row in db.execute(
            "SELECT slot_no, food_id, qty, unit FROM day_plan_entries "
            "WHERE day_plan_id = ? ORDER BY slot_no, sort_order, id",
            (plan_id,),
        )
    ]


def _first_entry(db, plan_id):
    return db.execute(
        "SELECT id, food_id, qty, unit, slot_no FROM day_plan_entries "
        "WHERE day_plan_id = ? ORDER BY slot_no, sort_order, id",
        (plan_id,),
    ).fetchone()


def _plan(db, plan_id):
    return db.execute("SELECT * FROM day_plans WHERE id = ?", (plan_id,)).fetchone()


def _person_and_profile(db, plan_id):
    row = _plan(db, plan_id)
    return row["person_id"], row["profile_id"]


def _food(db, name):
    return db.execute("SELECT id FROM foods WHERE name = ?", (name,)).fetchone()["id"]


def _slot(db, plan_id, slot_no):
    [slot] = [s for s in evaluate(db, plan_id).slots if s.slot_no == slot_no]
    return slot


def test_editing_a_draft_never_changes_the_saved_plan(db, keto):
    """The most important test in this design."""
    saved_totals, saved_entries = evaluate(db, keto).totals, _entries(db, keto)
    draft = drafts.start_draft(db, keto)
    first = _first_entry(db, draft)
    drafts.update_entry(db, first["id"], qty=first["qty"] * 3, unit=first["unit"])
    drafts.add_entry_to_draft(
        db, draft, slot_no=1, food_id=_food(db, "Pork Rinds"), qty=50, unit="g"
    )
    drafts.remove_entry(db, _slot(db, draft, 2).entries[0].entry_id)

    assert evaluate(db, keto).totals == saved_totals
    assert _entries(db, keto) == saved_entries
    assert evaluate(db, draft).totals != saved_totals


def test_a_draft_copies_every_entry_in_order(db, keto):
    draft = drafts.start_draft(db, keto)
    row = _plan(db, draft)
    assert (row["name"], row["status"], row["parent_plan_id"]) == (
        "Keto Meal Plan A (draft)", "draft", keto
    )
    assert _entries(db, draft) == _entries(db, keto)


def test_starting_a_draft_twice_returns_the_same_draft(db, keto):
    assert drafts.start_draft(db, keto) == drafts.start_draft(db, keto)


def test_a_draft_of_a_draft_is_refused(db, keto):
    draft = drafts.start_draft(db, keto)
    with pytest.raises(ValueError, match="already a draft"):
        drafts.start_draft(db, draft)


def test_entries_of_a_saved_plan_cannot_be_edited(db, keto):
    entry = _first_entry(db, keto)
    with pytest.raises(NotADraftError):
        drafts.update_entry(db, entry["id"], qty=2, unit=entry["unit"])
    with pytest.raises(NotADraftError):
        drafts.replace_entry_food(
            db, entry["id"], entry["food_id"], qty=2, unit=entry["unit"]
        )
    with pytest.raises(NotADraftError):
        drafts.remove_entry(db, entry["id"])
    with pytest.raises(NotADraftError):
        drafts.add_entry_to_draft(
            db, keto, slot_no=1, food_id=entry["food_id"], qty=1, unit="g"
        )
    assert _first_entry(db, keto)["qty"] == entry["qty"]


def test_a_non_positive_amount_is_refused_before_anything_changes(db, keto):
    draft = drafts.start_draft(db, keto)
    entry = _first_entry(db, draft)
    for bad in (0, -1, float("nan")):
        with pytest.raises(ValueError, match="greater than 0"):
            drafts.update_entry(db, entry["id"], qty=bad, unit=entry["unit"])
    assert _first_entry(db, draft)["qty"] == entry["qty"]


def test_parse_amount_reads_a_typed_number():
    assert drafts.parse_amount(" 1.5 ") == 1.5
    cases = [
        ("abc", "must be a number"),
        ("", "must be a number"),
        ("0", "greater than 0"),
        ("-2", "greater than 0"),
        ("inf", "greater than 0"),
        ("nan", "greater than 0"),
    ]
    for text, message in cases:
        with pytest.raises(ValueError, match=message):
            drafts.parse_amount(text)


def test_new_entries_go_to_the_end_of_their_slot(db, keto):
    draft = drafts.start_draft(db, keto)
    pork, coffee = _food(db, "Pork Rinds"), _food(db, "Buff Chick Coffee")
    drafts.add_entry_to_draft(db, draft, slot_no=2, food_id=pork, qty=10, unit="g")
    drafts.add_entry_to_draft(db, draft, slot_no=2, food_id=coffee, qty=1, unit="packet")
    assert [e.food_id for e in _slot(db, draft, 2).entries][-2:] == [pork, coffee]


def test_replacing_a_food_keeps_the_entry_in_place(db, keto):
    draft = drafts.start_draft(db, keto)
    first = _slot(db, draft, 2).entries[0]
    pork = _food(db, "Pork Rinds")
    drafts.replace_entry_food(db, first.entry_id, pork, qty=30, unit="g")
    now = _slot(db, draft, 2).entries[0]
    assert (now.entry_id, now.food_id, now.qty, now.unit) == (first.entry_id, pork, 30, "g")


def test_locate_entry_names_its_plan_and_slot(db, keto):
    entry = _first_entry(db, keto)
    where = drafts.locate_entry(db, entry["id"])
    assert (where.plan_id, where.slot_no) == (keto, entry["slot_no"])
    with pytest.raises(LookupError):
        drafts.locate_entry(db, 999_999)


def test_save_over_makes_the_parent_match_the_draft_and_removes_it(db, keto):
    draft = drafts.start_draft(db, keto)
    entry = _first_entry(db, draft)
    drafts.update_entry(db, entry["id"], qty=entry["qty"] * 2, unit=entry["unit"])
    draft_entries, draft_totals = _entries(db, draft), evaluate(db, draft).totals

    drafts.save_over(db, draft)

    assert _entries(db, keto) == draft_entries
    assert evaluate(db, keto).totals == draft_totals
    assert _plan(db, draft) is None


def test_save_over_needs_a_draft_with_a_parent(db, keto):
    person, profile = _person_and_profile(db, keto)
    blank = drafts.start_blank_draft(db, person, profile, "Rest day")
    with pytest.raises(ValueError, match="save it as new"):
        drafts.save_over(db, blank)


def test_save_as_new_keeps_lineage_and_leaves_the_parent_alone(db, keto):
    saved_totals = evaluate(db, keto).totals
    draft = drafts.start_draft(db, keto)
    entry = _first_entry(db, draft)
    drafts.update_entry(db, entry["id"], qty=entry["qty"] * 2, unit=entry["unit"])

    assert drafts.save_as_new(db, draft, name="Keto Meal Plan B") == draft

    row = _plan(db, draft)
    assert (row["name"], row["status"], row["parent_plan_id"]) == (
        "Keto Meal Plan B", "active", keto
    )
    assert evaluate(db, keto).totals == saved_totals


def test_save_as_new_refuses_a_name_already_in_use(db, keto):
    draft = drafts.start_draft(db, keto)
    with pytest.raises(DuplicatePlanNameError, match="Keto Meal Plan A"):
        drafts.save_as_new(db, draft, name="Keto Meal Plan A")
    assert _plan(db, draft)["status"] == "draft"


def test_a_draft_that_cannot_be_measured_cannot_be_saved(db, keto):
    saved_entries = _entries(db, keto)
    draft = drafts.start_draft(db, keto)
    drafts.add_entry_to_draft(
        db, draft, slot_no=1, food_id=_food(db, "Pork Rinds"), qty=1, unit="handful"
    )
    with pytest.raises(UnknownUnitError, match="handful"):
        drafts.save_over(db, draft)
    with pytest.raises(UnknownUnitError, match="handful"):
        drafts.save_as_new(db, draft, name="Keto Meal Plan B")
    assert _entries(db, keto) == saved_entries
    assert _plan(db, draft)["status"] == "draft"


def test_discard_removes_the_draft_and_its_entries(db, keto):
    saved_entries = _entries(db, keto)
    draft = drafts.start_draft(db, keto)
    drafts.discard_draft(db, draft)
    assert _plan(db, draft) is None
    assert _entries(db, draft) == []
    assert _entries(db, keto) == saved_entries


def test_a_blank_draft_has_its_name_and_no_entries(db, keto):
    person, profile = _person_and_profile(db, keto)
    blank = drafts.start_blank_draft(db, person, profile, "  Rest day ")
    row = _plan(db, blank)
    assert (row["name"], row["status"], row["parent_plan_id"], row["profile_id"]) == (
        "Rest day", "draft", None, profile
    )
    assert _entries(db, blank) == []


def test_a_blank_draft_refuses_a_taken_or_empty_name(db, keto):
    person, profile = _person_and_profile(db, keto)
    with pytest.raises(DuplicatePlanNameError):
        drafts.start_blank_draft(db, person, profile, "Keto Meal Plan A")
    with pytest.raises(ValueError, match="needs a name"):
        drafts.start_blank_draft(db, person, profile, "   ")


def test_a_blank_draft_refuses_another_persons_profile(db, keto):
    _, profile = _person_and_profile(db, keto)
    sam = create_person(db, "Sam")
    with pytest.raises(LookupError):
        drafts.start_blank_draft(db, sam, profile, "Sam plan")


def test_a_saved_plan_named_like_a_draft_does_not_block_a_new_draft(db, keto):
    person, profile = _person_and_profile(db, keto)
    db.execute(
        "INSERT INTO day_plans (person_id, profile_id, name, status, created_at) "
        "VALUES (?, ?, 'Keto Meal Plan A (draft)', 'active', 'now')",
        (person, profile),
    )
    db.commit()
    draft = drafts.start_draft(db, keto)
    assert _plan(db, draft)["name"] == "Keto Meal Plan A (draft 2)"


def test_names_ending_in_draft_are_reserved(db, keto):
    person, profile = _person_and_profile(db, keto)
    draft = drafts.start_draft(db, keto)
    with pytest.raises(ValueError, match="reserved"):
        drafts.save_as_new(db, draft, name="X (draft)")
    with pytest.raises(ValueError, match="reserved"):
        drafts.start_blank_draft(db, person, profile, "Y (draft)")
