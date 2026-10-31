"""The template environment, shared by the app and every route module."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from yolk.points import format_points, format_qty

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# Formatting only: "1P + ½F" and "3½". Templates still do no arithmetic.
templates.env.filters["points"] = format_points
templates.env.filters["qty"] = format_qty
