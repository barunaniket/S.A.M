import sys, os
from datetime import datetime, timedelta
import pytz
from src.utils.ics_generator import generate_ics

sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))
start = datetime(2026, 2, 23, 17, 0, tzinfo=pytz.timezone("Asia/Kolkata"))
end = start + timedelta(hours=1)

path = generate_ics(
    title="Test meeting",
    start_dt=start,
    end_dt=end,
    organizer={"name": "Chairman", "email": "chairman@college.edu"},
    attendees=[
        {"name": "Aniket", "email": "aniket@gmail.com"},
        {"name": "Krishna", "email": "krishna@gmail.com"},
    ],
)

print("ICS generated at:", path)
