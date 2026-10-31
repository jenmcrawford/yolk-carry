"""Adding a food: from its label, or from USDA."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.food_entry import (
    COUNTS_AS,
    FREE_ROLES,
    LabelInput,
    LabelInputError,
    UsdaUnavailable,
    create_label_food,
    create_usda_food,
    preview,
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
