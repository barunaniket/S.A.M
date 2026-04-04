from src.services.availability_engine import calculate_free_slots

fake_calendar = {
    "busy": [
        {
            "start": "2026-02-12T10:00:00Z",
            "end": "2026-02-12T11:00:00Z"
        },
        {
            "start": "2026-02-12T13:00:00Z",
            "end": "2026-02-12T14:00:00Z"
        }
    ]
}

result = calculate_free_slots(
    range_start="2026-02-12T09:00:00Z",
    range_end="2026-02-12T17:00:00Z",
    duration_minutes=30,
    buffer_minutes=0,
    busy_payload=fake_calendar
)

print(result)
