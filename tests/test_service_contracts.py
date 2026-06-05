"""
Smoke-test the service-envelope contract on the v13 services. Each public
function should return a dict with at least a `success` key; on failure
the dict should also carry a user-facing `message` (and ideally an
`error_code`). Run:

    python -m unittest tests.test_service_contracts
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


class TestEnvelopeShapes(unittest.TestCase):

    def test_attendance_query_fetch_sheet_clarification(self):
        from src.services import attendance_query
        result = attendance_query.fetch_sheet(org_id=42, subject="")
        self.assertIn("success", result)
        self.assertFalse(result["success"])
        self.assertIn("message", result)

    def test_attendance_query_list_class_roster_clarification(self):
        from src.services import attendance_query
        result = attendance_query.list_class_roster(org_id=42, batch="")
        self.assertIn("success", result)
        self.assertFalse(result["success"])
        self.assertIn("message", result)

    def test_mcq_generator_no_subject(self):
        from src.services import mcq_generator
        result = mcq_generator.generate_from_text(subject="", text="x" * 200)
        self.assertIn("success", result)
        self.assertFalse(result["success"])
        self.assertIn("message", result)
        self.assertIn("error_code", result)

    def test_mcq_generator_short_text(self):
        from src.services import mcq_generator
        result = mcq_generator.generate_from_text(subject="DSA", text="x")
        self.assertIn("success", result)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "INSUFFICIENT_TEXT")

    def test_mcq_generator_no_material(self):
        from src.services import mcq_generator
        with mock.patch(
            "src.services.course_materials.latest_with_text",
            return_value=None,
        ):
            result = mcq_generator.generate_for_subject(org_id=42, subject="X")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "NO_MATERIAL")
        self.assertIn("message", result)

    def test_assignment_service_create_no_body(self):
        from src.services import assignment_service
        result = assignment_service.create(
            org_id=1, faculty_id=1, batch="X", subject="Y", title="Z",
        )
        self.assertIn("success", result)
        self.assertFalse(result["success"])
        self.assertIn("message", result)


if __name__ == "__main__":
    unittest.main()
