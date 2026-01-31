"""
so yea wali file tum logo koo help kregi easily
user names extract krne me. tests/test_resolver.py
me iska demo hai
"""

from functools import lru_cache
from thefuzz import process
from utils.db_handler import get_all_faculty

@lru_cache(maxsize=1)
def get_cached_faculty():
    """
    Fetches faculty data once and stores it in memory.
    Useful for batch processing (e.g., resolving 5 participants at once).
    
    NOTE: In a long-running web server (FastAPI), you would use a 
    Time-To-Live (TTL) cache instead so it refreshes periodically.
    """
    return get_all_faculty()

def resolve_faculty_member(name_query, threshold=75):
    """
    Takes a name (e.g., "Sharma" or "Aniket") and finds the best match
    using the cached faculty list.
    """
    all_faculty = get_cached_faculty()
    
    if not all_faculty:
        print("Warning: Database is empty.")
        return None

    faculty_map = {person['name']: person for person in all_faculty}
    names_list = list(faculty_map.keys())
    match_result = process.extractOne(name_query, names_list)
    
    if match_result:
        best_match_name, score = match_result
        
        if score >= threshold:
            return faculty_map[best_match_name]
        else:
            print(f"❌ No strong match for '{name_query}' (Best: {best_match_name}, Score: {score})")
            return None
            
    return None

def resolve_participants(names_list):
    """
    Wrapper to handle a list of names.
    """
    resolved_users = []
    for name in names_list:
        user = resolve_faculty_member(name)
        if user:
            resolved_users.append(user)      
    return resolved_users

'''
how to use this?

from utils.db_handler import get_all_faculty
#first import krna

gemini_output_names = ["Ani", "ayuss", "Bismun", "Kishan", "mayank KD" ,"NonExistentPerson"]
#lets say the above are the names
#iske baad tests/test_resolver.py koo refer krna
'''