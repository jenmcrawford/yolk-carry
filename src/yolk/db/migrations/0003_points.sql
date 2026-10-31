-- The point system. One point is a fixed number of grams of one macro; the
-- sizes are data so the coach can change them without touching any food.
-- Points themselves are never stored: they are computed from macros and
-- these rules every time.
CREATE TABLE point_rules (
    point_type      TEXT PRIMARY KEY
                    CHECK (point_type IN ('fat', 'carb', 'protein', 'veggie')),
    grams_per_point REAL NOT NULL CHECK (grams_per_point > 0)
);

INSERT INTO point_rules (point_type, grams_per_point) VALUES
    ('fat', 15), ('carb', 25), ('protein', 25), ('veggie', 10);

-- App-wide settings. carb_basis is 'total' or 'net'; the library validates it.
CREATE TABLE settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

INSERT INTO settings (key, value) VALUES ('carb_basis', 'total');

-- Veggie vs carb is a judgement the macros cannot make, so the class is an
-- override. NULL means automatic: whichever macro gives the most points.
ALTER TABLE foods ADD COLUMN point_class TEXT
    CHECK (point_class IS NULL
           OR point_class IN ('fat', 'carb', 'protein', 'veggie', 'free'));

ALTER TABLE foods ADD COLUMN sugar_alcohol_g_100g REAL;

UPDATE foods SET point_class = 'veggie' WHERE role = 'veg';

-- The portion a source says is one serving of points. One row per source, so
-- the coach's portion survives Jen recording her own beside it.
CREATE TABLE point_portions (
    food_id     INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    source      TEXT NOT NULL CHECK (source IN ('coach', 'claude', 'label', 'manual')),
    qty         REAL NOT NULL CHECK (qty > 0),
    unit        TEXT NOT NULL,
    claimed     TEXT NOT NULL,
    PRIMARY KEY (food_id, source)
);

-- A points profile derives its targets from its slots' allotments, so it
-- stores no kcal or percentages that could drift from them. Changing the
-- CHECKs means rebuilding the table; the runner switches foreign keys off
-- around this script, so slot_templates and day_plans keep every row.
CREATE TABLE macro_profiles_new (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    effective_on    TEXT NOT NULL,
    basis           TEXT NOT NULL DEFAULT 'macros'
                    CHECK (basis IN ('macros', 'points')),
    kcal            REAL,
    fat_pct         REAL,
    carb_pct        REAL,
    protein_pct     REAL,
    kcal_tol_pct    REAL NOT NULL DEFAULT 1.0,
    protein_tol_g   REAL NOT NULL DEFAULT 8.0,
    macro_pct_tol   REAL NOT NULL DEFAULT 3.0,
    UNIQUE (person_id, name, effective_on),
    CHECK ((basis = 'macros' AND kcal IS NOT NULL AND kcal > 0
            AND fat_pct IS NOT NULL AND carb_pct IS NOT NULL
            AND protein_pct IS NOT NULL
            AND abs(fat_pct + carb_pct + protein_pct - 100) < 0.5)
        OR (basis = 'points' AND kcal IS NULL AND fat_pct IS NULL
            AND carb_pct IS NULL AND protein_pct IS NULL))
);

INSERT INTO macro_profiles_new
    (id, person_id, name, effective_on, basis, kcal, fat_pct, carb_pct,
     protein_pct, kcal_tol_pct, protein_tol_g, macro_pct_tol)
SELECT id, person_id, name, effective_on, 'macros', kcal, fat_pct, carb_pct,
       protein_pct, kcal_tol_pct, protein_tol_g, macro_pct_tol
FROM macro_profiles;

DROP TABLE macro_profiles;

ALTER TABLE macro_profiles_new RENAME TO macro_profiles;

-- Each meal's point allotment. Zero under a macros profile.
ALTER TABLE slot_templates ADD COLUMN fat_pts REAL NOT NULL DEFAULT 0 CHECK (fat_pts >= 0);
ALTER TABLE slot_templates ADD COLUMN carb_pts REAL NOT NULL DEFAULT 0 CHECK (carb_pts >= 0);
ALTER TABLE slot_templates ADD COLUMN protein_pts REAL NOT NULL DEFAULT 0 CHECK (protein_pts >= 0);
ALTER TABLE slot_templates ADD COLUMN veggie_pts REAL NOT NULL DEFAULT 0 CHECK (veggie_pts >= 0);
