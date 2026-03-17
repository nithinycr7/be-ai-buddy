from __future__ import annotations
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent.parent / "learning_engine.db"
SCHEMA_PATH = Path(__file__).parent / "learning_engine_schema.sql"


def init_learning_db():
    """Initialize SQLite DB with schema. Called once on startup."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        if SCHEMA_PATH.exists():
            conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    _seed_data()


def _seed_data():
    """Seed example concept data if DB is empty."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] > 0:
            return

        # Chapter
        conn.execute(
            "INSERT OR IGNORE INTO chapters (name, subject, grade, curriculum, sequence) VALUES (?,?,?,?,?)",
            ("Laws of Motion", "Physics", 9, "CBSE", 9)
        )
        row = conn.execute(
            "SELECT id FROM chapters WHERE name='Laws of Motion' AND curriculum='CBSE'"
        ).fetchone()
        chapter_id = row[0]

        # Concepts: (name, slug, concept_type, grade_min, grade_max, subject, chapter_id, keywords)
        concepts = [
            ("Newton's First Law",  "newtons-first-law",  "concept",      8, 9, "Physics", chapter_id, '["inertia","motion","rest","force"]'),
            ("Newton's Second Law", "newtons-second-law", "equation",     8, 9, "Physics", chapter_id, '["F=ma","force","mass","acceleration","newton second"]'),
            ("Newton's Third Law",  "newtons-third-law",  "relationship", 8, 9, "Physics", chapter_id, '["action","reaction","equal","opposite"]'),
            ("Inertia",             "inertia",            "concept",      6, 9, "Physics", None,       '["rest","motion","resistance","change"]'),
            ("Force",               "force",              "concept",      5, 9, "Physics", None,       '["push","pull","newton","N"]'),
            ("Mass",                "mass",               "concept",      4, 9, "Physics", None,       '["weight","kilograms","matter"]'),
            ("Acceleration",        "acceleration",       "equation",     7, 9, "Physics", None,       '["velocity","change","rate","m/s2"]'),
            ("Photosynthesis",      "photosynthesis",     "process",      5, 9, "Biology", None,       '["plants","sunlight","glucose","chlorophyll","food"]'),
            ("Water Cycle",         "water-cycle",        "process",      4, 8, "Geography", None,     '["evaporation","condensation","precipitation","rain"]'),
            ("Area of Circle",      "area-of-circle",     "equation",     5, 9, "Math",    None,       '["pi","radius","area","circle","pir2"]'),
        ]

        for name, slug, ctype, gmin, gmax, subj, chid, keywords in concepts:
            conn.execute(
                """INSERT OR IGNORE INTO concepts
                   (name, slug, concept_type, grade_min, grade_max, subject, chapter_id, curriculum, keywords)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'CBSE', ?)""",
                (name, slug, ctype, gmin, gmax, subj, chid, keywords)
            )

        # Relationships
        rels = [
            ("inertia",            "newtons-first-law",  "part_of",  1.0),
            ("newtons-first-law",  "newtons-second-law", "leads_to", 0.9),
            ("newtons-second-law", "newtons-third-law",  "leads_to", 0.9),
            ("force",              "newtons-second-law", "related",  1.0),
            ("mass",               "newtons-second-law", "related",  1.0),
            ("acceleration",       "newtons-second-law", "related",  1.0),
        ]
        for src_slug, tgt_slug, rel, strength in rels:
            src = conn.execute("SELECT id FROM concepts WHERE slug=?", (src_slug,)).fetchone()
            tgt = conn.execute("SELECT id FROM concepts WHERE slug=?", (tgt_slug,)).fetchone()
            if src and tgt:
                conn.execute(
                    """INSERT OR IGNORE INTO concept_relationships
                       (source_concept_id, target_concept_id, relationship_type, strength)
                       VALUES (?, ?, ?, ?)""",
                    (src[0], tgt[0], rel, strength)
                )

        conn.commit()


@contextmanager
def get_sqlite_db():
    """Context manager for SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
