"""In-memory state storage (default, backward compatible)."""
from typing import Any, Dict, Optional
import time
import asyncio
from contextlib import asynccontextmanager


class InMemoryStateStore:
    """Default in-memory storage for TWO_STEP flow (not durable)."""

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._payment_locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    async def set(self, key: str, args: Any) -> None:
        async with self._lock:
            self._store[key] = {"args": args, "ts": int(time.time() * 1000)}

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            return self._store.get(key)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def get_and_delete(self, key: str) -> Optional[Dict[str, Any]]:
        """Atomically get and delete a key. Returns None if key doesn't exist.

        This operation is atomic to prevent race conditions where multiple
        concurrent requests try to use the same payment_id.
        """
        async with self._lock:
            return self._store.pop(key, None)

    @asynccontextmanager
    async def lock(self, key: str):
        """Acquire a per-payment-id lock to prevent concurrent access.

        This ensures that only one request can process a specific payment_id
        at a time, preventing both race conditions and payment loss issues.

        Usage:
            async with state_store.lock(payment_id):
                # Critical section - only one request at a time
                stored = await state_store.get(payment_id)
                # ... process payment ...
                await state_store.delete(payment_id)
        """
        # Get or create lock for this payment_id
        async with self._locks_lock:
            if key not in self._payment_locks:
                self._payment_locks[key] = asyncio.Lock()
            payment_lock = self._payment_locks[key]

        # Acquire the payment-specific lock
        async with payment_lock:
            try:
                yield
            finally:
                # Cleanup lock after use
                async with self._locks_lock:
                    if key in self._payment_locks:
                        del self._payment_locks[key]
