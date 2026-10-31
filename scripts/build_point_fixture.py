"""Build tests/fixtures/point_system.json from the coach's point system lists.

Session tooling, not product code: run it by hand, it reads USDA
FoodData Central (cached), and writes the committed fixture. Coach portions
come from the coach's workbook ("Jen Crawford Point System Plan.xlsx"), the
source of truth; Claude-added foods come from the Claude copy and are
unverified.
"""
import json
import sys
import time
from pathlib import Path

from yolk.errors import SourceRequestError
from yolk.sources import usda

OUT = Path(sys.argv[1])
G = {"fat": 15.0, "carb": 25.0, "protein": 25.0, "veggie": 10.0}
OZ = 28.349523125


def fetch(fdc):
    for _ in range(4):
        try:
            payload = usda.get_food(fdc)
            break
        except SourceRequestError:
            time.sleep(2)
    else:
        raise SystemExit(f"could not fetch {fdc}")
    raw = {}
    for x in payload.get("foodNutrients", []):
        nid = x.get("nutrient", {}).get("id")
        if nid in (1008, 2047, 2048, 1003, 1004, 1005, 1079) and nid not in raw:
            raw[nid] = x.get("amount")
    kcal = raw.get(1008) or raw.get(2048) or raw.get(2047)
    return payload["description"], {
        "kcal": round(kcal, 2),
        "fat_g": round(raw.get(1004) or 0.0, 3),
        "carb_g": round(raw.get(1005) or 0.0, 3),
        "fiber_g": None if raw.get(1079) is None else round(raw[1079], 3),
        "protein_g": round(raw.get(1003) or 0.0, 3),
    }


def per_100(serving_g, kcal, fat, carb, fiber, protein):
    f = 100.0 / serving_g
    return {
        "kcal": round(kcal * f, 2), "fat_g": round(fat * f, 3),
        "carb_g": round(carb * f, 3),
        "fiber_g": None if fiber is None else round(fiber * f, 3),
        "protein_g": round(protein * f, 3),
    }


FOODS = []


def food(name, role, cls, *, fdc=None, macros=None, units=None, coach=None,
         claude=None, note="", verified=None, brand="", source=None):
    """coach / claude: (qty, unit, claimed)."""
    if fdc is not None:
        desc, m = fetch(fdc)
        src, ref = "usda", str(fdc)
        note = f"USDA FDC {fdc}: {desc}. {note}".strip()
    else:
        m, src, ref = macros, source or "label", None
    portions = []
    if coach:
        portions.append({"source": "coach", "qty": coach[0], "unit": coach[1], "claimed": coach[2]})
    if claude:
        portions.append({"source": "claude", "qty": claude[0], "unit": claude[1], "claimed": claude[2]})
    if verified is None:
        verified = fdc is not None and claude is None
    FOODS.append({
        "name": name, "brand": brand, "role": role, "point_class": cls,
        "macros_100g": m, "source": src, "source_ref": ref, "verified": verified,
        "units": units or {}, "portions": portions, "source_note": note,
    })


RECALLED = ("Label figures recalled from the product's published nutrition panel, "
            "not read from a package in hand; check against your package.")
ESTIMATE = "Claude's estimate with no single label behind it; check before relying on it."

# --- Coach: FAT OPTIONS = 15 grams each ------------------------------------
food("Hummus", "fat", "fat", fdc=174289, units={"tbsp": 15, "cup": 246}, coach=(3, "tbsp", "1F"))
food("Baba ghanoush", "fat", "fat", fdc=2710049, units={"cup": 230},
     coach=(1, "cup", "1F"), note="FNDDS 'Eggplant dip'; cup weight assumed 230 g.")
food("Sour cream", "fat", "fat", fdc=171257, units={"tbsp": 12, "cup": 230}, coach=(1 / 3, "cup", "1F"))
food("Almonds", "fat", "fat", fdc=2346393, units={"almond": 1.2, "cup": 143},
     coach=(25, "almond", "1F"),
     note="Coach tabs disagree (25 vs 15 almonds); 25 kept because 25 almonds is about 15 g fat.")
food("Peanut butter", "fat", "fat", units={"tablespoon": 16.0},
     macros={"kcal": 587.5, "fat_g": 50.62, "carb_g": 19.38, "fiber_g": None, "protein_g": 25.0},
     coach=(2, "tablespoon", "1F"), source="usda",
     note="Coach line '2 TBSP NUT BUTTER'; tabs disagree (2 vs 1.5 tbsp), 2 kept by macros. "
          "Attaches to the existing Keto Plan A peanut butter.")
food("Almond butter", "fat", "fat", fdc=168588, units={"tbsp": 16, "cup": 250},
     coach=(2, "tbsp", "1F"), note="Coach's samples use almond butter as the nut butter.")
food("Coconut oil", "fat", "fat", fdc=171412, units={"tbsp": 13.6, "tsp": 4.5}, coach=(1, "tbsp", "1F"))
food("Extra Virgin Olive Oil", "fat", "fat", units={"tbsp": 13.5},
     macros={"kcal": 888.89, "fat_g": 103.7, "carb_g": 0.0, "fiber_g": None, "protein_g": 0.0},
     coach=(1, "tbsp", "1F"), source="usda",
     note="Attaches to the existing Keto Plan A olive oil.")
food("Egg, whole", "fat", "fat", fdc=171287, units={"egg": 50}, coach=(3, "egg", "1F"),
     note="Large egg, 50 g.")
food("Egg yolk", "fat", "fat", fdc=172184, units={"yolk": 17}, coach=(2, "yolk", "1F"))
food("Mayonnaise", "fat", "fat", fdc=171009, units={"tbsp": 13.8}, coach=(1.5, "tbsp", "1F"),
     note="Coach tabs disagree (1.5 vs 1 tbsp); 1.5 kept by macros.")
food("Grass-fed butter", "fat", "fat", fdc=173410, units={"tbsp": 14.2}, coach=(1.5, "tbsp", "1F"),
     note="Coach tabs disagree (1.5 vs 1 tbsp); 1.5 tbsp is 1.15F and 1 tbsp 0.77F, so 1.5 kept.")
food("Curry, milk base", "fat", "fat", units={"cup": 240},
     macros={"kcal": 140, "fat_g": 12.0, "carb_g": 7.0, "fiber_g": 1.0, "protein_g": 2.0},
     coach=(0.5, "cup", "1F"), verified=False, source="manual", note=ESTIMATE)
food("Bitchin' Sauce", "fat", "fat", brand="Bitchin'", units={"tbsp": 14},
     macros=per_100(28, 100, 9, 3, 1, 2), coach=(2, "tbsp", "1F"), verified=False, note=RECALLED)
food("Green goddess dressing", "fat", "fat", fdc=169057, units={"tbsp": 15, "cup": 245},
     coach=(1, "cup", "1F"),
     note="USDA regular green goddess is oil-based; the coach's 1 cup likely means a light, "
          "yogurt-based bottle. Check the one you buy.")
food("Buffalo sauce", "fat", "fat", fdc=2709751, units={"cup": 240},
     coach=(0.25, "cup", "1F"),
     note="USDA buffalo sauce is nearly fat-free; the coach likely means a butter- or "
          "oil-based buffalo sauce. Check your bottle.")
food("Tzatziki", "fat", "fat", fdc=2705448, units={"cup": 240}, coach=(1, "cup", "1F"),
     note="FNDDS 'Tzatziki dip'; cup weight assumed 240 g.")

# --- Coach: CARB OPTIONS = 25 grams each -----------------------------------
food("Red potatoes, baked", "carb", "carb", fdc=170435, coach=(4, "oz", "1C"))
food("Farro, dry", "carb", "carb", fdc=2710828, units={"cup dry": 188},
     coach=(0.25, "cup dry", "1C"),
     note="Coach line '3/4 cup cooked (1/4 cup dry) farro'; no USDA cooked farro, so measured dry.")
food("Bulgur, cooked", "carb", "carb", fdc=170287, units={"cup": 182}, coach=(1, "cup", "1C"))
food("Japanese BBQ sauce", "carb", "carb", fdc=171167, units={"tbsp": 18},
     coach=(2.5, "tbsp", "1C"),
     note="USDA teriyaki sauce stands in for Japanese BBQ sauce; check your bottle.")
food("Crackers (Ritz, saltines, Wheat Thins)", "carb", "carb", fdc=174982,
     units={"cracker": 3.2}, coach=(12, "cracker", "1C"))
food("Sweet potato, baked", "carb", "carb", fdc=168483, units={"cup": 200}, coach=(5, "oz", "1C"))
food("High fiber English muffin", "carb", "carb", units={"muffin": 57},
     macros=per_100(57, 100, 1, 26, 8, 5), coach=(1, "muffin", "1C"), verified=False,
     note="Thomas' Light Multi-Grain style. " + RECALLED)
food("Rolled oats, dry", "carb", "carb", fdc=173904, units={"cup": 81}, coach=(0.5, "cup", "1C"))
food("Green Machine juice, mini", "carb", "carb", brand="Naked", units={"bottle": 296},
     macros=per_100(296, 180, 0, 42, 1, 2.7), coach=(1, "bottle", "1C"), verified=False,
     note="10 fl oz bottle assumed. " + RECALLED)
food("Bagel, plain", "carb", "carb", fdc=174899, units={"large bagel": 131},
     coach=(0.5, "large bagel", "1C"))
food("Apple", "carb", "carb", fdc=171688, units={"apple": 182, "cup slices": 109},
     coach=(1, "apple", "1C"), note="Medium apple, 182 g.")
food("Rice, white, cooked", "carb", "carb", fdc=168878, units={"cup": 158}, coach=(0.5, "cup", "1C"))
food("Rice, brown, cooked", "carb", "carb", fdc=169704, units={"cup": 202}, coach=(0.5, "cup", "1C"))
food("Quinoa, cooked", "carb", "carb", fdc=168917, units={"cup": 185}, coach=(2 / 3, "cup", "1C"))
food("Pasta, cooked", "carb", "carb", fdc=169737, units={"cup": 124}, coach=(0.5, "cup", "1C"),
     note="Spaghetti, cup not packed, 124 g.")
food("Low carb tortilla, large", "carb", "carb", units={"tortilla": 71},
     macros=per_100(71, 120, 4, 26, 19, 6), coach=(1, "tortilla", "1C"), verified=False,
     note="Mission Carb Balance burrito size. " + RECALLED)
food("Black beans, cooked", "carb", "carb", fdc=173735, units={"cup": 172}, coach=(0.75, "cup", "1C"))
food("Blueberries", "carb", "carb", fdc=171711, units={"cup": 148}, coach=(1, "cup", "1C"),
     note="Coach line '1 cup berries' / '1 cup frozen berries'; blueberries stand in.")
food("Rice cakes, plain", "carb", "carb", fdc=170250, units={"cake": 9}, coach=(4, "cake", "1C"))
food("Ezekiel bread", "carb", "carb", brand="Food for Life", units={"slice": 34},
     macros=per_100(34, 80, 0.5, 15, 3, 5), coach=(2, "slice", "1C"), verified=False, note=RECALLED)
food("Hash browns, frozen", "carb", "carb", fdc=170043, units={"cup": 210}, coach=(4, "oz", "1C"),
     note="Weighed frozen, before cooking.")
food("Jerk sauce", "carb", "carb", units={"cup": 255},
     macros={"kcal": 110, "fat_g": 0.5, "carb_g": 25.0, "fiber_g": 1.0, "protein_g": 1.0},
     coach=(1 / 3, "cup", "1C"), verified=False, source="manual", note=ESTIMATE)
food("Orange", "carb", "carb", fdc=746771, units={"orange": 140}, coach=(1, "orange", "1C"))
food("Grapefruit, pink", "carb", "carb", fdc=174673, units={"grapefruit": 246},
     coach=(0.5, "grapefruit", "1C"),
     note="Coach says 1/2 large grapefruit; USDA's whole fruit (3-3/4\") is 246 g.")

# --- Coach: PROTEIN OPTIONS = 25 grams each --------------------------------
food("Kielbasa", "protein", "protein", fdc=173877, coach=(7, "oz", "1P"))
food("Chicken breast, raw", "protein", "protein", fdc=171077, coach=(4, "oz", "1P"))
food("Chicken thigh, roasted", "protein", "protein", fdc=172388, coach=(3.5, "oz", "1P"),
     note="The coach's 3.5 oz thigh matches cooked weight, not raw.")
food("Tuna, canned in water", "protein", "protein", fdc=171986, coach=(4, "oz", "1P"))
food("Liquid egg whites", "protein", "protein", fdc=172183, units={"cup": 243, "egg white": 33},
     coach=(1, "cup", "1P"),
     note="Coach also lists 6 hard-boiled egg whites; same food, 33 g per white.")
food("Salmon, Atlantic, farmed, raw", "protein", "protein", fdc=175167, coach=(4, "oz", "1P"))
food("Whey protein powder", "protein", "protein", fdc=173180, units={"scoop": 32},
     coach=(1, "scoop", "1P"), note="Scoop assumed 32 g; check your tub.")
food("Mahi mahi, raw", "protein", "protein", fdc=171959, coach=(4, "oz", "1P"))
food("Ground turkey, 99% fat free, raw", "protein", "protein", fdc=172847, coach=(4, "oz", "1P"))
food("Shrimp, raw", "protein", "protein", fdc=175179, units={"large shrimp": 7},
     coach=(15, "large shrimp", "1P"), note="Large shrimp assumed 7 g each peeled; count sizes vary.")
food("Prosciutto", "protein", "protein", units={"slice": 14},
     macros={"kcal": 250, "fat_g": 16.0, "carb_g": 0.5, "fiber_g": 0.0, "protein_g": 26.0},
     coach=(3, "oz", "1P"), verified=False, source="manual",
     note="Coach line '3 oz prosciutto or bresaola'. " + ESTIMATE)
food("Salami, hard", "protein", "protein", fdc=172938, units={"slice": 10}, coach=(4, "oz", "1P"),
     note="Coach line '4 oz salami/genoa or pepperoni'.")
food("Turkey bacon", "protein", "protein", fdc=171639, units={"slice": 8.1}, coach=(7, "slice", "1P"),
     note="Coach tabs disagree (7 vs 6 slices); by macros neither reaches a point, 7 is closer.")
food("Cottage cheese, low fat", "protein", "protein", fdc=172182, units={"cup": 226},
     coach=(0.5, "cup", "1P"))
food("Deli turkey", "protein", "protein", fdc=172941, units={"slice": 16}, coach=(4, "oz", "1P"))
food("Chicken sausage", "protein", "protein", fdc=2706200, units={"link": 68},
     coach=(2, "link", "1P"), note="Link assumed 68 g.")
food("Pork bacon", "protein", "protein", fdc=168322, units={"slice": 11.5}, coach=(8, "slice", "1P"))
food("Ground beef, 93% lean, raw", "protein", "protein", fdc=173110, coach=(4, "oz", "1P"),
     note="Coach lines '4 oz ground beef' / '4 oz lean ground beef'.")
food("Sirloin steak, raw", "protein", "protein", fdc=2727574, coach=(4, "oz", "1P"))
food("Tilapia, raw", "protein", "protein", fdc=175176, coach=(4, "oz", "1P"))
food("Sashimi (yellowfin tuna)", "protein", "protein", fdc=175159, coach=(4, "oz", "1P"))
food("Premier Protein shake", "protein", "protein", brand="Premier Protein",
     units={"shake": 340}, macros=per_100(340, 160, 3, 4, 1, 30), coach=(1, "shake", "1P"),
     verified=False, note=RECALLED)
food("Quest Bar", "carb", None, brand="Quest", units={"bar": 60},
     macros={**per_100(60, 190, 8, 22, 14, 21), "sugar_alcohol_g": round(5 * 100 / 60, 3)},
     coach=(1, "bar", "meal replacement"), verified=False,
     note="Coach lists it as a meal replacement. " + RECALLED)

# --- Coach: VEGGIE OPTIONS = 10 grams carb ---------------------------------
food("Kale, raw", "veg", "veggie", fdc=168421, units={"cup": 21}, coach=(2, "cup", "1V"))
food("Zucchini, cooked", "veg", "veggie", fdc=169292, units={"cup": 180}, coach=(1, "cup", "1V"),
     note="Coach line '1 cup zucchini/squash'.")
food("Broccoli, cooked", "veg", "veggie", fdc=169967, units={"cup": 156}, coach=(1, "cup", "1V"))
food("Green beans, cooked", "veg", "veggie", fdc=169141, units={"cup": 125}, coach=(1, "cup", "1V"))
food("Brussels sprouts, cooked", "veg", "veggie", fdc=169971, units={"cup": 156}, coach=(1, "cup", "1V"))

# --- Coach: FREE FOODS -----------------------------------------------------
food("Sugar free jello", "sauce", "free", fdc=169598, units={"cup": 234})
food("Broth", "beverage", "free", fdc=171583, units={"cup": 221},
     note="Coach line 'broth: beef, veggie, chicken'; vegetable broth stands in.")
food("Leafy greens", "veg", "free", fdc=169249, units={"cup": 36}, note="Green leaf lettuce stands in.")
food("Mustard", "sauce", "free", fdc=172234, units={"tsp": 5})
food("Celery", "veg", "free", fdc=169988, units={"stalk": 40, "cup": 101})

# --- Foods the coach's Sample Option 1 needs -------------------------------
food("Potatoes, boiled", "carb", "carb", fdc=170438, units={"cup": 156})
food("Cheddar, sharp", "fat", None, fdc=170899, units={"slice": 28})

# --- Claude-added options (not from the coach) -----------------------------
for name, fdc, qty, claimed, note in (
    ("Chicken tenderloins, raw", 171077, 4, "1P", "Same USDA entry as raw chicken breast."),
    ("Rotisserie chicken breast, no skin", 171518, 3, "1P", "Cooked."),
    ("Ground chicken, raw", 171116, 5, "1P + ¾F", ""),
    ("Ground beef, 95% lean, raw", 171790, 4, "1P", ""),
    ("Ground beef, 90% lean, raw", 174030, 4.5, "1P + 1F", ""),
    ("Eye of round, raw", 746760, 4, "1P", "Coach-style line '4 oz eye of round / top round'."),
    ("Flank steak, raw", 169433, 4.25, "1P + ½F", ""),
    ("Tri-tip, raw", 168736, 4.5, "1P + ½F", ""),
    ("Skirt steak, raw", 172137, 4.75, "1P + ¾F", ""),
    ("NY strip, raw", 173116, 4.5, "1P + ¾F", ""),
    ("Ribeye, raw", 173380, 5, "1P + 1½F", ""),
    ("Chuck roast, raw", 2646174, 5, "1P + 1F", ""),
):
    food(name, "protein", "protein", fdc=fdc, claude=(qty, "oz", claimed), verified=False, note=note)
food("Ground beef, 85% lean, raw", "protein", "protein",
     macros={"kcal": 215, "fat_g": 15.0, "carb_g": 0.0, "fiber_g": 0.0, "protein_g": 18.59},
     claude=(4.75, "oz", "1P + 1¼F"), verified=False, source="manual",
     note="USDA 85/15 raw values, recalled rather than fetched; check.")

for name, fdc, units, qty, unit, note in (
    ("Cauliflower, raw", 169986, {"cup": 107}, 2, "cup", "Coach-style line '2 cups cauliflower / cauli rice'."),
    ("Bell pepper, red", 170108, {"pepper": 164, "cup": 149}, 1, "pepper", "Large pepper, 164 g."),
    ("Asparagus, raw", 168389, {"cup": 134}, 1.5, "cup", ""),
    ("Spinach, cooked", 168463, {"cup": 180}, 1.5, "cup", ""),
    ("Mushrooms, cooked", 169252, {"cup": 156}, 1.25, "cup", ""),
    ("Cabbage, shredded", 169975, {"cup": 70}, 2.5, "cup", "Coach-style line 'shredded cabbage / slaw mix'."),
    ("Carrots", 170393, {"cup": 128}, 0.75, "cup", ""),
    ("Cherry tomatoes", 170457, {"cup": 149, "cherry": 17}, 1.5, "cup", ""),
    ("Snap peas", 170010, {"cup": 98}, 1.5, "cup", ""),
    ("Spaghetti squash, cooked", 169299, {"cup": 155}, 1, "cup", ""),
    ("Butternut squash", 169295, {"cup": 140}, 0.5, "cup", ""),
    ("Eggplant", 169228, {"cup": 82}, 1, "cup", ""),
    ("Okra", 169260, {"cup": 100}, 1.25, "cup", ""),
    ("Cucumber", 168409, {"cucumber": 301, "cup": 104}, 1, "cucumber", "Large cucumber, 301 g."),
):
    food(name, "veg", "veggie", fdc=fdc, units=units, claude=(qty, unit, "1V"), verified=False, note=note)
food("Roasted peppers and onions", "veg", "veggie", units={"cup": 150},
     macros={"kcal": 33, "fat_g": 0.2, "carb_g": 7.7, "fiber_g": 1.9, "protein_g": 1.0},
     claude=(1, "cup", "1V"), verified=False, source="manual",
     note="Half red pepper, half onion. " + ESTIMATE)
food("Pico de gallo", "veg", "veggie", units={"cup": 160},
     macros={"kcal": 22, "fat_g": 0.2, "carb_g": 5.0, "fiber_g": 1.2, "protein_g": 0.9},
     claude=(1, "cup", "1V"), verified=False, source="manual", note=ESTIMATE)

# --- Costco haul, 2026-10-31 (Claude's Costco Items tab, label figures) -----
COSTCO = ("Costco haul 2026-10-31. Figures from Claude's Costco Items tab (package labels and "
          "retailer listings, Oct 2026), scaled from the portion shown; check your package.")
food("NuTrail Nut Granola, Blueberry Cinnamon", "fat", "fat", brand="NuTrail", units={"cup": 90},
     macros={**per_100(30, 170, 15, 9, 3, 4), "sugar_alcohol_g": round(4 * 100 / 30, 3)},
     claude=(1 / 3, "cup", "1F"), verified=False,
     note=COSTCO + " Fiber 3 g and sugar alcohol 4 g split assumed from 7 g combined.")
food("Chicken Birria", "protein", "protein", brand="On The Street Foods", units={},
     macros={**per_100(113, 150, 7, 1, None, 20)}, claude=(5, "oz", "1P + ½F"), verified=False,
     note=COSTCO + " Label: 4 oz = 150 cal, 20P/1C/7F.")
food("Carne Asada", "protein", "protein", brand="On The Street Foods",
     macros=per_100(128, 165 * 1.28, 11, 3, None, 25), claude=(4.5, "oz", "1P + ¾F"), verified=False,
     note=COSTCO + " Based on a sibling OTS carne asada listing; check your bag.")
food("Rustic Zuppa Toscana", "carb", None, brand="Ivar's", units={"cup": 245},
     macros=per_100(326, 271, 15, 24, None, 10), claude=(4 / 3, "cup", "1F + 1C"), verified=False,
     note=COSTCO + " Low protein; add a protein. Fiber not on the listing.")
food("Grassfed Beef Stroganoff", "carb", None, brand="Kevin's", units={"cup": 189},
     macros=per_100(283, 351, 15, 30, None, 24), claude=(1.5, "cup", "1F + 1C + 1P"), verified=False,
     note=COSTCO + " Cup weight from 40 oz = 4 portions of 1.5 cups. Fiber not on the listing.")
food("Cottage Cheese Protein Pancakes", "carb", None, brand="Crepini", units={"pancake": 30},
     macros=per_100(120, 216, 4, 25, 1, 20), claude=(4, "pancake", "1C + 1P"), verified=False,
     note=COSTCO + " Pancake weight assumed 30 g. 10 g added sugar per 4 pancakes.")
food("Cucumber Tzatziki", "fat", None, brand="Yaza", units={"cup": 240},
     macros=per_100(180, 258, 14, 12, 0, 21), claude=(0.75, "cup", "1F + ¾P"), verified=False,
     note=COSTCO + " Richer than the coach's generic tzatziki.")
food("Organic Madras Lentils", "carb", "carb", brand="Tasty Bite", units={"pouch": 285},
     macros=per_100(285, 254, 6, 38, 10, 12), claude=(1, "pouch", "1½C + ½P"), verified=False,
     note=COSTCO + " Non-dairy recipe; the older cream and butter recipe has more fat.")

# --- Points arithmetic for the report -------------------------------------
MASS = {"g": 1.0, "oz": OZ}


def grams(f, qty, unit):
    return qty * (MASS.get(unit) or f["units"][unit])


def points(f, g):
    m = f["macros_100g"]
    s = g / 100.0
    carbs = m["carb_g"] * s
    cls = f["point_class"]
    if cls == "free":
        return {"fat": 0, "carb": 0, "protein": 0, "veggie": 0}
    return {
        "fat": m["fat_g"] * s / G["fat"],
        "carb": 0 if cls == "veggie" else carbs / G["carb"],
        "protein": m["protein_g"] * s / G["protein"],
        "veggie": carbs / G["veggie"] if cls == "veggie" else 0,
    }


def main_type(f):
    if f["point_class"] in ("fat", "carb", "protein", "veggie"):
        return f["point_class"]
    p = points(f, 100)
    return max(("fat", "carb", "protein", "veggie"), key=lambda k: p[k])


flagged = []
for f in FOODS:
    for portion in f["portions"]:
        if portion["source"] != "coach" or f["point_class"] == "free":
            continue
        p = points(f, grams(f, portion["qty"], portion["unit"]))
        main = main_type(f)
        if not 0.75 <= p[main] <= 1.25:
            letter = main[0].upper() if main != "veggie" else "V"
            f["source_note"] = (f"FLAG: computes {p[main]:.2f}{letter} at the coach's portion. "
                                + f["source_note"]).strip()
            flagged.append(f"{f['name']}: {portion['qty']:g} {portion['unit']} = {p[main]:.2f}{letter}")
            # Checked means the macros came from USDA or a label AND the coach's
            # portion checks out; a flagged line does not.
            f["verified"] = False

BY_NAME = {f["name"]: f for f in FOODS}
SLOTS = [
    {"slot_no": 1, "name": "7:00", "time_of_day": "07:00", "fat": 1, "carb": 1, "protein": 1, "veggie": 0},
    {"slot_no": 2, "name": "10:00", "time_of_day": "10:00", "fat": 1, "carb": 0, "protein": 1, "veggie": 0},
    {"slot_no": 3, "name": "12:30", "time_of_day": "12:30", "fat": 1, "carb": 1, "protein": 1, "veggie": 0},
    {"slot_no": 4, "name": "3:00", "time_of_day": "15:00", "fat": 1, "carb": 0, "protein": 1, "veggie": 0},
    {"slot_no": 5, "name": "5:30", "time_of_day": "17:30", "fat": 1, "carb": 0, "protein": 1, "veggie": 0},
    {"slot_no": 6, "name": "8:30", "time_of_day": "20:30", "fat": 1, "carb": 1, "protein": 1, "veggie": 1},
]
SAMPLE_1 = [
    (1, [("Potatoes, boiled", 1, "cup"), ("Egg, whole", 2, "egg"), ("Pork bacon", 2, "slice")]),
    (2, [("Whey protein powder", 1, "scoop"), ("Almond butter", 2, "tbsp")]),
    (3, [("Quest Bar", 1, "bar"), ("Orange", 0.5, "orange")]),
    (4, [("Deli turkey", 3, "slice"), ("Cheddar, sharp", 2, "oz")]),
    (5, [("Almonds", 25, "almond"), ("Whey protein powder", 1, "scoop")]),
    (6, [("Salmon, Atlantic, farmed, raw", 4, "oz"), ("Broccoli, cooked", 1, "cup"),
         ("Rice, white, cooked", 0.5, "cup")]),
]
samples, misses = [], []
for slot_no, entries in SAMPLE_1:
    total = {"fat": 0.0, "carb": 0.0, "protein": 0.0, "veggie": 0.0}
    for name, qty, unit in entries:
        f = BY_NAME[name]
        for k, v in points(f, grams(f, qty, unit)).items():
            total[k] += v
    slot = SLOTS[slot_no - 1]
    off = [f"{k} {total[k]:.2f} vs {slot[k]}" for k in total if abs(total[k] - slot[k]) > 0.25]
    if off:
        misses.append({
            "sample": "Sample Option 1", "slot_no": slot_no,
            "points": {k: round(v, 4) for k, v in total.items()},
            "reason": "The coach's sample is a rough guide; by macros it lands at " + "; ".join(off) + ".",
        })
    samples.append({"slot_no": slot_no, "entries": [
        {"food": n, "qty": q, "unit": u} for n, q, u in entries
    ]})

fixture = {
    "_about": ("The coach's point system (Jen Crawford Point System Plan.xlsx) as seed data. "
               "Built in session by Claude on 2026-10-31 from USDA FoodData Central and package "
               "labels. Coach portions are kept as the coach wrote them; FLAG notes mark lines "
               "whose macros disagree."),
    "person": "Jen",
    "profile": {"name": "Active recovery", "effective_on": "2026-10-31",
                "kcal_tol_pct": 5.0, "protein_tol_g": 8.0, "macro_pct_tol": 3.0},
    "slots": SLOTS,
    "foods": FOODS,
    "samples": {"Sample Option 1": samples},
    "expected_misses": misses,
}
OUT.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{len(FOODS)} foods, {len(flagged)} flagged, {len(misses)} sample misses")
for line in flagged:
    print("  FLAG", line)
for m in misses:
    print("  MISS", m["slot_no"], m["reason"])
