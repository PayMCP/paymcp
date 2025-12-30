"""Redis state storage (production, durable, scalable)."""
from typing import Any, Dict, Optional, TYPE_CHECKING
import json
import time
import asyncio
from contextlib import asynccontextmanager

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisStateStore:
    """Production Redis storage for TWO_STEP flow."""

    def __init__(self, redis_client: "Redis", key_prefix: str = "paymcp:", ttl: int = 3600, lock_timeout: int = 30):
        self.redis = redis_client
        self.prefix = key_prefix
        self.ttl = ttl
        self.lock_timeout = lock_timeout

    async def set(self, key: str, args: Any, ttl_seconds: Optional[int] = None) -> None:
        data = json.dumps({"args": args, "ts": int(time.time() * 1000)})
        ttl = self.ttl if ttl_seconds is None else ttl_seconds
        await self.redis.setex(f"{self.prefix}{key}", ttl, data)

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        raw = await self.redis.get(f"{self.prefix}{key}")
        return json.loads(raw) if raw else None

    async def delete(self, key: str) -> None:
        await self.redis.delete(f"{self.prefix}{key}")

    async def get_and_delete(self, key: str) -> Optional[Dict[str, Any]]:
        """Atomically get and delete a key using Redis pipeline.

        This operation is atomic to prevent race conditions where multiple
        concurrent requests try to use the same payment_id.
        """
        full_key = f"{self.prefix}{key}"
        pipe = self.redis.pipeline()
        pipe.get(full_key)
        pipe.delete(full_key)
        results = await pipe.execute()
        raw = results[0]
        return json.loads(raw) if raw else None

    @asynccontextmanager
    async def lock(self, key: str, timeout: Optional[int] = None):
        """Acquire a distributed lock for a specific payment_id using Redis.

        This ensures that only one request across ALL server instances can
        process a specific payment_id at a time, preventing both race
        conditions and payment loss issues.

        Args:
            key: The payment_id to lock
            timeout: Lock timeout in seconds (default: self.lock_timeout)

        Usage:
            async with state_store.lock(payment_id):
                # Critical section - only one request at a time across all servers
                stored = await state_store.get(payment_id)
                # ... process payment ...
                await state_store.delete(payment_id)
        """
        lock_key = f"{self.prefix}lock:{key}"
        lock_timeout = timeout or self.lock_timeout
        lock_value = f"{time.time()}"  # Unique value for this lock acquisition

        # Try to acquire lock with exponential backoff
        acquired = False
        max_attempts = 10
        attempt = 0

        while not acquired and attempt < max_attempts:
            # SET NX EX: Set if Not eXists with EXpiration
            acquired = await self.redis.set(
                lock_key,
                lock_value,
                nx=True,  # Only set if doesn't exist
                ex=lock_timeout  # Expires after timeout seconds
            )

            if not acquired:
                # Wait with exponential backoff
                wait_time = min(0.1 * (2 ** attempt), 2.0)  # Max 2 seconds
                await asyncio.sleep(wait_time)
                attempt += 1

        if not acquired:
            raise RuntimeError(
                f"Failed to acquire lock for payment_id={key} after {max_attempts} attempts. "
                "Another request may be processing this payment."
            )

        try:
            yield
        finally:
            # Release lock only if we still own it (check value matches)
            # Use Lua script for atomic check-and-delete
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await self.redis.eval(lua_script, 1, lock_key, lock_value)
