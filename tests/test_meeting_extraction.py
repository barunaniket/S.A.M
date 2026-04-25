"""
Unit tests for file_ingestor.extract_meeting_metadata — verifies the LLM is
invoked, JSON output is parsed, and graceful fallback on bad output.

    python -m unittest tests.test_meeting_extraction
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

for k, v in {
    "NVIDIA_API_KEY":           "test",
    "WHATSAPP_PHONE_NUMBER_ID": "test",
    "WHATSAPP_ACCESS_TOKEN":    "test",
    "WHATSAPP_VERIFY_TOKEN":    "test",
    "WHATSAPP_APP_SECRET":      "supersecret",
}.items():
    os.environ.setdefault(k, v)


class TestExtractMeetingMetadata(unittest.TestCase):

    def _patch_llm(self, raw_response: str):
        fake = mock.MagicMock()
        fake.generate.return_value = raw_response
        return mock.patch(
            "src.utils.config_loader.get_llm_client", return_value=fake,
        )

    def test_extracts_meeting_from_text(self):
        from src.services import file_ingestor
        parsed = {"kind": "text",
                  "text": "Faculty meeting on 4 May 2026 at 4pm in Room 302."}
        good_json = (
            '{"title":"Faculty meeting","start_time":"2026-05-04T16:00:00",'
            '"end_time":"2026-05-04T17:00:00","location":"Room 302",'
            '"agenda":null,"found":true}'
        )
        with self._patch_llm(good_json):
            meta = file_ingestor.extract_meeting_metadata(parsed)
        self.assertTrue(meta["found"])
        self.assertEqual(meta["title"], "Faculty meeting")
        self.assertEqual(meta["start_time"], "2026-05-04T16:00:00")
        self.assertEqual(meta["location"], "Room 302")

    def test_no_meeting_in_attendee_only_excel(self):
        from src.services import file_ingestor
        parsed = {"kind": "excel",
                  "sheets": [{"sheet": "S1",
                               "columns": ["Name", "Email"],
                               "rows": [{"Name": "A", "Email": "a@u.edu"}]}]}
        empty_json = '{"title":null,"start_time":null,"end_time":null,' \
                     '"location":null,"agenda":null,"found":false}'
        with self._patch_llm(empty_json):
            meta = file_ingestor.extract_meeting_metadata(parsed)
        self.assertFalse(meta["found"])

    def test_invalid_json_is_swallowed(self):
        from src.services import file_ingestor
        with self._patch_llm("not json at all"):
            meta = file_ingestor.extract_meeting_metadata({"kind": "text",
                                                            "text": "stuff"})
        self.assertEqual(meta, {"found": False})

    def test_strips_markdown_fences(self):
        from src.services import file_ingestor
        wrapped = '```json\n{"found":true,"start_time":"2026-05-04T09:00:00",' \
                  '"title":"X","end_time":null,"location":null,"agenda":null}\n```'
        with self._patch_llm(wrapped):
            meta = file_ingestor.extract_meeting_metadata({"kind": "text",
                                                            "text": "x"})
        self.assertTrue(meta["found"])
        self.assertEqual(meta["title"], "X")

    def test_found_requires_start_time(self):
        # LLM might return found=true but empty start_time — we treat as no
        # meeting (we need a start time to schedule).
        from src.services import file_ingestor
        bad = '{"found":true,"start_time":null,"title":"x","end_time":null,' \
              '"location":null,"agenda":null}'
        with self._patch_llm(bad):
            meta = file_ingestor.extract_meeting_metadata({"kind": "text",
                                                            "text": "x"})
        self.assertFalse(meta["found"])


if __name__ == "__main__":
    unittest.main()
