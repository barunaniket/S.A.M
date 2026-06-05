"""
Unit tests for src/services/mcq_generator.py.

The OpenAI client and DB are mocked. Run:

    python -m unittest tests.test_mcq_generator
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
    os.environ.setdefault(k, "test")


_VALID = [
    {"question": "What is the time complexity of binary search?",
     "choices": ["O(n)", "O(log n)", "O(n log n)", "O(1)"],
     "correct_index": 1},
    {"question": "Which data structure uses LIFO order?",
     "choices": ["Queue", "Stack", "Tree", "Graph"],
     "correct_index": 1},
]


def _llm_returning(content: str):
    """Create a fake OpenAI client that always returns `content`."""
    completion = mock.MagicMock()
    completion.choices = [mock.MagicMock()]
    completion.choices[0].message.content = content

    client = mock.MagicMock()
    client.chat.completions.create.return_value = completion
    return client


class TestGenerateFromText(unittest.TestCase):

    def test_happy_path(self):
        from src.services import mcq_generator

        client = _llm_returning(json.dumps(_VALID))
        with mock.patch.object(mcq_generator, "_client",
                               return_value=client):
            result = mcq_generator.generate_from_text(
                subject="DSA",
                text="A long enough source paragraph " * 30,
                count=2,
            )
        self.assertTrue(result["success"])
        self.assertEqual(len(result["questions"]), 2)
        self.assertEqual(result["questions"][0]["correct_index"], 1)

    def test_strips_markdown_fences(self):
        from src.services import mcq_generator

        wrapped = f"```json\n{json.dumps(_VALID)}\n```"
        client = _llm_returning(wrapped)
        with mock.patch.object(mcq_generator, "_client",
                               return_value=client):
            result = mcq_generator.generate_from_text(
                subject="DSA",
                text="A long enough source paragraph " * 30,
                count=2,
            )
        self.assertTrue(result["success"])

    def test_drops_malformed_entries(self):
        from src.services import mcq_generator

        # 3 returned: one valid, one with bad choice count, one with bad index
        bad = [
            _VALID[0],
            {"question": "x", "choices": ["a", "b"], "correct_index": 0},
            {"question": "y", "choices": ["a", "b", "c", "d"],
             "correct_index": 7},
        ]
        client = _llm_returning(json.dumps(bad))
        with mock.patch.object(mcq_generator, "_client",
                               return_value=client):
            result = mcq_generator.generate_from_text(
                subject="DSA",
                text="A long enough source paragraph " * 30,
                count=5,
            )
        self.assertTrue(result["success"])
        self.assertEqual(len(result["questions"]), 1)

    def test_rejects_short_text(self):
        from src.services import mcq_generator
        result = mcq_generator.generate_from_text(
            subject="DSA", text="too short",
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "INSUFFICIENT_TEXT")

    def test_rejects_missing_subject(self):
        from src.services import mcq_generator
        result = mcq_generator.generate_from_text(
            subject="", text="x" * 200,
        )
        self.assertFalse(result["success"])

    def test_handles_bad_json(self):
        from src.services import mcq_generator

        client = _llm_returning("this is not json")
        with mock.patch.object(mcq_generator, "_client",
                               return_value=client):
            result = mcq_generator.generate_from_text(
                subject="DSA",
                text="A long enough source paragraph " * 30,
                count=5,
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "BAD_JSON")

    def test_handles_llm_exception(self):
        from src.services import mcq_generator

        client = mock.MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("502")
        with mock.patch.object(mcq_generator, "_client",
                               return_value=client):
            result = mcq_generator.generate_from_text(
                subject="DSA",
                text="A long enough source paragraph " * 30,
                count=5,
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "LLM_ERROR")


class TestGenerateForSubject(unittest.TestCase):

    def test_no_material_returns_friendly_error(self):
        from src.services import mcq_generator

        with mock.patch("src.services.course_materials.latest_with_text",
                        return_value=None):
            result = mcq_generator.generate_for_subject(
                org_id=42, subject="QuantumStuff",
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "NO_MATERIAL")

    def test_passes_through_material_text(self):
        from src.services import mcq_generator

        material = {"id": 11, "title": "DSA Slides w3",
                    "extracted_text": "Long content " * 50}
        client = _llm_returning(json.dumps(_VALID))
        with mock.patch("src.services.course_materials.latest_with_text",
                        return_value=material), \
             mock.patch.object(mcq_generator, "_client",
                               return_value=client):
            result = mcq_generator.generate_for_subject(
                org_id=42, subject="DSA", count=2,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["material_id"], 11)
        self.assertEqual(result["material_title"], "DSA Slides w3")


if __name__ == "__main__":
    unittest.main()
