import pytest

from yolk.macros import Macros
from yolk.people import create_person, create_profile
from yolk.planning import drafts
from yolk.planning.evaluate import DayEvaluation, add_entry, create_day_plan, evaluate
from yolk.planning.plans import (
    compare, draft_summaries, entry_units, get_plan, plan_slots, plan_summaries,
)
from yolk.seed import seed_keto_plan_a


def _second_person_with_plan(db) -> tuple[int, int]:
    sam = create_person(db, "Sam")
    profile = create_profile(
        db, sam, name="rest", effective_on="2026-07-14",
        kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
    )
    return sam, create_day_plan(db, sam, profile, name="Sam plan")


def _first_food_id(db, plan_id: int) -> int:
    return db.execute(
        "SELECT food_id FROM day_plan_entries WHERE day_plan_id = ? ORDER BY id",
        (plan_id,),
    ).fetchone()["food_id"]


def test_get_plan_returns_the_header_with_its_profile_name(db):
    plan_id, spec = seed_keto_plan_a(db)
    plan = get_plan(db, plan_id)
    assert plan.id == plan_id
    assert plan.name == spec["plan_name"]
    assert plan.profile_name == spec["profile"]["name"]
    assert plan.status == "active"


def test_get_plan_for_a_missing_plan_raises(db):
    with pytest.raises(LookupError):
        get_plan(db, 999)


def test_plan_summaries_marks_the_seeded_plan_within_tolerance(db):
    plan_id, spec = seed_keto_plan_a(db)
    person_id = get_plan(db, plan_id).person_id
    [summary] = plan_summaries(db, person_id)
    assert (summary.id, summary.name, summary.profile_name) == (
        plan_id, spec["plan_name"], spec["profile"]["name"]
    )
    assert summary.ok is True
    assert summary.error is None


def test_plan_summaries_leaves_out_archived_plans(db):
    plan_id, _ = seed_keto_plan_a(db)
    person_id = get_plan(db, plan_id).person_id
    db.execute("UPDATE day_plans SET status = 'archived' WHERE id = ?", (plan_id,))
    db.commit()
    assert plan_summaries(db, person_id) == []


def test_plan_summaries_shows_only_that_persons_plans(db):
    plan_id, _ = seed_keto_plan_a(db)
    sam, sam_plan = _second_person_with_plan(db)
    assert [s.id for s in plan_summaries(db, sam)] == [sam_plan]


def test_a_plan_that_cannot_be_evaluated_is_listed_with_its_error(db):
    """An unknown unit must not take the whole list down."""
    plan_id, _ = seed_keto_plan_a(db)
    person_id = get_plan(db, plan_id).person_id
    add_entry(
        db, plan_id, slot_no=1, food_id=_first_food_id(db, plan_id),
        qty=1, unit="handful",
    )
    [summary] = plan_summaries(db, person_id)
    assert summary.ok is None
    assert "handful" in summary.error


def test_a_blank_draft_shows_every_slot_template_empty(db):
    plan_id, spec = seed_keto_plan_a(db)
    header = get_plan(db, plan_id)
    blank = drafts.start_blank_draft(db, header.person_id, header.profile_id, "Rest day")
    slots = plan_slots(db, blank, evaluate(db, blank, partial=True))
    assert [(s.slot_no, s.name) for s in slots] == [
        (s["slot_no"], s["name"]) for s in spec["slots"]
    ]
    assert all(s.slot is None for s in slots)


def test_a_slot_with_entries_but_no_template_is_named_by_number(db):
    plan_id, _ = seed_keto_plan_a(db)
    add_entry(db, plan_id, slot_no=7, food_id=_first_food_id(db, plan_id), qty=10, unit="g")
    slots = plan_slots(db, plan_id, evaluate(db, plan_id))
    assert (slots[-1].slot_no, slots[-1].name) == (7, "Slot 7")
    assert slots[-1].slot is not None


def test_compare_subtracts_the_saved_totals_from_the_drafts():
    def day(totals):
        return DayEvaluation(
            day_plan_id=1, plan_name="p", totals=totals, target=Macros(),
            deltas=Macros(), within_tolerance={},
        )

    diff = compare(
        day(Macros(kcal=2300, protein_g=190, fat_g=90, carb_g=160)),
        day(Macros(kcal=2150, protein_g=200, fat_g=80, carb_g=160)),
    )
    assert diff == Macros(kcal=150, protein_g=-10, fat_g=10, carb_g=0)


def test_drafts_are_listed_apart_from_saved_plans(db):
    plan_id, _ = seed_keto_plan_a(db)
    person = get_plan(db, plan_id).person_id
    draft = drafts.start_draft(db, plan_id)
    assert [s.id for s in plan_summaries(db, person)] == [plan_id]
    assert [s.id for s in draft_summaries(db, person)] == [draft]


def test_get_plan_reports_a_drafts_parent(db):
    plan_id, _ = seed_keto_plan_a(db)
    draft = drafts.start_draft(db, plan_id)
    assert get_plan(db, draft).parent_plan_id == plan_id
    assert get_plan(db, plan_id).parent_plan_id is None


def test_entry_units_covers_every_food_in_the_plan(db):
    plan_id, _ = seed_keto_plan_a(db)
    evaluation = evaluate(db, plan_id)
    units = entry_units(db, evaluation)
    assert set(units) == {e.food_id for s in evaluation.slots for e in s.entries}
    coffee = db.execute(
        "SELECT id FROM foods WHERE name = 'Buff Chick Coffee'"
    ).fetchone()["id"]
    assert units[coffee][0] == "packet"
