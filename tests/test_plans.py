import pytest

from yolk.people import create_person, create_profile
from yolk.planning.evaluate import add_entry, create_day_plan
from yolk.planning.plans import get_plan, plan_summaries
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
