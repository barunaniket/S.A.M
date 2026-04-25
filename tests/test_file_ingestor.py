"""
Tests for src.services.file_ingestor — Excel header detection and free-text
attendee extraction. Run from repo root:

    python -m unittest tests.test_file_ingestor
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.services.file_ingestor import (
    extract_attendees,
    parse_file,
    summarize,
)


class TestFileIngestor(unittest.TestCase):

    def test_excel_header_detection(self):
        try:
            import pandas as pd
        except Exception:
            self.skipTest("pandas not installed")

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "students.xlsx")
            df = pd.DataFrame([
                {"Name": "Aniket B",  "Email": "aniket@example.edu", "Phone": "+91 90000 11111"},
                {"Name": "Mayank R",  "Email": "mayank@example.edu", "Phone": "+91-9000022222"},
                {"Name": "Krishna",   "Email": "k@example.edu",     "Phone": "9000033333"},
            ])
            df.to_excel(path, index=False)

            parsed = parse_file(path)
            self.assertEqual(parsed["kind"], "excel")
            attendees = extract_attendees(parsed)

            self.assertEqual(len(attendees), 3)
            emails = {a["email"] for a in attendees}
            self.assertIn("aniket@example.edu", emails)
            self.assertTrue(all(a["phone"] for a in attendees))

            summary = summarize(parsed, attendees)
            self.assertIn("3 contact", summary)

    def test_text_email_extraction(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write(
                "Hi! Please reach out to alice@example.com and bob@example.org "
                "for follow-up. (alice phone: +91 9123456780)\n"
                "We may also need carol@example.net.\n"
            )
            path = f.name
        try:
            parsed = parse_file(path)
            self.assertEqual(parsed["kind"], "text")
            attendees = extract_attendees(parsed)
            emails = {a["email"] for a in attendees}
            self.assertEqual(emails, {"alice@example.com", "bob@example.org",
                                      "carol@example.net"})
            self.assertTrue(any(a.get("phone") for a in attendees))
        finally:
            os.remove(path)

    def test_unsupported_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError):
                parse_file(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
