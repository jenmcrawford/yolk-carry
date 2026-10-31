"""Importing new foods from a receipt inbox CSV.

A receipt is read by Claude in a session, which finds each product's label
and writes one row per food (see docs/food-inbox.md). This module turns that
file into unchecked foods. Every row is checked before anything is written:
one bad row imports nothing, and the error names each bad line and column.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.food_entry import LabelInput, create_label_food, validate

INBOX_COLUMNS = (
    "name", "brand", "store", "serving_text", "serving_g", "kcal", "fat_g",
    "carb_g", "fiber_g", "sugar_alcohol_g", "protein_g", "point_class",
    "unit", "unit_g", "source_note",
)

_NUMBERS = ("serving_g", "kcal", "fat_g", "carb_g", "fiber_g", "sugar_alcohol_g",
            "protein_g", "unit_g")

# Which CSV column a LabelInput validation error belongs to.
_COLUMN_FOR_FIELD = {"counts_as": "point_class", "free_role": "point_class",
                     "unit_qty": "unit_g"}


@dataclass(frozen=True)
class InboxReport:
    # "name (brand)" for each food.
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class InboxError(YolkError):
    """The inbox could not be imported. `problems` reads 'line N, column: message'."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def _label(name: str, brand: str) -> str:
    return f"{name} ({brand})" if brand else name


def _row_to_label(row: dict[str, str]) -> tuple[LabelInput | None, dict[str, str]]:
    """A CSV row as a LabelInput, or the problems that stop it, by column."""
    problems: dict[str, str] = {}
    numbers: dict[str, float | None] = {}
    for column in _NUMBERS:
        text = row[column].strip()
        if not text:
            numbers[column] = None
            continue
        try:
            numbers[column] = float(text)
        except ValueError:
            problems[column] = f"{text!r} is not a plain number of grams or calories."
    if problems:
        return None, problems

    counts_as, _, free_role = row["point_class"].strip().partition(":")
    unit = row["unit"].strip() or None
    unit_qty = None
    if unit is not None:
        if not numbers["unit_g"] or numbers["unit_g"] <= 0:
            return None, {"unit_g": f"Give the grams in one {unit}."}
        if numbers["serving_g"]:
            unit_qty = numbers["serving_g"] / numbers["unit_g"]
    notes = " · ".join(
        part for part in (row["store"].strip(), row["serving_text"].strip(),
                          row["source_note"].strip()) if part
    )
    inp = LabelInput(
        name=row["name"].strip(),
        brand=row["brand"].strip(),
        serving_g=numbers["serving_g"],
        kcal=numbers["kcal"],
        fat_g=numbers["fat_g"],
        carb_g=numbers["carb_g"],
        fiber_g=numbers["fiber_g"],
        sugar_alcohol_g=numbers["sugar_alcohol_g"],
        protein_g=numbers["protein_g"],
        counts_as=counts_as or "auto",
        free_role=free_role or None,
        unit=unit,
        unit_qty=unit_qty,
        notes=notes or None,
    )
    errors = validate(inp)
    return inp, {_COLUMN_FOR_FIELD.get(f, f): message for f, message in errors.items()}


def _read(path: Path) -> list[tuple[int, dict[str, str]]]:
    # utf-8-sig and newline="" so a file saved by Excel reads the same as any other.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        if header != INBOX_COLUMNS:
            missing = [c for c in INBOX_COLUMNS if c not in header]
            extra = [c for c in header if c not in INBOX_COLUMNS]
            problems = [f"line 1: the columns must be exactly: {', '.join(INBOX_COLUMNS)}."]
            if missing:
                problems.append(f"line 1: missing column(s): {', '.join(missing)}.")
            if extra:
                problems.append(f"line 1: unknown column(s): {', '.join(extra)}.")
            raise InboxError(problems)
        rows = []
        for row in reader:
            values = {column: (row.get(column) or "") for column in INBOX_COLUMNS}
            if any(value.strip() for value in values.values()):
                rows.append((reader.line_num, values))
        return rows


def import_inbox(conn: Connection, path: Path) -> InboxReport:
    """Create an unchecked food for each new row; skip foods already in the
    library (same name and brand). All or nothing."""
    rows = _read(path)
    problems: list[str] = []
    labels: list[LabelInput] = []
    for line, row in rows:
        inp, errors = _row_to_label(row)
        for column, message in errors.items():
            problems.append(f"line {line}, {column}: {message}")
        if not errors:
            labels.append(inp)
    if problems:
        raise InboxError(problems)

    created: list[str] = []
    skipped: list[str] = []
    seen: set[tuple[str, str]] = set()
    try:
        for inp in labels:
            key = (inp.name.strip(), inp.brand.strip())
            exists = conn.execute(
                "SELECT 1 FROM foods WHERE name = ? AND brand = ?", key
            ).fetchone()
            if exists is not None or key in seen:
                skipped.append(_label(*key))
                continue
            create_label_food(conn, inp, commit=False)
            seen.add(key)
            created.append(_label(*key))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return InboxReport(created=created, skipped=skipped)
