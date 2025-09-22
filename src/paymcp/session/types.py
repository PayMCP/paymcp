from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Literal


@dataclass
class SessionKey:
    provider: str
    payment_id: str

    def to_str(self) -> str:
        return f"{self.provider}:{self.payment_id}"


@dataclass
class SessionData:
    args: Dict[str, Any]
    ts: int
    provider_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ISessionStorage(ABC):
    @abstractmethod
    async def set(
        self, key: SessionKey, data: SessionData, ttl_seconds: Optional[int] = None
    ) -> None:
        pass

    @abstractmethod
    async def get(self, key: SessionKey) -> Optional[SessionData]:
        pass

    @abstractmethod
    async def delete(self, key: SessionKey) -> None:
        pass

    @abstractmethod
    async def has(self, key: SessionKey) -> bool:
        pass

    @abstractmethod
    async def clear(self) -> None:
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        pass


@dataclass
class SessionStorageConfig:
    type: Literal["memory", "redis", "custom"]
    options: Optional[Dict[str, Any]] = None
