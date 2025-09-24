"""Extended tests for memory storage to cover missing branches."""

import pytest
import asyncio
from unittest.mock import Mock, patch
from paymcp.session.memory import InMemorySessionStorage
from paymcp.session.types import SessionKey, SessionData


class TestInMemorySessionStorageExtended:
    """Extended test cases for InMemorySessionStorage."""

    @pytest.mark.asyncio
    async def test_cleanup_loop_continuous_execution(self):
        """Test that cleanup loop continues after each iteration."""
        storage = InMemorySessionStorage()

        # Start cleanup task
        loop = asyncio.get_running_loop()
        storage._start_cleanup()

        # Add an item with short TTL
        key = SessionKey(provider="test", payment_id="123", mcp_session_id="abc")
        data = SessionData(args={}, ts=123456, provider_name="test")
        await storage.set(key, data, ttl_seconds=0.01)  # Very short TTL

        # Let cleanup run a bit
        await asyncio.sleep(0.02)

        # Item should be cleaned up
        assert await storage.get(key) is None

        # Cleanup task should still be running
        assert storage.cleanup_task is not None
        assert not storage.cleanup_task.done()

        # Clean up
        storage.destroy()

    @pytest.mark.asyncio
    async def test_destroy_with_running_cleanup_task(self):
        """Test destroy when cleanup task is still running."""
        storage = InMemorySessionStorage()

        # Start cleanup task
        loop = asyncio.get_running_loop()
        storage._start_cleanup()

        # Verify cleanup task is running
        assert storage.cleanup_task is not None
        assert not storage.cleanup_task.done()

        # Destroy should cancel the task
        storage.destroy()

        # Give a moment for cancellation to propagate
        await asyncio.sleep(0.01)

        # Task should be cancelled
        assert storage.cleanup_task.cancelled() or storage.cleanup_task.done()

        # Storage should be cleared
        assert len(storage.storage) == 0

    @pytest.mark.asyncio
    async def test_start_cleanup_with_done_task(self):
        """Test that _start_cleanup restarts a done task."""
        storage = InMemorySessionStorage()

        # Create a mock task that is done
        mock_task = Mock()
        mock_task.done.return_value = True
        storage.cleanup_task = mock_task

        # Start cleanup should create a new task
        loop = asyncio.get_running_loop()
        storage._start_cleanup()

        # Should have a new task
        assert storage.cleanup_task != mock_task
        assert storage.cleanup_task is not None
        assert not storage.cleanup_task.done()

        # Clean up
        storage.destroy()
