"""Exceptions raised by yolk.

Every error here marks a case where a silent default would produce a
plausible but wrong number. Raising is always preferable.
"""


class YolkError(Exception):
    """Base class for all yolk errors."""


class UnknownUnitError(YolkError):
    """No gram conversion is recorded for this food and unit."""


class MissingYieldError(YolkError):
    """A recipe has no cooked_yield_g, so per-100g macros cannot be computed."""


class RecipeCycleError(YolkError):
    """A recipe contains itself, directly or transitively."""
