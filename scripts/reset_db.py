# scripts/reset_db.py
import sys
import os

# Add the 'src' directory to the Python path so we can import utils
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from utils.db_handler import clear_faculty_table

if __name__ == "__main__":
    confirm = input("Are you sure you want to DELETE ALL faculty data? (y/n): ")
    if confirm.lower() == 'y':
        clear_faculty_table()
    else:
        print("Operation cancelled.")