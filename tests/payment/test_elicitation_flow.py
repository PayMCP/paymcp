"""Tests for the elicitation payment flow."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from paymcp.payment.flows.elicitation import make_paid_wrapper
from paymcp.providers.base import BasePaymentProvider


class TestElicitationFlow:
    """Test the elicitation payment flow."""

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
    def mock_func(self):
        """Create a mock function to be wrapped."""
        func = AsyncMock()
        func.__name__ = "test_function"
        func.return_value = {"result": "success"}
        return func

    @pytest.fixture
    def mock_ctx(self):
        """Create a mock context."""
        return Mock()

    @pytest.mark.asyncio
    async def test_make_paid_wrapper_successful_payment(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx
    ):
        """Test successful payment flow."""
        with patch("paymcp.payment.flows.elicitation.run_elicitation_loop") as mock_elicitation:

            mock_elicitation.return_value = "paid"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)
            result = await wrapper(ctx=mock_ctx)

            # Verify payment was created
            mock_provider.create_payment.assert_called_once_with(
                amount=10.0,
                currency="USD",
                description="test_function() execution fee"
            )

            # Verify function was called
            mock_func.assert_called_once_with(ctx=mock_ctx)
            assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_make_paid_wrapper_webview_unavailable(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx
    ):
        """Test payment flow when webview is not available."""
        with patch("paymcp.payment.flows.elicitation.run_elicitation_loop") as mock_elicitation, \
             patch("paymcp.payment.flows.elicitation.open_link_message") as mock_open_link:

            mock_elicitation.return_value = "paid"
            mock_open_link.return_value = "Open payment link"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)
            result = await wrapper(ctx=mock_ctx)

            # Verify open link message was used
            mock_open_link.assert_called_once_with("https://payment.url", 10.0, "USD")
            mock_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_paid_wrapper_payment_canceled(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx
    ):
        """Test payment flow when payment is canceled."""
        with patch("paymcp.payment.flows.elicitation.run_elicitation_loop") as mock_elicitation:

            mock_elicitation.return_value = "canceled"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)
            result = await wrapper(ctx=mock_ctx)

            # Verify function was not called and proper response returned
            mock_func.assert_not_called()
            assert result == {
                "status": "canceled",
                "message": "Payment canceled by user"
            }

    @pytest.mark.asyncio
    async def test_make_paid_wrapper_payment_pending(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx
    ):
        """Test payment flow when payment is pending."""
        with patch("paymcp.payment.flows.elicitation.run_elicitation_loop") as mock_elicitation:

            mock_elicitation.return_value = "pending"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)
            result = await wrapper(ctx=mock_ctx)

            # Verify function was not called and proper response returned
            mock_func.assert_not_called()
            assert result == {
                "status": "pending",
                "message": "We haven't received the payment yet. Click the button below to check again.",
                "next_step": "test_function",
                "payment_id": "payment_123"
            }

    @pytest.mark.asyncio
    async def test_make_paid_wrapper_elicitation_exception(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx
    ):
        """Test payment flow when elicitation raises exception."""
        with patch("paymcp.payment.flows.elicitation.run_elicitation_loop") as mock_elicitation:

            mock_elicitation.side_effect = RuntimeError("Elicitation failed")

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

            with pytest.raises(RuntimeError, match="Elicitation failed"):
                await wrapper(ctx=mock_ctx)

            # Verify function was not called
            mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_make_paid_wrapper_with_webview_message(
        self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx
    ):
        """No webview support: message always link."""
        with patch("paymcp.payment.flows.elicitation.run_elicitation_loop") as mock_elicitation, \
             patch("paymcp.payment.flows.elicitation.open_link_message") as mock_open_link:

            mock_elicitation.return_value = "paid"
            mock_open_link.return_value = "Open payment link"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)
            await wrapper(ctx=mock_ctx)

            # Verify link message was used
            mock_open_link.assert_called_once_with("https://payment.url", 10.0, "USD")

    @pytest.mark.asyncio
    async def test_make_paid_wrapper_no_ctx(
        self, mock_func, mock_mcp, mock_provider, price_info
    ):
        """Test payment flow when no context is provided."""
        with patch("paymcp.payment.flows.elicitation.run_elicitation_loop") as mock_elicitation:

            mock_elicitation.return_value = "paid"

            wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)
            result = await wrapper()

            # Verify elicitation was called with None context
            mock_elicitation.assert_called_once()
            args = mock_elicitation.call_args[0]
            assert args[0] is None  # ctx should be None

    @pytest.mark.asyncio
    async def test_wrapper_preserves_function_metadata(
        self, mock_func, mock_mcp, mock_provider, price_info
    ):
        """Test that wrapper preserves original function metadata."""
        mock_func.__doc__ = "Original docstring"
        mock_func.__name__ = "original_name"

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        assert wrapper.__name__ == "original_name"
        assert wrapper.__doc__ == "Original docstring"
