from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Literal


@dataclass
class SessionKey:
    """Session key with automatic transport detection.

    - HTTP with session ID: Uses mcp:{sessionId}:{paymentId} for multi-client isolation
    - STDIO or HTTP without session: Uses {provider}:{paymentId} for single client

    Note: HTTP transport should provide Mcp-Session-Id header per MCP spec.
    If missing, falls back to provider:paymentId (less isolation between clients).
    """

    provider: str
    payment_id: str
    mcp_session_id: Optional[str] = None  # MCP session ID (HTTP) - optional for STDIO

    def to_str(self) -> str:
        """Generate storage key based on available identifiers.

        Always uses {provider}:{paymentId} for simplicity and recovery.
        This allows any client to recover a payment by knowing the payment_id.
        """
        # Always use provider:payment_id for simplicity
        # This allows recovery after timeout without needing session ID
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
