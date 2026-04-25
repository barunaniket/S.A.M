"""
Dependency probes for the /api/v1/health endpoint.

Each probe runs in parallel, has a hard timeout, and returns a dict
{status: "live"|"broken", latency_ms: int, error?: str} — never raises.

Probes intentionally do not exercise mutating paths (no chat completion,
no email send, no calendar write); they verify reachability + auth handshake
only. That keeps /api/v1/health cheap and free of side effects.
"""

from __future__ import annotations

import asyncio
import smtplib
import time
from typing import Awaitable, Callable, Dict

import httpx

from src.utils.config_loader import Config


PROBE_TIMEOUT_S = 5.0
_ERROR_MAX_LEN = 120


def _live(latency_ms: int) -> Dict[str, object]:
    return {"status": "live", "latency_ms": latency_ms}


def _broken(latency_ms: int, error: str) -> Dict[str, object]:
    return {"status": "broken", "latency_ms": latency_ms, "error": error[:_ERROR_MAX_LEN]}


def _skipped(reason: str) -> Dict[str, object]:
    return {"status": "skipped", "latency_ms": 0, "error": reason}


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------

def _probe_database_sync() -> Dict[str, object]:
    from src.utils.db_handler import get_db_connection, release_db_connection

    started = time.perf_counter()
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        cur.close()
        return _live(int((time.perf_counter() - started) * 1000))
    except Exception as e:
        return _broken(int((time.perf_counter() - started) * 1000), f"{type(e).__name__}: {e}")
    finally:
        if conn is not None:
            try:
                release_db_connection(conn)
            except Exception:
                pass


def _probe_redis_sync() -> Dict[str, object]:
    import redis

    started = time.perf_counter()
    try:
        client = redis.from_url(Config.REDIS_URL, socket_connect_timeout=PROBE_TIMEOUT_S,
                                socket_timeout=PROBE_TIMEOUT_S)
        client.ping()
        return _live(int((time.perf_counter() - started) * 1000))
    except Exception as e:
        return _broken(int((time.perf_counter() - started) * 1000), f"{type(e).__name__}: {e}")


async def _probe_llm_nvidia() -> Dict[str, object]:
    if not Config.NVIDIA_API_KEY:
        return _skipped("NVIDIA_API_KEY not configured")

    started = time.perf_counter()
    headers = {"Authorization": f"Bearer {Config.NVIDIA_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            resp = await client.get(f"{Config.NVIDIA_BASE_URL.rstrip('/')}/models", headers=headers)
        latency = int((time.perf_counter() - started) * 1000)
        # Reachability + auth: anything <500 means the server responded.
        # 401/403 still means the endpoint is up but the key is bad — surface that.
        if resp.status_code >= 500:
            return _broken(latency, f"HTTP {resp.status_code}")
        if resp.status_code in (401, 403):
            return _broken(latency, f"HTTP {resp.status_code} (auth failed)")
        return _live(latency)
    except Exception as e:
        return _broken(int((time.perf_counter() - started) * 1000), f"{type(e).__name__}: {e}")


async def _probe_google_oauth() -> Dict[str, object]:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            resp = await client.get("https://accounts.google.com/.well-known/openid-configuration")
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code == 200:
            return _live(latency)
        return _broken(latency, f"HTTP {resp.status_code}")
    except Exception as e:
        return _broken(int((time.perf_counter() - started) * 1000), f"{type(e).__name__}: {e}")


def _probe_smtp_sync() -> Dict[str, object]:
    if not Config.SENDER_EMAIL or not Config.SENDER_PASSWORD:
        return _skipped("SENDER_EMAIL/SENDER_PASSWORD not configured")

    started = time.perf_counter()
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=PROBE_TIMEOUT_S) as s:
            s.starttls()
            s.login(Config.SENDER_EMAIL, Config.SENDER_PASSWORD)
        return _live(int((time.perf_counter() - started) * 1000))
    except Exception as e:
        return _broken(int((time.perf_counter() - started) * 1000), f"{type(e).__name__}: {e}")


async def _probe_whatsapp_graph() -> Dict[str, object]:
    if not Config.WHATSAPP_PHONE_NUMBER_ID or not Config.WHATSAPP_ACCESS_TOKEN:
        return _skipped("WhatsApp credentials not configured")

    started = time.perf_counter()
    url = (f"https://graph.facebook.com/{Config.WHATSAPP_GRAPH_VERSION}/"
           f"{Config.WHATSAPP_PHONE_NUMBER_ID}")
    headers = {"Authorization": f"Bearer {Config.WHATSAPP_ACCESS_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            resp = await client.get(url, headers=headers)
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code == 200:
            return _live(latency)
        if resp.status_code in (401, 403):
            return _broken(latency, f"HTTP {resp.status_code} (auth failed)")
        return _broken(latency, f"HTTP {resp.status_code}")
    except Exception as e:
        return _broken(int((time.perf_counter() - started) * 1000), f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

# Public dependency keys — referenced by ENDPOINT_DEPS in the route handler.
DEPENDENCY_NAMES = (
    "database",
    "redis",
    "llm_nvidia",
    "google_oauth",
    "smtp",
    "whatsapp_graph",
)


async def _run(probe: Callable[[], Awaitable[Dict[str, object]]]) -> Dict[str, object]:
    """Wrap a probe with a hard timeout so a single hung dep can't stall /health."""
    try:
        return await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_S + 0.5)
    except asyncio.TimeoutError:
        return _broken(int(PROBE_TIMEOUT_S * 1000), "probe timed out")
    except Exception as e:
        return _broken(0, f"{type(e).__name__}: {e}")


async def check_all() -> Dict[str, Dict[str, object]]:
    """Run every dependency probe in parallel and return a name -> result map."""
    results = await asyncio.gather(
        _run(lambda: asyncio.to_thread(_probe_database_sync)),
        _run(lambda: asyncio.to_thread(_probe_redis_sync)),
        _run(_probe_llm_nvidia),
        _run(_probe_google_oauth),
        _run(lambda: asyncio.to_thread(_probe_smtp_sync)),
        _run(_probe_whatsapp_graph),
    )
    return dict(zip(DEPENDENCY_NAMES, results))
