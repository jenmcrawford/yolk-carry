"""People, dated macro profiles, and meal slot templates.

Profiles are dated rows rather than constants, so recalculating targets as
body composition changes is a new row and old plans stay interpretable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from yolk.db import Connection
from yolk.macros import (
    KCAL_PER_G_CARB, KCAL_PER_G_FAT, KCAL_PER_G_PROTEIN, Macros, profile_targets,
)
from yolk.points import Points, load_rules


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


def create_points_profile(
    conn: Connection,
    person_id: int,
    *,
    name: str,
    effective_on: str,
    kcal_tol_pct: float = 5.0,
    protein_tol_g: float = 8.0,
    macro_pct_tol: float = 3.0,
    commit: bool = True,
) -> int:
    """A profile whose targets are its meals' point allotments added up.

    It stores no kcal or percentages, so nothing stored can drift from the
    points. The calorie window defaults wider than a macros profile's,
    because a points day counts calories from grams, not labels.
    """
    row = conn.execute(
        "INSERT INTO macro_profiles (person_id, name, effective_on, basis, "
        "kcal_tol_pct, protein_tol_g, macro_pct_tol) "
        "VALUES (?, ?, ?, 'points', ?, ?, ?) RETURNING id",
        (person_id, name, effective_on, kcal_tol_pct, protein_tol_g, macro_pct_tol),
    ).fetchone()
    if commit:
        conn.commit()
    return row["id"]


def profile_basis(conn: Connection, profile_id: int) -> str:
    """'macros' or 'points'."""
    row = conn.execute(
        "SELECT basis FROM macro_profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"No macro profile with id {profile_id}")
    return row["basis"]


def slot_allotments(conn: Connection, profile_id: int) -> dict[int, Points]:
    """Each meal's point allotment, by slot number. Empty for a macros profile."""
    if profile_basis(conn, profile_id) != "points":
        return {}
    rows = conn.execute(
        "SELECT slot_no, fat_pts, carb_pts, protein_pts, veggie_pts "
        "FROM slot_templates WHERE profile_id = ? ORDER BY slot_no",
        (profile_id,),
    ).fetchall()
    return {
        row["slot_no"]: Points(
            fat=row["fat_pts"], carb=row["carb_pts"],
            protein=row["protein_pts"], veggie=row["veggie_pts"],
        )
        for row in rows
    }


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
    """Gram targets for a profile.

    A points profile adds up its meals' allotments and multiplies by the
    point sizes; calories follow from the grams. Veggie points are carbs.
    """
    row = conn.execute(
        "SELECT basis, kcal, fat_pct, carb_pct, protein_pct FROM macro_profiles "
        "WHERE id = ?",
        (profile_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No macro profile with id {profile_id}")
    if row["basis"] == "points":
        rules = load_rules(conn)
        total = sum(slot_allotments(conn, profile_id).values(), Points.zero())
        fat_g = total.fat * rules.fat_g
        carb_g = total.carb * rules.carb_g + total.veggie * rules.veggie_g
        protein_g = total.protein * rules.protein_g
        return Macros(
            kcal=fat_g * KCAL_PER_G_FAT
            + carb_g * KCAL_PER_G_CARB
            + protein_g * KCAL_PER_G_PROTEIN,
            fat_g=fat_g,
            carb_g=carb_g,
            protein_g=protein_g,
        )
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
    allotment: Points | None = None,
    portable: bool = False,
    fixed: bool = False,
    notes: str | None = None,
    commit: bool = True,
) -> int:
    try:
        pts = allotment or Points.zero()
        row = conn.execute(
            "INSERT INTO slot_templates (person_id, profile_id, slot_no, name, "
            "time_of_day, portable, fixed, notes, fat_pts, carb_pts, protein_pts, "
            "veggie_pts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "RETURNING id",
            (person_id, profile_id, slot_no, name, time_of_day,
             int(portable), int(fixed), notes,
             pts.fat, pts.carb, pts.protein, pts.veggie),
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
    return [
        ProfileChoice(
            id=row["id"],
            name=row["name"],
            kcal=targets_for_profile(conn, row["id"]).kcal,
        )
        for row in rows
    ]
