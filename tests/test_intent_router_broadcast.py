"""
Tests for the broadcast_notification branch of intent_router.route_intent.

The router delegates to broadcast_service which talks to Redis + DB; both are
patched out so this runs offline. Run:

    python -m unittest tests.test_intent_router_broadcast
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Make Config.validate() pass even if .env is incomplete in the test env.
for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


class TestBroadcastIntent(unittest.TestCase):

    def test_broadcast_calls_service(self):
        from src.services import intent_router

        intent_payload = {
            "intent": "broadcast_notification",
            "entities": {
                "title":             "Lab cancelled",
                "body":              "Tomorrow's lab is cancelled.",
                "target_role":       "STUDENT",
                "target_department": "CSE",
                "channels":          ["email", "whatsapp"],
            },
        }

        with mock.patch.object(intent_router, "broadcast_by_filters") as m:
            m.return_value = {"success": True, "message": "Broadcast queued"}
            result = intent_router.route_intent(
                intent_payload,
                scheduler_email="hod@uni.edu",
                org_id=42,
            )

        self.assertTrue(result["success"])
        m.assert_called_once()
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["org_id"], 42)
        self.assertEqual(kwargs["target_role"], "STUDENT")
        self.assertEqual(kwargs["target_department"], "CSE")
        self.assertEqual(kwargs["body"], "Tomorrow's lab is cancelled.")
        self.assertEqual(kwargs["channels"], ["email", "whatsapp"])

    def test_broadcast_without_body_asks_for_clarification(self):
        from src.services import intent_router

        intent_payload = {
            "intent": "broadcast_notification",
            "entities": {"target_role": "STUDENT"},
        }
        result = intent_router.route_intent(
            intent_payload,
            scheduler_email="hod@uni.edu",
            org_id=1,
        )
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_broadcast_without_org_id_errors(self):
        from src.services import intent_router

        intent_payload = {
            "intent": "broadcast_notification",
            "entities": {"body": "hi", "target_role": "STUDENT"},
        }
        result = intent_router.route_intent(
            intent_payload, scheduler_email="hod@uni.edu",
        )
        self.assertFalse(result["success"])
        self.assertIn("org_id", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
