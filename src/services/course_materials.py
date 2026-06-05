"""
course_materials.py
-------------------
DAL for `course_materials` (PDFs/slides faculty have uploaded) and the
related `mcq_question_bank` rows (auto-generated MCQs awaiting approval
or already faculty-approved).

This module is the read/write layer; the LLM-driven generation logic
sits in mcq_generator.py.

Public API:

    record_material(org_id, subject, *, batch=None, title, file_path,
                    mime_type=None, extracted_text=None,
                    uploaded_by=None) -> dict
    list_materials(org_id, *, subject=None) -> list[dict]
    get_material(material_id) -> dict | None

    bulk_insert_questions(org_id, subject, *, source_material_id,
                          questions, generated_by='llm') -> list[int]
    list_bank(org_id, subject, *, approved_only=False,
              limit=50) -> list[dict]
    approve(org_id, *, ids, approved_by) -> int
    fetch_approved_for_session(org_id, subject, *,
                                count=5) -> list[dict]
        Returns approved questions in the format start_session() expects:
        [{"text": str, "choices": [a,b,c,d], "correct": int}, ...]
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# course_materials
# ---------------------------------------------------------------------------

def record_material(*, org_id: int, subject: str, title: str,
                    file_path: str, batch: Optional[str] = None,
                    mime_type: Optional[str] = None,
                    extracted_text: Optional[str] = None,
                    uploaded_by: Optional[int] = None) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO course_materials
                (org_id, subject, batch, title, file_path,
                 mime_type, extracted_text, uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, org_id, subject, batch, title, file_path,
                      mime_type, uploaded_by, created_at;
            """,
            (org_id, subject, batch, title, file_path,
             mime_type, extracted_text, uploaded_by),
        )
        row = dict(cur.fetchone())
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)
    return row


def list_materials(org_id: int, *,
                   subject: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if subject:
            cur.execute(
                """
                SELECT m.id, m.subject, m.batch, m.title, m.file_path,
                       m.mime_type, m.created_at, m.uploaded_by,
                       u.full_name AS uploaded_by_name
                  FROM course_materials m
                  LEFT JOIN users u ON u.id = m.uploaded_by
                 WHERE m.org_id  = %s
                   AND LOWER(m.subject) = LOWER(%s)
                 ORDER BY m.created_at DESC;
                """,
                (org_id, subject),
            )
        else:
            cur.execute(
                """
                SELECT m.id, m.subject, m.batch, m.title, m.file_path,
                       m.mime_type, m.created_at, m.uploaded_by,
                       u.full_name AS uploaded_by_name
                  FROM course_materials m
                  LEFT JOIN users u ON u.id = m.uploaded_by
                 WHERE m.org_id = %s
                 ORDER BY m.created_at DESC;
                """,
                (org_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def get_material(material_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM course_materials WHERE id = %s;",
            (material_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


def latest_with_text(org_id: int, subject: str) -> Optional[Dict[str, Any]]:
    """Most recent material with non-empty extracted_text, used by mcq_generator."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM course_materials
             WHERE org_id  = %s
               AND LOWER(subject) = LOWER(%s)
               AND extracted_text IS NOT NULL
               AND length(extracted_text) > 100
             ORDER BY created_at DESC
             LIMIT 1;
            """,
            (org_id, subject),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# mcq_question_bank
# ---------------------------------------------------------------------------

def bulk_insert_questions(*, org_id: int, subject: str,
                          source_material_id: Optional[int],
                          questions: List[Dict[str, Any]],
                          generated_by: str = "llm") -> List[int]:
    """
    Insert a batch of question candidates. Each question dict must have
    `question` (str), `choices` (list of 4 str) and `correct_index` (0-3).
    Returns the list of created bank row ids.
    """
    if generated_by not in ("llm", "manual"):
        raise ValueError("generated_by must be 'llm' or 'manual'")

    conn = get_db_connection()
    ids: List[int] = []
    try:
        cur = conn.cursor()
        for q in questions:
            cur.execute(
                """
                INSERT INTO mcq_question_bank
                    (org_id, subject, source_material_id,
                     question, choices, correct_index, generated_by)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                RETURNING id;
                """,
                (org_id, subject, source_material_id,
                 q["question"], json.dumps(q["choices"]),
                 int(q["correct_index"]), generated_by),
            )
            ids.append(cur.fetchone()["id"])
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)
    return ids


def list_bank(org_id: int, subject: str, *,
              approved_only: bool = False,
              limit: int = 50) -> List[Dict[str, Any]]:
    where = ["org_id = %s", "LOWER(subject) = LOWER(%s)"]
    params: List[Any] = [org_id, subject]
    if approved_only:
        where.append("approved_at IS NOT NULL")

    sql = f"""
        SELECT id, subject, source_material_id, question, choices,
               correct_index, generated_by, approved_by, approved_at,
               created_at
          FROM mcq_question_bank
         WHERE {" AND ".join(where)}
         ORDER BY (approved_at IS NULL) ASC, created_at DESC
         LIMIT {int(limit)};
    """

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def approve(*, org_id: int, ids: List[int],
            approved_by: int) -> int:
    """Mark the given bank rows approved. Returns rowcount."""
    if not ids:
        return 0
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE mcq_question_bank
               SET approved_by = %s,
                   approved_at = NOW()
             WHERE org_id = %s
               AND id = ANY(%s);
            """,
            (approved_by, org_id, list(ids)),
        )
        rc = cur.rowcount
        conn.commit()
        cur.close()
        return rc
    finally:
        release_db_connection(conn)


def fetch_approved_for_session(org_id: int, subject: str, *,
                                count: int = 5) -> List[Dict[str, Any]]:
    """
    Pull `count` most-recently-approved questions for this subject and
    return them in the shape attendance_mcq.start_session expects:

        [{"text": str, "choices": [a,b,c,d], "correct": int}, ...]
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, question, choices, correct_index
              FROM mcq_question_bank
             WHERE org_id = %s
               AND LOWER(subject) = LOWER(%s)
               AND approved_at IS NOT NULL
             ORDER BY approved_at DESC
             LIMIT %s;
            """,
            (org_id, subject, int(count)),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        release_db_connection(conn)

    out: List[Dict[str, Any]] = []
    for r in rows:
        choices = r["choices"]
        if isinstance(choices, str):
            try:
                choices = json.loads(choices)
            except json.JSONDecodeError:
                continue
        out.append({
            "text": r["question"],
            "choices": list(choices),
            "correct": int(r["correct_index"]),
        })
    return out
