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
    Resolve a list of display names to faculty dicts.
    Names that don't match are silently skipped.
    """
    resolved = []
    for name in names_list:
        user = resolve_faculty_member(name)
        if user:
            resolved.append(user)
    return resolved
