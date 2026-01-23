import csv
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from utils.db_handler import init_db, add_faculty_member

def seed_data():
    init_db()
    
    csv_path = 'data/faculty.csv'
    try:
        with open(csv_path, mode='r') as file:
            reader = csv.DictReader(file, skipinitialspace=True)
            for row in reader:
                print(f"Importing {row['name']}...")
                add_faculty_member(
                    row['name'], 
                    row['email'], 
                    row['phone'], 
                    row['department'], 
                    row['role']
                )
        print("Migration complete!")
    except FileNotFoundError:
        print("CSV file not found.")
    except KeyError as e:
        print(f"CSV Header Error: Missing column {e}.")

if __name__ == "__main__":
    seed_data()