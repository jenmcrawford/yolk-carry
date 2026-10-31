import pytest

from yolk.config import REPO_ROOT
from yolk.inbox import INBOX_COLUMNS, InboxError, import_inbox

HEADER = ",".join(INBOX_COLUMNS)
GRANOLA = ("NuTrail Nut Granola,NuTrail,Costco,1/3 cup (30 g),30,170,15,9,3,4,4,fat,cup,90,"
           "label photo 2026-10-31")
BIRRIA = ("Chicken Birria,On The Street Foods,Costco,4 oz (113 g),113,150,7,1,,,20,protein,,,"
          "label")


def _write(tmp_path, *rows, name="inbox.csv", **kwargs):
    path = tmp_path / name
    path.write_text("\n".join((HEADER, *rows)) + "\n", encoding=kwargs.get("encoding", "utf-8"))
    return path


def _count(db):
    return db.execute("SELECT count(*) AS n FROM foods").fetchone()["n"]


def test_template_header_matches_columns():
    template = REPO_ROOT / "docs" / "food-inbox-template.csv"
    first = template.read_text(encoding="utf-8-sig").splitlines()[0]
    assert first == HEADER


def test_template_rows_import(db):
    report = import_inbox(db, REPO_ROOT / "docs" / "food-inbox-template.csv")
    assert len(report.created) == 8


def test_imports_valid_rows_unverified(db, tmp_path):
    report = import_inbox(db, _write(tmp_path, GRANOLA, BIRRIA))
    assert report.created == ["NuTrail Nut Granola (NuTrail)", "Chicken Birria (On The Street Foods)"]
    rows = db.execute("SELECT verified, source, notes FROM foods ORDER BY id").fetchall()
    assert [(r["verified"], r["source"]) for r in rows] == [(0, "label"), (0, "label")]
    assert rows[0]["notes"] == "Costco · 1/3 cup (30 g) · label photo 2026-10-31"


def test_unit_grams_become_a_count(db, tmp_path):
    import_inbox(db, _write(tmp_path, GRANOLA))
    portion = db.execute("SELECT qty, unit FROM point_portions").fetchone()
    assert portion["unit"] == "cup"
    assert portion["qty"] == pytest.approx(1 / 3)


def test_blank_fiber_stays_unknown(db, tmp_path):
    import_inbox(db, _write(tmp_path, BIRRIA))
    assert db.execute("SELECT fiber_g_100g FROM foods").fetchone()["fiber_g_100g"] is None


def test_free_food_with_its_kind(db, tmp_path):
    broth = "Bone broth,Kettle & Fire,Sprouts,1 cup (240 g),240,40,0,0,0,,9,free:beverage,cup,240,"
    import_inbox(db, _write(tmp_path, broth))
    row = db.execute("SELECT role, point_class FROM foods").fetchone()
    assert tuple(row) == ("beverage", "free")


def test_one_bad_row_imports_nothing(db, tmp_path):
    no_serving = GRANOLA.replace(",30,170,", ",,170,", 1)
    too_fat = BIRRIA.replace("113,150,7,", "113,150,300,", 1)
    path = _write(tmp_path, no_serving, GRANOLA.replace("NuTrail Nut", "Other"), too_fat)
    with pytest.raises(InboxError) as caught:
        import_inbox(db, path)
    problems = "\n".join(caught.value.problems)
    assert "line 2, serving_g" in problems
    assert "line 4, fat_g" in problems
    assert "line 3" not in problems
    assert _count(db) == 0


def test_existing_name_brand_is_skipped(db, tmp_path):
    import_inbox(db, _write(tmp_path, GRANOLA))
    report = import_inbox(db, _write(tmp_path, GRANOLA, BIRRIA, name="again.csv"))
    assert report.skipped == ["NuTrail Nut Granola (NuTrail)"]
    assert report.created == ["Chicken Birria (On The Street Foods)"]
    assert _count(db) == 2


def test_excel_csv_imports(db, tmp_path):
    path = tmp_path / "excel.csv"
    path.write_bytes(
        ("\r\n".join((HEADER, GRANOLA, BIRRIA)) + "\r\n,,,,,,,,,,,,,,\r\n\r\n")
        .encode("utf-8-sig")
    )
    assert len(import_inbox(db, path).created) == 2


def test_unparseable_numbers_are_named(db, tmp_path):
    path = _write(
        tmp_path,
        GRANOLA.replace(",15,9,", ",12g,9,", 1),
        BIRRIA.replace(",7,1,", ',"1,5",1,', 1),
    )
    with pytest.raises(InboxError) as caught:
        import_inbox(db, path)
    problems = "\n".join(caught.value.problems)
    assert "line 2, fat_g" in problems and "12g" in problems
    assert "line 3, fat_g" in problems and "1,5" in problems


def test_unknown_column_is_refused(db, tmp_path):
    path = tmp_path / "odd.csv"
    path.write_text(HEADER.replace("store", "shop") + "\n" + GRANOLA + "\n", encoding="utf-8")
    with pytest.raises(InboxError) as caught:
        import_inbox(db, path)
    problems = "\n".join(caught.value.problems)
    assert "shop" in problems and "store" in problems
