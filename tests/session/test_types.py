"""Tests for session types."""

import pytest
from paymcp.session.types import (
    SessionKey,
    SessionData,
    ISessionStorage,
    SessionStorageConfig,
)
from typing import Optional
from dataclasses import asdict


class TestSessionKey:
    def test_to_str(self):
        """Test SessionKey.to_str() method."""
        key = SessionKey(provider="stripe", payment_id="pay_123")
        assert key.to_str() == "stripe:pay_123"

    def test_to_str_with_special_chars(self):
        """Test to_str with special characters."""
        key = SessionKey(provider="paypal-sandbox", payment_id="PAY_ABC#123")
        assert key.to_str() == "paypal-sandbox:PAY_ABC#123"

    def test_to_str_empty_values(self):
        """Test to_str with empty values."""
        key = SessionKey(provider="", payment_id="")
        assert key.to_str() == ":"


class TestSessionData:
    def test_dataclass_fields(self):
        """Test SessionData dataclass fields."""
        data = SessionData(
            args={"amount": 100, "currency": "USD"},
            ts=1234567890,
            provider_name="stripe",
            metadata={"user": "test"},
        )
        assert data.args == {"amount": 100, "currency": "USD"}
        assert data.ts == 1234567890
        assert data.provider_name == "stripe"
        assert data.metadata == {"user": "test"}

    def test_optional_fields_default(self):
        """Test optional fields default to None."""
        data = SessionData(args={"test": "data"}, ts=9999)
        assert data.provider_name is None
        assert data.metadata is None


class TestISessionStorage:
    def test_abstract_interface(self):
        """Test that ISessionStorage is abstract and cannot be instantiated."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ISessionStorage()

    def test_concrete_implementation(self):
        """Test that concrete implementation with all methods works."""

        class ConcreteStorage(ISessionStorage):
            async def set(
                self,
                key: SessionKey,
                data: SessionData,
                ttl_seconds: Optional[int] = None,
            ) -> None:
                pass

            async def get(self, key: SessionKey) -> Optional[SessionData]:
                return None

            async def delete(self, key: SessionKey) -> None:
                pass

            async def has(self, key: SessionKey) -> bool:
                return False

            async def clear(self) -> None:
                pass

            async def cleanup(self) -> None:
                pass

        # Should not raise error
        storage = ConcreteStorage()
        assert isinstance(storage, ISessionStorage)


class TestSessionStorageConfig:
    def test_memory_type(self):
        """Test config with memory type."""
        config = SessionStorageConfig(type="memory")
        assert config.type == "memory"
        assert config.options is None

    def test_redis_type_with_options(self):
        """Test config with redis type and options."""
        config = SessionStorageConfig(
            type="redis", options={"host": "localhost", "port": 6379}
        )
        assert config.type == "redis"
        assert config.options == {"host": "localhost", "port": 6379}

    def test_custom_type(self):
        """Test config with custom type."""
        config = SessionStorageConfig(
            type="custom", options={"implementation": "MyCustomStorage"}
        )
        assert config.type == "custom"
        assert config.options["implementation"] == "MyCustomStorage"
