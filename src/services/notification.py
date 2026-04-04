"""
notification.py
---------------
CRUD operations for in-app notifications.

Feature 12: After inserting a notification to DB, publish it to a Redis
pub/sub channel so connected WebSocket clients receive it in real time.
"""

import json

from src.utils.db_handler import get_db_connection, release_db_connection


def _publish_to_redis(user_id: int, message: str, notification_type: str):
    """Non-fatal Redis publish for WebSocket push (Feature 12)."""
    try:
        import redis as _redis
        from src.utils.config_loader import Config
        r = _redis.Redis.from_url(Config.REDIS_URL, decode_responses=True)
        r.publish(
            f"notifications:{user_id}",
            json.dumps({"message": message, "type": notification_type}),
        )
        r.close()
    except Exception as e:
        print(f"[notification] Redis publish failed (non-fatal): {e}")


def create_notification(user_id: int, message: str, notification_type: str) -> dict:
    """
    Persist a notification record for the frontend to poll,
    and publish to Redis so WebSocket clients are notified immediately.

    Returns dict with success bool.
    """

    query = """
        INSERT INTO notifications (user_id, message, type, read)
        VALUES (%s, %s, %s, %s);
    """

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, (user_id, message, notification_type, False))
        conn.commit()
        cur.close()

        # Real-time push
        _publish_to_redis(user_id, message, notification_type)

        return {"success": True, "message": "Notification created"}
    except Exception as e:
        if conn:
            conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            release_db_connection(conn)


def get_notifications(user_id: int, unread_only: bool = False) -> dict:
    """Fetch notifications for a user."""

    query = """
        SELECT id, user_id, message, type, read, created_at
        FROM notifications
        WHERE user_id = %s
    """
    if unread_only:
        query += " AND read = FALSE"
    query += " ORDER BY created_at DESC LIMIT 50;"

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, (user_id,))
        rows = cur.fetchall()
        cur.close()
        return {"success": True, "data": [dict(r) for r in rows]}
    except Exception as e:
        if conn:
            conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            release_db_connection(conn)


def mark_notification_read(notification_id: int) -> dict:
    """Mark a single notification as read."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE notifications SET read = TRUE WHERE id = %s;",
            (notification_id,),
        )
        conn.commit()
        cur.close()
        return {"success": True}
    except Exception as e:
        if conn:
            conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            release_db_connection(conn)
