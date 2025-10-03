# paymcp/state/redis.py
"""Redis-based state store implementation."""

from typing import Dict, Any, Optional
import json
import time
import logging

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None  # Set to None for type hints
    logger.warning("redis package not installed. RedisStateStore will not be available.")


if REDIS_AVAILABLE:
    class RedisStateStore:
        """Redis-based state store for distributed deployments.

        Suitable for production environments with multiple server instances.
        Data persists across process restarts.

        Requires redis package: pip install redis
        """

        def __init__(
            self,
            redis_url: str = "redis://localhost:6379/0",
            key_prefix: str = "paymcp:pending:",
            ttl: int = 3600
        ):
            """Initialize the Redis state store.

            Args:
                redis_url: Redis connection URL
                key_prefix: Prefix for all keys stored in Redis
                ttl: Time-to-live for stored data in seconds (default: 1 hour)

            Raises:
                ImportError: If redis package is not installed
            """
            self.redis_url = redis_url
            self.key_prefix = key_prefix
            self.ttl = ttl
            self._client: Optional[aioredis.Redis] = None
            logger.debug(f"RedisStateStore initialized with URL: {redis_url}")

        async def _get_client(self) -> aioredis.Redis:
            """Get or create Redis client connection.

            Returns:
                Redis client instance
            """
            if self._client is None:
                self._client = await aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
                logger.debug("Redis client connected")
            return self._client

        def _make_key(self, payment_id: str) -> str:
            """Generate Redis key with prefix.

            Args:
                payment_id: Payment identifier

            Returns:
                Full Redis key
            """
            return f"{self.key_prefix}{payment_id}"

        async def set(self, key: str, args: Dict[str, Any]) -> None:
            """Store arguments in Redis.

            Args:
                key: Unique payment identifier
                args: Dictionary of tool arguments to store

            Raises:
                Exception: If Redis operation fails
            """
            client = await self._get_client()
            redis_key = self._make_key(key)

            data = {
                'args': args,
                'ts': time.time()
            }

            # Store as JSON string with TTL
            await client.setex(
                redis_key,
                self.ttl,
                json.dumps(data)
            )
            logger.debug(f"Stored args for payment {key} in Redis (TTL: {self.ttl}s)")

        async def get(self, key: str) -> Optional[Dict[str, Any]]:
            """Retrieve arguments from Redis.

            Args:
                key: Unique payment identifier

            Returns:
                Dictionary with 'args' and 'ts' keys if found, None otherwise

            Raises:
                Exception: If Redis operation fails
            """
            client = await self._get_client()
            redis_key = self._make_key(key)

            data_str = await client.get(redis_key)
            if data_str is None:
                logger.debug(f"No args found for payment {key} in Redis")
                return None

            data = json.loads(data_str)
            logger.debug(f"Retrieved args for payment {key} from Redis")
            return data

        async def delete(self, key: str) -> None:
            """Delete arguments from Redis.

            Args:
                key: Unique payment identifier

            Raises:
                Exception: If Redis operation fails
            """
            client = await self._get_client()
            redis_key = self._make_key(key)

            deleted = await client.delete(redis_key)
            if deleted:
                logger.debug(f"Deleted args for payment {key} from Redis")
            else:
                logger.debug(f"No args to delete for payment {key} in Redis")

        async def close(self) -> None:
            """Close the Redis connection."""
            if self._client:
                await self._client.aclose()
                self._client = None
                logger.debug("Redis client closed")
else:
    # Provide a stub class that raises error when instantiated
    class RedisStateStore:
        """Stub class when redis is not installed."""

        def __init__(self, *args, **kwargs):
            raise ImportError(
                "redis package is required for RedisStateStore. "
                "Install with: pip install paymcp[redis]"
            )
