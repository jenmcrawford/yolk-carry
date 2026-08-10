"""People, dated macro profiles, and meal slot templates.

Profiles are dated rows rather than constants, so recalculating targets as
body composition changes is a new row and old plans stay interpretable.
"""

from __future__ import annotations

import sqlite3

from yolk.macros import Macros, profile_targets


def create_person(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute("INSERT INTO people (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def create_profile(
    conn: sqlite3.Connection,
    person_id: int,
    *,
    name: str,
    effective_on: str,
    kcal: float,
    fat_pct: float,
    carb_pct: float,
    protein_pct: float,
    kcal_tol_pct: float = 1.0,
    protein_tol_g: float = 2.0,
    macro_pct_tol: float = 3.0,
) -> int:
    cur = conn.execute(
        "INSERT INTO macro_profiles (person_id, name, effective_on, kcal, fat_pct, "
        "carb_pct, protein_pct, kcal_tol_pct, protein_tol_g, macro_pct_tol) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            person_id, name, effective_on, kcal, fat_pct, carb_pct, protein_pct,
            kcal_tol_pct, protein_tol_g, macro_pct_tol,
        ),
    )
    conn.commit()
    return cur.lastrowid


def active_profile(
    conn: sqlite3.Connection, person_id: int, name: str, on_date: str
) -> sqlite3.Row:
    """The profile in force on `on_date` — the latest row not in the future."""
    row = conn.execute(
        "SELECT * FROM macro_profiles WHERE person_id = ? AND name = ? "
        "AND effective_on <= ? ORDER BY effective_on DESC LIMIT 1",
        (person_id, name, on_date),
    ).fetchone()
    if row is None:
        raise LookupError(
            f"No {name!r} profile for person {person_id} effective on or before "
            f"{on_date}."
        )
    return row


def targets_for_profile(conn: sqlite3.Connection, profile_id: int) -> Macros:
    row = conn.execute(
        "SELECT kcal, fat_pct, carb_pct, protein_pct FROM macro_profiles WHERE id = ?",
        (profile_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No macro profile with id {profile_id}")
    return profile_targets(
        kcal=row["kcal"],
        fat_pct=row["fat_pct"],
        carb_pct=row["carb_pct"],
        protein_pct=row["protein_pct"],
    )


def create_slot(
    conn: sqlite3.Connection,
    person_id: int,
    profile_id: int,
    *,
    slot_no: int,
    name: str,
    time_of_day: str,
    roles: tuple[str, ...] = (),
    portable: bool = False,
    fixed: bool = False,
    notes: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO slot_templates (person_id, profile_id, slot_no, name, "
        "time_of_day, portable, fixed, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (person_id, profile_id, slot_no, name, time_of_day,
         int(portable), int(fixed), notes),
    )
    slot_id = cur.lastrowid
    for role in roles:
        conn.execute(
            "INSERT INTO slot_template_roles (slot_template_id, role) VALUES (?, ?)",
            (slot_id, role),
        )
    conn.commit()
    return slot_id
