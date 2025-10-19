"""Tests for the PROGRESS payment flow."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from paymcp.payment.flows.progress import make_paid_wrapper, DEFAULT_POLL_SECONDS, MAX_WAIT_SECONDS
from paymcp.providers.base import BasePaymentProvider


class TestProgressFlow:
    """Test the PROGRESS payment flow."""

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
        return mcp

    @pytest.fixture
    def price_info(self):
        """Create price information."""
        return {"price": 20.0, "currency": "USD"}

    @pytest.fixture
    def mock_func(self):
        """Create a mock function to be wrapped."""
        func = AsyncMock()
        func.__name__ = "test_progress_tool"
        func.return_value = {"result": "success"}
        return func

    @pytest.fixture
    def mock_ctx(self):
        """Create a mock context with report_progress method."""
        ctx = AsyncMock()
        ctx.report_progress = AsyncMock()
        return ctx

    @pytest.mark.asyncio
    async def test_progress_wrapper_instant_payment(self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper with instant payment (status=paid)."""
        # Provider returns 'paid' immediately
        mock_provider.get_payment_status.return_value = "paid"

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        # Call wrapper with ctx
        result = await wrapper(test_arg="value", ctx=mock_ctx)

        # Verify provider was called
        mock_provider.create_payment.assert_called_once_with(
            amount=price_info["price"],
            currency=price_info["currency"],
            description="test_progress_tool() execution fee"
        )

        # Verify progress was reported
        assert mock_ctx.report_progress.called
        assert mock_ctx.report_progress.call_count >= 2  # Initial + completion

        # Verify original function was called
        mock_func.assert_called_once_with(test_arg="value", ctx=mock_ctx)
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_progress_wrapper_pending_then_paid(self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper with pending→paid transition."""
        # First call returns 'pending', second returns 'paid'
        mock_provider.get_payment_status.side_effect = ["pending", "paid"]

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        result = await wrapper(ctx=mock_ctx)

        # Verify polling happened
        assert mock_provider.get_payment_status.call_count == 2

        # Verify progress was reported multiple times
        assert mock_ctx.report_progress.call_count >= 3  # Initial + pending update + completion

        # Verify original function was called
        mock_func.assert_called_once()
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_progress_wrapper_payment_failed(self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper when payment fails."""
        mock_provider.get_payment_status.return_value = "failed"

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        with pytest.raises(RuntimeError, match="Payment status is failed, expected 'paid'"):
            await wrapper(ctx=mock_ctx)

        # Verify original function was NOT called
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_wrapper_payment_canceled(self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper when payment is canceled."""
        mock_provider.get_payment_status.return_value = "canceled"

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        with pytest.raises(RuntimeError, match="Payment status is canceled, expected 'paid'"):
            await wrapper(ctx=mock_ctx)

        # Verify original function was NOT called
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_wrapper_payment_expired(self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper when payment expires."""
        mock_provider.get_payment_status.return_value = "expired"

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        with pytest.raises(RuntimeError, match="Payment status is expired, expected 'paid'"):
            await wrapper(ctx=mock_ctx)

        # Verify original function was NOT called
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_wrapper_timeout(self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper when payment times out."""
        # Always return 'pending' to trigger timeout
        mock_provider.get_payment_status.return_value = "pending"

        # Mock asyncio.sleep to avoid waiting for real timeout
        with patch('paymcp.payment.flows.progress.asyncio.sleep', new_callable=AsyncMock):
            with patch('paymcp.payment.flows.progress.MAX_WAIT_SECONDS', 6):  # Set short timeout
                with patch('paymcp.payment.flows.progress.DEFAULT_POLL_SECONDS', 3):
                    wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

                    with pytest.raises(RuntimeError, match="Payment timeout reached; aborting"):
                        await wrapper(ctx=mock_ctx)

        # Verify original function was NOT called
        mock_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_wrapper_no_ctx(self, mock_func, mock_mcp, mock_provider, price_info):
        """Test progress wrapper without context (no progress reporting)."""
        mock_provider.get_payment_status.return_value = "paid"

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        # Call without ctx parameter
        result = await wrapper(test_arg="value")

        # Verify original function was called
        mock_func.assert_called_once_with(test_arg="value")
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_progress_wrapper_ctx_without_report_progress(self, mock_func, mock_mcp, mock_provider, price_info):
        """Test progress wrapper with ctx that doesn't have report_progress method."""
        mock_provider.get_payment_status.return_value = "paid"

        # Create ctx without report_progress
        ctx_without_progress = Mock()
        # Explicitly remove report_progress if it exists
        if hasattr(ctx_without_progress, 'report_progress'):
            delattr(ctx_without_progress, 'report_progress')

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        # This should not raise an error
        result = await wrapper(ctx=ctx_without_progress)

        # Verify original function was called
        mock_func.assert_called_once()
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    @patch('paymcp.payment.flows.progress.open_payment_webview_if_available')
    async def test_progress_wrapper_webview_opened(self, mock_webview, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper when webview is successfully opened."""
        mock_provider.get_payment_status.return_value = "paid"
        mock_webview.return_value = True  # Webview opened successfully

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        result = await wrapper(ctx=mock_ctx)

        # Verify webview was attempted
        mock_webview.assert_called_once_with("https://payment.url")

        # Verify progress message mentions payment window
        first_call_args = mock_ctx.report_progress.call_args_list[0]
        assert "payment window" in first_call_args[1]["message"].lower()

        # Verify original function was called
        mock_func.assert_called_once()
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    @patch('paymcp.payment.flows.progress.open_payment_webview_if_available')
    async def test_progress_wrapper_webview_failed(self, mock_webview, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper when webview fails to open."""
        mock_provider.get_payment_status.return_value = "paid"
        mock_webview.return_value = False  # Webview failed to open

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        result = await wrapper(ctx=mock_ctx)

        # Verify webview was attempted
        mock_webview.assert_called_once_with("https://payment.url")

        # Verify progress message uses link instead
        first_call_args = mock_ctx.report_progress.call_args_list[0]
        assert "link" in first_call_args[1]["message"].lower()

        # Verify original function was called
        mock_func.assert_called_once()
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_progress_wrapper_state_store_not_used(self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test that state_store parameter is accepted but not used."""
        mock_provider.get_payment_status.return_value = "paid"

        # Create a mock state store
        mock_state_store = Mock()

        # Pass state_store parameter (should be accepted but not used)
        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info, state_store=mock_state_store)

        result = await wrapper(ctx=mock_ctx)

        # Verify state_store was NOT used
        assert not mock_state_store.called

        # Verify original function was called
        mock_func.assert_called_once()
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_progress_wrapper_multiple_pending_polls(self, mock_func, mock_mcp, mock_provider, price_info, mock_ctx):
        """Test progress wrapper with multiple pending status polls."""
        # Multiple pending statuses before paid
        mock_provider.get_payment_status.side_effect = ["pending", "pending", "pending", "paid"]

        wrapper = make_paid_wrapper(mock_func, mock_mcp, mock_provider, price_info)

        result = await wrapper(ctx=mock_ctx)

        # Verify polling happened multiple times
        assert mock_provider.get_payment_status.call_count == 4

        # Verify progress was reported for each pending state
        progress_calls = [call for call in mock_ctx.report_progress.call_args_list
                         if "Waiting for payment" in call[1]["message"]]
        assert len(progress_calls) == 3  # 3 pending status updates

        # Verify original function was called
        mock_func.assert_called_once()
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_progress_wrapper_preserves_function_metadata(self, mock_mcp, mock_provider, price_info):
        """Test that wrapper preserves original function metadata."""
        async def original_tool(arg1: str, arg2: int, ctx=None):
            """Original function docstring."""
            return f"{arg1}-{arg2}"

        wrapper = make_paid_wrapper(original_tool, mock_mcp, mock_provider, price_info)

        # Verify metadata preserved by functools.wraps
        assert wrapper.__name__ == "original_tool"
        assert wrapper.__doc__ == "Original function docstring."

    def test_constants(self):
        """Test that constants are defined correctly."""
        assert DEFAULT_POLL_SECONDS == 3
        assert MAX_WAIT_SECONDS == 15 * 60  # 15 minutes
