import pytest

from yolk.macros import Macros
from yolk.points import (
    PointRules,
    Points,
    counted_carbs,
    effective_class,
    format_points,
    load_rules,
    point_hints,
    points_for,
    set_carb_basis,
)

R = PointRules(fat_g=15.0, carb_g=25.0, protein_g=25.0, veggie_g=10.0, carb_basis="total")


def test_load_rules_reads_the_seeded_sizes(db):
    assert load_rules(db) == R


def test_fat_and_protein_points():
    assert points_for(Macros(fat_g=15, protein_g=25), "protein", R) == Points(
        fat=1, protein=1
    )


def test_carbs_are_carb_points_unless_veggie():
    assert points_for(Macros(carb_g=25), "carb", R) == Points(carb=1)
    veggie = points_for(Macros(carb_g=10), "veggie", R)
    assert veggie == Points(veggie=1)
    assert veggie.carb == 0


def test_free_foods_score_zero():
    assert points_for(Macros(fat_g=5, carb_g=3, protein_g=2), "free", R) == Points.zero()


def test_net_carbs_subtract_fiber_and_sugar_alcohol():
    m = Macros(carb_g=9, fiber_g=5, sugar_alcohol_g=2)
    assert counted_carbs(m, "net") == 2
    assert counted_carbs(m, "total") == 9


def test_net_carbs_floor_at_zero():
    assert counted_carbs(Macros(carb_g=3, fiber_g=5), "net") == 0


def test_net_with_unknown_fiber_counts_total():
    assert counted_carbs(Macros(carb_g=30), "net", fiber_known=False) == 30


def test_net_basis_applies_to_points():
    net = PointRules(15, 25, 25, 10, "net")
    assert points_for(Macros(carb_g=31, fiber_g=11), "carb", net) == Points(carb=0.8)


def test_automatic_class_is_largest():
    per_100g = Macros(fat_g=30, protein_g=25)
    assert effective_class(None, per_100g, R) == "fat"
    assert effective_class("veggie", per_100g, R) == "veggie"


def test_format_orders_by_size_then_f_c_p_v():
    assert format_points(Points(fat=0.5, protein=1)) == "1P + ½F"
    assert format_points(Points(1, 1, 1, 0)) == "1F + 1C + 1P"
    assert format_points(Points(protein=1.5)) == "1½P"
    assert format_points(Points(fat=0.1)) == "—"
    assert format_points(Points(carb=0.76, protein=0.96)) == "1P + ¾C"
    assert format_points(Points(veggie=1)) == "1V"


def test_hints_name_shortfalls_and_excess():
    target = Points(1, 1, 1, 0)
    assert point_hints(Points(1, 0.6, 1, 0), target) == ("½C short",)
    assert point_hints(Points(1.5, 1, 1, 0), target) == ("½F over",)
    assert point_hints(Points(1, 0.75, 1, 0), target) == ()
    assert point_hints(Points(1, 0, 1, 0), target) == ("1C short",)


def test_points_add_and_scale():
    assert Points(1, 0, 1, 0) + Points(0, 1, 0, 1) == Points(1, 1, 1, 1)
    assert Points(1, 2, 3, 4).scale(0.5) == Points(0.5, 1, 1.5, 2)


def test_set_carb_basis_validates(db):
    set_carb_basis(db, "net")
    assert load_rules(db).carb_basis == "net"
    with pytest.raises(ValueError):
        set_carb_basis(db, "gross")
    assert load_rules(db).carb_basis == "net"
