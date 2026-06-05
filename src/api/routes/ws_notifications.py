"""
ws_notifications.py
-------------------
Feature 12: Real-time notification push via WebSocket + Redis pub/sub.

WS /api/v1/ws/notifications/{user_id}

When notification.py calls create_notification(), it publishes to the Redis
channel "notifications:{user_id}".  This endpoint subscribes to that channel
and forwards each message to the connected WebSocket client immediately.

Falls back gracefully if Redis is unavailable — the polling endpoint at
GET /api/v1/notifications/{user_id} continues to work as before.
"""

import asyncio
import json
import logging

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from src.utils.config_loader import Config

logger = logging.getLogger(__name__)

router = APIRouter()


def _authorize(websocket: WebSocket, user_id: int) -> bool:
    """
    Validate the JWT passed as a `?token=` query param and confirm it belongs
    to `user_id`. WebSocket handshakes bypass the HTTP JWT middleware and
    browsers can't set an Authorization header on a WebSocket, so the token
    rides in the query string. Without this check any client could subscribe
    to another user's notification channel (IDOR).
    """
    token = websocket.query_params.get("token")
    if not token:
        return False
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=[Config.ALGORITHM])
    except jwt.InvalidTokenError:
        return False
    # The token's identity must match the channel being subscribed to.
    return payload.get("user_id") == user_id


@router.websocket("/ws/notifications/{user_id}")
async def websocket_notifications(websocket: WebSocket, user_id: int):
    """
    Stream real-time notifications to a connected client.

    The client connects once and receives JSON messages as they arrive:
        {"message": "...", "type": "invite|update|cancel|reminder"}

    The connection stays open until the client disconnects. The client must
    supply its JWT as `?token=<jwt>`; a missing/invalid token, or one whose
    user_id doesn't match the path, is rejected before accept.
    """
    if not _authorize(websocket, user_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    try:
        import redis.asyncio as aioredis
        from src.utils.config_loader import Config

        r      = aioredis.from_url(Config.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"notifications:{user_id}")

        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message.get("type") == "message":
                    await websocket.send_text(message["data"])
                else:
                    # Yield control so FastAPI can process other requests
                    await asyncio.sleep(0.05)

        except WebSocketDisconnect:
            pass

        finally:
            await pubsub.unsubscribe(f"notifications:{user_id}")
            await r.aclose()

    except ImportError:
        # redis.asyncio not available — send a one-time error and close
        await websocket.send_text(
            json.dumps({"error": "Redis not available; use polling endpoint instead."})
        )
        await websocket.close()

    except Exception:
        logger.exception("[ws_notifications] Unexpected error for user %s", user_id)
        try:
            await websocket.close()
        except Exception:
            pass
