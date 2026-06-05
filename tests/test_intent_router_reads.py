"""
Tests for the v13 read-path intents in intent_router.route_intent.

Covers:
    query_attendance_sheet
    query_my_attendance
    query_class_submissions
    list_open_assignments_for_faculty
    list_class_roster

Service layers are mocked, so this runs offline.

    python -m unittest tests.test_intent_router_reads
"""

import os
import sys
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


def _faculty(role="FACULTY"):
    return {"id": 7, "org_id": 42, "email": "f@uni.edu",
            "full_name": "Dr Sharma", "role": role}


def _student():
    return {"id": 11, "org_id": 42, "email": "s@uni.edu",
            "full_name": "Arjun", "role": "STUDENT"}


class TestQueryAttendanceSheet(unittest.TestCase):

    def test_dispatches_to_fetch_sheet(self):
        from src.services import intent_router

        payload = {
            "intent": "query_attendance_sheet",
            "entities": {"target_subject": "CS201",
                         "target_batch": "CSE-3A",
                         "query_date": "2026-04-30"},
        }
        with mock.patch("src.services.attendance_query.fetch_sheet") as fs, \
             mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_faculty()):
            fs.return_value = {"success": True, "message": "ok",
                               "data": {"present": [], "absent": []}}
            result = intent_router.route_intent(
                payload, scheduler_email="f@uni.edu", org_id=42,
            )
        self.assertTrue(result["success"])
        kwargs = fs.call_args.kwargs
        self.assertEqual(kwargs["org_id"], 42)
        self.assertEqual(kwargs["subject"], "CS201")
        self.assertEqual(kwargs["batch"], "CSE-3A")
        self.assertEqual(kwargs["class_date"], date(2026, 4, 30))

    def test_defaults_to_today_when_no_date_given(self):
        from src.services import intent_router

        payload = {"intent": "query_attendance_sheet",
                   "entities": {"target_subject": "DSA"}}
        with mock.patch("src.services.attendance_query.fetch_sheet") as fs, \
             mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_faculty()):
            fs.return_value = {"success": True, "message": "ok"}
            intent_router.route_intent(payload,
                                       scheduler_email="f@uni.edu",
                                       org_id=42)
        self.assertEqual(fs.call_args.kwargs["class_date"], date.today())

    def test_rejects_student(self):
        from src.services import intent_router

        payload = {"intent": "query_attendance_sheet",
                   "entities": {"target_subject": "CS201"}}
        with mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_student()):
            result = intent_router.route_intent(
                payload, scheduler_email="s@uni.edu", org_id=42,
            )
        self.assertFalse(result["success"])
        self.assertIn("faculty", result["message"].lower())

    def test_missing_subject_asks_for_clarification(self):
        from src.services import intent_router

        payload = {"intent": "query_attendance_sheet", "entities": {}}
        with mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_faculty()):
            result = intent_router.route_intent(
                payload, scheduler_email="f@uni.edu", org_id=42,
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_missing_org_id_errors(self):
        from src.services import intent_router

        result = intent_router.route_intent(
            {"intent": "query_attendance_sheet",
             "entities": {"target_subject": "CS201"}},
            scheduler_email="f@uni.edu",
        )
        self.assertFalse(result["success"])
        self.assertIn("query_attendance_sheet", result.get("error", ""))


class TestQueryMyAttendance(unittest.TestCase):

    def test_dispatches_to_fetch_my_summary(self):
        from src.services import intent_router

        payload = {"intent": "query_my_attendance", "entities": {}}
        with mock.patch("src.services.attendance_query.fetch_my_summary") as fm, \
             mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_student()):
            fm.return_value = {"success": True, "message": "x", "data": {}}
            result = intent_router.route_intent(
                payload, scheduler_email="s@uni.edu", org_id=42,
            )
        self.assertTrue(result["success"])
        fm.assert_called_once_with(11)

    def test_unknown_user_errors(self):
        from src.services import intent_router

        with mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=None):
            result = intent_router.route_intent(
                {"intent": "query_my_attendance", "entities": {}},
                scheduler_email="ghost@uni.edu", org_id=42,
            )
        self.assertFalse(result["success"])


class TestListOpenAssignmentsForFaculty(unittest.TestCase):

    def test_dispatches_and_formats(self):
        from src.services import intent_router

        rows = [{"id": 1, "subject": "CS201", "title": "Assgn 3",
                 "batch": "CSE-3A", "due_at": None, "submitted": 12,
                 "enrolled": 30, "status": "OPEN"}]
        with mock.patch("src.services.assignment_service.list_open_for_faculty",
                        return_value=rows), \
             mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_faculty()):
            result = intent_router.route_intent(
                {"intent": "list_open_assignments_for_faculty",
                 "entities": {}},
                scheduler_email="f@uni.edu", org_id=42,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["count"], 1)
        self.assertIn("Assgn 3", result["message"])

    def test_rejects_student(self):
        from src.services import intent_router

        with mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_student()):
            result = intent_router.route_intent(
                {"intent": "list_open_assignments_for_faculty",
                 "entities": {}},
                scheduler_email="s@uni.edu", org_id=42,
            )
        self.assertFalse(result["success"])


class TestQueryClassSubmissions(unittest.TestCase):

    def test_picks_assignment_by_label(self):
        from src.services import intent_router

        candidates = [
            {"id": 5, "subject": "CS201", "title": "Assgn 2",
             "batch": "CSE-3A", "status": "CLOSED", "org_id": 42,
             "due_at": None},
            {"id": 6, "subject": "CS201", "title": "Assgn 3",
             "batch": "CSE-3A", "status": "OPEN", "org_id": 42,
             "due_at": None},
        ]
        with mock.patch("src.services.assignment_service.list_open_for_faculty",
                        return_value=candidates), \
             mock.patch("src.services.assignment_service.submissions_for_assignment") as subs, \
             mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_faculty()):
            subs.return_value = {
                "success": True,
                "data": {
                    "assignment": candidates[1],
                    "submitted": [{"full_name": "Priya",
                                   "submitted_at": datetime(2026, 4, 30, 10, 0)}],
                    "missing": [{"full_name": "Arjun"}],
                },
            }
            result = intent_router.route_intent(
                {"intent": "query_class_submissions",
                 "entities": {"target_subject": "CS201",
                              "target_assignment_label": "assgn3"}},
                scheduler_email="f@uni.edu", org_id=42,
            )
        self.assertTrue(result["success"])
        # Picked assignment id 6 (Assgn 3), not 5 (Assgn 2)
        subs.assert_called_once_with(6)
        self.assertIn("Assgn 3", result["message"])

    def test_falls_back_to_most_recent_open(self):
        from src.services import intent_router

        candidates = [
            {"id": 8, "subject": "DSA", "title": "Lab 1",
             "batch": "CSE-3A", "status": "OPEN", "org_id": 42,
             "due_at": None},
        ]
        with mock.patch("src.services.assignment_service.list_open_for_faculty",
                        return_value=candidates), \
             mock.patch("src.services.assignment_service.submissions_for_assignment") as subs, \
             mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_faculty()):
            subs.return_value = {
                "success": True,
                "data": {"assignment": candidates[0],
                         "submitted": [], "missing": []},
            }
            intent_router.route_intent(
                {"intent": "query_class_submissions", "entities": {}},
                scheduler_email="f@uni.edu", org_id=42,
            )
        subs.assert_called_once_with(8)


class TestListClassRoster(unittest.TestCase):

    def test_requires_batch(self):
        from src.services import intent_router

        with mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_faculty()), \
             mock.patch("src.services.attendance_query.list_class_roster") as lr:
            lr.return_value = {"success": False,
                               "needs_clarification": True,
                               "message": "?"}
            result = intent_router.route_intent(
                {"intent": "list_class_roster", "entities": {}},
                scheduler_email="f@uni.edu", org_id=42,
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_dispatches_with_batch(self):
        from src.services import intent_router

        with mock.patch("src.utils.db_handler.get_user_by_email",
                        return_value=_faculty()), \
             mock.patch("src.services.attendance_query.list_class_roster") as lr:
            lr.return_value = {"success": True, "data": {"students": []},
                               "message": "ok"}
            intent_router.route_intent(
                {"intent": "list_class_roster",
                 "entities": {"target_batch": "CSE-3A"}},
                scheduler_email="f@uni.edu", org_id=42,
            )
        lr.assert_called_once_with(org_id=42, batch="CSE-3A")


if __name__ == "__main__":
    unittest.main()
