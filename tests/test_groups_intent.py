"""
Tests for the create_group / list_groups / broadcast-by-group branches of
intent_router. DB and Redis are mocked out.

    python -m unittest tests.test_groups_intent
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


class TestGroupsIntent(unittest.TestCase):

    def test_create_group_dispatches(self):
        from src.services import intent_router

        intent_payload = {
            "intent": "create_group",
            "entities": {
                "group_name":     "CSE-3A",
                "description":    "CSE 3rd year section A",
                "members_emails": ["a@uni.edu", "b@uni.edu"],
            },
        }

        with mock.patch.object(intent_router, "create_group") as create_g, \
             mock.patch.object(intent_router, "add_members_by_email") as add_m:
            create_g.return_value = {"success": True,
                                      "data": {"id": 7, "name": "CSE-3A"}}
            add_m.return_value = {"success": True, "matched": 2, "missing": []}
            result = intent_router.route_intent(
                intent_payload, scheduler_email="x@uni.edu", org_id=42,
            )

        self.assertTrue(result["success"])
        create_g.assert_called_once_with(
            org_id=42, name="CSE-3A", description="CSE 3rd year section A",
        )
        add_m.assert_called_once()
        self.assertEqual(add_m.call_args.kwargs["group_id"], 7)
        self.assertEqual(add_m.call_args.kwargs["emails"], ["a@uni.edu", "b@uni.edu"])

    def test_list_groups_dispatches(self):
        from src.services import intent_router

        with mock.patch.object(intent_router, "list_groups") as lg:
            lg.return_value = [
                {"id": 1, "name": "CSE-3A", "member_count": 47, "description": None,
                 "created_at": None},
            ]
            result = intent_router.route_intent(
                {"intent": "list_groups", "entities": {}},
                scheduler_email="x@uni.edu", org_id=42,
            )

        self.assertTrue(result["success"])
        self.assertIn("CSE-3A", result["message"])

    def test_broadcast_to_group_passes_group_name(self):
        from src.services import intent_router

        intent_payload = {
            "intent": "broadcast_notification",
            "entities": {
                "title":             "Lab cancelled",
                "body":              "Tomorrow's lab is cancelled.",
                "target_group_name": "CSE-3A",
                "channels":          ["email", "whatsapp"],
            },
        }

        with mock.patch.object(intent_router, "broadcast_by_filters") as m:
            m.return_value = {"success": True, "message": "queued"}
            intent_router.route_intent(
                intent_payload, scheduler_email="x@uni.edu", org_id=42,
            )

        self.assertEqual(m.call_args.kwargs["target_group_name"], "CSE-3A")


if __name__ == "__main__":
    unittest.main()
