"""People, dated macro profiles, and meal slot templates.

Profiles are dated rows rather than constants, so recalculating targets as
body composition changes is a new row and old plans stay interpretable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from yolk.db import Connection
from yolk.macros import Macros, profile_targets


def create_person(conn: Connection, name: str, *, commit: bool = True) -> int:
    row = conn.execute(
        "INSERT INTO people (name) VALUES (?) RETURNING id", (name,)
    ).fetchone()
    if commit:
        conn.commit()
    return row["id"]


@dataclass(frozen=True)
class Person:
    id: int
    name: str


@dataclass(frozen=True)
class ProfileChoice:
    id: int
    name: str
    kcal: float


def list_people(conn: Connection) -> list[Person]:
    rows = conn.execute("SELECT id, name FROM people ORDER BY id").fetchall()
    return [Person(id=row["id"], name=row["name"]) for row in rows]


def create_profile(
    conn: Connection,
    person_id: int,
    *,
    name: str,
    effective_on: str,
    kcal: float,
    fat_pct: float,
    carb_pct: float,
    protein_pct: float,
    kcal_tol_pct: float = 1.0,
    protein_tol_g: float = 8.0,
    macro_pct_tol: float = 3.0,
    commit: bool = True,
) -> int:
    row = conn.execute(
        "INSERT INTO macro_profiles (person_id, name, effective_on, kcal, fat_pct, "
        "carb_pct, protein_pct, kcal_tol_pct, protein_tol_g, macro_pct_tol) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (
            person_id, name, effective_on, kcal, fat_pct, carb_pct, protein_pct,
            kcal_tol_pct, protein_tol_g, macro_pct_tol,
        ),
    ).fetchone()
    if commit:
        conn.commit()
    return row["id"]


def active_profile(
    conn: Connection, person_id: int, name: str, on_date: str
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


def targets_for_profile(conn: Connection, profile_id: int) -> Macros:
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
    conn: Connection,
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
    commit: bool = True,
) -> int:
    try:
        row = conn.execute(
            "INSERT INTO slot_templates (person_id, profile_id, slot_no, name, "
            "time_of_day, portable, fixed, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "RETURNING id",
            (person_id, profile_id, slot_no, name, time_of_day,
             int(portable), int(fixed), notes),
        ).fetchone()
        slot_id = row["id"]
        for role in roles:
            conn.execute(
                "INSERT INTO slot_template_roles (slot_template_id, role) "
                "VALUES (?, ?)",
                (slot_id, role),
            )
    except Exception:
        conn.rollback()
        raise
    if commit:
        conn.commit()
    return slot_id


def slot_names(conn: Connection, profile_id: int) -> dict[int, str]:
    """Slot number to slot template name, for one profile's slots."""
    rows = conn.execute(
        "SELECT slot_no, name FROM slot_templates WHERE profile_id = ? "
        "ORDER BY slot_no",
        (profile_id,),
    ).fetchall()
    return {row["slot_no"]: row["name"] for row in rows}


def current_profiles(
    conn: Connection, person_id: int, on_date: str
) -> list[ProfileChoice]:
    """Each of the person's profiles as it stands on `on_date`, ordered by name."""
    rows = conn.execute(
        "SELECT id, name, kcal FROM macro_profiles m "
        "WHERE person_id = ? AND effective_on = ("
        "    SELECT max(effective_on) FROM macro_profiles "
        "    WHERE person_id = m.person_id AND name = m.name AND effective_on <= ?"
        ") ORDER BY name",
        (person_id, on_date),
    ).fetchall()
    return [ProfileChoice(id=row["id"], name=row["name"], kcal=row["kcal"]) for row in rows]
