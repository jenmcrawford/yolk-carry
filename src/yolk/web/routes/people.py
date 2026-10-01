"""Choosing whose plans to show."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse

from yolk.web.deps import PERSON_COOKIE, ViewerDep

router = APIRouter()


@router.post("/person")
def choose_person(person_id: Annotated[int, Form()], viewer: ViewerDep):
    response = RedirectResponse("/plans", status_code=303)
    if any(person.id == person_id for person in viewer.people):
        response.set_cookie(PERSON_COOKIE, str(person_id), httponly=True, samesite="lax")
    return response
