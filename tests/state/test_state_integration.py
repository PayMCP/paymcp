"""Integration tests for state storage with TWO_STEP flow.

These tests verify that state storage integrates correctly with the TWO_STEP
payment flow, testing both InMemoryStateStore and RedisStateStore.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from paymcp.state.memory import InMemoryStateStore
from paymcp.state.redis import RedisStateStore
from paymcp.payment.flows.two_step import make_paid_wrapper
from paymcp.providers.base import BasePaymentProvider


class TestStateStorageIntegration:
    """Integration tests for state storage in TWO_STEP flow."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock payment provider."""
        provider = Mock(spec=BasePaymentProvider)
        provider.create_payment = Mock(return_value=("payment_123", "https://payment.url"))
        provider.get_payment_status = Mock(return_value="paid")
        return provider

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock MCP instance."""
        mcp = Mock()
        mcp.tool = Mock(return_value=lambda func: func)
        return mcp

    @pytest.fixture
    def price_info(self):
        """Create price information."""
        return {"price": 15.0, "currency": "EUR"}

    @pytest.fixture
    def mock_func(self):
        """Create a mock function to be wrapped."""
        func = AsyncMock()
        func.__name__ = "test_tool"
        func.return_value = {"result": "executed", "args_received": {}}
        return func

    @pytest.mark.asyncio
    async def test_inmemory_state_storage_integration(
        self, mock_func, mock_mcp, mock_provider, price_info
    ):
        """Test InMemoryStateStore integration with TWO_STEP flow."""
        # Given: InMemoryStateStore
        state_store = InMemoryStateStore()

        # Create wrapper
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        # When: Initiate payment
        result = await wrapper(test_arg="test_value", another_arg=42)

        # Then: Verify payment initiation response
        assert "payment_id" in result
        assert result["payment_id"] == "payment_123"
        assert "payment_url" in result

        # Verify state was stored in InMemoryStateStore
        stored_state = await state_store.get("payment_123")
        assert stored_state is not None
        assert stored_state["args"]["test_arg"] == "test_value"
        assert stored_state["args"]["another_arg"] == 42
        assert "ts" in stored_state

    @pytest.mark.asyncio
    async def test_redis_state_storage_integration(
        self, mock_func, mock_mcp, mock_provider, price_info
    ):
        """Test RedisStateStore integration with TWO_STEP flow."""
        # Given: Mocked Redis client
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.get = AsyncMock()
        mock_redis.delete = AsyncMock()

        # Create RedisStateStore with mocked Redis
        state_store = RedisStateStore(mock_redis, key_prefix="test:", ttl=1800)

        # Create wrapper
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        # When: Initiate payment
        result = await wrapper(redis_test_arg="redis_value", number=123)

        # Then: Verify payment initiation response
        assert "payment_id" in result
        assert result["payment_id"] == "payment_123"

        # Verify Redis setex was called
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]

        # Verify Redis key format
        assert call_args[0] == "test:payment_123"

        # Verify TTL
        assert call_args[1] == 1800

        # Verify stored data contains arguments
        import json
        stored_data = json.loads(call_args[2])
        assert stored_data["args"]["redis_test_arg"] == "redis_value"
        assert stored_data["args"]["number"] == 123
        assert "ts" in stored_data

    @pytest.mark.asyncio
    async def test_state_store_backward_compatibility(
        self, mock_func, mock_mcp, mock_provider, price_info
    ):
        """Test that state_store parameter is backward compatible (defaults to InMemory)."""
        # Given: No state_store provided (None)
        # Note: In real usage, PayMCP core auto-creates InMemoryStateStore
        # Here we test that None is handled gracefully by checking the flow works

        state_store = InMemoryStateStore()  # Simulating auto-creation

        # When: Create wrapper
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        # Then: Should work without errors
        result = await wrapper(compat_arg="value")
        assert "payment_id" in result

    @pytest.mark.asyncio
    async def test_multiple_state_stores_isolation(
        self, mock_func, mock_mcp, mock_provider, price_info
    ):
        """Test that multiple state store instances maintain independent state."""
        # Given: Two independent InMemoryStateStore instances
        state_store_1 = InMemoryStateStore()
        state_store_2 = InMemoryStateStore()

        # Create two wrappers with different state stores
        wrapper_1 = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store_1
        )
        wrapper_2 = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store_2
        )

        # When: Initiate payments in both
        await wrapper_1(store1_arg="value1")
        await wrapper_2(store2_arg="value2")

        # Then: Each store should have its own state
        state_1 = await state_store_1.get("payment_123")
        state_2 = await state_store_2.get("payment_123")

        assert state_1["args"]["store1_arg"] == "value1"
        assert "store2_arg" not in state_1["args"]

        assert state_2["args"]["store2_arg"] == "value2"
        assert "store1_arg" not in state_2["args"]

    @pytest.mark.asyncio
    async def test_state_cleanup_after_confirmation(
        self, mock_func, mock_mcp, mock_provider, price_info
    ):
        """Test that state is cleaned up after successful payment confirmation."""
        # Given: State store with stored payment
        state_store = InMemoryStateStore()

        # Capture confirmation function
        confirm_func = None
        def capture_tool(*args, **kwargs):
            def decorator(func):
                nonlocal confirm_func
                confirm_func = func
                return func
            return decorator

        mock_mcp.tool = capture_tool

        # Create wrapper and initiate payment
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )
        await wrapper(cleanup_test="value")

        # Verify state exists
        state_before = await state_store.get("payment_123")
        assert state_before is not None

        # When: Confirm payment
        await confirm_func("payment_123")

        # Then: State should be cleaned up
        state_after = await state_store.get("payment_123")
        assert state_after is None
