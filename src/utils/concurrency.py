# src/utils/concurrency.py
import os
import uuid
import asyncio
from contextlib import asynccontextmanager
from redis.asyncio import Redis # NOTE: Using Async Redis client

# Connect to Redis (Async Version)
# Decode responses ensures we get strings, not bytes
redis_client = Redis.from_url(
    os.getenv("REDIS_URL", "redis://redis:6379/0"), 
    decode_responses=True
)

# LUA Script for Safe Release (Atomic Check-and-Delete)
UNLOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

class DoubleBookingError(Exception):
    """Raised when the resource is locked by another user."""
    pass

@asynccontextmanager
async def distributed_lock(resource_key: str, lock_timeout: int = 10, retries: int = 3):
    """
    Acquires a distributed lock asynchronously.
    NON-BLOCKING: Allows other users to access the API while this request waits.
    """
    lock_name = f"lock:{resource_key}"
    my_token = str(uuid.uuid4())
    acquired = False

    try:
        # 1. Spin Lock with Async Sleep
        for _ in range(retries + 1):
            # NX=Only set if Not Exists, EX=Expire time
            if await redis_client.set(lock_name, my_token, nx=True, ex=lock_timeout):
                acquired = True
                break
            # CRITICAL FIX: This yields control back to the event loop
            await asyncio.sleep(0.1)

        if not acquired:
            raise DoubleBookingError(f"Resource {resource_key} is currently locked.")

        # 🟢 CRITICAL SECTION
        yield

    finally:
        # 🔴 SAFE RELEASE (Using Lua Script)
        # We ignore errors here to prevent crashing if Redis goes away during release
        try:
            await redis_client.eval(UNLOCK_SCRIPT, 1, lock_name, my_token)
        except Exception as e:
            print(f"Warning: Failed to release lock {lock_name}: {e}")