"""Tests for InMemoryStateStore."""

import pytest
from paymcp.state.memory import InMemoryStateStore


class TestInMemoryStateStore:
    """Test the in-memory state storage implementation."""

    @pytest.fixture
    def store(self):
        """Create a fresh InMemoryStateStore instance."""
        return InMemoryStateStore()

    @pytest.mark.asyncio
    async def test_set_and_get(self, store):
        """Test basic set and get operations."""
        await store.set("test_key", {"arg1": "value1", "arg2": "value2"})

        result = await store.get("test_key")
        assert result is not None
        assert result["args"] == {"arg1": "value1", "arg2": "value2"}
        assert "ts" in result
        assert isinstance(result["ts"], int)

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, store):
        """Test getting a key that doesn't exist."""
        result = await store.get("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, store):
        """Test deleting an existing key."""
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
    async def test_delete_nonexistent_key(self, store):
        """Test deleting a key that doesn't exist (should not raise error)."""
        # Should not raise an exception
        await store.delete("nonexistent_key")

    @pytest.mark.asyncio
    async def test_overwrite_existing_key(self, store):
        """Test overwriting an existing key."""
        await store.set("test_key", {"data": "original"})
        await store.set("test_key", {"data": "updated"})

        result = await store.get("test_key")
        assert result["args"] == {"data": "updated"}

    @pytest.mark.asyncio
    async def test_multiple_keys(self, store):
        """Test storing multiple independent keys."""
        await store.set("key1", {"data": "value1"})
        await store.set("key2", {"data": "value2"})
        await store.set("key3", {"data": "value3"})

        result1 = await store.get("key1")
        result2 = await store.get("key2")
        result3 = await store.get("key3")

        assert result1["args"] == {"data": "value1"}
        assert result2["args"] == {"data": "value2"}
        assert result3["args"] == {"data": "value3"}

    @pytest.mark.asyncio
    async def test_timestamp_stored(self, store):
        """Test that timestamp is stored correctly."""
        import time
        before = int(time.time() * 1000)

        await store.set("test_key", {"data": "value"})

        after = int(time.time() * 1000)

        result = await store.get("test_key")
        timestamp = result["ts"]

        # Timestamp should be between before and after
        assert before <= timestamp <= after

    @pytest.mark.asyncio
    async def test_empty_args(self, store):
        """Test storing empty arguments."""
        await store.set("test_key", {})

        result = await store.get("test_key")
        assert result["args"] == {}

    @pytest.mark.asyncio
    async def test_complex_nested_args(self, store):
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

        result = await store.get("test_key")
        assert result["args"] == complex_data
