"""Comprehensive tests for RESUBMIT payment flow.

Tests cover all code paths including:
- Payment initiation
- Payment confirmation with various statuses
- Race condition prevention (ENG-215)
- Tool execution failure handling (ENG-214)
- Lock acquisition and release
- State management
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from paymcp.payment.flows.resubmit import make_paid_wrapper
from paymcp.state.memory import InMemoryStateStore
from paymcp.providers.base import BasePaymentProvider


class TestResubmitFlow:
    """Test the RESUBMIT payment flow implementation."""

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
        return Mock()

    @pytest.fixture
    def price_info(self):
        """Create price information."""
        return {"price": 10.0, "currency": "USD"}

    @pytest.fixture
    def state_store(self):
        """Create a fresh state store instance."""
        return InMemoryStateStore()

    @pytest.fixture
    def mock_func(self):
        """Create a mock function to be wrapped."""
        func = AsyncMock()
        func.__name__ = "test_tool"
        func.return_value = {"result": "success"}
        return func

    # ===== Payment Initiation Tests =====

    @pytest.mark.asyncio
    async def test_payment_initiation_no_payment_id(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test payment initiation when no payment_id is provided."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        with pytest.raises(RuntimeError) as exc_info:
            await wrapper(test_arg="value")

        err = exc_info.value
        assert err.code == 402
        assert err.error == "payment_required"
        assert err.data["payment_id"] == "payment_123"
        assert err.data["payment_url"] == "https://payment.url"
        assert "payment_123" in str(err)

        # Verify state was stored
        stored = await state_store.get("payment_123")
        assert stored is not None
        assert stored["args"]["test_arg"] == "value"

    @pytest.mark.asyncio
    async def test_payment_initiation_stores_kwargs(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that payment initiation stores all kwargs in state."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        with pytest.raises(RuntimeError):
            await wrapper(arg1="value1", arg2=42, arg3={"nested": "data"})

        stored = await state_store.get("payment_123")
        assert stored["args"]["arg1"] == "value1"
        assert stored["args"]["arg2"] == 42
        assert stored["args"]["arg3"] == {"nested": "data"}
        assert "ts" in stored

    # ===== Payment Confirmation Tests =====

    @pytest.mark.asyncio
    async def test_payment_confirmation_paid_status(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test successful payment confirmation and tool execution."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        # Setup: Store state
        await state_store.set("payment_123", {"test_arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # Execute with payment_id
        result = await wrapper(payment_id="payment_123", test_arg="value")

        # Verify tool was executed
        mock_func.assert_called_once()

        # Result is wrapped with annotations
        assert result["content"] == {"result": "success"}
        assert result["annotations"]["payment"]["status"] == "paid"
        assert result["annotations"]["payment"]["payment_id"] == "payment_123"

        # Verify state was deleted (single-use enforcement)
        stored = await state_store.get("payment_123")
        assert stored is None

    @pytest.mark.asyncio
    async def test_payment_confirmation_top_level_payment_id(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test payment_id passed as top-level keyword argument."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_456", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        result = await wrapper(payment_id="payment_456", arg="value")

        assert result["content"] == {"result": "success"}
        assert result["annotations"]["payment"]["status"] == "paid"
        assert await state_store.get("payment_456") is None

    @pytest.mark.asyncio
    async def test_payment_confirmation_nested_payment_id(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test payment_id passed nested in args dict."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_789", {"data": "test"})
        mock_provider.get_payment_status.return_value = "paid"

        # Simulate SDK-style args parameter
        result = await wrapper(args={"payment_id": "payment_789", "data": "test"})

        assert result["content"] == {"result": "success"}
        assert result["annotations"]["payment"]["status"] == "paid"
        mock_func.assert_called_once()

    # ===== Payment Status Tests =====

    @pytest.mark.asyncio
    async def test_payment_pending_status(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test handling of pending payment status."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "pending"

        with pytest.raises(RuntimeError) as exc_info:
            await wrapper(payment_id="payment_123")

        err = exc_info.value
        assert err.code == 402
        assert err.error == "payment_pending"
        assert "not confirmed yet" in str(err)

        # Verify state was NOT deleted (user can retry)
        stored = await state_store.get("payment_123")
        assert stored is not None

        # Verify tool was NOT executed
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_payment_canceled_status(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test handling of canceled payment status."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "canceled"

        with pytest.raises(RuntimeError) as exc_info:
            await wrapper(payment_id="payment_123")

        err = exc_info.value
        assert err.code == 402
        assert err.error == "payment_canceled"
        assert "canceled" in str(err).lower()

        # State kept for potential retry
        assert await state_store.get("payment_123") is not None
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_payment_failed_status(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test handling of failed payment status."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "failed"

        with pytest.raises(RuntimeError) as exc_info:
            await wrapper(payment_id="payment_123")

        err = exc_info.value
        assert err.code == 402
        assert err.error == "payment_failed"

        assert await state_store.get("payment_123") is not None
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_payment_unknown_status(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test handling of unrecognized payment status."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "processing"

        with pytest.raises(RuntimeError) as exc_info:
            await wrapper(payment_id="payment_123")

        err = exc_info.value
        assert err.code == 402
        assert err.error == "payment_unknown"
        assert "Unrecognized" in str(err)

        # State kept for retry
        assert await state_store.get("payment_123") is not None
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_payment_status_case_insensitive(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that payment status check is case-insensitive."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})

        # Test uppercase status
        mock_provider.get_payment_status.return_value = "PAID"
        result = await wrapper(payment_id="payment_123")
        assert result["content"] == {"result": "success"}

        # Test mixed case
        await state_store.set("payment_456", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "Paid"
        result = await wrapper(payment_id="payment_456")
        assert result["content"] == {"result": "success"}

    # ===== Error Handling Tests =====

    @pytest.mark.asyncio
    async def test_payment_id_not_found(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test error when payment_id doesn't exist in state."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        with pytest.raises(RuntimeError) as exc_info:
            await wrapper(payment_id="nonexistent_payment")

        err = exc_info.value
        assert err.code == 404
        assert err.error == "payment_id_not_found"
        assert "not found or already used" in err.data["retry_instructions"]

        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_payment_id_already_used(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that payment_id cannot be reused after successful execution."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # First execution - succeeds
        result1 = await wrapper(payment_id="payment_123")
        assert result1["content"] == {"result": "success"}

        # Second execution with same payment_id - should fail
        with pytest.raises(RuntimeError) as exc_info:
            await wrapper(payment_id="payment_123")

        err = exc_info.value
        assert err.code == 404
        assert "already used" in err.data["retry_instructions"]

    # ===== ENG-214: Tool Execution Failure Tests =====

    @pytest.mark.asyncio
    async def test_tool_execution_failure_state_preserved(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test ENG-214: If tool fails, state is NOT deleted (user can retry)."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # Make tool execution fail
        mock_func.side_effect = RuntimeError("Tool execution failed")

        with pytest.raises(RuntimeError) as exc_info:
            await wrapper(payment_id="payment_123")

        assert "Tool execution failed" in str(exc_info.value)

        # CRITICAL: State should still exist for retry
        stored = await state_store.get("payment_123")
        assert stored is not None
        assert stored["args"]["arg"] == "value"

    @pytest.mark.asyncio
    async def test_tool_execution_failure_user_can_retry(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test ENG-214: User can retry after tool execution failure."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # First attempt: tool fails
        mock_func.side_effect = RuntimeError("Network timeout")
        with pytest.raises(RuntimeError):
            await wrapper(payment_id="payment_123")

        # Second attempt: tool succeeds
        mock_func.side_effect = None
        mock_func.return_value = {"result": "success on retry"}

        result = await wrapper(payment_id="payment_123")
        assert result["content"] == {"result": "success on retry"}

        # Now state should be deleted
        assert await state_store.get("payment_123") is None

    # ===== ENG-215: Race Condition Tests =====

    @pytest.mark.asyncio
    async def test_race_condition_concurrent_requests(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test ENG-215: Race condition prevention with concurrent requests."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_race", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # Slow down tool execution to create race condition opportunity
        async def slow_tool(*args, **kwargs):
            await asyncio.sleep(0.1)
            return {"result": "success"}

        mock_func.side_effect = slow_tool

        # Launch two concurrent requests with same payment_id
        task1 = asyncio.create_task(wrapper(payment_id="payment_race"))
        task2 = asyncio.create_task(wrapper(payment_id="payment_race"))

        results = await asyncio.gather(task1, task2, return_exceptions=True)

        # One should succeed, one should fail with "not found" or "already used"
        successes = [r for r in results if isinstance(r, dict)]
        failures = [r for r in results if isinstance(r, RuntimeError)]

        assert len(successes) == 1
        assert len(failures) == 1
        assert failures[0].code == 404

        # Tool should only execute once
        assert mock_func.call_count == 1

        # State should be deleted
        assert await state_store.get("payment_race") is None

    @pytest.mark.asyncio
    async def test_race_condition_multiple_sequential_attempts(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that sequential attempts after first success are rejected."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_seq", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # First request succeeds
        result1 = await wrapper(payment_id="payment_seq")
        assert result1["content"] == {"result": "success"}

        # Subsequent requests fail
        for i in range(3):
            with pytest.raises(RuntimeError) as exc_info:
                await wrapper(payment_id="payment_seq")
            assert exc_info.value.code == 404

    # ===== Lock Management Tests =====

    @pytest.mark.asyncio
    async def test_lock_acquired_and_released(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that locks are properly acquired and released."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_lock", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # Execute
        await wrapper(payment_id="payment_lock")

        # Lock should be released after execution
        # We can verify by checking that _payment_locks is empty
        assert "payment_lock" not in state_store._payment_locks

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that locks are released even when exceptions occur."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_exc", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"
        mock_func.side_effect = RuntimeError("Test exception")

        with pytest.raises(RuntimeError):
            await wrapper(payment_id="payment_exc")

        # Lock should still be released
        assert "payment_exc" not in state_store._payment_locks

    @pytest.mark.asyncio
    async def test_lock_isolation_different_payment_ids(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that different payment_ids can be processed concurrently."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        # Setup two different payments
        await state_store.set("payment_a", {"arg": "a"})
        await state_store.set("payment_b", {"arg": "b"})
        mock_provider.get_payment_status.return_value = "paid"

        async def slow_tool(*args, **kwargs):
            await asyncio.sleep(0.05)
            return {"result": "success"}

        mock_func.side_effect = slow_tool

        # Both should execute concurrently without blocking each other
        task_a = asyncio.create_task(wrapper(payment_id="payment_a"))
        task_b = asyncio.create_task(wrapper(payment_id="payment_b"))

        results = await asyncio.gather(task_a, task_b)

        assert len(results) == 2
        assert all(r["content"] == {"result": "success"} for r in results)
        assert mock_func.call_count == 2

    # ===== Result Annotation Tests =====

    @pytest.mark.asyncio
    async def test_result_annotations_added(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that payment annotations are added to result."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # Return result with annotations attribute
        mock_result = Mock()
        mock_result.annotations = {}
        mock_func.return_value = mock_result

        result = await wrapper(payment_id="payment_123")

        assert result.annotations["payment"]["status"] == "paid"
        assert result.annotations["payment"]["payment_id"] == "payment_123"

    @pytest.mark.asyncio
    async def test_result_annotations_no_setattr(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test annotation handling when result doesn't support setattr."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        await state_store.set("payment_123", {"arg": "value"})
        mock_provider.get_payment_status.return_value = "paid"

        # Return immutable result (string)
        mock_func.return_value = "simple string result"

        result = await wrapper(payment_id="payment_123")

        # Should wrap in dict format
        assert result["content"] == "simple string result"
        assert result["annotations"]["payment"]["status"] == "paid"
        assert result["annotations"]["payment"]["payment_id"] == "payment_123"
        assert result["raw"] == "simple string result"

    # ===== Parameter Extraction Tests =====

    @pytest.mark.asyncio
    async def test_payment_id_extraction_priority(
        self, mock_func, mock_mcp, mock_provider, price_info, state_store
    ):
        """Test that top-level payment_id takes priority over nested."""
        wrapper = make_paid_wrapper(
            mock_func, mock_mcp, mock_provider, price_info, state_store
        )

        # Setup two different payment states
        await state_store.set("top_level_id", {"data": "correct"})
        await state_store.set("nested_id", {"data": "wrong"})

        mock_provider.get_payment_status.return_value = "paid"

        # Pass both - top-level should win
        result = await wrapper(
            payment_id="top_level_id",
            args={"payment_id": "nested_id", "data": "test"}
        )

        # Should have used top_level_id
        assert result["content"] == {"result": "success"}
        assert result["annotations"]["payment"]["payment_id"] == "top_level_id"
        # top_level_id state should be deleted
        assert await state_store.get("top_level_id") is None
        # nested_id state should still exist
        assert await state_store.get("nested_id") is not None
