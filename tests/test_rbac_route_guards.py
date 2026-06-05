"""
Guards added when the legacy KNOWN_UNGATED routes were drained and the
notification WebSocket was authenticated.

Covers:
  - require_roles() (any-auth) rejects a token with no role claim
  - any-auth routes accept any valid role
  - role-restricted routes reject an insufficient role and accept a permitted one
  - the notifications WebSocket rejects a missing/mismatched token

Mirrors the TestClient + JWT harness in test_api_endpoints.py. Service calls
are mocked so no DB / Redis / network is touched.

    PYTHONPATH=. python -m unittest tests.test_rbac_route_guards
"""

import os
import sys
import time
import unittest
from io import BytesIO
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Required env BEFORE importing src.* (Config.validate fails fast on missing
# keys). conftest.py also does this for pytest; repeated here so the module
# runs standalone under `python -m unittest`.
for _k, _v in {
    "GOOGLE_CLIENT_ID": "x", "GOOGLE_CLIENT_SECRET": "x", "GOOGLE_PROJECT_ID": "x",
    "GOOGLE_API_SCOPES": "x", "SENDER_EMAIL": "x@y.io", "SENDER_PASSWORD": "x",
    "NVIDIA_API_KEY": "x", "DATABASE_URL": "postgresql://t:t@localhost:5432/t",
    "WHATSAPP_PHONE_NUMBER_ID": "PNID", "WHATSAPP_ACCESS_TOKEN": "WA",
    "WHATSAPP_VERIFY_TOKEN": "V", "WHATSAPP_APP_SECRET": "S",
    "SECRET_KEY": "test-secret-key-for-jwt",
}.items():
    os.environ.setdefault(_k, _v)

import jwt as pyjwt
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from src.main import app
from src.utils.config_loader import Config

USER_ID = 7
ORG_ID = 42
EMAIL = "faculty@uni.edu"

client = TestClient(app)


def _jwt(uid=USER_ID, oid=ORG_ID, email=EMAIL, role="FACULTY", with_role=True) -> str:
    claims = {"user_id": uid, "org_id": oid, "email": email,
              "exp": int(time.time()) + 3600}
    if with_role:
        claims["role"] = role
    return pyjwt.encode(claims, Config.SECRET_KEY, algorithm=Config.ALGORITHM)


def _hdr(role="FACULTY", with_role=True) -> dict:
    return {"Authorization": f"Bearer {_jwt(role=role, with_role=with_role)}"}


class TestAnyAuthGuards(unittest.TestCase):
    """Routes gated with require_roles() (any authenticated user)."""

    def test_tasks_requires_role_claim(self):
        # A token with no role claim is rejected even on an any-auth route.
        r = client.get("/api/v1/tasks", headers=_hdr(with_role=False))
        self.assertEqual(r.status_code, 403)

    def test_tasks_allows_any_role(self):
        with mock.patch("src.api.routes.tasks.list_tasks_for_assignee") as m:
            m.return_value = []
            r = client.get("/api/v1/tasks", headers=_hdr(role="STUDENT"))
        self.assertEqual(r.status_code, 200)

    def test_timetable_me_allows_any_role(self):
        with mock.patch("src.api.routes.timetable.list_entries_for_user") as m:
            m.return_value = []
            r = client.get("/api/v1/timetable/me", headers=_hdr(role="STUDENT"))
        self.assertEqual(r.status_code, 200)


class TestRoleRestrictedGuards(unittest.TestCase):
    """Routes gated to FACULTY / ADMIN / SUPER_ADMIN."""

    def test_availability_denies_student(self):
        r = client.post(
            "/api/v1/availability",
            headers=_hdr(role="STUDENT"),
            json={"range_start": "2026-05-01T09:00:00",
                  "range_end": "2026-05-01T17:00:00", "busy_payload": {}},
        )
        self.assertEqual(r.status_code, 403)

    def test_availability_allows_faculty(self):
        with mock.patch("src.api.routes.availability.calculate_free_slots") as m:
            m.return_value = {"success": True, "slots": []}
            r = client.post(
                "/api/v1/availability",
                headers=_hdr(role="FACULTY"),
                json={"range_start": "2026-05-01T09:00:00",
                      "range_end": "2026-05-01T17:00:00", "busy_payload": {}},
            )
        self.assertEqual(r.status_code, 200)

    def test_uploads_denies_student(self):
        # The role dependency runs before the handler, so even a valid file is
        # rejected for an insufficient role.
        r = client.post(
            "/api/v1/uploads",
            headers=_hdr(role="STUDENT"),
            files={"file": ("roster.csv", BytesIO(b"name,email\n"), "text/csv")},
        )
        self.assertEqual(r.status_code, 403)


class TestNotificationsWebSocketAuth(unittest.TestCase):
    """WS /api/v1/ws/notifications/{user_id} must carry a matching JWT."""

    def test_ws_rejects_without_token(self):
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/ws/notifications/{USER_ID}") as ws:
                ws.receive_text()

    def test_ws_rejects_mismatched_user(self):
        # Token for USER_ID trying to subscribe to a different user's channel.
        token = _jwt(uid=USER_ID)
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/api/v1/ws/notifications/9999?token={token}"
            ) as ws:
                ws.receive_text()


if __name__ == "__main__":
    unittest.main()
