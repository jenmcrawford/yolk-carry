-- A draft is a day plan with status 'draft'. Changing a CHECK means rebuilding
-- the table: the runner switches foreign keys off around this script and
-- checks them all afterwards, so day_plan_entries keeps every row.
CREATE TABLE day_plans_new (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    profile_id      INTEGER NOT NULL REFERENCES macro_profiles(id) ON DELETE RESTRICT,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived', 'draft')),
    parent_plan_id  INTEGER REFERENCES day_plans(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    notes           TEXT,
    UNIQUE (person_id, name)
);

INSERT INTO day_plans_new
    (id, person_id, profile_id, name, status, parent_plan_id, created_at, notes)
SELECT id, person_id, profile_id, name, status, parent_plan_id, created_at, notes
FROM day_plans;

DROP TABLE day_plans;

ALTER TABLE day_plans_new RENAME TO day_plans;

-- At most one open draft per saved plan. A blank draft has no parent, and
-- unique indexes allow repeated NULLs, so several blank drafts may coexist.
CREATE UNIQUE INDEX idx_one_draft_per_plan
    ON day_plans (parent_plan_id) WHERE status = 'draft';
