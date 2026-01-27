from datetime import datetime, timedelta
import pytz
from src.utils.ics_generator import generate_ics


start = datetime(2026, 2, 23, 17, 0, tzinfo=pytz.timezone("Asia/Kolkata"))
end = start + timedelta(hours=1)

path = generate_ics(
    title="Republic Day Faculty Meeting",
    start_dt=start,
    end_dt=end,
    organizer={"name": "Chairman", "email": "chairman@college.edu"},
    attendees=[
        {"name": "Aniket", "email": "aniket@gmail.com"},
        {"name": "Krishna", "email": "krishna@gmail.com"},
    ],
)

print("ICS generated at:", path)
