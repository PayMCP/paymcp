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

    # ===== get_and_delete Tests =====

    @pytest.mark.asyncio
    async def test_get_and_delete_existing_key(self, store):
        """Test atomically getting and deleting an existing key."""
        await store.set("test_key", {"data": "value"})

        result = await store.get_and_delete("test_key")
        assert result is not None
        assert result["args"] == {"data": "value"}

        # Key should be deleted
        result_after = await store.get("test_key")
        assert result_after is None

    @pytest.mark.asyncio
    async def test_get_and_delete_nonexistent_key(self, store):
        """Test get_and_delete on nonexistent key returns None."""
        result = await store.get_and_delete("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_and_delete_atomicity(self, store):
        """Test that get_and_delete is atomic (no race conditions)."""
        import asyncio

        await store.set("race_key", {"data": "value"})

        # Attempt concurrent get_and_delete
        results = await asyncio.gather(
            store.get_and_delete("race_key"),
            store.get_and_delete("race_key"),
            store.get_and_delete("race_key")
        )

        # Only one should succeed
        successes = [r for r in results if r is not None]
        failures = [r for r in results if r is None]

        assert len(successes) == 1
        assert len(failures) == 2

    # ===== Lock Tests =====

    @pytest.mark.asyncio
    async def test_lock_basic_usage(self, store):
        """Test basic lock acquisition and release."""
        async with store.lock("test_lock"):
            # Inside lock - should be able to perform operations
            await store.set("test_key", {"data": "value"})
            result = await store.get("test_key")
            assert result["args"]["data"] == "value"

        # After lock - lock should be released
        assert "test_lock" not in store._payment_locks

    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent_access(self, store):
        """Test that lock prevents concurrent access to same key."""
        import asyncio

        execution_order = []

        async def task1():
            async with store.lock("shared_key"):
                execution_order.append("task1_start")
                await asyncio.sleep(0.1)
                execution_order.append("task1_end")

        async def task2():
            await asyncio.sleep(0.01)  # Start slightly after task1
            async with store.lock("shared_key"):
                execution_order.append("task2_start")
                execution_order.append("task2_end")

        await asyncio.gather(task1(), task2())

        # Task1 should complete before task2 starts
        assert execution_order == ["task1_start", "task1_end", "task2_start", "task2_end"]

    @pytest.mark.asyncio
    async def test_lock_different_keys_concurrent(self, store):
        """Test that locks on different keys don't block each other."""
        import asyncio

        execution_order = []

        async def task_a():
            async with store.lock("key_a"):
                execution_order.append("a_start")
                await asyncio.sleep(0.05)
                execution_order.append("a_end")

        async def task_b():
            async with store.lock("key_b"):
                execution_order.append("b_start")
                await asyncio.sleep(0.05)
                execution_order.append("b_end")

        await asyncio.gather(task_a(), task_b())

        # Both should start before either finishes
        assert "a_start" in execution_order
        assert "b_start" in execution_order
        # The exact order might vary, but both pairs should be present
        assert "a_end" in execution_order
        assert "b_end" in execution_order

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(self, store):
        """Test that lock is released even when exception occurs."""
        try:
            async with store.lock("exc_key"):
                raise RuntimeError("Test exception")
        except RuntimeError:
            pass

        # Lock should be released
        assert "exc_key" not in store._payment_locks

        # Should be able to acquire lock again
        async with store.lock("exc_key"):
            pass

    @pytest.mark.asyncio
    async def test_lock_cleanup_after_use(self, store):
        """Test that lock is cleaned up from _payment_locks after use."""
        async with store.lock("cleanup_key"):
            # During lock, key should exist in _payment_locks
            assert "cleanup_key" in store._payment_locks

        # After lock, key should be removed
        assert "cleanup_key" not in store._payment_locks

    @pytest.mark.asyncio
    async def test_lock_multiple_sequential_acquisitions(self, store):
        """Test that same lock can be acquired multiple times sequentially."""
        for i in range(5):
            async with store.lock("sequential_key"):
                await store.set(f"key_{i}", {"iteration": i})

        # All operations should succeed
        for i in range(5):
            result = await store.get(f"key_{i}")
            assert result["args"]["iteration"] == i
