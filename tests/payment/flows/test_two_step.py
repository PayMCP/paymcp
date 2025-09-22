"""Tests for two-step payment flow."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from paymcp.payment.flows.two_step import make_paid_wrapper
from paymcp.session.types import SessionData


class TestTwoStepFlow:
    """Test two-step payment flow functionality."""

    @pytest.fixture
    def mock_function(self):
        """Create a mock function to wrap."""
        func = Mock(__name__="test_func", __doc__="Test function")
        func.return_value = "result"
        return func

    @pytest.fixture
    def mock_mcp(self):
        """Create mock MCP instance."""
        mcp = Mock()
        mcp.tool = Mock(return_value=lambda f: f)
        return mcp

    @pytest.fixture
    def mock_provider(self):
        """Create mock payment provider."""
        provider = Mock()
        provider.create_payment = Mock(return_value=("payment_123", "https://pay.test"))
        provider.get_payment_status = Mock(return_value="pending")
        provider.get_name = Mock(return_value="test_provider")
        return provider

    def test_make_paid_wrapper_creation(self, mock_function, mock_mcp, mock_provider):
        """Test that two-step wrapper is created successfully."""
        price_info = {"price": 10, "currency": "USD"}

        wrapper = make_paid_wrapper(mock_function, mock_mcp, mock_provider, price_info)

        assert wrapper is not None
        assert hasattr(wrapper, "__name__")
        assert (
            wrapper.__name__ == "test_func"
        )  # functools.wraps preserves original name

    @pytest.mark.asyncio
    async def test_payment_initiation_flow(
        self, mock_function, mock_mcp, mock_provider
    ):
        """Test payment initiation returns payment info."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage:
            storage = AsyncMock()
            storage.set.return_value = None
            mock_storage.return_value = storage

            # Two-step flow returns payment info, not exception
            result = await wrapper()

            assert result["status"] == "pending"
            assert result["payment_url"] == "https://pay.test"
            assert result["payment_id"] == "payment_123"
            assert "confirm_test_func_payment" in result["next_step"]

    @pytest.mark.asyncio
    async def test_confirm_payment_tool(self, mock_function, mock_mcp, mock_provider):
        """Test the confirm payment tool registration."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        # Create wrapper - this should register the confirm tool
        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        # Check that mcp.tool was called to register confirm tool
        assert mock_mcp.tool.called
        tool_call_args = mock_mcp.tool.call_args
        assert tool_call_args[1]["name"] == "confirm_test_func_payment"

    @pytest.mark.asyncio
    async def test_webview_opening(self, mock_function, mock_mcp, mock_provider):
        """Test webview opening behavior."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage:
            storage = AsyncMock()
            storage.set.return_value = None
            mock_storage.return_value = storage

            with patch(
                "paymcp.payment.flows.two_step.open_payment_webview_if_available"
            ) as mock_webview:
                # Test with webview available
                mock_webview.return_value = True
                result = await wrapper()
                assert "payment_url" in result
                mock_webview.assert_called_once_with("https://pay.test")

                # Test with webview not available
                mock_webview.return_value = False
                result = await wrapper()
                assert "payment_url" in result
