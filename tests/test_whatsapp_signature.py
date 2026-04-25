"""
Test the Meta WhatsApp webhook HMAC verifier in isolation. Run from repo root:

    python -m unittest tests.test_whatsapp_signature
"""

import hashlib
import hmac
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestWhatsAppSignature(unittest.TestCase):

    def setUp(self):
        # Ensure config thinks the env vars are set BEFORE importing the
        # service — Config.validate() fails fast on missing required keys.
        os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
        os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test")
        os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
        os.environ.setdefault("WHATSAPP_APP_SECRET", "supersecret")
        os.environ.setdefault("NVIDIA_API_KEY", "test")

    def test_valid_signature(self):
        from src.services.whatsapp_service import verify_signature
        from src.utils.config_loader import Config

        body = b'{"object":"whatsapp_business_account","entry":[]}'
        secret = Config.WHATSAPP_APP_SECRET.encode()
        digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
        header = f"sha256={digest}"

        self.assertTrue(verify_signature(body, header))

    def test_invalid_signature(self):
        from src.services.whatsapp_service import verify_signature

        body = b'{"object":"whatsapp_business_account","entry":[]}'
        bad = "sha256=" + ("0" * 64)
        self.assertFalse(verify_signature(body, bad))

    def test_missing_header(self):
        from src.services.whatsapp_service import verify_signature

        self.assertFalse(verify_signature(b"{}", None))


if __name__ == "__main__":
    unittest.main()
