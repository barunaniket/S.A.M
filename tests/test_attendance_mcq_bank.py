"""
Verify that attendance_mcq.start_session prefers the
mcq_question_bank over the hardcoded QUESTION_BANK dict when
approved bank rows exist for the subject. Also confirms the
hardcoded bank is the dev-only fallback.

    python -m unittest tests.test_attendance_mcq_bank
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


class TestResolveQuestions(unittest.TestCase):

    def test_prefers_bank_when_approved_rows_exist(self):
        from src.services import attendance_mcq

        bank = [
            {"text": "Curated Q1", "choices": ["a", "b", "c", "d"],
             "correct": 0},
            {"text": "Curated Q2", "choices": ["a", "b", "c", "d"],
             "correct": 1},
        ]
        with mock.patch(
            "src.services.course_materials.fetch_approved_for_session",
            return_value=bank,
        ):
            result = attendance_mcq._resolve_questions(
                subject="DSA", org_id=42, count=2,
            )
        self.assertEqual(result, bank)

    def test_falls_back_to_hardcoded_when_bank_empty(self):
        from src.services import attendance_mcq

        with mock.patch(
            "src.services.course_materials.fetch_approved_for_session",
            return_value=[],
        ):
            result = attendance_mcq._resolve_questions(
                subject="DSA", org_id=42, count=5,
            )
        # Hardcoded DSA bank has 5 entries
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["text"],
                         attendance_mcq.QUESTION_BANK["DSA"][0]["text"])

    def test_unknown_subject_falls_back_to_dsa_dev(self):
        from src.services import attendance_mcq

        with mock.patch(
            "src.services.course_materials.fetch_approved_for_session",
            return_value=[],
        ):
            result = attendance_mcq._resolve_questions(
                subject="QuantumComputing", org_id=42,
            )
        self.assertEqual(result, attendance_mcq.QUESTION_BANK["DSA"])

    def test_org_id_none_uses_hardcoded(self):
        """Orgless calls (legacy) should not hit the DB."""
        from src.services import attendance_mcq
        with mock.patch(
            "src.services.course_materials.fetch_approved_for_session",
        ) as fapfs:
            result = attendance_mcq._resolve_questions(
                subject="Compilers", org_id=None,
            )
        fapfs.assert_not_called()
        self.assertEqual(result, attendance_mcq.QUESTION_BANK["Compilers"])

    def test_db_error_falls_through_to_hardcoded(self):
        """If the bank lookup blows up, never fail the quiz — fall back."""
        from src.services import attendance_mcq

        with mock.patch(
            "src.services.course_materials.fetch_approved_for_session",
            side_effect=RuntimeError("DB down"),
        ):
            result = attendance_mcq._resolve_questions(
                subject="DSA", org_id=42,
            )
        self.assertEqual(result, attendance_mcq.QUESTION_BANK["DSA"])


if __name__ == "__main__":
    unittest.main()
