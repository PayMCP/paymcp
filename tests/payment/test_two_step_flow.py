"""Tests for the two-step payment flow."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
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

        store.set = mock_set
        store.get = mock_get
        store.delete = mock_delete
        return store

    @pytest.mark.asyncio
    async def test_initiate_step_with_webview(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test the initiation step when webview is available."""
        with patch("paymcp.payment.flows.two_step.open_payment_webview_if_available") as mock_webview, \
             patch("paymcp.payment.flows.two_step.opened_webview_message") as mock_webview_msg:

            mock_webview.return_value = True
            mock_webview_msg.return_value = "Webview opened for payment"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)
            result = await wrapper(arg1="value1", arg2="value2")

            # Verify payment was created
            mock_provider.create_payment.assert_called_once_with(
                amount=15.0,
                currency="EUR",
                description="test_tool() execution fee"
            )

            # Verify webview message was used
            mock_webview_msg.assert_called_once_with("https://payment.url", 15.0, "EUR")

            # Verify response structure
            assert result["payment_url"] == "https://payment.url"
            assert result["payment_id"] == "payment_123"
            assert result["next_step"] == "confirm_test_tool_payment"
            assert result["message"] == "Webview opened for payment"

            # Verify args were stored
            assert mock_state_store._storage["payment_123"]["args"] == {"arg1": "value1", "arg2": "value2"}

    @pytest.mark.asyncio
    async def test_initiate_step_without_webview(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test the initiation step when webview is not available."""
        with patch("paymcp.payment.flows.two_step.open_payment_webview_if_available") as mock_webview, \
             patch("paymcp.payment.flows.two_step.open_link_message") as mock_link_msg:

            mock_webview.return_value = False
            mock_link_msg.return_value = "Open payment link"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)
            result = await wrapper(test_param="test_value")

            # Verify link message was used
            mock_link_msg.assert_called_once_with("https://payment.url", 15.0, "EUR")

            # Verify response structure
            assert result["message"] == "Open payment link"
            assert mock_state_store._storage["payment_123"]["args"] == {"test_param": "test_value"}

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

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        # Test with unknown payment ID
        with pytest.raises(RuntimeError, match="Unknown or expired payment_id"):
            await confirm_func("unknown_payment_id")

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

        # Test the confirm step
        with pytest.raises(RuntimeError, match="Payment status is pending, expected 'paid'"):
            await confirm_func("payment_123")

        # Verify original function was not called
        mock_func.assert_not_called()

        # Verify args were not cleaned up (payment still pending)
        assert "payment_123" in mock_state_store._storage

    @pytest.mark.asyncio
    async def test_confirm_tool_registration(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_state_store
    ):
        """Test that the confirm tool is properly registered."""
        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, mock_state_store)

        # Verify the confirm tool was registered
        mock_mcp.tool.assert_called_once_with(
            name="confirm_test_tool_payment",
            description="Confirm payment and execute test_tool()"
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