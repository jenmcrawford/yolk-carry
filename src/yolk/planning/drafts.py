"""Drafts: the only way a plan's entries change.

A draft is a day_plans row with status 'draft'. Edits land on the draft, and a
saved plan changes only when a draft is saved over it, so a half-finished idea
can never leak into a plan in use. Every function here commits on success and
rolls back on failure.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from yolk.db import Connection
from yolk.errors import DuplicatePlanNameError, NotADraftError
from yolk.foods import portion_macros

DRAFT_SUFFIX = " (draft)"


@dataclass(frozen=True)
class EntryLocation:
    plan_id: int
    slot_no: int


@contextmanager
def _unit_of_work(conn: Connection) -> Iterator[None]:
    """Commit what the block wrote, or roll all of it back if it raised."""
    try:
        yield
    except Exception:
        conn.rollback()
        raise
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_positive(qty: float) -> None:
    # Written as a positive test so that NaN, which compares false to
    # everything, is refused too.
    if not (math.isfinite(qty) and qty > 0):
        raise ValueError("Amount must be greater than 0.")


def parse_amount(text: str) -> float:
    """A typed amount as a number greater than 0, or ValueError saying what is wrong."""
    cleaned = text.strip()
    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError(f"Amount must be a number, not {cleaned!r}.") from None
    _require_positive(value)
    return value


def _plan(conn: Connection, plan_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, person_id, profile_id, name, status, parent_plan_id, notes "
        "FROM day_plans WHERE id = ?",
        (plan_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No day plan with id {plan_id}")
    return row


def _draft(conn: Connection, plan_id: int) -> sqlite3.Row:
    row = _plan(conn, plan_id)
    if row["status"] != "draft":
        raise NotADraftError(
            f"{row['name']!r} is a saved plan, not a draft. Start a draft to "
            f"change it."
        )
    return row


def locate_entry(conn: Connection, entry_id: int) -> EntryLocation:
    """Which plan and slot an entry belongs to."""
    row = conn.execute(
        "SELECT day_plan_id, slot_no FROM day_plan_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No plan entry with id {entry_id}")
    return EntryLocation(plan_id=row["day_plan_id"], slot_no=row["slot_no"])


def _name_row(conn: Connection, person_id: int, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id FROM day_plans WHERE person_id = ? AND name = ?",
        (person_id, name),
    ).fetchone()


def _free_name(
    conn: Connection, person_id: int, name: str, *, ignore_id: int | None = None
) -> str:
    """The name, stripped, once it is known to be non-empty, unreserved and unused."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("A plan needs a name.")
    if cleaned.endswith(DRAFT_SUFFIX):
        raise ValueError(
            "Plan names ending in “ (draft)” are reserved for drafts."
        )
    row = _name_row(conn, person_id, cleaned)
    if row is not None and row["id"] != ignore_id:
        raise DuplicatePlanNameError(f"You already have a plan called {cleaned!r}.")
    return cleaned


def require_food(conn: Connection, food_id: int) -> None:
    """Raise LookupError unless the food exists."""
    if conn.execute("SELECT id FROM foods WHERE id = ?", (food_id,)).fetchone() is None:
        raise LookupError(f"No food with id {food_id}")


def _copy_entries(conn: Connection, from_plan: int, to_plan: int) -> None:
    conn.execute(
        "INSERT INTO day_plan_entries (day_plan_id, slot_no, food_id, qty, unit, "
        "flex, flex_min_g, flex_max_g, sort_order) "
        "SELECT ?, slot_no, food_id, qty, unit, flex, flex_min_g, flex_max_g, "
        "sort_order FROM day_plan_entries WHERE day_plan_id = ? "
        "ORDER BY slot_no, sort_order, id",
        (to_plan, from_plan),
    )


def _require_measurable(conn: Connection, plan_id: int) -> None:
    """Raise, naming the food and unit, if any entry cannot become macros."""
    for row in conn.execute(
        "SELECT food_id, qty, unit FROM day_plan_entries WHERE day_plan_id = ?",
        (plan_id,),
    ).fetchall():
        portion_macros(conn, row["food_id"], row["qty"], row["unit"])


def start_draft(conn: Connection, plan_id: int) -> int:
    """Open a draft of a saved plan, or return the draft already open for it."""
    plan = _plan(conn, plan_id)
    if plan["status"] == "draft":
        raise ValueError(f"{plan['name']!r} is already a draft.")
    existing = conn.execute(
        "SELECT id FROM day_plans WHERE parent_plan_id = ? AND status = 'draft'",
        (plan_id,),
    ).fetchone()
    if existing is not None:
        return existing["id"]
    name = plan["name"] + DRAFT_SUFFIX
    number = 2
    while _name_row(conn, plan["person_id"], name) is not None:
        name = f"{plan['name']} (draft {number})"
        number += 1
    with _unit_of_work(conn):
        draft_id = conn.execute(
            "INSERT INTO day_plans (person_id, profile_id, name, status, "
            "parent_plan_id, created_at, notes) "
            "VALUES (?, ?, ?, 'draft', ?, ?, ?) RETURNING id",
            (plan["person_id"], plan["profile_id"], name, plan_id, _now(),
             plan["notes"]),
        ).fetchone()["id"]
        _copy_entries(conn, plan_id, draft_id)
    return draft_id


def start_blank_draft(
    conn: Connection, person_id: int, profile_id: int, name: str
) -> int:
    """A new, empty plan to fill in, as a draft with no parent."""
    profile = conn.execute(
        "SELECT person_id FROM macro_profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    if profile is None or profile["person_id"] != person_id:
        raise LookupError(f"Person {person_id} has no macro profile {profile_id}.")
    cleaned = _free_name(conn, person_id, name)
    with _unit_of_work(conn):
        draft_id = conn.execute(
            "INSERT INTO day_plans (person_id, profile_id, name, status, created_at) "
            "VALUES (?, ?, ?, 'draft', ?) RETURNING id",
            (person_id, profile_id, cleaned, _now()),
        ).fetchone()["id"]
    return draft_id


def add_entry_to_draft(
    conn: Connection,
    draft_id: int,
    *,
    slot_no: int,
    food_id: int,
    qty: float,
    unit: str,
) -> int:
    """Add a food at the end of a slot."""
    _require_positive(qty)
    _draft(conn, draft_id)
    require_food(conn, food_id)
    with _unit_of_work(conn):
        entry_id = conn.execute(
            "INSERT INTO day_plan_entries (day_plan_id, slot_no, food_id, qty, unit, "
            "sort_order) "
            "SELECT ?, ?, ?, ?, ?, coalesce(max(sort_order), -1) + 1 "
            "FROM day_plan_entries WHERE day_plan_id = ? AND slot_no = ? "
            "RETURNING id",
            (draft_id, slot_no, food_id, qty, unit, draft_id, slot_no),
        ).fetchone()["id"]
    return entry_id


def update_entry(conn: Connection, entry_id: int, *, qty: float, unit: str) -> None:
    _require_positive(qty)
    _draft(conn, locate_entry(conn, entry_id).plan_id)
    with _unit_of_work(conn):
        conn.execute(
            "UPDATE day_plan_entries SET qty = ?, unit = ? WHERE id = ?",
            (qty, unit, entry_id),
        )


def replace_entry_food(
    conn: Connection, entry_id: int, food_id: int, *, qty: float, unit: str
) -> None:
    """Swap the food on an entry, keeping its slot and position."""
    _require_positive(qty)
    _draft(conn, locate_entry(conn, entry_id).plan_id)
    require_food(conn, food_id)
    with _unit_of_work(conn):
        conn.execute(
            "UPDATE day_plan_entries SET food_id = ?, qty = ?, unit = ? WHERE id = ?",
            (food_id, qty, unit, entry_id),
        )


def remove_entry(conn: Connection, entry_id: int) -> None:
    _draft(conn, locate_entry(conn, entry_id).plan_id)
    with _unit_of_work(conn):
        conn.execute("DELETE FROM day_plan_entries WHERE id = ?", (entry_id,))


def save_over(conn: Connection, draft_id: int) -> None:
    """Replace the parent plan's entries with the draft's, then drop the draft."""
    draft = _draft(conn, draft_id)
    parent_id = draft["parent_plan_id"]
    if parent_id is None:
        raise ValueError(
            "This draft is a new plan, not a copy of one, so save it as new."
        )
    _require_measurable(conn, draft_id)
    with _unit_of_work(conn):
        conn.execute("DELETE FROM day_plan_entries WHERE day_plan_id = ?", (parent_id,))
        _copy_entries(conn, draft_id, parent_id)
        # The draft's own entries go with it: ON DELETE CASCADE.
        conn.execute("DELETE FROM day_plans WHERE id = ?", (draft_id,))


def save_as_new(conn: Connection, draft_id: int, *, name: str) -> int:
    """Make the draft a saved plan under `name`, keeping its parent as lineage."""
    draft = _draft(conn, draft_id)
    cleaned = _free_name(conn, draft["person_id"], name, ignore_id=draft_id)
    _require_measurable(conn, draft_id)
    with _unit_of_work(conn):
        conn.execute(
            "UPDATE day_plans SET name = ?, status = 'active', created_at = ? "
            "WHERE id = ?",
            (cleaned, _now(), draft_id),
        )
    return draft_id


def discard_draft(conn: Connection, draft_id: int) -> None:
    _draft(conn, draft_id)
    with _unit_of_work(conn):
        conn.execute("DELETE FROM day_plans WHERE id = ?", (draft_id,))
