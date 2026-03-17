PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS chapters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    subject     TEXT    NOT NULL,
    grade       INTEGER NOT NULL,
    curriculum  TEXT    NOT NULL DEFAULT 'CBSE',
    sequence    INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, grade, curriculum)
);

CREATE TABLE IF NOT EXISTS concepts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    slug            TEXT    NOT NULL,
    description     TEXT,
    concept_type    TEXT    NOT NULL,
    grade_min       INTEGER NOT NULL DEFAULT 3,
    grade_max       INTEGER NOT NULL DEFAULT 9,
    subject         TEXT    NOT NULL,
    chapter_id      INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    curriculum      TEXT    NOT NULL DEFAULT 'CBSE',
    difficulty      TEXT    DEFAULT 'medium',
    keywords        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(slug, curriculum)
);

CREATE TABLE IF NOT EXISTS concept_relationships (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_concept_id   INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    target_concept_id   INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    relationship_type   TEXT    NOT NULL,
    strength            REAL    DEFAULT 1.0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_concept_id, target_concept_id, relationship_type)
);

CREATE TABLE IF NOT EXISTS concept_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_slug    TEXT    NOT NULL,
    grade           INTEGER NOT NULL,
    curriculum      TEXT    NOT NULL DEFAULT 'CBSE',
    learning_mode   TEXT    NOT NULL,
    response_json   TEXT    NOT NULL,
    model_used      TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP,
    UNIQUE(concept_slug, grade, curriculum, learning_mode)
);

CREATE TABLE IF NOT EXISTS learning_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id          TEXT    NOT NULL,
    tenant_id           TEXT    NOT NULL DEFAULT 'demo-school',
    concept_slug        TEXT    NOT NULL,
    learning_mode       TEXT    NOT NULL,
    grade               INTEGER NOT NULL,
    duration_seconds    INTEGER,
    completed           BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_concepts_slug     ON concepts(slug);
CREATE INDEX IF NOT EXISTS idx_concepts_subject  ON concepts(subject, grade_min, grade_max);
CREATE INDEX IF NOT EXISTS idx_concepts_type     ON concepts(concept_type);
CREATE INDEX IF NOT EXISTS idx_rels_src          ON concept_relationships(source_concept_id);
CREATE INDEX IF NOT EXISTS idx_rels_tgt          ON concept_relationships(target_concept_id);
CREATE INDEX IF NOT EXISTS idx_cache_lookup      ON concept_cache(concept_slug, grade, curriculum, learning_mode);
CREATE INDEX IF NOT EXISTS idx_sessions_student  ON learning_sessions(student_id, tenant_id);
