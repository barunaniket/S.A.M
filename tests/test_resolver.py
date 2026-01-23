import sys
import os
from thefuzz import process

# 1. Add 'src' to path so we can import 'utils'
# We ONLY import from utils, ignoring the broken 'services' folder
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from utils.db_handler import get_all_faculty

# --- LOGIC DEFINITION (Temporarily defined here to bypass import errors) ---

def resolve_faculty_member(name_query, threshold=75):
    """
    Takes a name (e.g., "Sharma" or "Aniket") and finds the best match
    in the Postgres database.
    """
    # Fetch from DB
    all_faculty = get_all_faculty()
    
    if not all_faculty:
        print("Warning: Database is empty.")
        return None

    # Create Map
    faculty_map = {person['name']: person for person in all_faculty}
    names_list = list(faculty_map.keys())

    # Fuzzy Match
    match_result = process.extractOne(name_query, names_list)
    
    if match_result:
        best_match_name, score = match_result
        
        # Validation Threshold
        if score >= threshold:
            print(f"✅ Matched '{name_query}' to '{best_match_name}' (Score: {score})")
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

# --- TEST EXECUTION ---

if __name__ == "__main__":
    # Test Data (Simulating Gemini JSON output)
    gemini_output_names = ["Ani", "ayuss", "Bismun", "Kishan", "mayank KD" ,"NonExistentPerson"]

    print("--- Testing User Resolver (Standalone) ---")
    results = resolve_participants(gemini_output_names)

    print("\n--- Final Invitation List ---")
    if not results:
        print("No participants found.")
    
    for person in results:
        print(f"Name: {person['name']} | Email: {person['email']} | Role: {person['role']}")