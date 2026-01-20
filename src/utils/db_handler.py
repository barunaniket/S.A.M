import csv

def get_faculty_data():
    faculty_list = []
    # Path relative to project root
    with open('data/faculty.csv', mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            faculty_list.append(row)
    return faculty_list