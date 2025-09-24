"""Extended tests for two-step payment flow to cover missing branches."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from paymcp.payment.flows.two_step import make_paid_wrapper
from paymcp.session.types import SessionData


class TestTwoStepExtended:
    """Extended test cases for two-step payment flow."""

    @pytest.mark.asyncio
    async def test_extract_session_id_exception_in_initiate(self):
        """Test that initiation continues even if extract_session_id raises exception."""
        mock_provider = Mock()
        mock_provider.get_name.return_value = "test_provider"
        mock_provider.create_payment.return_value = ("payment_123", "https://pay.test/123")

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        mock_mcp = Mock()
        mock_mcp.tool = Mock(return_value=lambda f: f)

        price_info = {"price": 10, "currency": "USD"}
        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage:
            storage = AsyncMock()
            mock_storage.return_value = storage

            # Mock extract_session_id to raise exception
            with patch("paymcp.payment.flows.two_step.extract_session_id") as mock_extract:
                mock_extract.side_effect = Exception("Session extraction failed")

                with patch("paymcp.payment.flows.two_step.logger") as mock_logger:
                    # Call wrapper with ctx
                    result = await wrapper(ctx=mock_mcp)

                    # Should still return payment info
                    assert "payment_id" in result
                    assert "payment_url" in result

                    # Check that debug log was called for exception
                    mock_logger.debug.assert_any_call("Could not extract session ID: Session extraction failed")

    @pytest.mark.asyncio
    async def test_extract_session_id_with_value_in_initiate(self):
        """Test that extracted session ID is logged when present in initiate."""
        mock_provider = Mock()
        mock_provider.get_name.return_value = "test_provider"
        mock_provider.create_payment.return_value = ("payment_123", "https://pay.test/123")

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        mock_mcp = Mock()
        mock_mcp.tool = Mock(return_value=lambda f: f)

        price_info = {"price": 10, "currency": "USD"}
        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage:
            storage = AsyncMock()
            mock_storage.return_value = storage

            # Mock extract_session_id to return a value
            with patch("paymcp.payment.flows.two_step.extract_session_id") as mock_extract:
                mock_extract.return_value = "session-123"

                with patch("paymcp.payment.flows.two_step.logger") as mock_logger:
                    # Call wrapper with ctx
                    result = await wrapper(ctx=mock_mcp)

                    # Should still return payment info
                    assert "payment_id" in result
                    assert "payment_url" in result

                    # Check that debug log was called with session ID
                    mock_logger.debug.assert_any_call("Extracted MCP session ID: session-123")