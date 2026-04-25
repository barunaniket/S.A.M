"""
Tests for the upload-driven lightweight meeting flow:

  - create_meeting_lite persists, generates ICS, fans out, schedules reminders
  - orchestrator._execute_pending_upload routes to meeting_lite when start_time
    is set in entities (and falls back to broadcast otherwise)

Run:
    python -m unittest tests.test_meeting_lite
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k, v in {
    "NVIDIA_API_KEY":           "test",
    "WHATSAPP_PHONE_NUMBER_ID": "test",
    "WHATSAPP_ACCESS_TOKEN":    "test",
    "WHATSAPP_VERIFY_TOKEN":    "test",
    "WHATSAPP_APP_SECRET":      "supersecret",
}.items():
    os.environ.setdefault(k, v)


class TestCreateMeetingLite(unittest.TestCase):

    def test_happy_path_dispatches(self):
        from src.services import meeting_lite

        with mock.patch.object(meeting_lite, "_insert_meeting", return_value=42), \
             mock.patch.object(meeting_lite, "generate_ics",
                                return_value="data/ics/test.ics") as ics, \
             mock.patch.object(meeting_lite, "_broadcast_invites",
                                return_value={"email": 2, "whatsapp": 2}) as bc, \
             mock.patch.object(meeting_lite, "_schedule_reminders") as sched:
            result = meeting_lite.create_meeting_lite(
                org_id=1,
                organizer_id=7,
                organizer_name="Faculty X",
                organizer_email="f@uni.edu",
                title="Faculty meeting",
                start_time="2026-05-04T16:00:00",
                end_time=None,            # default to start + 1h
                attendees=[
                    {"name": "A", "email": "a@uni.edu", "phone": "9999900001"},
                    {"name": "B", "email": "b@uni.edu", "phone": "9999900002"},
                ],
                location="Room 302",
                agenda="Mid-term planning",
                upload_id=99,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["meeting_id"], 42)
        self.assertEqual(result["counts"], {"email": 2, "whatsapp": 2})
        self.assertEqual(result["attendee_count"], 2)
        self.assertEqual(result["ics_path"], "data/ics/test.ics")
        ics.assert_called_once()
        bc.assert_called_once()
        sched.assert_called_once()
        # reminders are scheduled with the same attendee list
        self.assertEqual(sched.call_args.args[0], 42)            # meeting_id
        self.assertEqual(sched.call_args.args[4][0]["email"], "a@uni.edu")

    def test_missing_start_time_returns_failure(self):
        from src.services import meeting_lite
        result = meeting_lite.create_meeting_lite(
            org_id=1, organizer_id=1,
            organizer_name="X", organizer_email="x@x",
            title="t", start_time="not-a-date", end_time=None,
            attendees=[{"email": "a@a"}],
        )
        self.assertFalse(result["success"])
        self.assertIn("start time", result["message"].lower())

    def test_no_attendees_returns_failure(self):
        from src.services import meeting_lite
        result = meeting_lite.create_meeting_lite(
            org_id=1, organizer_id=1,
            organizer_name="X", organizer_email="x@x",
            title="t", start_time="2026-05-04T16:00:00", end_time=None,
            attendees=[],
        )
        self.assertFalse(result["success"])

    def test_end_before_start_returns_failure(self):
        from src.services import meeting_lite
        result = meeting_lite.create_meeting_lite(
            org_id=1, organizer_id=1,
            organizer_name="X", organizer_email="x@x",
            title="t",
            start_time="2026-05-04T16:00:00",
            end_time="2026-05-04T15:00:00",
            attendees=[{"email": "a@a"}],
        )
        self.assertFalse(result["success"])


class TestOrchestratorRoutesToMeetingLite(unittest.TestCase):
    """Confirm orchestrator picks lite path vs broadcast based on entities."""

    def _build_session(self):
        from src.services import whatsapp_orchestrator as orch
        user = {"id": 7, "org_id": 1, "email": "f@uni.edu",
                "full_name": "Faculty X", "role": "FACULTY"}
        session = {"pending_upload_id": 99,
                    "pending_attendees": [
                        {"name": "A", "email": "a@u.edu", "phone": "9001"},
                    ]}
        return orch, user, session

    def _patch_db(self, orch):
        # _execute_pending_upload reads from pending_uploads via raw conn —
        # mock that out so no real DB is touched.
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {"parsed": {
            "kind": "excel", "text": "",
            "attendees": [{"name": "A", "email": "a@u.edu", "phone": "9001"}],
        }}
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        return [
            mock.patch.object(orch, "get_db_connection", return_value=fake_conn),
            mock.patch.object(orch, "release_db_connection"),
        ]

    def test_with_start_time_calls_meeting_lite(self):
        orch, user, session = self._build_session()
        patches = self._patch_db(orch)

        with mock.patch("src.services.meeting_lite.create_meeting_lite") as cml:
            cml.return_value = {"success": True, "message": "scheduled"}
            for p in patches: p.start()
            try:
                result = orch._execute_pending_upload(
                    user, "+919001", session,
                    entities={
                        "title":      "Faculty meeting",
                        "start_time": "2026-05-04T16:00:00",
                        "end_time":   "2026-05-04T17:00:00",
                        "location":   "Room 302",
                    },
                )
            finally:
                mock.patch.stopall()

        cml.assert_called_once()
        kwargs = cml.call_args.kwargs
        self.assertEqual(kwargs["title"], "Faculty meeting")
        self.assertEqual(kwargs["location"], "Room 302")
        self.assertEqual(kwargs["upload_id"], 99)
        self.assertEqual(result["message"], "scheduled")

    def test_without_start_time_falls_back_to_broadcast(self):
        orch, user, session = self._build_session()
        patches = self._patch_db(orch)

        with mock.patch("src.services.broadcast_service.broadcast_to_attendees") as bc, \
             mock.patch("src.services.meeting_lite.create_meeting_lite") as cml:
            bc.return_value = {"success": True, "message": "broadcast"}
            for p in patches: p.start()
            try:
                result = orch._execute_pending_upload(
                    user, "+919001", session,
                    entities={"body": "Hi everyone, please confirm attendance."},
                )
            finally:
                mock.patch.stopall()

        cml.assert_not_called()
        bc.assert_called_once()
        self.assertEqual(result["message"], "broadcast")


if __name__ == "__main__":
    unittest.main()
