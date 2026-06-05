"""
Verify assignment deadline-nudge scheduling via
src/tasks/assignments.schedule_reminders_for_assignment.

The Celery dispatch is mocked, so this runs offline. Run:

    python -m unittest tests.test_assignment_reminders
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


def _patched_db(rows):
    """Mock get_db_connection / release_db_connection. fetchone returns
    rows[0]; rowcount-style counters tracked on the cur mock."""
    cur = mock.MagicMock()
    cur.fetchone.side_effect = rows + [None] * 32  # plenty of headroom
    cur.fetchall.return_value = []
    conn = mock.MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


class TestSchedule(unittest.TestCase):

    def test_schedules_24h_1h_and_overdue(self):
        from src.tasks import assignments as a_tasks

        future = datetime.utcnow() + timedelta(days=2)
        conn, cur = _patched_db([{"org_id": 42}])
        send_task = mock.MagicMock()
        send_task.return_value = mock.MagicMock(id="celery-id")
        celery_app = mock.MagicMock(send_task=send_task)

        with mock.patch("src.tasks.assignments.get_db_connection",
                        return_value=conn), \
             mock.patch("src.tasks.assignments.release_db_connection"), \
             mock.patch("src.services.org_settings.get",
                        return_value=[24, 1]), \
             mock.patch("src.worker.celery_app", celery_app):
            ids = a_tasks.schedule_reminders_for_assignment(
                assignment_id=11, due_at=future,
            )
        # 24h, 1h, overdue closer = 3 calls
        self.assertEqual(send_task.call_count, 3)
        self.assertEqual(len(ids), 3)
        # The closer must call close_assignment, not dispatch_assignment_nudge
        names = [c.args[0] for c in send_task.call_args_list]
        self.assertIn("close_assignment", names)
        self.assertIn("dispatch_assignment_nudge", names)

    def test_skips_offsets_in_the_past(self):
        from src.tasks import assignments as a_tasks

        # due in 30min — 24h offset would land in the past
        soon = datetime.utcnow() + timedelta(minutes=30)
        conn, _ = _patched_db([{"org_id": 42}])
        send_task = mock.MagicMock()
        send_task.return_value = mock.MagicMock(id="celery-id")
        celery_app = mock.MagicMock(send_task=send_task)

        with mock.patch("src.tasks.assignments.get_db_connection",
                        return_value=conn), \
             mock.patch("src.tasks.assignments.release_db_connection"), \
             mock.patch("src.services.org_settings.get",
                        return_value=[24, 1]), \
             mock.patch("src.worker.celery_app", celery_app):
            ids = a_tasks.schedule_reminders_for_assignment(
                assignment_id=11, due_at=soon,
            )
        # 24h skipped (past), 1h skipped (past), only the overdue closer fires
        self.assertEqual(send_task.call_count, 1)
        self.assertEqual(send_task.call_args.args[0], "close_assignment")
        self.assertEqual(len(ids), 1)

    def test_unknown_assignment_returns_empty(self):
        from src.tasks import assignments as a_tasks
        conn, _ = _patched_db([None])
        with mock.patch("src.tasks.assignments.get_db_connection",
                        return_value=conn), \
             mock.patch("src.tasks.assignments.release_db_connection"):
            ids = a_tasks.schedule_reminders_for_assignment(
                assignment_id=999,
                due_at=datetime.utcnow() + timedelta(days=1),
            )
        self.assertEqual(ids, [])

    def test_empty_offsets_only_schedules_closer(self):
        from src.tasks import assignments as a_tasks

        future = datetime.utcnow() + timedelta(days=2)
        conn, _ = _patched_db([{"org_id": 42}])
        send_task = mock.MagicMock()
        send_task.return_value = mock.MagicMock(id="celery-id")
        celery_app = mock.MagicMock(send_task=send_task)

        with mock.patch("src.tasks.assignments.get_db_connection",
                        return_value=conn), \
             mock.patch("src.tasks.assignments.release_db_connection"), \
             mock.patch("src.services.org_settings.get", return_value=[]), \
             mock.patch("src.worker.celery_app", celery_app):
            ids = a_tasks.schedule_reminders_for_assignment(
                assignment_id=11, due_at=future,
            )
        # No nudges; only the overdue closer
        self.assertEqual(send_task.call_count, 1)
        self.assertEqual(send_task.call_args.args[0], "close_assignment")
        self.assertEqual(len(ids), 1)


class TestDispatchNudge(unittest.TestCase):

    def test_skips_already_submitted(self):
        from src.tasks import assignments as a_tasks

        assignment = {"id": 11, "status": "OPEN", "subject": "CS201",
                      "title": "Assgn 3",
                      "due_at": datetime.utcnow() + timedelta(hours=1)}
        snapshot = {"success": True,
                    "data": {"submitted": [{"user_id": 1}],
                             "missing": [{"user_id": 2,
                                          "full_name": "Arjun",
                                          "telegram_chat_id": 100}]}}
        conn, _ = _patched_db([{"id": 11}])

        with mock.patch("src.services.assignment_service.get_assignment",
                        return_value=assignment), \
             mock.patch("src.services.assignment_service.submissions_for_assignment",
                        return_value=snapshot), \
             mock.patch("src.tasks.assignments.get_db_connection",
                        return_value=conn), \
             mock.patch("src.tasks.assignments.release_db_connection"), \
             mock.patch("src.services.telegram_service.send_buttons") as sb, \
             mock.patch("src.services.telegram_service.send_text"):
            res = a_tasks.dispatch_nudge(11, "1h")

        # Only the missing student gets a button card
        self.assertEqual(sb.call_count, 1)
        self.assertIn("1/1", res)


if __name__ == "__main__":
    unittest.main()
