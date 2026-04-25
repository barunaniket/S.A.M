"""
Tests for GET /api/v1/health.

Run from repo root:

    PYTHONPATH=. .venv/bin/python -m unittest tests.test_health_endpoint
"""

import os
import sys
import unittest
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

from fastapi.testclient import TestClient

from src.main import app
from src.api.routes import health as health_route


client = TestClient(app)


def _all_live():
    return {
        "database":       {"status": "live",    "latency_ms": 1},
        "redis":          {"status": "live",    "latency_ms": 1},
        "llm_nvidia":     {"status": "live",    "latency_ms": 1},
        "google_oauth":   {"status": "live",    "latency_ms": 1},
        "smtp":           {"status": "live",    "latency_ms": 1},
        "whatsapp_graph": {"status": "live",    "latency_ms": 1},
    }


class TestHealthEndpoint(unittest.TestCase):

    def test_health_is_public_no_jwt_required(self):
        async def fake(): return _all_live()
        with mock.patch.object(health_route.health_check, "check_all", side_effect=fake):
            r = client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200, r.text)

    def test_all_live_when_every_dep_healthy(self):
        async def fake(): return _all_live()
        with mock.patch.object(health_route.health_check, "check_all", side_effect=fake):
            r = client.get("/api/v1/health")

        body = r.json()
        self.assertTrue(body["success"])
        self.assertGreater(body["data"]["summary"]["total_endpoints"], 0)
        self.assertEqual(body["data"]["summary"]["broken"], 0)
        self.assertEqual(body["data"]["summary"]["live"],
                         body["data"]["summary"]["total_endpoints"])
        for ep in body["data"]["endpoints"]:
            self.assertEqual(ep["status"], "live")
            self.assertNotIn("broken_due_to", ep)

    def test_broken_llm_only_flips_process_routes(self):
        deps = _all_live()
        deps["llm_nvidia"] = {"status": "broken", "latency_ms": 1, "error": "401"}

        async def fake(): return deps
        with mock.patch.object(health_route.health_check, "check_all", side_effect=fake):
            r = client.get("/api/v1/health")

        body = r.json()
        process_routes = [e for e in body["data"]["endpoints"]
                          if e["path"].startswith("/api/v1/process")]
        self.assertGreater(len(process_routes), 0, "expected /api/v1/process* routes to exist")
        for ep in process_routes:
            self.assertEqual(ep["status"], "broken")
            self.assertIn("llm_nvidia", ep["broken_due_to"])

        # Routes that don't depend on the LLM stay live.
        groups_routes = [e for e in body["data"]["endpoints"]
                         if e["path"].startswith("/api/v1/groups")]
        for ep in groups_routes:
            self.assertEqual(ep["status"], "live")

    def test_broken_db_flips_db_routes_but_not_oauth_only(self):
        deps = _all_live()
        deps["database"] = {"status": "broken", "latency_ms": 1, "error": "ECONNREFUSED"}

        async def fake(): return deps
        with mock.patch.object(health_route.health_check, "check_all", side_effect=fake):
            r = client.get("/api/v1/health")

        body = r.json()
        # /auth/* depends only on google_oauth, so it should still be live.
        auth_routes = [e for e in body["data"]["endpoints"] if e["path"].startswith("/auth/")]
        self.assertGreater(len(auth_routes), 0)
        for ep in auth_routes:
            self.assertEqual(ep["status"], "live")

        # /api/v1/groups depends on database → broken.
        groups_routes = [e for e in body["data"]["endpoints"]
                         if e["path"].startswith("/api/v1/groups")]
        for ep in groups_routes:
            self.assertEqual(ep["status"], "broken")
            self.assertEqual(ep["broken_due_to"], ["database"])

    def test_total_endpoints_excludes_framework_routes(self):
        async def fake(): return _all_live()
        with mock.patch.object(health_route.health_check, "check_all", side_effect=fake):
            r = client.get("/api/v1/health")

        body = r.json()
        paths = [e["path"] for e in body["data"]["endpoints"]]
        for fw in ("/openapi.json", "/docs", "/redoc"):
            self.assertNotIn(fw, paths)

    def test_health_route_itself_is_listed_with_no_deps(self):
        async def fake(): return _all_live()
        with mock.patch.object(health_route.health_check, "check_all", side_effect=fake):
            r = client.get("/api/v1/health")

        body = r.json()
        self_entry = next(e for e in body["data"]["endpoints"]
                          if e["path"] == "/api/v1/health")
        self.assertEqual(self_entry["depends_on"], [])
        self.assertEqual(self_entry["status"], "live")

    def test_no_unmapped_endpoints(self):
        """If a new route is added but the ENDPOINT_DEPS table isn't updated,
        this test surfaces it so the operator notices."""
        async def fake(): return _all_live()
        with mock.patch.object(health_route.health_check, "check_all", side_effect=fake):
            r = client.get("/api/v1/health")

        body = r.json()
        unmapped = [e["path"] for e in body["data"]["endpoints"] if e.get("unmapped")]
        self.assertEqual(unmapped, [],
                         f"unmapped routes — add to _ENDPOINT_DEPS in src/api/routes/health.py: {unmapped}")


if __name__ == "__main__":
    unittest.main()
