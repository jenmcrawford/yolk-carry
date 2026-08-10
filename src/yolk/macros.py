"""The Macros value type and macro-target arithmetic.

Every food in the database stores macros per 100 g. Macros is the unit of
aggregation: scale it by (grams / 100) to get a portion's contribution.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

KCAL_PER_G_FAT = 9.0
KCAL_PER_G_CARB = 4.0
KCAL_PER_G_PROTEIN = 4.0


@dataclass(frozen=True)
class Macros:
    kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carb_g: float = 0.0
    fiber_g: float = 0.0

    @staticmethod
    def zero() -> "Macros":
        return Macros()

    def __add__(self, other: "Macros") -> "Macros":
        if not isinstance(other, Macros):
            return NotImplemented
        return Macros(
            kcal=self.kcal + other.kcal,
            protein_g=self.protein_g + other.protein_g,
            fat_g=self.fat_g + other.fat_g,
            carb_g=self.carb_g + other.carb_g,
            fiber_g=self.fiber_g + other.fiber_g,
        )

    __radd__ = __add__

    def scale(self, factor: float) -> "Macros":
        return Macros(
            kcal=self.kcal * factor,
            protein_g=self.protein_g * factor,
            fat_g=self.fat_g * factor,
            carb_g=self.carb_g * factor,
            fiber_g=self.fiber_g * factor,
        )

    def replace(self, **kwargs: float) -> "Macros":
        return replace(self, **kwargs)


def profile_targets(
    kcal: float, fat_pct: float, carb_pct: float, protein_pct: float
) -> Macros:
    """Convert a profile's percentage split into gram targets."""
    return Macros(
        kcal=kcal,
        fat_g=kcal * fat_pct / 100.0 / KCAL_PER_G_FAT,
        carb_g=kcal * carb_pct / 100.0 / KCAL_PER_G_CARB,
        protein_g=kcal * protein_pct / 100.0 / KCAL_PER_G_PROTEIN,
    )
