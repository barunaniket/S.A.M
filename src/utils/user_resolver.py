"""
user_resolver.py
----------------
Resolve human-readable display names to DB faculty records using fuzzy matching.
"""

from functools import lru_cache
from thefuzz import process

from src.utils.db_handler import get_all_faculty


@lru_cache(maxsize=1)
def _get_cached_faculty():
    """
    Fetch all faculty once and cache in memory.
    Call invalidate_faculty_cache() when the faculty table changes.
    """
    return get_all_faculty()


def invalidate_faculty_cache():
    """Clear the in-memory faculty cache so the next call re-fetches from DB."""
    _get_cached_faculty.cache_clear()


def resolve_faculty_member(name_query: str, threshold: int = 75):
    """
    Fuzzy-match a name string against the faculty list.

    Parameters
    ----------
    name_query : str  — the name as typed/spoken (e.g. "Sharma", "Aniket")
    threshold  : int  — minimum fuzz score to accept a match (0-100)

    Returns the matching faculty dict, or None if no strong match found.
    """
    all_faculty = _get_cached_faculty()

    if not all_faculty:
        return None

    faculty_map = {person["name"]: person for person in all_faculty}
    names_list = list(faculty_map.keys())

    match_result = process.extractOne(name_query, names_list)

    if not match_result:
        return None

    best_match_name, score = match_result

    if score >= threshold:
        return faculty_map[best_match_name]

    return None


def resolve_participants(names_list: list) -> list:
    """
    Resolve a list of display names to faculty dicts. For each match we also
    enrich with the matching `users` row (if any) so callers get phone_number
    alongside email — required for WhatsApp fan-out.

    Names that don't match are silently skipped.
    """
    from src.utils.db_handler import get_user_by_email

    resolved = []
    for name in names_list:
        faculty = resolve_faculty_member(name)
        if not faculty:
            continue

        enriched = dict(faculty)
        email = faculty.get("email")
        if email:
            user_row = get_user_by_email(email)
            if user_row and user_row.get("phone_number"):
                enriched["phone_number"] = user_row["phone_number"]
        resolved.append(enriched)
    return resolved


# ---------------------------------------------------------------------------
# Group expansion (e.g. "All HODs", "cs faculty", "CSE-3A")
# ---------------------------------------------------------------------------

_GROUP_KEYWORDS = {
    # token → SQL filter on users
    "all hods":        "role = 'ADMIN' AND department IS NOT NULL",
    "hods":            "role = 'ADMIN' AND department IS NOT NULL",
    "all faculty":     "role = 'FACULTY'",
    "all teachers":    "role = 'FACULTY'",
    "all students":    "role = 'STUDENT'",
}


def _users_via_group_name(org_id: int, token: str) -> list:
    """Try to resolve a participant token via user_groups → user_group_members."""
    from src.utils.db_handler import get_db_connection, release_db_connection

    if not org_id or not token:
        return []
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.email, u.full_name AS name, u.phone_number,
                   u.role, u.department
              FROM user_groups g
              JOIN user_group_members m ON m.group_id = g.id
              JOIN users u ON u.id = m.user_id
             WHERE g.org_id = %s
               AND (LOWER(g.name) = LOWER(%s)
                    OR LOWER(g.name) LIKE LOWER(%s));
            """,
            (org_id, token, f"%{token}%"),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception:
        return []
    finally:
        release_db_connection(conn)


def _users_via_keyword(org_id: int, token: str) -> list:
    """Resolve role-style keywords like 'all HODs', 'all faculty'."""
    from src.utils.db_handler import get_db_connection, release_db_connection

    key = token.strip().lower()
    sql_filter = _GROUP_KEYWORDS.get(key)
    if not sql_filter or not org_id:
        return []
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, email, full_name AS name, phone_number, role, department
              FROM users
             WHERE org_id = %s AND {sql_filter};
            """,
            (org_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception:
        return []
    finally:
        release_db_connection(conn)


def _fuzzy_user_in_org(org_id: int, token: str, min_score: int = 78):
    """
    Fuzzy-match a name token against the org's users table directly. Returns
    one user dict (top hit ≥ min_score) or None. Used as the individual-name
    fallback inside expand_participant_names — bypasses the legacy
    `faculty` table which isn't in this schema.
    """
    from thefuzz import fuzz
    from src.utils.db_handler import get_db_connection, release_db_connection

    if not org_id or not token:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, email, full_name AS name, phone_number, role, department
              FROM users
             WHERE org_id = %s
               AND role IN ('FACULTY','ADMIN','SUPER_ADMIN','BOOKING_AUTHORITY','STUDENT');
            """,
            (org_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception:
        return None
    finally:
        release_db_connection(conn)

    best = None
    best_score = 0
    for r in rows:
        full = (r.get("name") or "").strip()
        if not full:
            continue
        score = max(
            fuzz.token_set_ratio(token, full),
            fuzz.partial_ratio(token.lower(), full.lower()),
        )
        if score > best_score:
            best, best_score = r, score
    if best and best_score >= min_score:
        return best
    return None


def expand_participant_names(org_id: int, names_list: list) -> list:
    """
    Resolve a mixed list of participant tokens. Tries in order:
      1. role keyword (e.g. "all HODs", "all faculty")
      2. user_groups name match (exact or substring)
      3. fuzzy match against the org's users table

    Deduplicates on email.
    """
    from src.utils.db_handler import get_user_by_email

    seen_emails = set()
    out = []

    def _push(record: dict):
        email = record.get("email")
        if email and email in seen_emails:
            return
        if email:
            seen_emails.add(email)
        # enrich with phone_number from users table if missing
        if email and not record.get("phone_number"):
            try:
                u = get_user_by_email(email)
                if u and u.get("phone_number"):
                    record["phone_number"] = u["phone_number"]
            except Exception:
                pass
        out.append(record)

    for raw in names_list or []:
        token = (raw or "").strip()
        if not token:
            continue

        keyword_hits = _users_via_keyword(org_id, token)
        if keyword_hits:
            for u in keyword_hits:
                _push(u)
            continue

        group_hits = _users_via_group_name(org_id, token)
        if group_hits:
            for u in group_hits:
                _push(u)
            continue

        user = _fuzzy_user_in_org(org_id, token)
        if user:
            _push(user)

    return out
