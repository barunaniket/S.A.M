"""
Walk every FastAPI route and assert each non-`/auth/*`, non-`/webhooks/*`
endpoint has either:
  - a `Depends(require_roles(...))` dependency in its decorator, OR
  - is explicitly whitelisted below as 'auth not required' (health, OAuth
    callback, websocket handshakes).

Exits non-zero if anything is unmapped. Run in CI to prevent the same
'forgot the role guard' regression that bit /meetings, /groups,
/analytics before v13.

    python scripts/audit_route_rbac.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Avoid Config.validate() blowing up if env vars are missing in CI.
for k in ("NVIDIA_API_KEY", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
          "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "DATABASE_URL",
          "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_PROJECT_ID",
          "GOOGLE_API_SCOPES", "SENDER_EMAIL", "SENDER_PASSWORD"):
    os.environ.setdefault(k, "x")


# Routes that explicitly opt out of role gating. Add with care — the JWT
# middleware still applies, so these are still authenticated.
WHITELIST_PREFIXES = (
    "/auth",
    "/webhooks",
    "/api/v1/health",
    "/api/v1/ws/",
    "/docs",
    "/openapi",
    "/redoc",
    "/api/test-secure",
    # User-self-service: every authenticated user manages their own data.
    "/api/v1/me/",
    "/api/v1/notifications",
    "/api/v1/agenda",
    "/api/v1/process",
)
WHITELIST_PATHS = {
    "/",
}


# Routes that are intentionally still on the JWT-only-no-role-guard model
# from before v13's RBAC backfill. The list is now empty — every legacy
# route carries either `require_roles(...)` or `require_roles()` (any-auth).
# Keep this set as the regression backstop: if a *new* route is added
# without a guard, the audit fails. Only add an entry here as a deliberate,
# reviewed exception, and aim to drain it again.
KNOWN_UNGATED: set[str] = set()


def main() -> int:
    from fastapi.routing import APIRoute

    from src.main import app

    new_unmapped: list[str] = []
    legacy_unmapped: list[str] = []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        path = r.path
        if path in WHITELIST_PATHS:
            continue
        if any(path.startswith(p) for p in WHITELIST_PREFIXES):
            continue
        guarded = False
        for dep in r.dependant.dependencies:
            call = getattr(dep, "call", None)
            qualname = getattr(call, "__qualname__", "") or ""
            module = getattr(call, "__module__", "") or ""
            if "require_roles" in qualname or "require_roles" in module:
                guarded = True
                break
            if (qualname.startswith("require_roles.")
                    or module.endswith("rbac")):
                guarded = True
                break
        if guarded:
            continue
        for method in sorted(r.methods or []):
            entry = f"{method} {path}"
            if entry in KNOWN_UNGATED:
                legacy_unmapped.append(entry)
            else:
                new_unmapped.append(entry)

    if legacy_unmapped:
        print(f"⚠ {len(legacy_unmapped)} route(s) on the legacy ungated list "
              "(tracked, not failing):")
        for line in sorted(set(legacy_unmapped)):
            print(f"  {line}")

    if new_unmapped:
        print(f"\n❌ {len(new_unmapped)} NEW route(s) without require_roles "
              "and not in the legacy list:")
        for line in sorted(set(new_unmapped)):
            print(f"  {line}")
        print("\nAdd `dependencies=[Depends(require_roles(...))]` or, for "
              "an explicit any-authenticated route, `Depends(require_roles())`.")
        return 1

    print("\n✅ No new ungated routes. All v13+ endpoints carry require_roles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
