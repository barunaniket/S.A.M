akiro@fedora:/run/media/akiro/Windows-SSD/Users/Aniket Barun/Desktop/Work/Agentic AI PES/S.A.M$   git add tests/test_api_endpoints.py tests/test_button_orchestration.py tests/test_file_ingestor.py tests/test_groups_intent.py tests/test_health_endpoint.py
  tests/test_intent_router_broadcast.py tests/test_meeting_extraction.py tests/test_meeting_lite.py tests/test_whatsapp_audit.py tests/test_whatsapp_signature.py
  git commit -m "test: add coverage for endpoints, intents, audit, ingestion, and orchestration"
tests/test_intent_router_broadcast.py: line 8: $'\nTests for the broadcast_notification branch of intent_router.route_intent.\n\nThe router delegates to broadcast_service which talks to Redis + DB; both are\npatched out so this runs offline. Run:\n\n    python -m unittest tests.test_intent_router_broadcast\n': command not found
^C^C^Ctests/test_intent_router_broadcast.py: line 13: from: command not found
tests/test_intent_router_broadcast.py: line 15: syntax error near unexpected token `0,'
tests/test_intent_router_broadcast.py: line 15: `sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))'
[main 9c99372] test: add coverage for endpoints, intents, audit, ingestion, and orchestration
 5 files changed, 1066 insertions(+)
 create mode 100644 tests/test_api_endpoints.py
 create mode 100644 tests/test_button_orchestration.py
 create mode 100644 tests/test_file_ingestor.py
 create mode 100644 tests/test_groups_intent.py
 create mode 100644 tests/test_health_endpoint.py
akiro@fedora:/run/media/akiro/Windows-SSD/Users/Aniket Barun/Desktop/Work/Agentic AI PES/S.A.M$ """
Test that whatsapp_queue.queue_whatsapp triggers an audit insert. We mock
both Redis and the audit module's DB calls.

    python -m unittest tests.test_whatsapp_audit
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


class TestWhatsAppAudit(unittest.TestCase):

    def test_outbound_audit_called(self):
        from src.services import whatsapp_queue

        fake_redis = mock.MagicMock()
        with mock.patch.object(whatsapp_queue, "_get_redis_client",
                               return_value=fake_redis), \
             mock.patch.object(whatsapp_queue, "log_outbound") as log_out:
            whatsapp_queue.queue_whatsapp(
                "+91 90000 11111", "Hi there",
                metadata={"intent": "broadcast", "org_id": 1, "user_id": 7},
            )

        fake_redis.lpush.assert_called_once()
        log_out.assert_called_once()
        kwargs = log_out.call_args.kwargs
        self.assertEqual(kwargs["phone"], "+91 90000 11111")
        self.assertEqual(kwargs["body"], "Hi there")
        self.assertEqual(kwargs["intent"], "broadcast")
        self.assertEqual(kwargs["org_id"], 1)
        self.assertEqual(kwargs["user_id"], 7)

    def test_empty_args_skip_audit(self):
        from src.services import whatsapp_queue

        with mock.patch.object(whatsapp_queue, "_get_redis_client") as r, \
             mock.patch.object(whatsapp_queue, "log_outbound") as log_out:
            whatsapp_queue.queue_whatsapp("", "body")
            whatsapp_queue.queue_whatsapp("+1234567890", "")

        r.assert_not_called()
        log_out.assert_not_called()


if __name__ == "__main__":
    unittest.main()
