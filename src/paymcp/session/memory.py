import asyncio
import time
from typing import Dict, Optional
from dataclasses import dataclass

from .types import ISessionStorage, SessionData, SessionKey

@dataclass
class StoredSession:
    data: SessionData
    expires_at: Optional[float] = None

class InMemorySessionStorage(ISessionStorage):
    def __init__(self):
        self.storage: Dict[str, StoredSession] = {}
        self.cleanup_task: Optional[asyncio.Task] = None
        self._start_cleanup()

    def _start_cleanup(self):
        try:
            loop = asyncio.get_running_loop()
            if self.cleanup_task is None or self.cleanup_task.done():
                self.cleanup_task = loop.create_task(self._cleanup_loop())
        except RuntimeError:
            pass

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(60)
            await self.cleanup()

    async def set(self, key: SessionKey, data: SessionData, ttl_seconds: Optional[int] = None) -> None:
        composite_key = key.to_str()
        expires_at = None
        if ttl_seconds:
            expires_at = time.time() + ttl_seconds

        self.storage[composite_key] = StoredSession(
            data=data,
            expires_at=expires_at
        )

    async def get(self, key: SessionKey) -> Optional[SessionData]:
        composite_key = key.to_str()
        stored = self.storage.get(composite_key)

        if not stored:
            return None

        if stored.expires_at and time.time() > stored.expires_at:
            del self.storage[composite_key]
            return None

        return stored.data

    async def delete(self, key: SessionKey) -> None:
        composite_key = key.to_str()
        if composite_key in self.storage:
            del self.storage[composite_key]

    async def has(self, key: SessionKey) -> bool:
        data = await self.get(key)
        return data is not None

    async def clear(self) -> None:
        self.storage.clear()

    async def cleanup(self) -> None:
        now = time.time()
        keys_to_remove = []
        for key, stored in self.storage.items():
            if stored.expires_at and now > stored.expires_at:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.storage[key]

    def destroy(self):
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
        self.storage.clear()