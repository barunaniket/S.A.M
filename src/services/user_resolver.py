import csv
from thefuzz import process, fuzz

def resolve_user(name_query, csv_path='data/faculty.csv', threshold=85):
    """
    Matches a name from user input to a faculty member in the CSV.
    Uses fuzzy matching to handle partial names or titles.
    """
    users = []
    with open(csv_path, mode='r') as file:
        reader = csv.DictReader(file)
        users = list(reader)

    # Extract all full names for comparison
    names = [u['name'] for u in users]
    
    # Find the best match using fuzzy logic
    # [cite: 77] mentions an 85% threshold for S.A.M.
    match, score = process.extractOne(name_query, names, scorer=fuzz.token_set_ratio)
    
    if score >= threshold:
        # Return the full user dictionary for the match
        return next(u for u in users if u['name'] == match)
    
    return None

def resolve_multiple_users(names_list):
    """
    Helper to resolve a list of names found in an instruction.
    """
    resolved = []
    for name in names_list:
        user = resolve_user(name)
        if user:
            resolved.append(user)
    return resolved