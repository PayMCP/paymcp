"""Tests for the two-step payment flow."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from contextlib import asynccontextmanager
from paymcp.payment.flows.two_step import make_paid_wrapper
from paymcp.providers.base import BasePaymentProvider


class TestTwoStepFlow:
    """Test the two-step payment flow."""

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
        # Mock tool to return a decorator that captures the function
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
        func.return_value = {"result": "executed"}
        return func

    @pytest.fixture
    def mock_state_store(self):
        """Create a mock state store."""
        store = AsyncMock()
        store._storage = {}

        async def mock_set(key, args):
            store._storage[key] = {"args": args, "ts": 123456}

        async def mock_get(key):
            return store._storage.get(key)

        async def mock_delete(key):
            store._storage.pop(key, None)

        @asynccontextmanager
        async def mock_lock(_key):
            yield

        store.set = mock_set
        store.get = mock_get
        store.delete = mock_delete
        store.lock = mock_lock
        return store

    @pytest.mark.asyncio
    async def test_initiate_step_uses_link_message(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Initiation step always uses link message (no webview)."""
        with patch("paymcp.payment.flows.two_step.open_link_message") as mock_link_msg:
            mock_link_msg.return_value = "Open payment link"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)
            result = await wrapper(test_param="test_value")

            mock_provider.create_payment.assert_called_once_with(
                amount=15.0,
                currency="EUR",
                description="test_tool() execution fee"
            )
            mock_link_msg.assert_called_once_with("https://payment.url", 15.0, "EUR")
            assert result["message"] == "Open payment link"
            assert result["payment_url"] == "https://payment.url"
            assert result["payment_id"] == "payment_123"
            assert result["next_step"] == "confirm_test_tool_payment"
            assert mock_state_store._storage["payment_123"]["args"] == {"test_param": "test_value"}

    @pytest.mark.asyncio
    async def test_initiate_step_drops_ctx_from_state(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Ensure ctx is not persisted to state."""
        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        fake_ctx = object()
        await wrapper(ctx=fake_ctx, test_param="test_value")

        stored_args = mock_state_store._storage["payment_123"]["args"]
        assert "ctx" not in stored_args
        assert stored_args["test_param"] == "test_value"

    @pytest.mark.asyncio
    async def test_confirm_step_successful_payment(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test the confirmation step with successful payment."""
        # Capture the confirm function when tool decorator is called
        confirm_func = None
        def capture_tool(*args, **kwargs):
            def decorator(func):
                nonlocal confirm_func
                confirm_func = func
                return func
            return decorator

        mock_mcp.tool = capture_tool

        # Setup: First run initiate step
        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)
        await wrapper(original_arg="original_value")

        # Verify confirm tool was registered
        assert confirm_func is not None

        # Test the confirm step
        result = await confirm_func("payment_123")

        # Verify payment status was checked
        mock_provider.get_payment_status.assert_called_once_with("payment_123")

        # Verify original function was called with stored args
        mock_func.assert_called_once_with(original_arg="original_value")

        # Verify result
        assert result == {"result": "executed"}

        # Verify args were cleaned up
        assert "payment_123" not in mock_state_store._storage

    @pytest.mark.asyncio
    async def test_confirm_step_unknown_payment_id(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test the confirmation step with unknown payment ID."""
        # Capture the confirm function when tool decorator is called
        confirm_func = None
        def capture_tool(*args, **kwargs):
            def decorator(func):
                nonlocal confirm_func
                confirm_func = func
                return func
            return decorator

        mock_mcp.tool = capture_tool

        make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        # Test with unknown payment ID - should return error object
        result = await confirm_func("unknown_payment_id")

        # Verify error response structure
        assert result["status"] == "error"
        assert result["message"] == "Unknown or expired payment_id"
        assert result["payment_id"] == "unknown_payment_id"
        assert "Unknown or expired payment_id" in result["content"][0]["text"]

        # Verify original function was not called
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_step_unpaid_status(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test the confirmation step when payment is not yet paid."""
        # Capture the confirm function when tool decorator is called
        confirm_func = None
        def capture_tool(*args, **kwargs):
            def decorator(func):
                nonlocal confirm_func
                confirm_func = func
                return func
            return decorator

        mock_mcp.tool = capture_tool

        # Setup: First run initiate step
        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)
        await wrapper(test_arg="test_value")

        # Set provider to return unpaid status
        mock_provider.get_payment_status.return_value = "pending"

        # Test the confirm step - should return error object
        result = await confirm_func("payment_123")

        # Verify error response structure
        assert result["status"] == "error"
        assert result["message"] == "Payment status is pending, expected 'paid'"
        assert result["payment_id"] == "payment_123"
        assert "Payment status is pending" in result["content"][0]["text"]

        # Verify original function was not called
        mock_func.assert_not_called()

        # Verify args were not cleaned up (payment still pending)
        assert "payment_123" in mock_state_store._storage

    @pytest.mark.asyncio
    async def test_confirm_tool_registration(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test that the confirm tool is properly registered."""
        make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        # Verify the confirm tool was registered
        mock_mcp.tool.assert_called_once_with(
            name="confirm_test_tool_payment",
            description="Confirm payment and execute test_tool(). Call this only after the user confirms the payment"
        )

    def test_wrapper_preserves_function_metadata(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test that wrapper preserves original function metadata."""
        mock_func.__doc__ = "Original function docstring"
        mock_func.__name__ = "original_function"

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        assert wrapper.__name__ == "original_function"
        assert wrapper.__doc__ == "Original function docstring"

    @pytest.mark.asyncio
    async def test_multiple_pending_payments(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test handling multiple pending payments."""
        # Create provider that returns different payment IDs
        mock_provider.create_payment.side_effect = [
            ("payment_1", "https://payment1.url"),
            ("payment_2", "https://payment2.url")
        ]

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        # Initiate two payments
        await wrapper(first_call="value1")
        await wrapper(second_call="value2")

        # Verify both payments are stored
        assert "payment_1" in mock_state_store._storage
        assert "payment_2" in mock_state_store._storage
        assert mock_state_store._storage["payment_1"]["args"] == {"first_call": "value1"}
        assert mock_state_store._storage["payment_2"]["args"] == {"second_call": "value2"}

    @pytest.mark.asyncio
    async def test_pending_args_debug_logging(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test that payment confirmation is logged for debugging."""
        # Capture the confirm function when tool decorator is called
        confirm_func = None
        def capture_tool(*args, **kwargs):
            def decorator(func):
                nonlocal confirm_func
                confirm_func = func
                return func
            return decorator

        mock_mcp.tool = capture_tool

        # Setup: First run initiate step
        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)
        await wrapper(debug_arg="debug_value")

        # Test the confirm step (should log info about payment_id)
        with patch("paymcp.payment.flows.two_step.logger") as mock_logger:
            await confirm_func("payment_123")

            # Verify logging occurred with payment_id
            assert mock_logger.info.called
            info_calls = mock_logger.info.call_args_list
            assert any("payment_id=payment_123" in str(call) for call in info_calls)

    @pytest.mark.asyncio
    async def test_confirm_step_empty_payment_id(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test the confirmation step with empty payment ID."""
        # Capture the confirm function when tool decorator is called
        confirm_func = None
        def capture_tool(*args, **kwargs):
            def decorator(func):
                nonlocal confirm_func
                confirm_func = func
                return func
            return decorator

        mock_mcp.tool = capture_tool

        make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        # Test with empty string payment ID - should return error object (covers line 30)
        result = await confirm_func("")

        # Verify error response structure
        assert result["status"] == "error"
        assert result["message"] == "Missing payment_id"
        assert "Missing payment_id" in result["content"][0]["text"]

        # Verify original function was not called
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_step_none_payment_id(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test the confirmation step with None payment ID."""
        # Capture the confirm function when tool decorator is called
        confirm_func = None
        def capture_tool(*args, **kwargs):
            def decorator(func):
                nonlocal confirm_func
                confirm_func = func
                return func
            return decorator

        mock_mcp.tool = capture_tool

        make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        # Test with None payment ID - should return error object (covers line 30)
        result = await confirm_func(None)

        # Verify error response structure
        assert result["status"] == "error"
        assert result["message"] == "Missing payment_id"
        assert "Missing payment_id" in result["content"][0]["text"]

        # Verify original function was not called
        mock_func.assert_not_called()
