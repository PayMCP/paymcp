# tests/state/test_redis.py
"""Tests for RedisStateStore."""

import pytest

# Skip all tests if redis is not installed
try:
    from paymcp.state import RedisStateStore
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis package not installed")


@pytest.mark.asyncio
@pytest.mark.integration  # Mark as integration test (requires Redis server)
async def test_redis_set_and_get():
    """Test storing and retrieving data from Redis."""
    store = RedisStateStore(redis_url="redis://localhost:6379/0")

    try:
        # Store data
        await store.set("test_key", {"arg1": "value1", "arg2": 42})

        # Retrieve data
        result = await store.get("test_key")
        assert result is not None
        assert result["args"] == {"arg1": "value1", "arg2": 42}
        assert "ts" in result
        assert isinstance(result["ts"], float)
    finally:
        # Cleanup
        await store.delete("test_key")
        await store.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_get_nonexistent():
    """Test retrieving nonexistent key returns None."""
    store = RedisStateStore(redis_url="redis://localhost:6379/0")

    try:
        result = await store.get("nonexistent_key_redis")
        assert result is None
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_delete():
    """Test deleting data from Redis."""
    store = RedisStateStore(redis_url="redis://localhost:6379/0")

    try:
        # Store data
        await store.set("test_key_delete", {"data": "value"})

        # Verify it exists
        result = await store.get("test_key_delete")
        assert result is not None

        # Delete it
        await store.delete("test_key_delete")

        # Verify it's gone
        result = await store.get("test_key_delete")
        assert result is None
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_ttl():
    """Test that data expires after TTL."""
    import asyncio

    store = RedisStateStore(redis_url="redis://localhost:6379/0", ttl=2)  # 2 second TTL

    try:
        # Store data with short TTL
        await store.set("ttl_test_key", {"data": "value"})

        # Should exist immediately
        result = await store.get("ttl_test_key")
        assert result is not None

        # Wait for expiration
        await asyncio.sleep(3)

        # Should be gone
        result = await store.get("ttl_test_key")
        assert result is None
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_key_prefix():
    """Test that key prefix is applied correctly."""
    store = RedisStateStore(redis_url="redis://localhost:6379/0", key_prefix="test_prefix:")

    try:
        await store.set("my_key", {"data": "value"})

        # Verify we can retrieve with the same store
        result = await store.get("my_key")
        assert result is not None
        assert result["args"]["data"] == "value"

        # Verify key has prefix in Redis
        client = await store._get_client()
        # The actual key in Redis should be "test_prefix:my_key"
        raw_key = "test_prefix:my_key"
        exists = await client.exists(raw_key)
        assert exists == 1

        # Cleanup
        await store.delete("my_key")
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_complex_data():
    """Test storing complex nested data structures in Redis."""
    store = RedisStateStore(redis_url="redis://localhost:6379/0")

    complex_data = {
        "user": "test_user",
        "params": {
            "nested": {
                "value": 123,
                "list": [1, 2, 3]
            }
        },
        "items": ["a", "b", "c"]
    }

    try:
        await store.set("complex_key", complex_data)
        result = await store.get("complex_key")

        assert result["args"] == complex_data
        assert result["args"]["params"]["nested"]["list"] == [1, 2, 3]
    finally:
        await store.delete("complex_key")
        await store.close()


def test_redis_import_error():
    """Test that proper error is raised when redis is not installed."""
    # This test is only meaningful if redis IS installed
    if not REDIS_AVAILABLE:
        pytest.skip("redis is not installed - cannot test import error")

    # If redis IS installed, we can't test the ImportError
    # This is a placeholder to document the expected behavior
    pass
