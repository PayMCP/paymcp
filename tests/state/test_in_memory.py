# tests/state/test_in_memory.py
"""Tests for InMemoryStateStore."""

import pytest
from paymcp.state import InMemoryStateStore


@pytest.mark.asyncio
async def test_set_and_get():
    """Test storing and retrieving data."""
    store = InMemoryStateStore()

    # Store data
    await store.set("test_key", {"arg1": "value1", "arg2": 42})

    # Retrieve data
    result = await store.get("test_key")
    assert result is not None
    assert result["args"] == {"arg1": "value1", "arg2": 42}
    assert "ts" in result
    assert isinstance(result["ts"], float)


@pytest.mark.asyncio
async def test_get_nonexistent():
    """Test retrieving nonexistent key returns None."""
    store = InMemoryStateStore()

    result = await store.get("nonexistent_key")
    assert result is None


@pytest.mark.asyncio
async def test_delete():
    """Test deleting data."""
    store = InMemoryStateStore()

    # Store data
    await store.set("test_key", {"data": "value"})

    # Verify it exists
    result = await store.get("test_key")
    assert result is not None

    # Delete it
    await store.delete("test_key")

    # Verify it's gone
    result = await store.get("test_key")
    assert result is None


@pytest.mark.asyncio
async def test_delete_nonexistent():
    """Test deleting nonexistent key doesn't raise error."""
    store = InMemoryStateStore()

    # Should not raise
    await store.delete("nonexistent_key")


@pytest.mark.asyncio
async def test_overwrite():
    """Test overwriting existing data."""
    store = InMemoryStateStore()

    # Store initial data
    await store.set("test_key", {"version": 1})
    result1 = await store.get("test_key")
    assert result1["args"]["version"] == 1

    # Overwrite with new data
    await store.set("test_key", {"version": 2})
    result2 = await store.get("test_key")
    assert result2["args"]["version"] == 2


@pytest.mark.asyncio
async def test_multiple_keys():
    """Test storing multiple keys independently."""
    store = InMemoryStateStore()

    await store.set("key1", {"data": "value1"})
    await store.set("key2", {"data": "value2"})
    await store.set("key3", {"data": "value3"})

    result1 = await store.get("key1")
    result2 = await store.get("key2")
    result3 = await store.get("key3")

    assert result1["args"]["data"] == "value1"
    assert result2["args"]["data"] == "value2"
    assert result3["args"]["data"] == "value3"


@pytest.mark.asyncio
async def test_clear():
    """Test clearing all stored data."""
    store = InMemoryStateStore()

    # Store multiple keys
    await store.set("key1", {"data": "value1"})
    await store.set("key2", {"data": "value2"})

    # Clear all
    store.clear()

    # Verify all are gone
    assert await store.get("key1") is None
    assert await store.get("key2") is None


@pytest.mark.asyncio
async def test_size():
    """Test size tracking."""
    store = InMemoryStateStore()

    assert store.size() == 0

    await store.set("key1", {"data": "value1"})
    assert store.size() == 1

    await store.set("key2", {"data": "value2"})
    assert store.size() == 2

    await store.delete("key1")
    assert store.size() == 1

    store.clear()
    assert store.size() == 0


@pytest.mark.asyncio
async def test_complex_data():
    """Test storing complex nested data structures."""
    store = InMemoryStateStore()

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

    await store.set("complex_key", complex_data)
    result = await store.get("complex_key")

    assert result["args"] == complex_data
    assert result["args"]["params"]["nested"]["list"] == [1, 2, 3]
