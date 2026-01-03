"""Tests for RedisStateStore."""

import pytest
from unittest.mock import AsyncMock
import json
from paymcp.state.redis import RedisStateStore


class TestRedisStateStore:
    """Test the Redis state storage implementation."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        from unittest.mock import Mock
        mock = AsyncMock()
        mock.setex = AsyncMock()
        mock.get = AsyncMock()
        mock.delete = AsyncMock()
        # pipeline() should return a regular Mock, not AsyncMock
        mock.pipeline = Mock()
        return mock

    @pytest.fixture
    def store(self, mock_redis):
        """Create a RedisStateStore with mocked Redis client."""
        return RedisStateStore(mock_redis)

    @pytest.mark.asyncio
    async def test_init_defaults(self, mock_redis):
        """Test default initialization parameters."""
        store = RedisStateStore(mock_redis)
        assert store.redis == mock_redis
        assert store.prefix == "paymcp:"
        assert store.ttl == 3600

    @pytest.mark.asyncio
    async def test_init_custom_params(self, mock_redis):
        """Test initialization with custom parameters."""
        store = RedisStateStore(
            mock_redis,
            key_prefix="custom:",
            ttl=7200
        )
        assert store.prefix == "custom:"
        assert store.ttl == 7200

    @pytest.mark.asyncio
    async def test_set(self, store, mock_redis):
        """Test setting a value in Redis."""
        args = {"arg1": "value1", "arg2": "value2"}
        await store.set("test_key", args)

        # Verify setex was called with correct parameters
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]

        # Check key
        assert call_args[0] == "paymcp:test_key"

        # Check TTL
        assert call_args[1] == 3600

        # Check data format
        data = json.loads(call_args[2])
        assert data["args"] == args
        assert "ts" in data
        assert isinstance(data["ts"], int)

    @pytest.mark.asyncio
    async def test_set_with_custom_prefix(self, mock_redis):
        """Test setting a value with custom prefix."""
        store = RedisStateStore(mock_redis, key_prefix="custom:")
        await store.set("test_key", {"data": "value"})

        call_args = mock_redis.setex.call_args[0]
        assert call_args[0] == "custom:test_key"

    @pytest.mark.asyncio
    async def test_set_with_custom_ttl(self, mock_redis):
        """Test setting a value with custom TTL."""
        store = RedisStateStore(mock_redis, ttl=7200)
        await store.set("test_key", {"data": "value"})

        call_args = mock_redis.setex.call_args[0]
        assert call_args[1] == 7200

    @pytest.mark.asyncio
    async def test_set_with_override_ttl_seconds(self, store, mock_redis):
        """Test setting a value with per-call TTL override."""
        await store.set("test_key", {"data": "value"}, ttl_seconds=15)

        call_args = mock_redis.setex.call_args[0]
        assert call_args[1] == 15

    @pytest.mark.asyncio
    async def test_get_existing_key(self, store, mock_redis):
        """Test getting an existing key from Redis."""
        stored_data = json.dumps({
            "args": {"arg1": "value1"},
            "ts": 123456789
        })
        mock_redis.get.return_value = stored_data

        result = await store.get("test_key")

        mock_redis.get.assert_called_once_with("paymcp:test_key")
        assert result["args"] == {"arg1": "value1"}
        assert result["ts"] == 123456789

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, store, mock_redis):
        """Test getting a key that doesn't exist."""
        mock_redis.get.return_value = None

        result = await store.get("nonexistent_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, store, mock_redis):
        """Test deleting a key from Redis."""
        await store.delete("test_key")

        mock_redis.delete.assert_called_once_with("paymcp:test_key")

    @pytest.mark.asyncio
    async def test_delete_with_custom_prefix(self, mock_redis):
        """Test deleting a key with custom prefix."""
        store = RedisStateStore(mock_redis, key_prefix="custom:")
        await store.delete("test_key")

        mock_redis.delete.assert_called_once_with("custom:test_key")

    @pytest.mark.asyncio
    async def test_empty_args(self, store, mock_redis):
        """Test storing empty arguments."""
        await store.set("test_key", {})

        call_args = mock_redis.setex.call_args[0]
        data = json.loads(call_args[2])
        assert data["args"] == {}

    @pytest.mark.asyncio
    async def test_complex_nested_args(self, store, mock_redis):
        """Test storing complex nested data structures."""
        complex_data = {
            "nested": {
                "level1": {
                    "level2": ["item1", "item2", "item3"]
                }
            },
            "list": [1, 2, 3, 4, 5],
            "mixed": {"a": 1, "b": [2, 3], "c": {"d": 4}}
        }

        await store.set("test_key", complex_data)

        call_args = mock_redis.setex.call_args[0]
        data = json.loads(call_args[2])
        assert data["args"] == complex_data

    @pytest.mark.asyncio
    async def test_get_with_bytes_response(self, store, mock_redis):
        """Test getting a key when Redis returns bytes."""
        stored_data = json.dumps({
            "args": {"arg1": "value1"},
            "ts": 123456789
        })
        # Redis sometimes returns bytes instead of str
        mock_redis.get.return_value = stored_data.encode('utf-8')

        result = await store.get("test_key")

        # Should handle bytes correctly
        assert result is not None

    @pytest.mark.asyncio
    async def test_timestamp_in_milliseconds(self, store, mock_redis):
        """Test that timestamp is stored in milliseconds."""
        import time
        before_ms = int(time.time() * 1000)

        await store.set("test_key", {"data": "value"})

        after_ms = int(time.time() * 1000)

        call_args = mock_redis.setex.call_args[0]
        data = json.loads(call_args[2])
        timestamp = data["ts"]

        # Timestamp should be in milliseconds range
        assert before_ms <= timestamp <= after_ms
        # Should be much larger than seconds
        assert timestamp > 1000000000000  # After year 2001 in milliseconds

    @pytest.mark.asyncio
    async def test_get_and_delete_existing_key(self, store, mock_redis):
        """Test atomically getting and deleting an existing key."""
        from unittest.mock import Mock
        stored_data = json.dumps({
            "args": {"data": "value"},
            "ts": 123456789
        })
        mock_pipeline = Mock()
        mock_pipeline.get = Mock()
        mock_pipeline.delete = Mock()
        mock_pipeline.execute = AsyncMock(return_value=[stored_data, 1])
        mock_redis.pipeline.return_value = mock_pipeline

        result = await store.get_and_delete("test_key")

        # Verify pipeline was used
        mock_redis.pipeline.assert_called_once()
        mock_pipeline.get.assert_called_once_with("paymcp:test_key")
        mock_pipeline.delete.assert_called_once_with("paymcp:test_key")
        mock_pipeline.execute.assert_called_once()
        assert result["args"] == {"data": "value"}

    @pytest.mark.asyncio
    async def test_get_and_delete_nonexistent_key(self, store, mock_redis):
        """Test get_and_delete on nonexistent key returns None."""
        from unittest.mock import Mock
        mock_pipeline = Mock()
        mock_pipeline.get = Mock()
        mock_pipeline.delete = Mock()
        mock_pipeline.execute = AsyncMock(return_value=[None, 0])
        mock_redis.pipeline.return_value = mock_pipeline

        result = await store.get_and_delete("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_lock_acquire_and_release(self, store, mock_redis):
        """Test basic lock acquisition and release."""
        mock_redis.set.return_value = True  # Lock acquired
        mock_redis.eval = AsyncMock()

        async with store.lock("test_lock"):
            # Inside lock
            pass

        # Verify lock was acquired
        mock_redis.set.assert_called()
        call_kwargs = mock_redis.set.call_args[1]
        assert call_kwargs["nx"] is True
        assert call_kwargs["ex"] == 30  # default timeout

        # Verify lock was released
        mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_lock_acquire_with_retry(self, store, mock_redis):
        """Test lock acquisition with exponential backoff."""
        # Fail twice, then succeed
        mock_redis.set.side_effect = [False, False, True]
        mock_redis.eval = AsyncMock()

        async with store.lock("test_lock"):
            pass

        # Verify set was called 3 times
        assert mock_redis.set.call_count == 3

    @pytest.mark.asyncio
    async def test_lock_acquisition_failure(self, store, mock_redis):
        """Test RuntimeError when lock cannot be acquired."""
        mock_redis.set.return_value = False  # Always fail

        with pytest.raises(RuntimeError, match="Failed to acquire lock"):
            async with store.lock("test_lock"):
                pass

    @pytest.mark.asyncio
    async def test_lock_custom_timeout(self, store, mock_redis):
        """Test lock with custom timeout."""
        mock_redis.set.return_value = True
        mock_redis.eval = AsyncMock()

        async with store.lock("test_lock", timeout=60):
            pass

        call_kwargs = mock_redis.set.call_args[1]
        assert call_kwargs["ex"] == 60

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(self, store, mock_redis):
        """Test that lock is released even when exception occurs."""
        mock_redis.set.return_value = True
        mock_redis.eval = AsyncMock()

        try:
            async with store.lock("test_lock"):
                raise RuntimeError("Test exception")
        except RuntimeError:
            pass

        # Lock should still be released
        mock_redis.eval.assert_called_once()
