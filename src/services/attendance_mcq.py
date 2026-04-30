"""
attendance_mcq.py
-----------------
MCQ-based attendance. Faculty triggers a quiz; the bot pushes 5 questions
to every student in the batch, one every 15 seconds. Students tap an
inline keyboard button (A/B/C/D). After the last question the session
auto-closes, scores are computed, and an attendance record is written for
each student (≥ threshold correct → PRESENT, else ABSENT). The faculty
gets a Telegram DM with the full breakdown and can override individual
students by replying `mark <name> present|absent`.

Public API used by the rest of the codebase:

    start_session(faculty, batch, subject, questions=None,
                  threshold=4, seconds_per_q=15) -> dict
    dispatch_question(session_id, q_index)
    record_answer(session_id, user_id, q_index, choice) -> dict
    close_session(session_id) -> dict
    override_attendance(session_id, student_query, status,
                         marked_by) -> dict
    get_session(session_id) -> dict | None

The Celery wiring lives in src/worker.py (`dispatch_mcq_question` and
`close_mcq_session` tasks).
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src.services.attendance_common import (
    _enrolled_students,
    _fuzzy_pick,
    latest_open_session_for_faculty,
)
from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


# Hardcoded question bank. For the demo we don't need an authoring UI —
# the faculty just says "start mcq attendance for DSA" and we pick from
# here. Pull from a future `mcq_question_bank` table when this becomes
# more than a prototype.
QUESTION_BANK: Dict[str, List[Dict[str, Any]]] = {
    "DSA": [
        {"text": "Time complexity of binary search on a sorted array?",
         "choices": ["O(n)", "O(log n)", "O(n log n)", "O(1)"], "correct": 1},
        {"text": "Which data structure uses LIFO order?",
         "choices": ["Queue", "Stack", "Tree", "Graph"], "correct": 1},
        {"text": "Worst-case time for Quick Sort?",
         "choices": ["O(n)", "O(n log n)", "O(n²)", "O(log n)"], "correct": 2},
        {"text": "Average lookup time in a hash table?",
         "choices": ["O(n)", "O(log n)", "O(1)", "O(n²)"], "correct": 2},
        {"text": "DFS uses which data structure internally?",
         "choices": ["Queue", "Stack", "Heap", "Set"], "correct": 1},
    ],
    "Compilers": [
        {"text": "Which phase generates intermediate code?",
         "choices": ["Lexical analysis", "Syntax analysis",
                     "Semantic analysis", "Code generation"], "correct": 2},
        {"text": "What does a parser produce?",
         "choices": ["Tokens", "Parse tree", "Bytecode", "Symbol table"],
         "correct": 1},
        {"text": "LL(1) parser scans the input:",
         "choices": ["Right to left", "Left to right with 1 lookahead",
                     "Bottom up", "Both directions"], "correct": 1},
        {"text": "Symbol table is consulted by:",
         "choices": ["Lexer only", "Parser only",
                     "Multiple phases", "Linker only"], "correct": 2},
        {"text": "Three-address code is a form of:",
         "choices": ["Assembly", "Intermediate representation",
                     "Source code", "Machine code"], "correct": 1},
    ],
    "Algorithms": [
        {"text": "Dijkstra's algorithm fails on graphs with:",
         "choices": ["Cycles", "Negative weights", "Disconnected components",
                     "More than 1000 nodes"], "correct": 1},
        {"text": "Dynamic programming reduces work by:",
         "choices": ["Recursion only", "Memoizing subproblems",
                     "Greedy choices", "Random sampling"], "correct": 1},
        {"text": "BFS shortest-path is correct on:",
         "choices": ["Weighted graphs", "Unweighted graphs",
                     "Directed acyclic graphs only", "Trees only"], "correct": 1},
        {"text": "Sorting lower bound for comparison-based algorithms?",
         "choices": ["Ω(n)", "Ω(log n)", "Ω(n log n)", "Ω(n²)"], "correct": 2},
        {"text": "Master theorem applies to:",
         "choices": ["Iterative algorithms",
                     "Divide-and-conquer recurrences",
                     "Backtracking only", "Greedy proofs"], "correct": 1},
    ],
}


# Letter labels in the order shown to students.
LETTERS = ["A", "B", "C", "D"]


def _resolve_questions(subject: str) -> List[Dict[str, Any]]:
    """Pull the canonical set for a subject; fall back to DSA if unknown."""
    key = (subject or "").strip()
    if key in QUESTION_BANK:
        return QUESTION_BANK[key]
    # Try case-insensitive
    for k, v in QUESTION_BANK.items():
        if k.lower() == key.lower():
            return v
    logger.info("MCQ bank has no entry for %r — falling back to DSA", subject)
    return QUESTION_BANK["DSA"]


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def start_session(faculty: Dict[str, Any], batch: str, subject: str,
                  questions: Optional[List[Dict[str, Any]]] = None,
                  threshold: int = 4,
                  seconds_per_q: int = 15) -> Dict[str, Any]:
    """
    Create the session row, schedule Q1..Qn dispatches and the close task,
    and return a summary the orchestrator can show to the faculty.
    """
    questions = questions or _resolve_questions(subject)
    if not questions:
        return {"success": False, "message": "No questions available."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO mcq_sessions
                (org_id, faculty_id, batch, subject, questions,
                 threshold, seconds_per_q)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING id;
            """,
            (faculty["org_id"], faculty["id"], batch, subject,
             json.dumps(questions), int(threshold), int(seconds_per_q)),
        )
        session_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    # Schedule the dispatches. Q1 fires immediately (eta = now); Q2 after
    # one window, etc. Final close is one second after the last window
    # ends so trailing answers can land.
    try:
        from src.worker import close_mcq_session, dispatch_mcq_question

        now = datetime.utcnow()
        for i in range(len(questions)):
            eta = now + timedelta(seconds=i * seconds_per_q)
            dispatch_mcq_question.apply_async(args=[session_id, i], eta=eta)

        close_eta = now + timedelta(
            seconds=len(questions) * seconds_per_q + 2,
        )
        close_mcq_session.apply_async(args=[session_id], eta=close_eta)
    except Exception:
        logger.exception("Failed to schedule MCQ dispatch tasks for "
                         "session %s", session_id)

    enrolled = _enrolled_students(faculty["org_id"], batch)
    return {
        "success": True,
        "session_id": session_id,
        "subject": subject,
        "batch": batch,
        "question_count": len(questions),
        "duration_seconds": len(questions) * seconds_per_q + 2,
        "threshold": threshold,
        "enrolled": len(enrolled),
        "message": (f"📝 Started MCQ attendance for <b>{subject}</b> "
                    f"({batch}, {len(enrolled)} student(s) enrolled). "
                    f"{len(questions)} questions × {seconds_per_q}s. "
                    f"Pass threshold: {threshold}/{len(questions)}.\n\n"
                    f"I'll DM you the results in about "
                    f"{(len(questions) * seconds_per_q + 5)} seconds."),
    }


def dispatch_question(session_id: int, q_index: int) -> None:
    """
    Push question q_index to every paired student in the session's batch.
    Called by the Celery `dispatch_mcq_question` task.
    """
    session = get_session(session_id)
    if not session or session["status"] != "IN_PROGRESS":
        logger.info("dispatch_question: session %s not active, skipping", session_id)
        return

    questions = session["questions"]
    if q_index >= len(questions):
        return
    q = questions[q_index]

    students = _enrolled_students(session["org_id"], session["batch"])
    if not students:
        logger.info("dispatch_question: no paired students in batch %s",
                    session["batch"])
        return

    body = (f"<b>Question {q_index + 1} of {len(questions)}</b>\n"
            f"<i>{session['subject']} · {session['seconds_per_q']}s</i>\n\n"
            f"{q['text']}")

    buttons = [
        {"id": f"mcq_{session_id}_{q_index}_{i}",
         "title": f"{LETTERS[i]}. {q['choices'][i]}"}
        for i in range(len(q["choices"]))
    ]

    # Lazy import to avoid orchestrator/circular dependency issues.
    from src.services.telegram_service import send_buttons

    sent = 0
    for s in students:
        if not s.get("telegram_chat_id"):
            continue
        try:
            send_buttons(
                chat_id=int(s["telegram_chat_id"]),
                body=body,
                buttons=buttons,
                footer=f"Q{q_index + 1}",
            )
            sent += 1
        except Exception:
            logger.exception("MCQ dispatch failed for student %s", s.get("id"))

    logger.info("MCQ session %s — Q%s dispatched to %s student(s)",
                session_id, q_index + 1, sent)


def record_answer(session_id: int, user_id: int, q_index: int,
                  choice: int) -> Dict[str, Any]:
    """
    Persist a single tap. Returns {success, late} so the orchestrator can
    answer_callback with the right feedback.

    Late = the student answered after the question's window closed (we
    still record it for visibility but don't count it for scoring; the
    decision happens in close_session).
    """
    if choice < 0 or choice > 3:
        return {"success": False, "message": "Invalid choice."}

    session = get_session(session_id)
    if not session:
        return {"success": False, "message": "That quiz no longer exists."}

    if session["status"] == "CLOSED":
        return {"success": False, "message": "That quiz has already closed."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO mcq_responses
                (session_id, user_id, q_index, choice)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (session_id, user_id, q_index) DO NOTHING
            RETURNING id;
            """,
            (session_id, user_id, q_index, choice),
        )
        inserted = cur.fetchone() is not None
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    if not inserted:
        return {"success": True, "duplicate": True,
                "message": "You've already answered that one."}

    # Was this answer late?
    started = session["started_at"]
    seconds_per_q = session["seconds_per_q"]
    window_end = started + timedelta(seconds=(q_index + 1) * seconds_per_q)
    late = datetime.utcnow() > window_end

    return {"success": True, "late": late,
            "message": ("Locked in (late — won't count)." if late
                        else "Locked in ✓")}


def close_session(session_id: int) -> Dict[str, Any]:
    """
    Score the session, write attendance_records, DM the faculty.
    Idempotent — calling twice is a no-op on the second call.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM mcq_sessions WHERE id = %s FOR UPDATE;
            """,
            (session_id,),
        )
        session_row = cur.fetchone()
        if not session_row:
            cur.close()
            return {"success": False, "message": "Session not found."}
        if session_row["status"] == "CLOSED":
            cur.close()
            return {"success": True, "already_closed": True}

        session = _normalize_session_row(dict(session_row))
        questions = session["questions"]
        threshold = session["threshold"]
        seconds_per_q = session["seconds_per_q"]
        started = session["started_at"]

        # Pull every student in the batch (regardless of whether they
        # answered — non-responders are absent).
        students = _enrolled_students(session["org_id"], session["batch"], cur=cur)

        # Pull all responses for this session.
        cur.execute(
            "SELECT user_id, q_index, choice, answered_at "
            "FROM mcq_responses WHERE session_id = %s;",
            (session_id,),
        )
        rows = cur.fetchall()

        per_student: Dict[int, Dict[int, Dict[str, Any]]] = {}
        for r in rows:
            per_student.setdefault(r["user_id"], {})[r["q_index"]] = dict(r)

        results = []
        today = date.today()
        for s in students:
            score = 0
            for qi, q in enumerate(questions):
                window_end = started + timedelta(seconds=(qi + 1) * seconds_per_q)
                resp = per_student.get(s["id"], {}).get(qi)
                if not resp:
                    continue
                if resp["answered_at"] > window_end:
                    continue
                if resp["choice"] == q["correct"]:
                    score += 1

            status = "PRESENT" if score >= threshold else "ABSENT"
            cur.execute(
                """
                INSERT INTO attendance_records
                    (org_id, user_id, subject, class_date, status,
                     source, score, session_id, marked_by, overridden)
                VALUES (%s, %s, %s, %s, %s, 'mcq', %s, %s, %s, FALSE)
                ON CONFLICT (user_id, subject, class_date) DO UPDATE
                    SET status      = EXCLUDED.status,
                        score       = EXCLUDED.score,
                        session_id  = EXCLUDED.session_id,
                        marked_by   = EXCLUDED.marked_by,
                        marked_at   = NOW(),
                        overridden  = FALSE;
                """,
                (session["org_id"], s["id"], session["subject"], today, status,
                 score, session_id, session["faculty_id"]),
            )
            results.append({"user_id": s["id"], "name": s["full_name"],
                            "score": score, "status": status})

        cur.execute(
            "UPDATE mcq_sessions SET status='CLOSED', closed_at=NOW() "
            "WHERE id = %s;",
            (session_id,),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    # DM the faculty with results + override hint.
    _send_results_to_faculty(session, results)

    return {"success": True, "session_id": session_id,
            "results": results}


def get_session(session_id: int) -> Optional[Dict[str, Any]]:
    """Fetch + normalize a session row. Returns None if not found."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM mcq_sessions WHERE id = %s;",
                    (session_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)
    return _normalize_session_row(dict(row)) if row else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_session_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce JSONB and timestamps into Python objects."""
    out = dict(row)
    q = out.get("questions")
    if isinstance(q, str):
        try:
            out["questions"] = json.loads(q)
        except json.JSONDecodeError:
            out["questions"] = []
    return out


def _send_results_to_faculty(session: Dict[str, Any],
                             results: List[Dict[str, Any]]) -> None:
    """DM the faculty with a results summary + override hint."""
    from src.services.telegram_service import send_text
    from src.utils.db_handler import get_db_connection, release_db_connection

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_chat_id, full_name FROM users WHERE id = %s;",
            (session["faculty_id"],),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)

    if not row or not row.get("telegram_chat_id"):
        return

    threshold = session["threshold"]
    qcount = len(session["questions"])
    present = [r for r in results if r["status"] == "PRESENT"]
    absent  = [r for r in results if r["status"] == "ABSENT"]

    lines = [f"📊 <b>{session['subject']}</b> attendance — "
             f"{session['batch']} ({len(results)} student(s))"]
    lines.append(f"<i>Pass: {threshold}/{qcount}</i>\n")
    if present:
        lines.append("<b>Present</b>")
        for r in present:
            lines.append(f"  ✓ {r['name']} — {r['score']}/{qcount}")
    if absent:
        lines.append("\n<b>Absent</b>")
        for r in absent:
            lines.append(f"  ✗ {r['name']} — {r['score']}/{qcount}")
    if not results:
        lines.append("<i>No students were enrolled in this batch.</i>")

    lines.append("\n<i>To override, reply with</i> "
                 "<code>mark &lt;name&gt; present</code> "
                 "<i>or</i> <code>mark &lt;name&gt; absent</code>")

    send_text(int(row["telegram_chat_id"]), "\n".join(lines))
