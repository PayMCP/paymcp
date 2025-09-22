"""Tests for in-memory session storage."""
import pytest
import asyncio
import time
from unittest.mock import patch, MagicMock

from paymcp.session.types import SessionKey, SessionData
from paymcp.session.memory import InMemorySessionStorage


class TestInMemorySessionStorage:
    """Test suite for InMemorySessionStorage."""

    @pytest.fixture
    def storage(self):
        """Create a fresh storage instance for each test."""
        storage = InMemorySessionStorage()
        yield storage
        storage.destroy()

    @pytest.fixture
    def sample_key(self):
        """Sample session key."""
        return SessionKey(provider="stripe", payment_id="pay_123")

    @pytest.fixture
    def sample_data(self):
        """Sample session data."""
        return SessionData(
            args={"amount": 100, "currency": "USD"},
            ts=int(time.time() * 1000),
            provider_name="stripe",
            metadata={"tool": "test"}
        )

    @pytest.mark.asyncio
    async def test_set_and_get(self, storage, sample_key, sample_data):
        """Test storing and retrieving session data."""
        await storage.set(sample_key, sample_data)
        retrieved = await storage.get(sample_key)

        assert retrieved is not None
        assert retrieved.args == sample_data.args
        assert retrieved.provider_name == sample_data.provider_name

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, storage):
        """Test retrieving non-existent session."""
        key = SessionKey(provider="stripe", payment_id="nonexistent")
        retrieved = await storage.get(key)

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_provider_isolation(self, storage, sample_data):
        """Test that different providers don't conflict."""
        stripe_key = SessionKey(provider="stripe", payment_id="pay_123")
        paypal_key = SessionKey(provider="paypal", payment_id="pay_123")

        stripe_data = SessionData(
            args={"provider": "stripe"},
            ts=int(time.time() * 1000)
        )
        paypal_data = SessionData(
            args={"provider": "paypal"},
            ts=int(time.time() * 1000)
        )

        await storage.set(stripe_key, stripe_data)
        await storage.set(paypal_key, paypal_data)

        retrieved_stripe = await storage.get(stripe_key)
        retrieved_paypal = await storage.get(paypal_key)

        assert retrieved_stripe.args["provider"] == "stripe"
        assert retrieved_paypal.args["provider"] == "paypal"

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, storage, sample_key, sample_data):
        """Test session expiration with TTL."""
        # Set with 1 second TTL
        await storage.set(sample_key, sample_data, ttl_seconds=1)

        # Should exist immediately
        assert await storage.has(sample_key) is True

        # Wait for expiration
        await asyncio.sleep(1.5)

        # Should be expired
        assert await storage.has(sample_key) is False

    @pytest.mark.asyncio
    async def test_no_ttl_persistence(self, storage, sample_key, sample_data):
        """Test that sessions without TTL don't expire."""
        await storage.set(sample_key, sample_data)

        # Simulate time passing (without actually sleeping)
        with patch('time.time', return_value=time.time() + 3600):
            retrieved = await storage.get(sample_key)
            assert retrieved is not None

    @pytest.mark.asyncio
    async def test_delete(self, storage, sample_key, sample_data):
        """Test deleting a session."""
        await storage.set(sample_key, sample_data)
        await storage.delete(sample_key)

        retrieved = await storage.get(sample_key)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, storage):
        """Test deleting non-existent session doesn't raise."""
        key = SessionKey(provider="stripe", payment_id="nonexistent")
        # Should not raise
        await storage.delete(key)

    @pytest.mark.asyncio
    async def test_has(self, storage, sample_key, sample_data):
        """Test checking session existence."""
        assert await storage.has(sample_key) is False

        await storage.set(sample_key, sample_data)
        assert await storage.has(sample_key) is True

        await storage.delete(sample_key)
        assert await storage.has(sample_key) is False

    @pytest.mark.asyncio
    async def test_clear(self, storage, sample_data):
        """Test clearing all sessions."""
        keys = [
            SessionKey(provider="stripe", payment_id="pay_1"),
            SessionKey(provider="paypal", payment_id="pay_2"),
            SessionKey(provider="square", payment_id="pay_3"),
        ]

        for key in keys:
            await storage.set(key, sample_data)

        await storage.clear()

        for key in keys:
            assert await storage.has(key) is False

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, storage):
        """Test cleanup removes only expired sessions."""
        expired_key = SessionKey(provider="stripe", payment_id="expired")
        valid_key = SessionKey(provider="stripe", payment_id="valid")
        permanent_key = SessionKey(provider="stripe", payment_id="permanent")

        data = SessionData(args={}, ts=int(time.time() * 1000))

        # Set with different TTLs
        await storage.set(expired_key, data, ttl_seconds=0.1)
        await storage.set(valid_key, data, ttl_seconds=100)
        await storage.set(permanent_key, data)  # No TTL

        # Wait for first to expire
        await asyncio.sleep(0.2)

        await storage.cleanup()

        assert await storage.has(expired_key) is False
        assert await storage.has(valid_key) is True
        assert await storage.has(permanent_key) is True

    @pytest.mark.asyncio
    async def test_cleanup_task_lifecycle(self, storage):
        """Test that cleanup task is managed properly."""
        # The cleanup task is only created if there's a running loop
        # In test environment, it might be None
        if storage.cleanup_task is not None:
            # Destroy should cancel task
            storage.destroy()
            assert storage.cleanup_task.cancelled() or storage.cleanup_task.done()
        else:
            # Just verify destroy works without error
            storage.destroy()

    @pytest.mark.asyncio
    async def test_special_characters_in_keys(self, storage, sample_data):
        """Test handling special characters in keys."""
        special_key = SessionKey(
            provider="stripe-test:special",
            payment_id="pay:123:test/special"
        )

        await storage.set(special_key, sample_data)
        retrieved = await storage.get(special_key)

        assert retrieved is not None
        assert retrieved.args == sample_data.args

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, storage, sample_key):
        """Test concurrent set operations."""
        data1 = SessionData(args={"value": 1}, ts=int(time.time() * 1000))
        data2 = SessionData(args={"value": 2}, ts=int(time.time() * 1000))

        # Concurrent sets - last one wins
        await asyncio.gather(
            storage.set(sample_key, data1),
            storage.set(sample_key, data2)
        )

        retrieved = await storage.get(sample_key)
        # Due to race condition, either value could win
        assert retrieved.args["value"] in [1, 2]

    @pytest.mark.asyncio
    async def test_session_update(self, storage, sample_key):
        """Test updating an existing session."""
        data1 = SessionData(args={"version": 1}, ts=int(time.time() * 1000))
        data2 = SessionData(args={"version": 2}, ts=int(time.time() * 1000))

        await storage.set(sample_key, data1, ttl_seconds=60)
        await storage.set(sample_key, data2, ttl_seconds=120)

        retrieved = await storage.get(sample_key)
        assert retrieved.args["version"] == 2

    def test_start_cleanup_without_running_loop(self):
        """Test that cleanup task handles missing event loop gracefully."""
        # This runs outside async context
        storage = InMemorySessionStorage()
        # Should not raise even without running loop
        assert storage is not None
        storage.destroy()