"""Tests for Redis state store with mocked Redis client.

These tests verify the RedisStateStore wrapper logic without requiring a real Redis instance.
Integration tests with real Redis are in paymcp-flow-tester.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json
import time


def create_mock_redis_client():
    """Helper to create a properly configured mock Redis client."""
    mock_client = AsyncMock()
    mock_client.setex = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.delete = AsyncMock()
    mock_client.aclose = AsyncMock()
    return mock_client


@pytest.mark.asyncio
async def test_redis_initialization():
    """Test RedisStateStore initialization with custom parameters."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        from paymcp.state.redis import RedisStateStore

        store = RedisStateStore(
            redis_url="redis://localhost:6379/1",
            key_prefix="test:prefix:",
            ttl=7200
        )
        assert store.redis_url == "redis://localhost:6379/1"
        assert store.key_prefix == "test:prefix:"
        assert store.ttl == 7200
        assert store._client is None  # Lazy initialization


@pytest.mark.asyncio
async def test_redis_make_key():
    """Test key formatting with prefix."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        from paymcp.state.redis import RedisStateStore

        store = RedisStateStore(key_prefix="paymcp:test:")
        assert store._make_key("payment123") == "paymcp:test:payment123"
        assert store._make_key("abc") == "paymcp:test:abc"


@pytest.mark.asyncio
async def test_redis_set():
    """Test set() method calls setex with correct parameters."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()

            async def mock_from_url(*args, **kwargs):
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore(ttl=3600)
            test_args = {'tool': 'test', 'amount': 1.00}

            await store.set('payment_id_123', test_args)

            # Verify setex was called
            assert mock_client.setex.called
            call_args = mock_client.setex.call_args[0]

            # Check key
            assert call_args[0] == "paymcp:pending:payment_id_123"

            # Check TTL
            assert call_args[1] == 3600

            # Check data is JSON with args and timestamp
            data = json.loads(call_args[2])
            assert 'args' in data
            assert 'ts' in data
            assert data['args'] == test_args


@pytest.mark.asyncio
async def test_redis_get_existing():
    """Test get() method retrieves and deserializes data."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()

            test_data = {
                'args': {'tool': 'test', 'amount': 1.00},
                'ts': time.time()
            }
            mock_client.get.return_value = json.dumps(test_data)

            async def mock_from_url(*args, **kwargs):
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore()
            result = await store.get('payment_id_123')

            # Verify get was called with correct key
            mock_client.get.assert_called_once_with("paymcp:pending:payment_id_123")

            # Verify data was deserialized correctly
            assert result is not None
            assert result['args'] == test_data['args']
            assert 'ts' in result


@pytest.mark.asyncio
async def test_redis_get_nonexistent():
    """Test get() returns None for nonexistent key."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()
            mock_client.get.return_value = None

            async def mock_from_url(*args, **kwargs):
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore()
            result = await store.get('nonexistent_key')

            assert result is None


@pytest.mark.asyncio
async def test_redis_delete():
    """Test delete() method calls Redis delete."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()
            mock_client.delete.return_value = 1  # Key was deleted

            async def mock_from_url(*args, **kwargs):
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore()
            await store.delete('payment_id_123')

            # Verify delete was called with correct key
            mock_client.delete.assert_called_once_with("paymcp:pending:payment_id_123")


@pytest.mark.asyncio
async def test_redis_delete_nonexistent():
    """Test delete() works even if key doesn't exist."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()
            mock_client.delete.return_value = 0  # Key didn't exist

            async def mock_from_url(*args, **kwargs):
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore()
            await store.delete('nonexistent_key')

            # Should not raise an error
            assert mock_client.delete.called


@pytest.mark.asyncio
async def test_redis_close():
    """Test close() method properly closes the Redis client."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()

            async def mock_from_url(*args, **kwargs):
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore()

            # Initialize client
            await store._get_client()
            assert store._client is not None

            # Close
            await store.close()

            # Verify aclose was called
            mock_client.aclose.assert_called_once()

            # Verify client is cleared
            assert store._client is None


@pytest.mark.asyncio
async def test_redis_close_no_client():
    """Test close() works even if client was never initialized."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        from paymcp.state.redis import RedisStateStore

        store = RedisStateStore()

        # Close without initializing client
        await store.close()  # Should not raise


@pytest.mark.asyncio
async def test_redis_client_lazy_initialization():
    """Test that Redis client is created lazily on first use."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()
            call_count = 0

            async def mock_from_url(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore()
            assert store._client is None

            # First operation triggers client creation
            await store.set('key1', {'data': '1'})
            assert call_count == 1

            # Subsequent operations reuse client
            mock_client.get.return_value = json.dumps({'args': {'data': '1'}, 'ts': time.time()})
            await store.get('key1')
            await store.delete('key1')

            # Client should still only be created once
            assert call_count == 1


@pytest.mark.asyncio
async def test_redis_connection_parameters():
    """Test that connection parameters are passed correctly to Redis."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()

            async def mock_from_url(url, encoding, decode_responses):
                # Verify parameters
                assert url == "redis://custom:6379/5"
                assert encoding == "utf-8"
                assert decode_responses == True
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore(redis_url="redis://custom:6379/5")
            await store._get_client()


@pytest.mark.asyncio
async def test_redis_complex_data_serialization():
    """Test that complex nested data structures are serialized correctly."""
    with patch('paymcp.state.redis.REDIS_AVAILABLE', True):
        with patch('paymcp.state.redis.aioredis') as mock_aioredis:
            from paymcp.state.redis import RedisStateStore

            mock_client = create_mock_redis_client()

            async def mock_from_url(*args, **kwargs):
                return mock_client

            mock_aioredis.from_url = mock_from_url

            store = RedisStateStore()

            complex_args = {
                'nested': {
                    'deep': {
                        'data': [1, 2, 3]
                    }
                },
                'list': ['a', 'b', 'c'],
                'number': 42,
                'boolean': True,
                'null': None
            }

            await store.set('complex_key', complex_args)

            # Verify data was JSON serialized correctly
            call_args = mock_client.setex.call_args[0]
            stored_data = json.loads(call_args[2])
            assert stored_data['args'] == complex_args


def test_redis_stub_class_when_unavailable():
    """Test that stub class raises ImportError when redis package not installed."""
    # We can't easily test the actual stub class without reloading the module
    # But we can verify the conditional logic exists
    from paymcp.state import redis as redis_module

    assert hasattr(redis_module, 'REDIS_AVAILABLE')
    assert hasattr(redis_module, 'RedisStateStore')

    # When REDIS_AVAILABLE is True (normal case), we get the real class
    # When False, we get the stub class that raises ImportError
    # The stub class testing is better done in integration tests
