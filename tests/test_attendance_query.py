"""
Unit tests for src/services/attendance_query.py.

The DB layer is mocked at get_db_connection so these run offline. Run:

    python -m unittest tests.test_attendance_query
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


def _fake_cursor(rows):
    """A cursor mock that returns `rows` from fetchall and a single row
    from fetchone (the first element)."""
    cur = mock.MagicMock()
    cur.fetchall.return_value = rows
    cur.fetchone.return_value = rows[0] if rows else None
    return cur


def _patched_conn(rows):
    """Return (mock_conn, fake_get, fake_release) so callers can patch."""
    cur = _fake_cursor(rows)
    conn = mock.MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


class TestFetchSheet(unittest.TestCase):

    def test_today_default_when_no_date_given(self):
        from src.services import attendance_query

        rows = [
            {"id": 1, "user_id": 11, "subject": "CS201",
             "class_date": date.today(), "status": "PRESENT",
             "score": 5, "overridden": False, "source": "mcq",
             "full_name": "Priya", "batch": "CSE-3A"},
            {"id": 2, "user_id": 12, "subject": "CS201",
             "class_date": date.today(), "status": "ABSENT",
             "score": 1, "overridden": False, "source": "mcq",
             "full_name": "Arjun", "batch": "CSE-3A"},
        ]
        conn, cur = _patched_conn(rows)
        with mock.patch("src.services.attendance_query.get_db_connection",
                        return_value=conn), \
             mock.patch("src.services.attendance_query.release_db_connection"):
            result = attendance_query.fetch_sheet(
                org_id=42, subject="CS201", batch="CSE-3A",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total"], 2)
        self.assertEqual(len(result["data"]["present"]), 1)
        self.assertEqual(len(result["data"]["absent"]), 1)
        # Verify subject + class_date were in the SQL params
        args = cur.execute.call_args
        self.assertIn(date.today(), args[0][1])

    def test_empty_state_returns_friendly_message(self):
        from src.services import attendance_query

        conn, _ = _patched_conn([])
        with mock.patch("src.services.attendance_query.get_db_connection",
                        return_value=conn), \
             mock.patch("src.services.attendance_query.release_db_connection"):
            result = attendance_query.fetch_sheet(
                org_id=42, subject="CS201",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total"], 0)
        self.assertIn("No records", result["message"])

    def test_no_subject_asks_for_clarification(self):
        from src.services import attendance_query
        result = attendance_query.fetch_sheet(org_id=42, subject="")
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_date_range_filters(self):
        from src.services import attendance_query

        conn, cur = _patched_conn([])
        with mock.patch("src.services.attendance_query.get_db_connection",
                        return_value=conn), \
             mock.patch("src.services.attendance_query.release_db_connection"):
            attendance_query.fetch_sheet(
                org_id=42, subject="CS201",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 30),
            )
        sql, params = cur.execute.call_args[0]
        self.assertIn("class_date >=", sql)
        self.assertIn("class_date <=", sql)
        self.assertIn(date(2026, 4, 1), params)
        self.assertIn(date(2026, 4, 30), params)


class TestFetchMySummary(unittest.TestCase):

    def test_per_subject_percent(self):
        from src.services import attendance_query

        # First execute fetches the user; second fetches the aggregation.
        cur = mock.MagicMock()
        cur.fetchone.return_value = {"full_name": "Arjun"}
        cur.fetchall.return_value = [
            {"subject": "CS201", "total": 20, "present": 18,
             "last_class": date(2026, 4, 30)},
            {"subject": "DSA", "total": 10, "present": 5,
             "last_class": date(2026, 4, 28)},
        ]
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        with mock.patch("src.services.attendance_query.get_db_connection",
                        return_value=conn), \
             mock.patch("src.services.attendance_query.release_db_connection"):
            result = attendance_query.fetch_my_summary(11)

        self.assertTrue(result["success"])
        summary = result["data"]["summary"]
        self.assertEqual(len(summary), 2)
        cs = next(r for r in summary if r["subject"] == "CS201")
        self.assertAlmostEqual(cs["percent"], 90.0)


class TestListClassRoster(unittest.TestCase):

    def test_no_batch_clarifies(self):
        from src.services import attendance_query
        result = attendance_query.list_class_roster(org_id=42, batch="")
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_returns_students(self):
        from src.services import attendance_query

        conn, _ = _patched_conn([
            {"id": 11, "full_name": "Priya", "email": "p@uni.edu",
             "batch": "CSE-3A", "telegram_chat_id": 100,
             "phone_number": None, "last_seen": date(2026, 4, 30)},
        ])
        with mock.patch("src.services.attendance_query.get_db_connection",
                        return_value=conn), \
             mock.patch("src.services.attendance_query.release_db_connection"):
            result = attendance_query.list_class_roster(
                org_id=42, batch="CSE-3A",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["count"], 1)
        self.assertIn("Priya", result["message"])


if __name__ == "__main__":
    unittest.main()
