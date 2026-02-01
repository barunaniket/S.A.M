from src.services.notification_dispatcher import send_meeting_notification


def test_send_meeting_invite_success():
    meeting_details = {
        "title": "Test Meeting Invite",
        "start": "2025-02-01T15:00:00",
        "end": "2025-02-01T16:00:00",
        "link": "https://meet.google.com/test-link",
        "organizer": "Mayank",

        # These 3 keys match the existing invite template placeholders
        "time_str": "2025-02-01 15:00 to 2025-02-01 16:00",
        "location": "Google Meet",
        "agenda": "Unit test invite email from S.A.M"
    }

    result = send_meeting_notification(
        recipient_email="YOUR_EMAIL@gmail.com",
        notification_type="invite",
        meeting_details=meeting_details,
        ics_attachment=None
    )

    assert result["success"] is True
    assert result["recipient"] == "YOUR_EMAIL@gmail.com"
    assert result["notification_type"] == "invite"
    assert "sent_at" in result


def test_send_meeting_update_success():
    meeting_details = {
        "title": "Test Meeting Update",
        "start": "2025-02-02T15:00:00",
        "end": "2025-02-02T16:00:00",
        "link": "https://meet.google.com/test-update-link",
        "organizer": "Mayank",

        "time_str": "2025-02-02 15:00 to 2025-02-02 16:00",
        "location": "Google Meet",
        "agenda": "Updated timing for unit test"
    }

    result = send_meeting_notification(
        recipient_email="YOUR_EMAIL@gmail.com",
        notification_type="update",
        meeting_details=meeting_details,
        ics_attachment=None
    )

    assert result["success"] is True
    assert result["recipient"] == "YOUR_EMAIL@gmail.com"
    assert result["notification_type"] == "update"
    assert "sent_at" in result


def test_send_meeting_cancel_success():
    meeting_details = {
        "title": "Test Meeting Cancel",
        "start": "2025-02-03T15:00:00",
        "end": "2025-02-03T16:00:00",
        "link": "https://meet.google.com/test-cancel-link",
        "organizer": "Mayank",

        "time_str": "2025-02-03 15:00 to 2025-02-03 16:00",
        "location": "Google Meet",
        "agenda": "Cancel test"
    }

    result = send_meeting_notification(
        recipient_email="YOUR_EMAIL@gmail.com",
        notification_type="cancel",
        meeting_details=meeting_details,
        ics_attachment=None
    )

    assert result["success"] is True
    assert result["recipient"] == "YOUR_EMAIL@gmail.com"
    assert result["notification_type"] == "cancel"
    assert "sent_at" in result


def test_send_meeting_notification_invalid_type():
    meeting_details = {
        "title": "Invalid Notification Test",
        "time_str": "N/A",
        "location": "N/A",
        "agenda": "N/A"
    }

    result = send_meeting_notification(
        recipient_email="YOUR_EMAIL@gmail.com",
        notification_type="wrong_type",
        meeting_details=meeting_details
    )

    assert result["success"] is False
    assert "error" in result

