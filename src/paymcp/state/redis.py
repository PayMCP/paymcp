"""Redis state storage (production, durable, scalable)."""
from typing import Any, Dict, Optional, TYPE_CHECKING
import json
import time

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisStateStore:
    """Production Redis storage for TWO_STEP flow."""

    def __init__(self, redis_client: "Redis", key_prefix: str = "paymcp:", ttl: int = 3600):
        self.redis = redis_client
        self.prefix = key_prefix
        self.ttl = ttl

    async def set(self, key: str, args: Any) -> None:
        data = json.dumps({"args": args, "ts": int(time.time() * 1000)})
        await self.redis.setex(f"{self.prefix}{key}", self.ttl, data)

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        raw = await self.redis.get(f"{self.prefix}{key}")
        return json.loads(raw) if raw else None

    async def delete(self, key: str) -> None:
        await self.redis.delete(f"{self.prefix}{key}")
