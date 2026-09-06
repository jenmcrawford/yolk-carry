PRAGMA foreign_keys = ON;
PRAGMA user_version = 2;

CREATE TABLE people (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE
);

CREATE TABLE tags (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    kind    TEXT NOT NULL
            CHECK (kind IN ('allergen', 'ingredient_class', 'diet', 'attribute'))
);

CREATE TABLE foods (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('item', 'recipe')),
    name            TEXT NOT NULL,
    brand           TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL
                    CHECK (role IN ('protein', 'carb', 'fat', 'veg',
                                    'sauce', 'beverage', 'supplement')),
    kcal_100g       REAL,
    protein_g_100g  REAL,
    fat_g_100g      REAL,
    carb_g_100g     REAL,
    fiber_g_100g    REAL,
    cooked_yield_g  REAL CHECK (cooked_yield_g IS NULL OR cooked_yield_g > 0),
    -- how cooked_yield_g was arrived at. 'raw_derived' means it is the summed
    -- raw component weight, not a measurement: such a recipe's per-100 g figures
    -- are nominal, correct per serving and wrong per gram.
    yield_basis     TEXT CHECK (yield_basis IS NULL
                                OR yield_basis IN ('measured', 'raw_derived')),
    instructions    TEXT,
    source          TEXT NOT NULL
                    CHECK (source IN ('usda', 'off', 'label', 'manual',
                                      'computed', 'cronometer')),
    source_ref      TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    verified_on     TEXT,
    computed_at     TEXT,
    notes           TEXT,
    UNIQUE (name, brand),
    -- items must carry macros; recipes may compute them later
    CHECK (kind = 'recipe' OR (kcal_100g IS NOT NULL
                               AND protein_g_100g IS NOT NULL
                               AND fat_g_100g IS NOT NULL
                               AND carb_g_100g IS NOT NULL))
);

CREATE TABLE food_tags (
    food_id INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (food_id, tag_id)
);

CREATE TABLE food_units (
    id                  INTEGER PRIMARY KEY,
    food_id             INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    unit                TEXT NOT NULL,
    grams               REAL NOT NULL CHECK (grams > 0),
    is_default_display  INTEGER NOT NULL DEFAULT 0 CHECK (is_default_display IN (0, 1)),
    UNIQUE (food_id, unit)
);

CREATE TABLE food_components (
    id              INTEGER PRIMARY KEY,
    parent_food_id  INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    child_food_id   INTEGER NOT NULL REFERENCES foods(id) ON DELETE RESTRICT,
    qty             REAL NOT NULL CHECK (qty > 0),
    unit            TEXT NOT NULL,
    flex            INTEGER NOT NULL DEFAULT 0 CHECK (flex IN (0, 1)),
    flex_min_g      REAL,
    flex_max_g      REAL,
    note            TEXT,
    CHECK (parent_food_id <> child_food_id),
    CHECK (flex = 0 OR (flex_min_g IS NOT NULL
                        AND flex_max_g IS NOT NULL
                        AND flex_min_g <= flex_max_g))
);

CREATE TABLE protocols (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    owner_person_id     INTEGER REFERENCES people(id) ON DELETE CASCADE,
    description         TEXT,
    UNIQUE (name, owner_person_id)
);

CREATE TABLE protocol_rules (
    id              INTEGER PRIMARY KEY,
    protocol_id     INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
    rule            TEXT NOT NULL CHECK (rule IN ('exclude', 'limit', 'prefer')),
    target          TEXT NOT NULL CHECK (target IN ('tag', 'food')),
    target_id       INTEGER NOT NULL,
    limit_g_per_day REAL,
    hard_exclude    INTEGER NOT NULL DEFAULT 0 CHECK (hard_exclude IN (0, 1)),
    note            TEXT,
    CHECK (rule <> 'limit' OR limit_g_per_day IS NOT NULL)
);

CREATE TABLE person_protocols (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    protocol_id INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    started_on  TEXT,
    ended_on    TEXT
);

CREATE TABLE macro_profiles (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    effective_on    TEXT NOT NULL,
    kcal            REAL NOT NULL CHECK (kcal > 0),
    fat_pct         REAL NOT NULL,
    carb_pct        REAL NOT NULL,
    protein_pct     REAL NOT NULL,
    kcal_tol_pct    REAL NOT NULL DEFAULT 1.0,
    protein_tol_g   REAL NOT NULL DEFAULT 8.0,
    macro_pct_tol   REAL NOT NULL DEFAULT 3.0,
    UNIQUE (person_id, name, effective_on),
    CHECK (abs(fat_pct + carb_pct + protein_pct - 100) < 0.5)
);

CREATE TABLE slot_templates (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    profile_id  INTEGER NOT NULL REFERENCES macro_profiles(id) ON DELETE CASCADE,
    slot_no     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    time_of_day TEXT NOT NULL,
    portable    INTEGER NOT NULL DEFAULT 0 CHECK (portable IN (0, 1)),
    fixed       INTEGER NOT NULL DEFAULT 0 CHECK (fixed IN (0, 1)),
    notes       TEXT,
    UNIQUE (profile_id, slot_no)
);

CREATE TABLE slot_template_roles (
    id                  INTEGER PRIMARY KEY,
    slot_template_id    INTEGER NOT NULL REFERENCES slot_templates(id) ON DELETE CASCADE,
    role                TEXT NOT NULL
                        CHECK (role IN ('protein', 'carb', 'fat', 'veg',
                                        'sauce', 'beverage', 'supplement')),
    min_count           INTEGER NOT NULL DEFAULT 1 CHECK (min_count >= 0),
    UNIQUE (slot_template_id, role)
);

CREATE TABLE day_plans (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    profile_id      INTEGER NOT NULL REFERENCES macro_profiles(id) ON DELETE RESTRICT,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived')),
    parent_plan_id  INTEGER REFERENCES day_plans(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    notes           TEXT,
    UNIQUE (person_id, name)
);

CREATE TABLE day_plan_entries (
    id          INTEGER PRIMARY KEY,
    day_plan_id INTEGER NOT NULL REFERENCES day_plans(id) ON DELETE CASCADE,
    slot_no     INTEGER NOT NULL,
    food_id     INTEGER NOT NULL REFERENCES foods(id) ON DELETE RESTRICT,
    qty         REAL NOT NULL CHECK (qty > 0),
    unit        TEXT NOT NULL,
    flex        INTEGER NOT NULL DEFAULT 0 CHECK (flex IN (0, 1)),
    flex_min_g  REAL,
    flex_max_g  REAL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    CHECK (flex = 0 OR (flex_min_g IS NOT NULL
                        AND flex_max_g IS NOT NULL
                        AND flex_min_g <= flex_max_g))
);

CREATE TABLE inventory (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    food_id     INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    location    TEXT NOT NULL CHECK (location IN ('pantry', 'fridge', 'freezer')),
    qty_g       REAL CHECK (qty_g IS NULL OR qty_g >= 0),
    portions    REAL CHECK (portions IS NULL OR portions >= 0),
    status      TEXT NOT NULL DEFAULT 'have'
                CHECK (status IN ('have', 'low', 'out')),
    updated_at  TEXT NOT NULL,
    note        TEXT,
    UNIQUE (person_id, food_id, location)
);

CREATE INDEX idx_food_components_parent ON food_components(parent_food_id);
CREATE INDEX idx_food_components_child ON food_components(child_food_id);
CREATE INDEX idx_day_plan_entries_plan ON day_plan_entries(day_plan_id);
CREATE INDEX idx_food_units_food ON food_units(food_id);
