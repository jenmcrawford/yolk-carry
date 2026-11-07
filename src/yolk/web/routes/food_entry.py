"""Adding a food: from its label, or from USDA."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.food_entry import (
    COUNTS_AS,
    FREE_ROLES,
    FoodEdit,
    LabelInput,
    LabelInputError,
    NotEditable,
    UsdaUnavailable,
    create_label_food,
    create_usda_food,
    food_detail,
    mark_checked,
    preview,
    update_food,
    usda_search,
)
from yolk.points import load_rules
from yolk.web.deps import ConnDep, ViewerDep
from yolk.web.templating import templates

router = APIRouter()

_NUMBERS = ("serving_g", "kcal", "fat_g", "carb_g", "fiber_g", "sugar_alcohol_g", "protein_g",
            "unit_qty")


@dataclass(frozen=True)
class LabelForm:
    """The label form as typed, so a refused save can show it back unchanged."""

    values: dict[str, str]

    def parse(self) -> tuple[LabelInput, dict[str, str]]:
        """The typed values as a LabelInput, plus an error for each number
        that does not read as one. A blank number is None, for validate()."""
        errors: dict[str, str] = {}
        numbers: dict[str, float | None] = {}
        for field in _NUMBERS:
            text = self.values[field].strip()
            if not text:
                numbers[field] = None
                continue
            try:
                numbers[field] = float(text)
            except ValueError:
                numbers[field] = None
                errors[field] = f"{text!r} is not a number. Enter grams as a plain number."
        v = self.values
        return (
            LabelInput(
                name=v["name"],
                brand=v["brand"],
                counts_as=v["counts_as"] or "auto",
                free_role=v["free_role"] or None,
                unit=v["unit"].strip() or None,
                notes=v["notes"].strip() or None,
                **numbers,
            ),
            errors,
        )


def label_form(
    name: Annotated[str, Form()] = "",
    brand: Annotated[str, Form()] = "",
    serving_g: Annotated[str, Form()] = "",
    kcal: Annotated[str, Form()] = "",
    fat_g: Annotated[str, Form()] = "",
    carb_g: Annotated[str, Form()] = "",
    fiber_g: Annotated[str, Form()] = "",
    sugar_alcohol_g: Annotated[str, Form()] = "",
    protein_g: Annotated[str, Form()] = "",
    counts_as: Annotated[str, Form()] = "auto",
    free_role: Annotated[str, Form()] = "",
    unit: Annotated[str, Form()] = "",
    unit_qty: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
) -> LabelForm:
    return LabelForm(values=dict(locals()))


LabelFormDep = Annotated[LabelForm, Depends(label_form)]


def _new_page(
    request: Request, viewer, form: LabelForm, *, errors=None, usda_error=None,
    status_code=200,
):
    return templates.TemplateResponse(
        request,
        "foods/new.html",
        {
            "viewer": viewer,
            "form": form.values,
            "errors": errors or {},
            "usda_error": usda_error,
            "counts_as": COUNTS_AS,
            "free_roles": FREE_ROLES,
        },
        status_code=status_code,
    )


@router.get("/foods/new", response_class=HTMLResponse)
def new_food_page(request: Request, viewer: ViewerDep):
    return _new_page(request, viewer, label_form())


@router.post("/foods/new/preview", response_class=HTMLResponse)
def new_food_preview(request: Request, conn: ConnDep, form: LabelFormDep):
    inp, errors = form.parse()
    shown = preview(conn, inp)
    return templates.TemplateResponse(
        request,
        "foods/_preview.html",
        {"preview": shown, "errors": {**shown.errors, **errors}},
    )


@router.post("/foods/new")
def save_new_food(request: Request, conn: ConnDep, viewer: ViewerDep, form: LabelFormDep):
    inp, errors = form.parse()
    if errors:
        return _new_page(request, viewer, form, errors=errors, status_code=422)
    try:
        food_id = create_label_food(conn, inp)
    except LabelInputError as exc:
        return _new_page(request, viewer, form, errors=exc.errors, status_code=422)
    return RedirectResponse(f"/foods/{food_id}", status_code=303)


@router.get("/foods/new/usda", response_class=HTMLResponse)
def usda_results(request: Request, conn: ConnDep, q: str = ""):
    query = q.strip()
    context = {"query": query, "counts_as": COUNTS_AS, "free_roles": FREE_ROLES}
    if query:
        try:
            context["choices"] = usda_search(query, load_rules(conn))
        except UsdaUnavailable as exc:
            # A missing key is a setup step, not a crash: say what to do.
            context["unavailable"] = str(exc)
    return templates.TemplateResponse(request, "foods/_usda_results.html", context)


@router.post("/foods/new/usda")
def add_usda_food(
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    fdc_id: Annotated[int, Form()],
    counts_as: Annotated[str, Form()] = "auto",
    free_role: Annotated[str, Form()] = "",
):
    try:
        food_id = create_usda_food(
            conn, fdc_id, counts_as=counts_as, free_role=free_role or None
        )
    except LabelInputError as exc:
        return _new_page(
            request, viewer, label_form(), usda_error=" ".join(exc.errors.values()),
            status_code=422,
        )
    except UsdaUnavailable as exc:
        return _new_page(
            request, viewer, label_form(), usda_error=f"USDA could not be reached: {exc}",
            status_code=503,
        )
    return RedirectResponse(f"/foods/{food_id}", status_code=303)


# --- A food's own page ----------------------------------------------------------
# {food_id:int} so these never match /foods/new or /foods/search.

def _detail_or_404(conn, food_id: int):
    try:
        return food_detail(conn, food_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"There is no food {food_id}.")


@router.get("/foods/{food_id:int}", response_class=HTMLResponse)
def food_page(food_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    return templates.TemplateResponse(
        request, "foods/detail.html", {"viewer": viewer, "food": _detail_or_404(conn, food_id)}
    )


@router.post("/foods/{food_id:int}/check")
def check_food(food_id: int, conn: ConnDep):
    _detail_or_404(conn, food_id)
    mark_checked(conn, food_id)
    return RedirectResponse(f"/foods/{food_id}", status_code=303)


_EDIT_NUMBERS = ("kcal", "fat_g", "carb_g", "fiber_g", "sugar_alcohol_g", "protein_g",
                 "manual_qty")


def _edit_values(conn, food_id: int) -> dict[str, str]:
    d = _detail_or_404(conn, food_id)
    s, m = d.summary, d.summary.per_100g
    manual = next((p for p in d.portions if p.source == "manual"), None)

    def number(value):
        return "" if value is None else f"{value:g}"

    return {
        "name": s.name, "brand": s.brand,
        "kcal": number(m.kcal), "fat_g": number(m.fat_g), "carb_g": number(m.carb_g),
        "fiber_g": number(m.fiber_g) if s.fiber_known else "",
        "sugar_alcohol_g": number(d.sugar_alcohol_g_100g), "protein_g": number(m.protein_g),
        "counts_as": s.point_class or "auto",
        "free_role": s.role if s.point_class == "free" else "",
        "units": "\n".join(f"{unit} = {grams:g}" for unit, grams in s.units),
        "manual_qty": number(manual.qty) if manual else "",
        "manual_unit": manual.unit if manual else "",
    }


def _parse_edit(values: dict[str, str]) -> tuple[FoodEdit, dict[str, str]]:
    errors: dict[str, str] = {}
    numbers: dict[str, float | None] = {}
    for field in _EDIT_NUMBERS:
        text = values[field].strip()
        try:
            numbers[field] = float(text) if text else None
        except ValueError:
            numbers[field] = None
            errors[field] = f"{text!r} is not a number."
    units: dict[str, float] = {}
    for line in values["units"].splitlines():
        if not line.strip():
            continue
        unit, sep, grams = line.partition("=")
        try:
            if not sep:
                raise ValueError(line)
            units[unit.strip()] = float(grams)
        except ValueError:
            errors["units"] = f"Write each unit as 'name = grams', not {line.strip()!r}."
    manual_unit = values["manual_unit"].strip()
    manual = None
    if numbers["manual_qty"] is not None:
        if not manual_unit:
            errors["manual_portion"] = "Give your portion a unit."
        manual = (numbers["manual_qty"], manual_unit)
    return (
        FoodEdit(
            name=values["name"], brand=values["brand"],
            kcal=numbers["kcal"], fat_g=numbers["fat_g"], carb_g=numbers["carb_g"],
            fiber_g=numbers["fiber_g"], sugar_alcohol_g=numbers["sugar_alcohol_g"],
            protein_g=numbers["protein_g"], counts_as=values["counts_as"] or "auto",
            free_role=values["free_role"] or None, units=units, manual_portion=manual,
        ),
        errors,
    )


def _edit_page(request, viewer, food_id: int, values, *, errors=None, status_code=200):
    return templates.TemplateResponse(
        request,
        "foods/edit.html",
        {
            "viewer": viewer, "food_id": food_id, "form": values, "errors": errors or {},
            "counts_as": COUNTS_AS, "free_roles": FREE_ROLES,
        },
        status_code=status_code,
    )


def _editable_or_409(conn, food_id: int):
    if _detail_or_404(conn, food_id).summary.kind == "recipe":
        raise HTTPException(
            status_code=409,
            detail="A recipe's macros come from its components; edit those instead.",
        )


@router.get("/foods/{food_id:int}/edit", response_class=HTMLResponse)
def edit_food_page(food_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    _editable_or_409(conn, food_id)
    return _edit_page(request, viewer, food_id, _edit_values(conn, food_id))


@router.post("/foods/{food_id:int}/edit")
async def save_food_edit(food_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    _editable_or_409(conn, food_id)
    form = await request.form()
    fields = ("name", "brand", "counts_as", "free_role", "units", "manual_unit", *_EDIT_NUMBERS)
    values = {field: str(form.get(field, "")) for field in fields}
    edit, errors = _parse_edit(values)
    if not errors:
        try:
            update_food(conn, food_id, edit)
        except LabelInputError as exc:
            errors = exc.errors
        except NotEditable as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    if errors:
        return _edit_page(request, viewer, food_id, values, errors=errors, status_code=422)
    return RedirectResponse(f"/foods/{food_id}", status_code=303)
