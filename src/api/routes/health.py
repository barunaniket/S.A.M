"""
GET /api/v1/health — point-in-time status of every API endpoint.

Strategy:
  1. Probe each external dependency once (DB, Redis, NVIDIA LLM, Google OAuth,
     SMTP, WhatsApp Graph) — see src.services.health_check.
  2. Walk app.routes and tag each route with the dependencies it relies on.
  3. A route is "live" iff every dep in its declared list is "live".

Public endpoint — added to the JWT skip list in src/utils/middleware.py so
uptime monitors and load balancers can scrape it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable, List, Tuple

from fastapi import APIRouter, Request
from fastapi.routing import APIRoute, APIWebSocketRoute

from src.services import health_check

router = APIRouter()


# Ordered list of (path_prefix, deps). The first matching prefix wins, so put
# more-specific prefixes BEFORE their parents (e.g. /api/v1/ws/notifications
# must come before any other /api/v1/* rule).
_ENDPOINT_DEPS: List[Tuple[str, List[str]]] = [
    # Public / framework
    ("/api/v1/health",                 []),
    ("/api/test-secure",               []),

    # Auth (Google OAuth)
    ("/auth",                          ["google_oauth"]),

    # Lifecycle (experimental meeting state machine)
    ("/api/v1/experimental/meeting",   ["database", "google_oauth"]),

    # Core domain
    ("/api/v1/meetings",               ["database", "google_oauth"]),
    ("/api/v1/availability",           ["database", "google_oauth"]),
    ("/api/v1/agenda",                 ["database", "google_oauth"]),
    ("/api/v1/calendar",               ["database", "google_oauth"]),
    ("/api/v1/process",                ["database", "llm_nvidia"]),
    ("/api/v1/notifications",          ["database"]),
    ("/api/v1/email",                  ["database", "smtp", "redis"]),
    ("/api/v1/analytics",              ["database"]),
    ("/api/v1/ws/notifications",       ["redis", "database"]),
    ("/api/v1/uploads",                ["database"]),
    ("/api/v1/groups",                 ["database"]),

    # Webhooks
    ("/webhooks/whatsapp",             ["whatsapp_graph", "database"]),
]

# Routes that exist on the app but are part of the framework, not the API.
_FRAMEWORK_PATHS = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}


def _deps_for(path: str) -> Tuple[List[str], bool]:
    """Return (deps, unmapped). Exact-match `/` short-circuits to no deps."""
    if path == "/":
        return [], False
    for prefix, deps in _ENDPOINT_DEPS:
        # Exact match, or this is a sub-path of the prefix
        # (so /api/v1/meetings/{id} matches the /api/v1/meetings rule).
        if path == prefix or path.startswith(prefix + "/"):
            return deps, False
    # Default — surface so the operator notices the gap.
    return ["database"], True


def _iter_routes(routes: Iterable) -> Iterable[Tuple[str, str, str]]:
    """Yield (method, path, tag) for every API and WebSocket route."""
    for route in routes:
        if isinstance(route, APIRoute):
            tag = (route.tags[0] if route.tags else "")
            for method in sorted(route.methods or []):
                if method in ("HEAD", "OPTIONS"):
                    continue
                yield method, route.path, tag
        elif isinstance(route, APIWebSocketRoute):
            yield "WS", route.path, "WebSocket"


@router.get("/health")
async def api_health(request: Request):
    """Report dependency health and per-endpoint status."""
    started = time.perf_counter()

    deps = await health_check.check_all()

    endpoints = []
    live_count = 0
    broken_count = 0

    for method, path, tag in _iter_routes(request.app.routes):
        if path in _FRAMEWORK_PATHS:
            continue

        required, unmapped = _deps_for(path)
        broken_due_to = [d for d in required if deps.get(d, {}).get("status") == "broken"]
        status = "broken" if broken_due_to else "live"

        entry = {
            "method": method,
            "path": path,
            "tag": tag,
            "depends_on": required,
            "status": status,
        }
        if broken_due_to:
            entry["broken_due_to"] = broken_due_to
        if unmapped:
            entry["unmapped"] = True

        endpoints.append(entry)
        if status == "live":
            live_count += 1
        else:
            broken_count += 1

    duration_ms = int((time.perf_counter() - started) * 1000)

    return {
        "success": True,
        "data": {
            "summary": {
                "total_endpoints": len(endpoints),
                "live": live_count,
                "broken": broken_count,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
            },
            "dependencies": deps,
            "endpoints": endpoints,
        },
    }
