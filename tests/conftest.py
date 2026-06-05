"""
pytest bootstrap shared by the whole suite.

`src/utils/config_loader.py` runs `Config.validate()` at import time and calls
`sys.exit(1)` if any REQUIRED_KEY is missing. Locally that's satisfied by the
developer's `.env`; in CI there is no `.env`, so we seed dummy values here.

conftest.py is imported by pytest *before* it collects any test module, so
these env vars are in place before the first `import src.*`. We use
`setdefault` so a real environment value (or one a specific test sets) always
wins — this only fills gaps.
"""

import os
import sys
from pathlib import Path

# Make `import src.*` work regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_DUMMY_ENV = {
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "GOOGLE_PROJECT_ID": "test-project",
    "GOOGLE_API_SCOPES": "https://www.googleapis.com/auth/calendar",
    "SENDER_EMAIL": "test@example.com",
    "SENDER_PASSWORD": "test-password",
    "NVIDIA_API_KEY": "test",
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "WHATSAPP_PHONE_NUMBER_ID": "PNID",
    "WHATSAPP_ACCESS_TOKEN": "WA_TOKEN",
    "WHATSAPP_VERIFY_TOKEN": "VERIFY_ME",
    "WHATSAPP_APP_SECRET": "supersecret",
    "SECRET_KEY": "test-secret-key-for-jwt",
}

for _k, _v in _DUMMY_ENV.items():
    os.environ.setdefault(_k, _v)
