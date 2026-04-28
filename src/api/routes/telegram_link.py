"""
/api/v1/me/telegram/* — pairing-code lifecycle for the SPOC's Telegram link.

Three routes:

    POST   /api/v1/me/telegram/pair      generate a 6-char code (5 min TTL)
    GET    /api/v1/me/telegram/status    is this user paired? what's the handle?
    DELETE /api/v1/me/telegram           unlink (clear telegram_chat_id)

The actual code-consumption lives in
src.services.telegram_orchestrator._try_consume_pairing_code, which fires
when the user DMs the bot `/start CODE`.
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from src.services.telegram_service import is_configured
from src.utils.config_loader import Config
from src.utils.db_handler import get_db_connection, release_db_connection

router = APIRouter()


# Strip ambiguous chars (0/O/1/I/L/Q) so a printed code is unmistakable
# when the SPOC is reading it off the screen and typing it on a phone.
_CODE_ALPHABET = "ABCDEFGHJKMNPRSTUVWXYZ23456789"
_CODE_LEN = 6
_CODE_TTL_MINUTES = 5


def _make_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def _envelope(success: bool, data=None, message: str = "",
              error_code: str = None) -> dict:
    return {"success": success, "data": data,
            "message": message, "error_code": error_code}


@router.post("/pair")
async def create_pairing_code(request: Request):
    """
    Generate a fresh 6-char pairing code for the calling user. Invalidates
    any open codes they had outstanding so the latest one always wins.
    """
    if not is_configured():
        return _envelope(False, message="Telegram bot is not configured on the server.",
                         error_code="NOT_CONFIGURED")

    user_id = getattr(request.state, "user_id", None)
    org_id  = getattr(request.state, "org_id", None)
    if not user_id or not org_id:
        return _envelope(False, message="Missing identity on JWT.",
                         error_code="MISSING_CLAIMS")

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)
    # Try a few times in the unlikely case of a primary-key collision.
    code = None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Mark any outstanding codes for this user as consumed so /status
        # doesn't report stale ones.
        cur.execute(
            "UPDATE telegram_pairing_codes SET consumed = TRUE "
            "WHERE user_id = %s AND consumed = FALSE;",
            (user_id,),
        )
        for _ in range(8):
            candidate = _make_code()
            try:
                cur.execute(
                    """
                    INSERT INTO telegram_pairing_codes
                        (code, user_id, org_id, expires_at)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (candidate, user_id, org_id, expires_at),
                )
                code = candidate
                break
            except Exception:
                conn.rollback()
                continue
        if not code:
            cur.close()
            return _envelope(False, message="Couldn't allocate a pairing code; please retry.",
                             error_code="CODE_COLLISION")
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    bot_username = (Config.TELEGRAM_BOT_USERNAME or "").lstrip("@") or None
    deep_link = f"https://t.me/{bot_username}?start={code}" if bot_username else None
    return _envelope(True, data={
        "code":        code,
        "expires_at":  expires_at.isoformat(),
        "ttl_minutes": _CODE_TTL_MINUTES,
        "bot_username": bot_username,
        "deep_link":   deep_link,
    }, message="Pairing code generated")


@router.get("/status")
async def telegram_status(request: Request):
    """Reports whether the calling user has linked their Telegram account."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return _envelope(False, message="Missing identity on JWT.",
                         error_code="MISSING_CLAIMS")

    if not is_configured():
        return _envelope(True, data={"linked": False, "configured": False},
                         message="Telegram bot is not configured on the server.")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT telegram_chat_id, telegram_username
              FROM users WHERE id = %s LIMIT 1;
            """,
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)

    if not row or not row.get("telegram_chat_id"):
        return _envelope(True,
                         data={"linked": False, "configured": True},
                         message="Telegram not linked")

    return _envelope(True, data={
        "linked":   True,
        "configured": True,
        "username": row.get("telegram_username"),
        "chat_id":  row.get("telegram_chat_id"),
    }, message="Telegram linked")


@router.delete("")
async def unlink_telegram(request: Request):
    """Clear telegram_chat_id and telegram_username for the calling user."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return _envelope(False, message="Missing identity on JWT.",
                         error_code="MISSING_CLAIMS")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE users
               SET telegram_chat_id = NULL, telegram_username = NULL
             WHERE id = %s;
            """,
            (user_id,),
        )
        # Also drop any open pairing codes — the user has explicitly unlinked.
        cur.execute(
            "UPDATE telegram_pairing_codes SET consumed = TRUE "
            "WHERE user_id = %s AND consumed = FALSE;",
            (user_id,),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    return _envelope(True, data={"linked": False},
                     message="Telegram unlinked")
