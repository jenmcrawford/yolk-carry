"""Per-request plumbing: the database connection and the current person.

Routes get both through FastAPI dependencies, so no route opens a connection,
checks the database is ready, or decides who is looking.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from yolk.db import Connection
from yolk.db.connection import connect
from yolk.db.migrate import pending
from yolk.people import Person, list_people
from yolk.planning.plans import PlanHeader, get_plan

PERSON_COOKIE = "yolk_person"

INIT_COMMAND = "uv run python -m yolk init --seed"
MIGRATE_COMMAND = "uv run python -m yolk migrate"


class SetupRequired(Exception):
    """The database cannot serve pages yet. `command` is what fixes it."""

    def __init__(self, message: str, command: str) -> None:
        super().__init__(message)
        self.message = message
        self.command = command


def get_conn(request: Request) -> Iterator[Connection]:
    """One connection per request, closed after the response.

    The app never migrates and never creates the database: either would hide
    a setup problem behind a page that looks fine.
    """
    path = request.app.state.db_path
    if not path.is_file():
        # connect() would create an empty file here, and an empty file looks
        # like a database to every later check. Refuse before opening.
        raise SetupRequired(f"There is no database at {path}.", INIT_COMMAND)
    conn = connect(path, check_same_thread=False)
    try:
        waiting = pending(conn)
        if waiting:
            raise SetupRequired(
                f"The database at {path} has not applied migration(s) "
                f"{', '.join(str(v) for v in waiting)}.",
                MIGRATE_COMMAND,
            )
        yield conn
    finally:
        conn.close()


ConnDep = Annotated[Connection, Depends(get_conn)]


@dataclass(frozen=True)
class Viewer:
    """Who the page is for, and who else could be picked."""

    person: Person
    people: list[Person]


def get_viewer(request: Request, conn: ConnDep) -> Viewer:
    """The person named by the cookie, or the first person if it names nobody."""
    people = list_people(conn)
    if not people:
        raise SetupRequired("The database has nobody in it yet.", INIT_COMMAND)
    chosen = request.cookies.get(PERSON_COOKIE)
    for person in people:
        if str(person.id) == chosen:
            return Viewer(person=person, people=people)
    return Viewer(person=people[0], people=people)


ViewerDep = Annotated[Viewer, Depends(get_viewer)]


def owned_plan(
    conn: Connection, viewer: Viewer, plan_id: int, *, status: str | None = None
) -> PlanHeader:
    """The plan, if it exists, is the viewer's, and has `status` when given.

    Anything else is a 404, so one person's address can never open another
    person's plan.
    """
    try:
        plan = get_plan(conn, plan_id)
    except LookupError:
        plan = None
    if (
        plan is None
        or plan.person_id != viewer.person.id
        or (status is not None and plan.status != status)
    ):
        raise HTTPException(status_code=404, detail=f"There is no plan {plan_id}.")
    return plan


def is_htmx(request: Request) -> bool:
    """Whether htmx sent this request, and so wants a fragment back."""
    return request.headers.get("hx-request") == "true"
