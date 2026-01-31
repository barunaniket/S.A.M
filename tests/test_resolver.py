import sys
import os

# 1. Add 'src' to path so we can import 'utils'
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

# 2. Import the ACTUAL function (now cached) instead of defining a copy here
from utils.user_resolver import resolve_participants

if __name__ == "__main__":
    # Test Data (Simulating Gemini JSON output)
    gemini_output_names = ["Ani", "ayuss", "Bismun", "Kishan", "mayank KD" ,"NonExistentPerson"]

    print("--- Testing User Resolver (Using Cache) ---")
    
    # First Run: Will hit the database
    print("\n[Run 1] Fetching from DB...")
    results = resolve_participants(gemini_output_names)

    # Second Run: Should be instant (fetching from cache)
    print("\n[Run 2] Fetching from Cache (Should be instant)...")
    results_cached = resolve_participants(gemini_output_names)

    print("\n--- Final Invitation List ---")
    if not results:
        print("No participants found.")
    
    for person in results:
        print(f"Name: {person['name']} | Email: {person['email']} | Role: {person['role']}")