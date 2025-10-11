"""In-memory state storage (default, backward compatible)."""
from typing import Any, Dict, Optional
import time


class InMemoryStateStore:
    """Default in-memory storage for TWO_STEP flow (not durable)."""

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}

    async def set(self, key: str, args: Any) -> None:
        self._store[key] = {"args": args, "ts": int(time.time() * 1000)}

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
