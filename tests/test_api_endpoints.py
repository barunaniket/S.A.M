"""
End-to-end HTTP tests for every S.A.M API route.

Strategy: drive the FastAPI app via TestClient, mock the service layer so
no DB / Redis / Google / SMTP / LLM / Meta call is made. We're verifying:
  - routing (right URL → right handler)
  - auth (JWT required where expected; webhooks/health public)
  - request-shape validation (Pydantic)
  - that handlers call the right service with the right args
  - that responses have the expected shape

Run from repo root:

    PYTHONPATH=. .venv/bin/python -m unittest tests.test_api_endpoints
"""

import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from io import BytesIO
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Required env BEFORE importing src.* (Config.validate fails fast on missing keys).
for k, v in {
    "NVIDIA_API_KEY":           "test",
    "WHATSAPP_PHONE_NUMBER_ID": "PNID",
    "WHATSAPP_ACCESS_TOKEN":    "WA_TOKEN",
    "WHATSAPP_VERIFY_TOKEN":    "VERIFY_ME",
    "WHATSAPP_APP_SECRET":      "supersecret",
}.items():
    os.environ.setdefault(k, v)

import jwt as pyjwt
from fastapi.testclient import TestClient

from src.main import app
from src.utils.config_loader import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = 7
ORG_ID  = 42
EMAIL   = "faculty@uni.edu"


def _jwt(uid=USER_ID, oid=ORG_ID, email=EMAIL, role="SUPER_ADMIN") -> str:
    # Default role is SUPER_ADMIN so a single token passes every route guard
    # (require_roles rejects a token with no role claim). Pass role=... to test
    # role-specific behaviour.
    return pyjwt.encode(
        {"user_id": uid, "org_id": oid, "email": email, "role": role,
         "exp": int(time.time()) + 3600},
        Config.SECRET_KEY,
        algorithm=Config.ALGORITHM,
    )


def _hdr() -> dict:
    return {"Authorization": f"Bearer {_jwt()}"}


client = TestClient(app)


# ---------------------------------------------------------------------------
# Health + JWT plumbing
# ---------------------------------------------------------------------------

class TestHealthAndAuthPlumbing(unittest.TestCase):

    def test_root_health_no_auth(self):
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_secure_requires_jwt(self):
        r = client.get("/api/test-secure")
        # FastAPI's HTTPBearer returns 403 when header missing; our middleware
        # returns 401. Either is "blocked".
        self.assertIn(r.status_code, (401, 403))

    def test_secure_with_valid_jwt(self):
        r = client.get("/api/test-secure", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["user_id"], USER_ID)
        self.assertEqual(body["org_id"], ORG_ID)

    def test_secure_with_expired_jwt(self):
        bad = pyjwt.encode(
            {"user_id": 1, "org_id": 1, "email": "x@y", "exp": 1},
            Config.SECRET_KEY, algorithm=Config.ALGORITHM,
        )
        r = client.get("/api/test-secure", headers={"Authorization": f"Bearer {bad}"})
        self.assertEqual(r.status_code, 401)

    def test_docs_public(self):
        # Swagger UI is auth-excluded.
        r = client.get("/docs")
        self.assertEqual(r.status_code, 200)
        r = client.get("/openapi.json")
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# /auth/* (Google OAuth)
# ---------------------------------------------------------------------------

class TestAuthRoutes(unittest.TestCase):

    def test_login_url(self):
        with mock.patch("src.api.routes.auth.auth_service") as svc:
            svc.get_login_url.return_value = "https://accounts.google.com/o/oauth2/auth?stub"
            r = client.get("/auth/login-url")
        self.assertEqual(r.status_code, 200)
        self.assertIn("accounts.google.com", r.json()["url"])

    def test_callback_happy_path(self):
        with mock.patch("src.api.routes.auth.auth_service") as svc, \
             mock.patch("src.api.routes.auth.upsert_google_user") as upsert, \
             mock.patch("src.api.routes.auth.create_jwt_token") as mint:
            async def fake_exchange(code):  return {"access_token": "AT", "refresh_token": "RT"}
            async def fake_user_info(at):    return {"email": "u@x.io", "name": "U", "picture": "p"}
            svc.exchange_code.side_effect = fake_exchange
            svc.get_user_info.side_effect = fake_user_info
            svc.encrypt_token.return_value = "ENC"
            upsert.return_value = {"id": 1, "org_id": 1, "email": "u@x.io",
                                    "full_name": "U", "picture_url": "p", "role": "FACULTY"}
            mint.return_value = "JWT_VAL"
            r = client.post("/auth/callback", json={"code": "abc"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["token"], "JWT_VAL")

    def test_callback_google_error(self):
        with mock.patch("src.api.routes.auth.auth_service") as svc:
            async def fake_exchange(code):  return {"error": "invalid_grant"}
            svc.exchange_code.side_effect = fake_exchange
            r = client.post("/auth/callback", json={"code": "bad"})
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# /api/v1/meetings
# ---------------------------------------------------------------------------

class TestMeetingsRoutes(unittest.TestCase):

    def test_create_meeting_requires_jwt(self):
        r = client.post("/api/v1/meetings", json={
            "title": "x", "start_datetime": "2026-05-01T10:00:00",
            "end_datetime": "2026-05-01T11:00:00", "participant_names": [],
        })
        self.assertIn(r.status_code, (401, 403))

    def test_create_meeting_dispatches(self):
        with mock.patch("src.api.routes.meetings.create_meeting") as m:
            m.return_value = {"success": True, "meeting_id": "MID-1"}
            r = client.post("/api/v1/meetings", json={
                "title": "Sync", "start_datetime": "2026-05-01T10:00:00",
                "end_datetime": "2026-05-01T11:00:00",
                "participant_names": ["Aniket"],
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["meeting_id"], "MID-1")
        m.assert_called_once()
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["scheduler_email"], EMAIL)
        self.assertEqual(kwargs["title"], "Sync")
        self.assertEqual(kwargs["participant_names"], ["Aniket"])

    def test_create_meeting_failure_returns_400(self):
        with mock.patch("src.api.routes.meetings.create_meeting") as m:
            m.return_value = {"success": False, "error": "Conflict"}
            r = client.post("/api/v1/meetings", json={
                "title": "x", "start_datetime": "2026-05-01T10:00:00",
                "end_datetime": "2026-05-01T11:00:00", "participant_names": [],
            }, headers=_hdr())
        self.assertEqual(r.status_code, 400)

    def test_reschedule_meeting(self):
        with mock.patch("src.api.routes.meetings.reschedule_meeting") as m:
            m.return_value = {"success": True}
            r = client.patch("/api/v1/meetings/MID-1", json={
                "new_start_datetime": "2026-05-02T10:00:00",
                "new_end_datetime":   "2026-05-02T11:00:00",
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once()

    def test_cancel_meeting(self):
        with mock.patch("src.api.routes.meetings.cancel_meeting") as m:
            m.return_value = {"success": True}
            r = client.delete("/api/v1/meetings/MID-1", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once()
        self.assertEqual(m.call_args.kwargs["meeting_id"], "MID-1")

    def test_search_meetings(self):
        with mock.patch("src.api.routes.meetings.search_meetings") as m:
            m.return_value = {"success": True, "data": []}
            r = client.post("/api/v1/meetings/search",
                            json={"participants": ["Aniket"]}, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once_with({"participants": ["Aniket"]})


# ---------------------------------------------------------------------------
# /api/v1/availability
# ---------------------------------------------------------------------------

class TestAvailabilityRoute(unittest.TestCase):

    def test_availability_dispatches(self):
        with mock.patch("src.api.routes.availability.calculate_free_slots") as m:
            m.return_value = {"success": True, "data": {"free_slots": []}}
            r = client.post("/api/v1/availability", json={
                "range_start": "2026-05-01T09:00:00",
                "range_end":   "2026-05-01T17:00:00",
                "duration_minutes": 30,
                "buffer_minutes":   10,
                "busy_payload": {"calendars": {EMAIL: {"busy": []}}},
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once()

    def test_availability_requires_jwt(self):
        r = client.post("/api/v1/availability", json={
            "range_start": "2026-05-01T09:00:00",
            "range_end":   "2026-05-01T17:00:00",
        })
        self.assertIn(r.status_code, (401, 403))


# ---------------------------------------------------------------------------
# /api/v1/agenda
# ---------------------------------------------------------------------------

class TestAgendaRoute(unittest.TestCase):

    def test_agenda_dispatches(self):
        with mock.patch("src.api.routes.agenda.generate_daily_briefing") as m:
            m.return_value = {"success": True, "data": []}
            r = client.get("/api/v1/agenda?date=2026-05-01", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once_with(user_email=EMAIL, date="2026-05-01")

    def test_agenda_missing_date_422(self):
        r = client.get("/api/v1/agenda", headers=_hdr())
        self.assertEqual(r.status_code, 422)


# ---------------------------------------------------------------------------
# /api/v1/process — LLM intent routing
# ---------------------------------------------------------------------------

class TestProcessRoutes(unittest.TestCase):

    def test_process_intent(self):
        # Fully replace the lazy singleton with a stub so no NVIDIA call fires.
        from src.api.routes import process as proc_mod
        stub = mock.MagicMock()
        stub.process_user_intent.return_value = {
            "intent": "list_meetings", "entities": {}, "confidence": 0.9,
        }
        with mock.patch.object(proc_mod, "_get_processor", return_value=stub):
            r = client.post("/api/v1/process", json={
                "user_input": "what meetings do I have today",
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["intent"], "list_meetings")

    def test_process_execute_routes_through_intent_router(self):
        from src.api.routes import process as proc_mod
        stub = mock.MagicMock()
        stub.process_user_intent.return_value = {
            "intent": "list_meetings", "entities": {}, "confidence": 0.9,
        }
        with mock.patch.object(proc_mod, "_get_processor", return_value=stub), \
             mock.patch.object(proc_mod, "route_intent") as rt:
            rt.return_value = {"success": True, "data": []}
            r = client.post("/api/v1/process/execute", json={
                "user_input": "what meetings do I have today",
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        rt.assert_called_once()
        # route_intent is called as (intent_result, scheduler_email, org_id=...)
        args, kwargs = rt.call_args
        positional_or_kw = list(args) + [kwargs.get(k) for k in ("scheduler_email", "org_id")]
        self.assertIn(EMAIL,  positional_or_kw)
        self.assertIn(ORG_ID, positional_or_kw)

    def test_process_execute_propagates_llm_error(self):
        from src.api.routes import process as proc_mod
        stub = mock.MagicMock()
        stub.process_user_intent.return_value = {"intent": "error", "message": "boom"}
        with mock.patch.object(proc_mod, "_get_processor", return_value=stub):
            r = client.post("/api/v1/process/execute", json={
                "user_input": "garble",
            }, headers=_hdr())
        self.assertEqual(r.status_code, 500)

    def test_process_clarify(self):
        with mock.patch("src.api.routes.process.get_clarification") as m:
            m.return_value = "When should the meeting start?"
            r = client.post("/api/v1/process/clarify", json={
                "missing_fields": ["start_time"],
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        self.assertIn("question", r.json())


# ---------------------------------------------------------------------------
# /api/v1/notifications
# ---------------------------------------------------------------------------

class TestNotificationsRoutes(unittest.TestCase):

    def test_create_notification(self):
        with mock.patch("src.api.routes.notifications.create_notification") as m:
            m.return_value = {"success": True}
            r = client.post("/api/v1/notifications", json={
                "user_id": 1, "message": "hi", "notification_type": "info",
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once()

    def test_get_notifications(self):
        with mock.patch("src.api.routes.notifications.get_notifications") as m:
            m.return_value = {"success": True, "data": []}
            r = client.get("/api/v1/notifications/1?unread_only=true", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        kwargs = m.call_args.kwargs
        self.assertEqual(kwargs["user_id"], 1)
        self.assertTrue(kwargs["unread_only"])

    def test_mark_read(self):
        with mock.patch("src.api.routes.notifications.mark_notification_read") as m:
            m.return_value = {"success": True}
            r = client.patch("/api/v1/notifications/123/read", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once_with(notification_id=123)


# ---------------------------------------------------------------------------
# /api/v1/email/*
# ---------------------------------------------------------------------------

class TestEmailRoutes(unittest.TestCase):

    def test_send_direct_email(self):
        from src.api.routes import email as email_mod
        with mock.patch.object(email_mod, "_email_service") as svc:
            svc.send_email.return_value = {"success": True}
            r = client.post("/api/v1/email/send", json={
                "target_name": "Aniket", "subject": "Hi", "message_body": "Hello",
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        svc.send_email.assert_called_once()

    def test_queue_email(self):
        with mock.patch("src.api.routes.email.queue_email") as m:
            r = client.post("/api/v1/email/queue", json={
                "to_addr": "x@y.com", "subject": "Hi", "body": "Hello",
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once()

    def test_email_notify(self):
        with mock.patch("src.api.routes.email.send_meeting_notification") as m:
            m.return_value = {"success": True}
            r = client.post("/api/v1/email/notify", json={
                "recipient_email": "x@y.com", "notification_type": "invite",
                "meeting_details": {"title": "Sync"},
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once()


# ---------------------------------------------------------------------------
# /api/v1/calendar/sync + /api/v1/analytics/meetings
# ---------------------------------------------------------------------------

class TestCalendarAndAnalytics(unittest.TestCase):

    def test_calendar_sync(self):
        with mock.patch("src.api.routes.calendar.sync_calendar_changes") as m:
            m.return_value = {"success": True, "data": {"synced": 0}}
            r = client.post("/api/v1/calendar/sync", json={
                "calendar_id": "primary", "lookback_minutes": 60,
            }, headers=_hdr())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once()

    def test_analytics(self):
        with mock.patch("src.api.routes.analytics.get_meeting_analytics") as m:
            m.return_value = {"success": True, "data": {"total_meetings": 0}}
            r = client.get(
                "/api/v1/analytics/meetings?from_date=2026-04-01&to_date=2026-04-30",
                headers=_hdr(),
            )
        self.assertEqual(r.status_code, 200)
        m.assert_called_once_with(EMAIL, "2026-04-01", "2026-04-30")


# ---------------------------------------------------------------------------
# /api/v1/uploads
# ---------------------------------------------------------------------------

class TestUploadsRoute(unittest.TestCase):

    def test_upload_dispatches(self):
        # parse_file/extract_attendees/extract_meeting/persist all mocked.
        from src.api.routes import uploads as up
        with mock.patch.object(up, "parse_file") as pf, \
             mock.patch.object(up, "extract_attendees") as ea, \
             mock.patch.object(up, "extract_meeting_metadata") as em, \
             mock.patch.object(up, "persist_pending_upload") as pp:
            pf.return_value = {"kind": "text", "text": "hello"}
            ea.return_value = []
            em.return_value = {"found": False}
            pp.return_value = 99
            r = client.post(
                "/api/v1/uploads",
                files={"file": ("note.txt", b"hello world", "text/plain")},
                headers=_hdr(),
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["upload_id"], 99)
        self.assertEqual(body["kind"], "text")
        self.assertFalse(body["meeting_found"])

    def test_upload_extracts_meeting_when_present(self):
        from src.api.routes import uploads as up
        with mock.patch.object(up, "parse_file") as pf, \
             mock.patch.object(up, "extract_attendees") as ea, \
             mock.patch.object(up, "extract_meeting_metadata") as em, \
             mock.patch.object(up, "persist_pending_upload") as pp:
            pf.return_value = {"kind": "text", "text": "Meeting Tuesday 4pm"}
            ea.return_value = [{"email": "a@u.edu"}]
            em.return_value = {"found": True, "title": "Faculty meeting",
                                "start_time": "2026-05-04T16:00:00",
                                "end_time": "2026-05-04T17:00:00",
                                "location": "Room 302", "agenda": None}
            pp.return_value = 100
            r = client.post(
                "/api/v1/uploads",
                files={"file": ("agenda.txt", b"...", "text/plain")},
                headers=_hdr(),
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["meeting_found"])
        self.assertEqual(body["meeting"]["title"], "Faculty meeting")

    def test_upload_unsupported_extension(self):
        r = client.post(
            "/api/v1/uploads",
            files={"file": ("audio.mp3", b"fake", "audio/mpeg")},
            headers=_hdr(),
        )
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# /api/v1/groups/*
# ---------------------------------------------------------------------------

class TestGroupRoutes(unittest.TestCase):

    def test_list_groups(self):
        with mock.patch("src.api.routes.groups.group_service") as gs:
            gs.list_groups.return_value = [{"id": 1, "name": "CSE-3A",
                                             "member_count": 47}]
            r = client.get("/api/v1/groups", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"][0]["name"], "CSE-3A")
        gs.list_groups.assert_called_once_with(ORG_ID)

    def test_create_group(self):
        with mock.patch("src.api.routes.groups.group_service") as gs:
            gs.create_group.return_value = {"success": True,
                                             "data": {"id": 5, "name": "CSE-3A"}}
            r = client.post("/api/v1/groups",
                            json={"name": "CSE-3A", "description": "section A"},
                            headers=_hdr())
        self.assertEqual(r.status_code, 200)
        gs.create_group.assert_called_once()
        kwargs = gs.create_group.call_args.kwargs
        self.assertEqual(kwargs["org_id"], ORG_ID)
        self.assertEqual(kwargs["name"], "CSE-3A")
        self.assertEqual(kwargs["created_by"], USER_ID)

    def test_delete_group(self):
        with mock.patch("src.api.routes.groups.group_service") as gs:
            gs.delete_group.return_value = {"success": True}
            r = client.delete("/api/v1/groups/5", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        gs.delete_group.assert_called_once_with(ORG_ID, 5)

    def test_list_members(self):
        with mock.patch("src.api.routes.groups.group_service") as gs:
            gs.list_members.return_value = [{"id": 1, "email": "a@u.edu"}]
            r = client.get("/api/v1/groups/5/members", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        gs.list_members.assert_called_once_with(ORG_ID, 5)

    def test_add_members_by_email(self):
        with mock.patch("src.api.routes.groups.group_service") as gs:
            gs.add_members_by_email.return_value = {"success": True,
                                                     "matched": 2, "missing": []}
            r = client.post("/api/v1/groups/5/members",
                            json={"emails": ["a@u.edu", "b@u.edu"]},
                            headers=_hdr())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["added"], 2)

    def test_add_members_requires_payload(self):
        r = client.post("/api/v1/groups/5/members", json={}, headers=_hdr())
        self.assertEqual(r.status_code, 400)

    def test_remove_member(self):
        with mock.patch("src.api.routes.groups.group_service") as gs:
            gs.remove_member.return_value = {"success": True}
            r = client.delete("/api/v1/groups/5/members/9", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        gs.remove_member.assert_called_once_with(ORG_ID, 5, 9)


# ---------------------------------------------------------------------------
# /webhooks/whatsapp
# ---------------------------------------------------------------------------

def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        Config.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()


class TestWhatsAppWebhook(unittest.TestCase):

    def test_verify_handshake_success(self):
        r = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe",
                    "hub.verify_token": Config.WHATSAPP_VERIFY_TOKEN,
                    "hub.challenge": "ECHO_ME"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "ECHO_ME")

    def test_verify_handshake_bad_token(self):
        r = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe",
                    "hub.verify_token": "WRONG",
                    "hub.challenge": "ECHO_ME"},
        )
        self.assertEqual(r.status_code, 403)

    def test_inbound_rejects_bad_signature(self):
        body = json.dumps({"entry": []}).encode()
        r = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": "sha256=" + ("0" * 64),
                     "Content-Type": "application/json"},
        )
        self.assertEqual(r.status_code, 403)

    def test_inbound_dispatches_to_orchestrator(self):
        payload = {
            "entry": [
                {"changes": [{"value": {"messages": [
                    {"from": "919999999999", "id": "wamid.x", "type": "text",
                     "text": {"body": "hi"}},
                ]}}]},
            ],
        }
        body = json.dumps(payload).encode()
        sig = _sign(body)
        with mock.patch("src.services.whatsapp_orchestrator.handle_webhook_payload") as h:
            r = client.post(
                "/webhooks/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": sig,
                         "Content-Type": "application/json"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["received"])
        h.assert_called_once()

    def test_inbound_swallows_orchestrator_exceptions(self):
        # Orchestrator failure must not turn into a non-2xx (Meta retries hard).
        body = json.dumps({"entry": []}).encode()
        sig = _sign(body)
        with mock.patch("src.services.whatsapp_orchestrator.handle_webhook_payload",
                        side_effect=RuntimeError("DB down")):
            r = client.post(
                "/webhooks/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": sig,
                         "Content-Type": "application/json"},
            )
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# /api/v1/experimental/meeting/*  (lifecycle state machine)
# ---------------------------------------------------------------------------

class TestLifecycleRoutes(unittest.TestCase):

    def test_create_pending(self):
        with mock.patch("src.api.lifecycle_routes.lifecycle_store") as store:
            r = client.post("/api/v1/experimental/meeting/MID-9", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        store.create_meeting.assert_called_once_with("MID-9")

    def test_schedule_transition(self):
        with mock.patch("src.api.lifecycle_routes.transition_meeting_status") as t:
            t.return_value = {"success": True, "message": "ok"}
            r = client.patch("/api/v1/experimental/meeting/MID-9/schedule", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        t.assert_called_once_with("MID-9", "SCHEDULED")

    def test_cancel_transition(self):
        with mock.patch("src.api.lifecycle_routes.transition_meeting_status") as t:
            t.return_value = {"success": True, "message": "ok"}
            r = client.delete("/api/v1/experimental/meeting/MID-9", headers=_hdr())
        self.assertEqual(r.status_code, 200)
        t.assert_called_once_with("MID-9", "CANCELLED")

    def test_failed_transition_returns_400(self):
        with mock.patch("src.api.lifecycle_routes.transition_meeting_status") as t:
            t.return_value = {"success": False, "message": "Invalid transition"}
            r = client.patch("/api/v1/experimental/meeting/MID-9/schedule", headers=_hdr())
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
