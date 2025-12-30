"""In-memory state storage (default, backward compatible)."""
from typing import Any, Dict, Optional
import time
import asyncio
from contextlib import asynccontextmanager


class InMemoryStateStore:
    """Default in-memory storage for TWO_STEP flow (not durable)."""

    def __init__(self, ttl: int = 3600, sweep_interval: int = 600):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._payment_locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()
        self._ttl = ttl
        self._sweep_interval_ms = sweep_interval * 1000
        self._last_sweep_ms = 0
        self._sweeper_task: Optional[asyncio.Task] = None
        self._sweeper_stop = asyncio.Event()

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _is_expired(self, entry: Dict[str, Any], now_ms: int) -> bool:
        expires_at = entry.get("expires_at")
        return isinstance(expires_at, (int, float)) and expires_at <= now_ms

    def _sweep_locked(self, now_ms: int) -> None:
        expired_keys = [
            key for key, entry in self._store.items()
            if self._is_expired(entry, now_ms)
        ]
        for key in expired_keys:
            self._store.pop(key, None)
        self._last_sweep_ms = now_ms

    def _sweep_if_needed_locked(self, now_ms: int) -> None:
        if self._sweep_interval_ms <= 0:
            return
        if now_ms - self._last_sweep_ms < self._sweep_interval_ms:
            return
        self._sweep_locked(now_ms)

    def start_sweeper(self) -> None:
        if self._sweep_interval_ms <= 0:
            return
        if self._sweeper_task and not self._sweeper_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._sweeper_task = loop.create_task(self._run_sweeper())

    async def close(self) -> None:
        if not self._sweeper_task:
            return
        self._sweeper_stop.set()
        self._sweeper_task.cancel()
        try:
            await self._sweeper_task
        except asyncio.CancelledError:
            pass
        self._sweeper_task = None
        self._sweeper_stop = asyncio.Event()

    async def _run_sweeper(self) -> None:
        interval_s = self._sweep_interval_ms / 1000
        try:
            while not self._sweeper_stop.is_set():
                await asyncio.sleep(interval_s)
                now_ms = self._now_ms()
                async with self._lock:
                    self._sweep_locked(now_ms)
        except asyncio.CancelledError:
            pass

    async def set(self, key: str, args: Any, ttl_seconds: Optional[int] = None) -> None:
        self.start_sweeper()
        now_ms = self._now_ms()
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        expires_at = int(now_ms + (ttl * 1000)) if ttl and ttl > 0 else None
        async with self._lock:
            self._sweep_if_needed_locked(now_ms)
            self._store[key] = {"args": args, "ts": now_ms, "expires_at": expires_at}

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        self.start_sweeper()
        now_ms = self._now_ms()
        async with self._lock:
            self._sweep_if_needed_locked(now_ms)
            entry = self._store.get(key)
            if not entry:
                return None
            if self._is_expired(entry, now_ms):
                self._store.pop(key, None)
                return None
            return entry

    async def delete(self, key: str) -> None:
        self.start_sweeper()
        now_ms = self._now_ms()
        async with self._lock:
            self._sweep_if_needed_locked(now_ms)
            self._store.pop(key, None)

    async def get_and_delete(self, key: str) -> Optional[Dict[str, Any]]:
        """Atomically get and delete a key. Returns None if key doesn't exist.

        This operation is atomic to prevent race conditions where multiple
        concurrent requests try to use the same payment_id.
        """
        self.start_sweeper()
        now_ms = self._now_ms()
        async with self._lock:
            self._sweep_if_needed_locked(now_ms)
            entry = self._store.pop(key, None)
            if not entry or self._is_expired(entry, now_ms):
                return None
            return entry

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
