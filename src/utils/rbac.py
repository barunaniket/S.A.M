"""
Role-based access control for FastAPI routes.

The JWT middleware (src/utils/middleware.py) populates request.state.role from
the JWT payload. require_roles(...) is a FastAPI dependency that asserts the
caller's role is in the allowed set, raising 403 otherwise.

Usage::

    from fastapi import APIRouter, Depends
    from src.utils.rbac import require_roles

    router = APIRouter()

    @router.post("/academic/upload",
                 dependencies=[Depends(require_roles("SUPER_ADMIN"))])
    def upload_calendar(...):
        ...
"""

from typing import Iterable

from fastapi import HTTPException, Request, status


# Canonical role set. Anything outside this is rejected at decode time.
KNOWN_ROLES = frozenset({
    "ADMIN",
    "FACULTY",
    "STUDENT",
    "SUPER_ADMIN",
    "BOOKING_AUTHORITY",
})


def require_roles(*allowed: str):
    """
    Build a FastAPI dependency that allows only the given roles.

    SUPER_ADMIN always passes (org-wide root). If a route should *also* allow
    SUPER_ADMIN explicitly, just include "SUPER_ADMIN" in `allowed`.

    Empty `allowed` means "any authenticated user" — useful as an explicit
    opt-out marker for routes that intentionally don't gate by role.
    """
    allowed_set = frozenset(allowed)

    unknown = allowed_set - KNOWN_ROLES
    if unknown:
        raise ValueError(f"require_roles() got unknown role(s): {sorted(unknown)}")

    def _dep(request: Request) -> str:
        role = getattr(request.state, "role", None)
        if not role:
            # JWT did not carry role. The middleware will already have
            # rejected unauthenticated requests, so this is a malformed token.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token missing role claim — please log in again.",
            )

        if not allowed_set:
            return role  # ANY-authenticated opt-out

        if role == "SUPER_ADMIN" or role in allowed_set:
            return role

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This action requires one of: {sorted(allowed_set)}",
        )

    return _dep


def has_role(request: Request, *allowed: str) -> bool:
    """Convenience predicate for inline checks (not for dependency injection)."""
    role = getattr(request.state, "role", None)
    if not role:
        return False
    if role == "SUPER_ADMIN":
        return True
    return role in set(allowed)
