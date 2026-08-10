import pytest

from yolk.macros import Macros, profile_targets


def test_macros_add():
    a = Macros(kcal=100, protein_g=10, fat_g=5, carb_g=2)
    b = Macros(kcal=50, protein_g=3, fat_g=1, carb_g=8)
    total = a + b
    assert total.kcal == 150
    assert total.protein_g == 13
    assert total.fat_g == 6
    assert total.carb_g == 10


def test_macros_scale():
    per_100g = Macros(kcal=200, protein_g=20, fat_g=10, carb_g=4, fiber_g=2)
    scaled = per_100g.scale(1.5)
    assert scaled.kcal == 300
    assert scaled.protein_g == 30
    assert scaled.fiber_g == 3


def test_macros_sum_of_empty_is_zero():
    assert sum([], Macros.zero()) == Macros.zero()


def test_profile_targets_training_day():
    # 2150 kcal at 34% fat / 28% carb / 38% protein
    t = profile_targets(kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38)
    assert t.kcal == 2150
    assert t.fat_g == pytest.approx(81.22, abs=0.01)
    assert t.carb_g == pytest.approx(150.5, abs=0.01)
    assert t.protein_g == pytest.approx(204.25, abs=0.01)


def test_profile_targets_rest_day():
    # 2115 kcal at 39% fat / 18% carb / 43% protein
    t = profile_targets(kcal=2115, fat_pct=39, carb_pct=18, protein_pct=43)
    assert t.fat_g == pytest.approx(91.65, abs=0.01)
    assert t.carb_g == pytest.approx(95.18, abs=0.01)
    assert t.protein_g == pytest.approx(227.36, abs=0.01)
