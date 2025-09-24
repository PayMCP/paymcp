"""Tests for progress payment flow."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from paymcp.payment.flows.progress import make_paid_wrapper
from paymcp.session.types import SessionData


class TestProgressFlow:
    """Test progress payment flow functionality."""

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
        mcp.progress = Mock()
        # Add async report_progress for progress flow
        mcp.report_progress = AsyncMock()
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
        """Test that progress wrapper is created successfully."""
        price_info = {"price": 10, "currency": "USD"}

        wrapper = make_paid_wrapper(mock_function, mock_mcp, mock_provider, price_info)

        assert wrapper is not None
        assert hasattr(wrapper, "__name__")
        assert (
            wrapper.__name__ == "test_func"
        )  # functools.wraps preserves original name
        
    def test_no_confirmation_tool_registered(self, mock_function, mock_mcp, mock_provider):
        """Test that PROGRESS flow does NOT register confirmation tools."""
        price_info = {"price": 10, "currency": "USD"}
        
        # Create wrapper
        wrapper = make_paid_wrapper(mock_function, mock_mcp, mock_provider, price_info)
        
        # Verify that mcp.tool was NOT called (no confirmation tool registered)
        mock_mcp.tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_monitoring_flow(
        self, mock_function, mock_mcp, mock_provider
    ):
        """Test progress flow with payment monitoring."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            storage = AsyncMock()
            storage.get.return_value = None  # No existing session
            mock_storage.return_value = storage

            # Simulate payment becoming paid immediately
            mock_provider.get_payment_status.return_value = "paid"

            # Progress flow polls and finds it paid immediately
            result = await wrapper(ctx=mock_mcp)
            assert result == "result"

    @pytest.mark.asyncio
    async def test_progress_with_paid_session(
        self, mock_function, mock_mcp, mock_provider
    ):
        """Test progress flow with already paid session."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        # Already paid
        mock_provider.get_payment_status.return_value = "paid"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            storage = AsyncMock()
            # Existing paid session
            from paymcp.session.types import SessionData

            storage.get.return_value = SessionData(
                args={"amount": 10, "currency": "USD"},
                ts=123456,
                provider_name="test_provider",
            )
            mock_storage.return_value = storage

            # Progress flow starts fresh and polls
            mock_provider.get_payment_status.return_value = "paid"  # Immediately paid

            result = await wrapper(ctx=mock_mcp)
            assert result == "result"

    @pytest.mark.asyncio
    async def test_progress_updates_sent(self, mock_function, mock_mcp, mock_provider):
        """Test that progress updates are sent during monitoring."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function that takes time and accepts ctx
        async def slow_func(ctx=None, **kwargs):
            await asyncio.sleep(0.01)  # Shorter delay for testing
            return "result"

        slow_func.__name__ = "test_func"
        slow_func.__doc__ = "Test function"

        wrapper = make_paid_wrapper(slow_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage, \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            storage = AsyncMock()
            storage.get.return_value = None
            mock_storage.return_value = storage

            # Progress flow reports progress during polling
            mock_provider.get_payment_status.return_value = "paid"  # Immediately paid

            # Mock ctx with report_progress method
            ctx = Mock()
            ctx.report_progress = AsyncMock()

            result = await wrapper(ctx=ctx)
            assert result == "result"

            # Verify progress was reported at least once
            assert ctx.report_progress.call_count >= 1

    @pytest.mark.asyncio
    async def test_progress_canceled_payment(
        self, mock_function, mock_mcp, mock_provider
    ):
        """Test progress flow when payment is canceled."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            storage = AsyncMock()
            storage.get.return_value = None
            mock_storage.return_value = storage

            # Payment gets canceled immediately
            mock_provider.get_payment_status.return_value = "canceled"

            result = await wrapper(ctx=mock_mcp)

            # Progress flow returns status instead of raising exception
            assert result["status"] == "canceled"
            assert "Payment canceled" in result["message"]

    @pytest.mark.asyncio
    async def test_progress_retry_with_payment_id(self, mock_function, mock_mcp, mock_provider):
        """Test progress flow retry with existing payment_id."""
        price_info = {"price": 10, "currency": "USD"}
        
        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"
        
        # Payment already paid from previous attempt
        mock_provider.get_payment_status.return_value = "paid"
        
        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)
        
        with patch(
            "paymcp.session.manager.SessionManager.get_storage"
        ) as mock_storage, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            storage = AsyncMock()
            mock_storage.return_value = storage

            # Call with payment_id from previous attempt
            result = await wrapper(ctx=mock_mcp, payment_id="payment_123")

            # Should check status and execute immediately without creating new payment
            mock_provider.get_payment_status.assert_called_once_with("payment_123")
            mock_provider.create_payment.assert_not_called()
            assert result == "result"
            async_func.assert_called_once()
            
    @pytest.mark.asyncio
    async def test_progress_retry_with_canceled_payment(self, mock_function, mock_mcp, mock_provider):
        """Test progress flow retry with canceled payment_id."""
        price_info = {"price": 10, "currency": "USD"}
        
        # Create async mock function  
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"
        
        # Payment was canceled
        mock_provider.get_payment_status.return_value = "canceled"
        
        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)
        
        with patch(
            "paymcp.session.manager.SessionManager.get_storage"
        ) as mock_storage, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            storage = AsyncMock()
            mock_storage.return_value = storage

            # Call with payment_id from previous attempt
            result = await wrapper(ctx=mock_mcp, payment_id="payment_123")

            # Should return canceled status without executing
            assert result["status"] == "canceled"
            assert "Previous payment was canceled" in result["message"]
            async_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_monitoring_error_handling(
        self, mock_function, mock_mcp, mock_provider
    ):
        """Test error handling in progress monitoring."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            storage = AsyncMock()
            storage.get.return_value = None
            mock_storage.return_value = storage

            # Test error handling during progress polling
            mock_provider.get_payment_status.side_effect = Exception("Provider error")

            with patch("paymcp.payment.flows.progress.logger") as mock_logger:
                # Progress flow should handle provider errors gracefully
                with pytest.raises(Exception, match="Provider error"):
                    await wrapper(ctx=mock_mcp)

    @pytest.mark.asyncio
    async def test_progress_extract_session_id_exception(self):
        """Test that flow continues even if extract_session_id raises exception."""
        mock_provider = Mock()
        mock_provider.get_name.return_value = "test_provider"
        mock_provider.create_payment.return_value = ("payment_123", "https://pay.test/123")
        mock_provider.get_payment_status.return_value = "paid"

        # Mock the async function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        price_info = {"price": 10.0, "currency": "USD"}
        mock_mcp = Mock()
        mock_mcp.report_progress = AsyncMock()

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        # Mock extract_session_id to raise exception
        with patch("paymcp.payment.flows.progress.extract_session_id") as mock_extract:
            mock_extract.side_effect = Exception("Session extraction failed")

            with patch("paymcp.payment.flows.progress.logger") as mock_logger:
                with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage, \
                     patch("asyncio.sleep", new_callable=AsyncMock):
                    storage = AsyncMock()
                    storage.get.return_value = None
                    mock_storage.return_value = storage

                    result = await wrapper(ctx=mock_mcp)
                    assert result == "result"

                    # Check that debug log was called for exception
                    mock_logger.debug.assert_any_call("Could not extract session ID: Session extraction failed")

    @pytest.mark.asyncio
    async def test_progress_extract_session_id_with_value(self):
        """Test that extracted session ID is logged when present."""
        mock_provider = Mock()
        mock_provider.get_name.return_value = "test_provider"
        mock_provider.create_payment.return_value = ("payment_123", "https://pay.test/123")
        mock_provider.get_payment_status.return_value = "paid"

        # Mock the async function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        price_info = {"price": 10.0, "currency": "USD"}
        mock_mcp = Mock()
        mock_mcp.report_progress = AsyncMock()

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        # Mock extract_session_id to return a value
        with patch("paymcp.payment.flows.progress.extract_session_id") as mock_extract:
            mock_extract.return_value = "session-123"

            with patch("paymcp.payment.flows.progress.logger") as mock_logger:
                with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage, \
                     patch("asyncio.sleep", new_callable=AsyncMock):
                    storage = AsyncMock()
                    storage.get.return_value = None
                    mock_storage.return_value = storage

                    result = await wrapper(ctx=mock_mcp)
                    assert result == "result"

                    # Check that debug log was called with session ID
                    mock_logger.debug.assert_any_call("Extracted MCP session ID: session-123")

    @pytest.mark.asyncio
    async def test_progress_no_report_progress_attribute(self):
        """Test that flow works even if ctx has no report_progress."""
        mock_provider = Mock()
        mock_provider.get_name.return_value = "test_provider"
        mock_provider.create_payment.return_value = ("payment_123", "https://pay.test/123")
        mock_provider.get_payment_status.return_value = "paid"

        # Mock the async function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        price_info = {"price": 10.0, "currency": "USD"}
        mock_mcp = Mock(spec=[])  # Mock with no report_progress attribute

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch("paymcp.session.manager.SessionManager.get_storage") as mock_storage, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            storage = AsyncMock()
            storage.get.return_value = None
            mock_storage.return_value = storage

            # Should work without errors
            result = await wrapper(ctx=mock_mcp)
            assert result == "result"
