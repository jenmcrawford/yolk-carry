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

from yolk.config import REPO_ROOT
from yolk.db import Connection
from yolk.foods import create_item
from yolk.macros import Macros
from yolk.people import create_person, create_profile, create_slot
from yolk.planning.evaluate import add_entry, create_day_plan

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "keto_plan_a.json"

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
