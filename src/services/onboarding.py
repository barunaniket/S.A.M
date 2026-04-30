"""
onboarding.py
-------------
Chat-first onboarding flow used when an unknown Telegram (or WhatsApp)
user DMs the bot for the first time.

Two halves:

  1. start_onboarding(channel, identifier, ...)
       Generate a token, persist a row in onboarding_tokens, return the
       Google OAuth URL the user should tap. The token is embedded in the
       OAuth `state` param so the callback can route us back here.

  2. complete_onboarding(token, google_userinfo, encrypted_refresh_token,
                          access_token)
       Called from /auth/callback when state == 'onboard:tg:<token>'.
       Looks up (and consumes) the onboarding row, then either:
         - matches an existing pre-seeded user by email and binds the
           channel identifier (telegram_chat_id / phone_number) to them,
         - or creates a fresh user with role STUDENT (the safe default
           for chat-first sign-ups in an institutional roster setting).
       Pushes a welcome DM via the right channel and returns the user.

The flow assumes institutional Gmail-as-roster verification: production
seed data populates `users` with the email of every faculty/student
in advance; the OAuth callback simply matches and binds. New emails
land as STUDENT and can be promoted from the SUPER_ADMIN UI.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from src.utils.config_loader import Config
from src.utils.db_handler import (
    get_db_connection,
    get_system_db,
    release_db_connection,
)
from src.utils.google_auth import GoogleAuthService

logger = logging.getLogger(__name__)


_TOKEN_TTL_MINUTES = 15
_DEFAULT_ORG_ID = 1


# ---------------------------------------------------------------------------
# Step 1: kick off — issue token + Google OAuth URL
# ---------------------------------------------------------------------------

def start_onboarding(channel: str, identifier: str,
                     telegram_username: Optional[str] = None) -> Dict[str, str]:
    """
    Generate an onboarding token, persist it, and build the Google OAuth
    URL the user should tap to verify themselves.

    Returns:
        {"token": ..., "auth_url": ..., "expires_at": ISO}

    Raises:
        ValueError on unknown channel.
    """
    if channel not in ("telegram", "whatsapp"):
        raise ValueError(f"Unsupported onboarding channel: {channel}")

    token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_TOKEN_TTL_MINUTES)

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Mark any earlier open tokens for this identity as consumed so the
        # most recent one is unambiguous (user retried /start).
        cur.execute(
            """
            UPDATE onboarding_tokens
               SET consumed = TRUE
             WHERE channel = %s AND identifier = %s AND consumed = FALSE;
            """,
            (channel, str(identifier)),
        )
        cur.execute(
            """
            INSERT INTO onboarding_tokens
                (token, channel, identifier, telegram_username, expires_at)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (token, channel, str(identifier), telegram_username, expires_at),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    auth_service = GoogleAuthService()
    state = f"onboard:{('tg' if channel == 'telegram' else 'wa')}:{token}"
    auth_url = auth_service.get_login_url(state)
    return {"token": token, "auth_url": auth_url,
            "expires_at": expires_at.isoformat()}


# ---------------------------------------------------------------------------
# Step 2: complete — consume token + bind/upsert user + welcome DM
# ---------------------------------------------------------------------------

def parse_onboarding_state(state: Optional[str]) -> Optional[Tuple[str, str]]:
    """
    Returns (channel, token) if `state` looks like an onboarding state, else None.
    """
    if not state or not state.startswith("onboard:"):
        return None
    parts = state.split(":")
    if len(parts) != 3:
        return None
    short = parts[1]
    channel = "telegram" if short == "tg" else "whatsapp" if short == "wa" else None
    if not channel:
        return None
    return channel, parts[2]


def complete_onboarding(token: str, google_userinfo: Dict[str, Any],
                        access_token: Optional[str],
                        encrypted_refresh_token: Optional[str]
                        ) -> Optional[Dict[str, Any]]:
    """
    Atomically consume the onboarding token, then either bind the channel
    identifier to a pre-seeded user (matched by email) or create a new
    user with role STUDENT.

    Pushes a welcome DM on the originating channel and returns the user
    dict on success, None on failure.
    """
    email = (google_userinfo.get("email") or "").lower().strip()
    if not email:
        return None

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE onboarding_tokens
               SET consumed = TRUE
             WHERE token = %s
               AND consumed = FALSE
               AND expires_at > NOW()
            RETURNING channel, identifier, telegram_username;
            """,
            (token,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            cur.close()
            logger.warning("complete_onboarding: token invalid/expired/consumed")
            return None

        channel = row["channel"]
        identifier = row["identifier"]
        tg_username = row.get("telegram_username")

        # ---- Roster gate: reject any Google email that wasn't pre-seeded.
        # The institutional roster (data/students.csv + data/faculty.csv,
        # loaded via scripts/load_rosters.py) IS the source of truth for
        # who can onboard. Anyone not in that table gets a friendly DM and
        # the token stays consumed (anti-replay).
        cur.execute(
            "SELECT id, role FROM users WHERE email = %s AND org_id = %s LIMIT 1;",
            (email, _DEFAULT_ORG_ID),
        )
        roster_hit = cur.fetchone()
        if not roster_hit:
            conn.commit()
            cur.close()
            logger.info("complete_onboarding: rejecting non-roster email %s "
                        "(channel=%s)", email, channel)
            _notify_rejected(channel, identifier, email)
            return {
                "rejected": True,
                "reason": "not_in_roster",
                "email": email,
                "channel": channel,
            }

        # Roster match → UPDATE only (we know the row exists, role is preserved).
        if channel == "telegram":
            cur.execute(
                """
                UPDATE users
                   SET full_name               = COALESCE(%s, full_name),
                       picture_url             = COALESCE(%s, picture_url),
                       access_token            = %s,
                       encrypted_refresh_token = COALESCE(%s, encrypted_refresh_token),
                       telegram_chat_id        = %s,
                       telegram_username       = %s,
                       updated_at              = NOW()
                 WHERE email = %s AND org_id = %s
                RETURNING id, org_id, email, full_name, role, picture_url,
                          phone_number, batch, telegram_chat_id, telegram_username,
                          office_location;
                """,
                (
                    google_userinfo.get("name") or None,
                    google_userinfo.get("picture") or None,
                    access_token,
                    encrypted_refresh_token,
                    int(identifier),
                    tg_username,
                    email,
                    _DEFAULT_ORG_ID,
                ),
            )
        else:  # whatsapp
            cur.execute(
                """
                UPDATE users
                   SET full_name               = COALESCE(%s, full_name),
                       picture_url             = COALESCE(%s, picture_url),
                       access_token            = %s,
                       encrypted_refresh_token = COALESCE(%s, encrypted_refresh_token),
                       phone_number            = %s,
                       updated_at              = NOW()
                 WHERE email = %s AND org_id = %s
                RETURNING id, org_id, email, full_name, role, picture_url,
                          phone_number, batch, office_location;
                """,
                (
                    google_userinfo.get("name") or None,
                    google_userinfo.get("picture") or None,
                    access_token,
                    encrypted_refresh_token,
                    identifier,
                    email,
                    _DEFAULT_ORG_ID,
                ),
            )
        user = dict(cur.fetchone())

        # Tag the onboarding row with the user we ended up linking to
        # (audit trail for "did this token actually onboard someone?").
        cur.execute(
            "UPDATE onboarding_tokens SET consumed_user_id = %s WHERE token = %s;",
            (user["id"], token),
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        logger.exception("complete_onboarding failed")
        return None
    finally:
        release_db_connection(conn)

    # Push a welcome DM. Best-effort — onboarding is "done" even if the
    # message fails (the OAuth side already succeeded).
    try:
        _send_welcome(channel, user)
    except Exception:
        logger.exception("Welcome DM failed for user %s", user.get("id"))

    return user


# ---------------------------------------------------------------------------
# Welcome DM (kicks off the role-aware next step)
# ---------------------------------------------------------------------------

def _send_welcome(channel: str, user: Dict[str, Any]) -> None:
    """
    Send a channel-appropriate welcome message. For faculty without a
    timetable yet, kick straight into the timetable upload flow. For
    students, just confirm and prompt for their batch if missing.
    """
    role = (user.get("role") or "").upper()
    name = user.get("full_name") or "there"

    if channel == "telegram":
        from src.services.conversation_store import set_session_tg
        from src.services.telegram_service import send_text

        chat_id = user.get("telegram_chat_id")
        if not chat_id:
            return

        if role in ("FACULTY", "ADMIN", "SUPER_ADMIN"):
            if not _faculty_has_timetable(user["id"]):
                set_session_tg(chat_id, {
                    "user_id": user["id"], "org_id": user["org_id"],
                    "state": "AWAITING_TIMETABLE",
                })
                send_text(chat_id,
                          f"✅ Linked as <b>{name}</b> ({role}).\n\n"
                          "Now let's set up your weekly timetable so students can "
                          "find you and SAM can spot scheduling conflicts.\n\n"
                          "You can:\n"
                          "• Send a <b>photo</b> of your printed timetable\n"
                          "• Send a <b>voice note</b> describing it\n"
                          "• Or <b>type it out</b> (one class per line: "
                          "day, time, subject, room)")
                return
            # Faculty with timetable already on file — fully provisioned.
            send_text(chat_id,
                      f"✅ Linked as <b>{name}</b> ({role}). Welcome back!\n\n"
                      "You can chat with me to schedule meetings, run broadcasts, "
                      "or update your timetable. Type <code>/help</code> for the "
                      "full list.")
            return

        if role == "STUDENT":
            if not user.get("batch"):
                set_session_tg(chat_id, {
                    "user_id": user["id"], "org_id": user["org_id"],
                    "state": "AWAITING_BATCH",
                })
                send_text(chat_id,
                          f"✅ Linked as <b>{name}</b>.\n\n"
                          "What's your batch? (e.g. <code>CSE-3A</code>, "
                          "<code>ECE-2B</code>) — reply with just the batch code.")
                return
            send_text(chat_id,
                      f"✅ Linked as <b>{name}</b> (Student, {user['batch']}). Welcome!\n\n"
                      "You can ask me where any teacher will be, "
                      "what's coming up in your batch's class cancellations, "
                      "or for the day's announcements.")
            return

        if role == "BOOKING_AUTHORITY":
            send_text(chat_id,
                      f"✅ Linked as <b>{name}</b> (Booking authority). Welcome.\n\n"
                      "I'll DM you booking requests as they come in — tap "
                      "Approve or Deny to act on them.")
            return

        send_text(chat_id, f"✅ Linked as <b>{name}</b>.")
        return

    # WhatsApp parallel — same shape, different transport. Stub for now.
    if channel == "whatsapp":
        try:
            from src.services.whatsapp_queue import queue_whatsapp
            phone = user.get("phone_number")
            if phone:
                queue_whatsapp(phone,
                               f"✅ Linked as {name}. Reply 'help' for what I can do.")
        except Exception:
            pass


def _notify_rejected(channel: str, identifier: str, email: str) -> None:
    """
    Best-effort DM to a user whose Google email isn't in the institutional
    roster. Token has already been marked consumed (anti-replay) by the
    caller.
    """
    body = (f"❌ Sorry — your Google account <b>{email}</b> is not on the "
            "institute roster. If this is a mistake, please reach out to "
            "your admin.")
    try:
        if channel == "telegram":
            from src.services.telegram_service import send_text
            send_text(int(identifier), body)
        elif channel == "whatsapp":
            from src.services.whatsapp_queue import queue_whatsapp
            queue_whatsapp(identifier,
                           f"Sorry — your Google account {email} is not on "
                           "the institute roster. If this is a mistake, "
                           "please reach out to your admin.")
    except Exception:
        logger.exception("Failed to DM rejected onboarder %s on %s",
                         email, channel)


def _faculty_has_timetable(user_id: int) -> bool:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM timetable_entries WHERE user_id = %s LIMIT 1;",
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        return bool(row)
    except Exception:
        # Table may not exist yet (very early dev); treat as no timetable
        # so we still send the prompt.
        return False
    finally:
        release_db_connection(conn)
