"""SQLite data access for the learning engine (concepts + sessions).

The learning engine uses SQLite (not Mongo), so this is its repository: the only
place that runs SQL. Synchronous, matching the sqlite driver + the sync endpoints.
"""
from __future__ import annotations

from typing import List, Optional

from app.db.sqlite_db import get_sqlite_db


def track_session(*, student_id: str, tenant: str, slug: str, learning_mode: str, grade: int) -> None:
    with get_sqlite_db() as db:
        db.execute(
            """INSERT INTO learning_sessions
               (student_id, tenant_id, concept_slug, learning_mode, grade)
               VALUES (?, ?, ?, ?, ?)""",
            (student_id, tenant, slug, learning_mode, grade))


def search_concepts(*, q: str, grade: int, curriculum: str, subject: Optional[str]) -> List[dict]:
    with get_sqlite_db() as db:
        sql = """
            SELECT slug, name, concept_type, subject, grade_min, grade_max
            FROM concepts
            WHERE (lower(name) LIKE ? OR keywords LIKE ?)
            AND grade_min <= ? AND grade_max >= ?
            AND curriculum = ?
        """
        params: list = [f"%{q.lower()}%", f"%{q.lower()}%", grade, grade, curriculum]
        if subject:
            sql += " AND subject = ?"
            params.append(subject)
        sql += " LIMIT 10"
        rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def related_concepts(*, slug: str, grade: int) -> List[dict]:
    with get_sqlite_db() as db:
        rows = db.execute(
            """SELECT c2.slug, c2.name, c2.concept_type, cr.relationship_type, cr.strength
               FROM concept_relationships cr
               JOIN concepts c1 ON c1.id = cr.source_concept_id
               JOIN concepts c2 ON c2.id = cr.target_concept_id
               WHERE c1.slug = ? AND c2.grade_min <= ? AND c2.grade_max >= ?
               ORDER BY cr.strength DESC
               LIMIT 8""",
            (slug, grade, grade)).fetchall()
    return [dict(r) for r in rows]
