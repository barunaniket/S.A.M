"""
Confirm the orchestrator routes Meta button_reply payloads through to the
right action (confirm vs discard) without consulting the LLM.

    python -m unittest tests.test_button_orchestration
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


_FAKE_USER = {"id": 7, "org_id": 42, "email": "f@uni.edu",
              "full_name": "Faculty X", "role": "FACULTY",
              "phone_number": "+919999999999"}


class TestButtonOrchestration(unittest.TestCase):

    def _patches(self):
        from src.services import whatsapp_orchestrator as orch
        return [
            mock.patch.object(orch, "resolve_user_by_phone", return_value=_FAKE_USER),
            mock.patch.object(orch, "already_seen", return_value=False),
            mock.patch.object(orch, "log_inbound"),
            mock.patch.object(orch, "queue_whatsapp"),
            mock.patch.object(orch, "append_history"),
            mock.patch.object(orch, "get_session", return_value={
                "user_id": 7, "org_id": 42, "state": "AWAITING_INTENT",
                "pending_upload_id": 99,
            }),
            mock.patch.object(orch, "clear_session"),
        ]

    def test_confirm_button_executes_pending(self):
        from src.services import whatsapp_orchestrator as orch

        with mock.patch.object(orch, "_execute_pending_upload",
                               return_value={"success": True,
                                             "message": "Sent."}) as exec_p, \
             mock.patch.object(orch, "LLMProcessor") as llm_cls:
            for p in self._patches():
                p.start()
            try:
                orch.handle_inbound_message(
                    "+919999999999",
                    {
                        "id":   "wamid.test1",
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": orch.BTN_CONFIRM_UPLOAD,
                                             "title": "Send to all"},
                        },
                    },
                )
            finally:
                mock.patch.stopall()

        exec_p.assert_called_once()
        llm_cls.assert_not_called()

    def test_discard_button_marks_discarded(self):
        from src.services import whatsapp_orchestrator as orch

        with mock.patch.object(orch, "_discard_pending") as discard, \
             mock.patch.object(orch, "LLMProcessor") as llm_cls:
            for p in self._patches():
                p.start()
            try:
                orch.handle_inbound_message(
                    "+919999999999",
                    {
                        "id":   "wamid.test2",
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": orch.BTN_DISCARD_UPLOAD,
                                             "title": "Discard"},
                        },
                    },
                )
            finally:
                mock.patch.stopall()

        discard.assert_called_once()
        llm_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
