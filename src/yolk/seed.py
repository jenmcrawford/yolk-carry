"""Build the Keto Plan A fixture into a database.

The golden test and `yolk init --seed` both call this, so a change to how the
plan is built cannot make the test and the real database disagree. The fixture
lives under tests/ and is not packaged: seeding is a development and first-run
convenience, not a runtime feature.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from dataclasses import dataclass, field

from yolk.config import REPO_ROOT
from yolk.db import Connection
from yolk.errors import YolkError
from yolk.foods import create_item
from yolk.macros import Macros
from yolk.people import create_person, create_points_profile, create_profile, create_slot
from yolk.planning.evaluate import add_entry, create_day_plan
from yolk.points import Points, add_portion

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "keto_plan_a.json"
POINT_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "point_system.json"

# An existing food's macros "differ" from the fixture's beyond this share.
_MACRO_DIFFERENCE = 0.05

_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)


def parse_time_of_day(slot_name: str) -> str:
    """Pull `06:30` out of `"Meal 1 - 6:30am Wake Up"`.

    Raises rather than guessing: a slot with no stated time is a fixture
    problem, and a made-up time would be a plausible wrong answer.
    """
    match = _TIME.search(slot_name)
    if match is None:
        raise ValueError(
            f"Slot name {slot_name!r} has no time in it, so time_of_day cannot "
            f"be derived. Expected something like '6:30am'."
        )
    hour, minute, meridiem = int(match.group(1)), match.group(2), match.group(3).lower()
    if meridiem == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return f"{hour:02d}:{minute}"


def seed_keto_plan_a(
    conn: Connection, fixture_path: Path = FIXTURE_PATH
) -> tuple[int, dict]:
    """Create the person, profile, slots, foods, and plan from the fixture.

    Foods are marked verified: every fixture entry's source_note cites a
    product label or a USDA id, and was checked when the fixture was built.

    Every write here happens in one transaction (each helper is called with
    commit=False, and the connection is committed once at the end). A fixture
    problem partway through -- an unparseable slot name, say -- must not
    leave a person, a profile, a plan, and some foods behind: the `day_plans`
    guard `yolk init --seed` uses to refuse re-seeding would then block the
    only way to retry, short of deleting the database file.
    """
    spec = json.loads(fixture_path.read_text(encoding="utf-8"))
    today = date.today().isoformat()

    try:
        person_id = create_person(conn, "Jen", commit=False)
        profile_id = create_profile(
            conn, person_id,
            name=spec["profile"]["name"],
            effective_on=spec["profile"]["effective_on"],
            kcal=spec["profile"]["kcal"],
            fat_pct=spec["profile"]["fat_pct"],
            carb_pct=spec["profile"]["carb_pct"],
            protein_pct=spec["profile"]["protein_pct"],
            commit=False,
        )
        plan_id = create_day_plan(
            conn, person_id, profile_id, name=spec["plan_name"], commit=False
        )

        food_ids: dict[str, int] = {}
        for slot in spec["slots"]:
            create_slot(
                conn, person_id, profile_id,
                slot_no=slot["slot_no"],
                name=slot["name"],
                time_of_day=parse_time_of_day(slot["name"]),
                roles=tuple(dict.fromkeys(e["role"] for e in slot["entries"])),
                commit=False,
            )
            for entry in slot["entries"]:
                name = entry["food"]
                if name not in food_ids:
                    m = entry["macros_100g"]
                    food_ids[name] = create_item(
                        conn,
                        name=name,
                        role=entry["role"],
                        macros=Macros(
                            kcal=m["kcal"],
                            protein_g=m["protein_g"],
                            fat_g=m["fat_g"],
                            carb_g=m["carb_g"],
                        ),
                        source=entry.get("source", "manual"),
                        units=entry.get("units") or None,
                        notes=entry.get("source_note"),
                        verified=True,
                        verified_on=today,
                        commit=False,
                    )
                add_entry(
                    conn, plan_id,
                    slot_no=slot["slot_no"],
                    food_id=food_ids[name],
                    qty=entry["qty"],
                    unit=entry["unit"],
                    commit=False,
                )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return plan_id, spec


@dataclass(frozen=True)
class SeedReport:
    profile_id: int
    created: list[str] = field(default_factory=list)
    attached: list[str] = field(default_factory=list)
    # "<food>: fat 50.6 here vs 55.5 in the fixture", existing macros kept.
    macro_differences: list[str] = field(default_factory=list)
    # Foods whose coach portion disagrees with their macros.
    flagged: list[str] = field(default_factory=list)
    already_seeded: bool = False


def _macro_differences(row, fixture_macros: dict) -> list[str]:
    found = []
    for name, column in (("fat", "fat_g_100g"), ("carb", "carb_g_100g"),
                         ("protein", "protein_g_100g")):
        ours, theirs = row[column] or 0.0, fixture_macros[f"{name}_g"]
        if abs(ours - theirs) > _MACRO_DIFFERENCE * max(abs(ours), abs(theirs), 1.0):
            found.append(f"{row['name']}: {name} {ours:g} here vs {theirs:g} in the fixture")
    return found


def seed_point_system(
    conn: Connection, fixture_path: Path = POINT_FIXTURE_PATH
) -> SeedReport:
    """Add the coach's point system to a database that already has its person.

    Creates the points profile and its meals, and the coach's foods with
    their portions. A food already in the library (same name and brand) is
    reused: it gets the fixture's point class and portions, and keeps its own
    macros, with any disagreement named in the report.

    One transaction, and safe to run twice: a person who already has the
    fixture's profile is reported as already seeded and nothing is written.
    """
    spec = json.loads(fixture_path.read_text(encoding="utf-8"))
    person = conn.execute(
        "SELECT id FROM people WHERE name = ?", (spec["person"],)
    ).fetchone()
    if person is None:
        raise YolkError(
            f"There is no person named {spec['person']!r} to seed the point system "
            f"for. Run `yolk init --seed` on a new database, or add them first."
        )
    profile = spec["profile"]
    existing = conn.execute(
        "SELECT id FROM macro_profiles WHERE person_id = ? AND name = ? "
        "AND effective_on = ?",
        (person["id"], profile["name"], profile["effective_on"]),
    ).fetchone()
    if existing is not None:
        return SeedReport(profile_id=existing["id"], already_seeded=True)

    created: list[str] = []
    attached: list[str] = []
    differences: list[str] = []
    try:
        profile_id = create_points_profile(
            conn, person["id"],
            name=profile["name"],
            effective_on=profile["effective_on"],
            kcal_tol_pct=profile["kcal_tol_pct"],
            protein_tol_g=profile["protein_tol_g"],
            macro_pct_tol=profile["macro_pct_tol"],
            commit=False,
        )
        for slot in spec["slots"]:
            create_slot(
                conn, person["id"], profile_id,
                slot_no=slot["slot_no"],
                name=slot["name"],
                time_of_day=slot["time_of_day"],
                allotment=Points(
                    fat=slot["fat"], carb=slot["carb"],
                    protein=slot["protein"], veggie=slot["veggie"],
                ),
                commit=False,
            )

        for food in spec["foods"]:
            m = food["macros_100g"]
            row = conn.execute(
                "SELECT * FROM foods WHERE name = ? AND brand = ?",
                (food["name"], food["brand"]),
            ).fetchone()
            if row is None:
                food_id = create_item(
                    conn,
                    name=food["name"],
                    brand=food["brand"],
                    role=food["role"],
                    macros=Macros(
                        kcal=m["kcal"],
                        protein_g=m["protein_g"],
                        fat_g=m["fat_g"],
                        carb_g=m["carb_g"],
                        fiber_g=m["fiber_g"] or 0.0,
                    ),
                    fiber_known=m["fiber_g"] is not None,
                    sugar_alcohol_g_100g=m.get("sugar_alcohol_g"),
                    point_class=food["point_class"],
                    source=food["source"],
                    source_ref=food["source_ref"],
                    verified=food["verified"],
                    units=food["units"] or None,
                    notes=food["source_note"] or None,
                    commit=False,
                )
                created.append(food["name"])
            else:
                food_id = row["id"]
                if food["point_class"] is not None:
                    conn.execute(
                        "UPDATE foods SET point_class = ? WHERE id = ?",
                        (food["point_class"], food_id),
                    )
                for unit, grams in food["units"].items():
                    conn.execute(
                        "INSERT INTO food_units (food_id, unit, grams) VALUES (?, ?, ?) "
                        "ON CONFLICT (food_id, unit) DO NOTHING",
                        (food_id, unit, grams),
                    )
                differences.extend(_macro_differences(row, m))
                attached.append(food["name"])
            for portion in food["portions"]:
                already = conn.execute(
                    "SELECT 1 FROM point_portions WHERE food_id = ? AND source = ?",
                    (food_id, portion["source"]),
                ).fetchone()
                if already is None:
                    add_portion(
                        conn, food_id,
                        source=portion["source"],
                        qty=portion["qty"],
                        unit=portion["unit"],
                        claimed=portion["claimed"],
                        commit=False,
                    )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return SeedReport(
        profile_id=profile_id,
        created=created,
        attached=attached,
        macro_differences=differences,
        flagged=[f["name"] for f in spec["foods"] if f["source_note"].startswith("FLAG")],
    )
