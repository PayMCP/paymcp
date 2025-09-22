"""Tests for elicitation payment flow."""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from paymcp.payment.flows.elicitation import make_paid_wrapper
from paymcp.session.types import SessionData


class TestElicitationFlow:
    """Test elicitation payment flow functionality."""

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
        # Create proper elicit response
        from types import SimpleNamespace
        elicit_response = SimpleNamespace(action="accept")
        mcp.elicit = AsyncMock(return_value=elicit_response)
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
        """Test that elicitation wrapper is created successfully."""
        price_info = {"price": 10, "currency": "USD"}

        wrapper = make_paid_wrapper(mock_function, mock_mcp, mock_provider, price_info)

        assert wrapper is not None
        assert hasattr(wrapper, '__name__')
        assert wrapper.__name__ == "test_func"  # functools.wraps preserves original name

    @pytest.mark.asyncio
    async def test_elicitation_accept_flow(self, mock_function, mock_mcp, mock_provider):
        """Test elicitation flow when payment is accepted."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch('src.paymcp.session.manager.SessionManager.get_storage') as mock_storage:
            storage = AsyncMock()
            storage.get.return_value = None  # No existing session
            mock_storage.return_value = storage

            # Mock the elicitation loop to return paid immediately
            mock_provider.get_payment_status.return_value = "paid"

            # Elicitation flow needs ctx in kwargs - will timeout after 15 seconds
            # Since we can't easily mock run_elicitation_loop due to imports,
            # we'll just verify the function executes
            result = await wrapper(ctx=mock_mcp)
            assert result == "result"

            # Function should have been called
            async_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_elicitation_decline_flow(self, mock_function, mock_mcp, mock_provider):
        """Test elicitation flow when payment is declined."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch('src.paymcp.session.manager.SessionManager.get_storage') as mock_storage:
            storage = AsyncMock()
            storage.get.return_value = None
            mock_storage.return_value = storage

            # Override the elicit response for decline
            from types import SimpleNamespace
            mock_mcp.elicit.return_value = SimpleNamespace(action="cancel")

            with patch('src.paymcp.utils.elicitation.run_elicitation_loop') as mock_elicit:
                # Simulate user declining payment
                mock_elicit.return_value = "canceled"

                with pytest.raises(Exception) as exc_info:
                    await wrapper(ctx=mock_mcp)

                assert "Payment canceled" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_elicitation_with_existing_session(self, mock_function, mock_mcp, mock_provider):
        """Test elicitation flow with existing paid session."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        # Payment already paid
        mock_provider.get_payment_status.return_value = "paid"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch('src.paymcp.session.manager.SessionManager.get_storage') as mock_storage:
            storage = AsyncMock()
            # Existing session
            storage.get.return_value = SessionData(
                args={"amount": 10, "currency": "USD"},
                ts=123456,
                provider_name="test_provider"
            )
            mock_storage.return_value = storage

            # Mock payment as immediately paid
            mock_provider.get_payment_status.return_value = "paid"

            # Elicitation needs ctx
            result = await wrapper(ctx=mock_mcp)
            assert result == "result"

            # Function should be called since payment is paid
            async_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_elicitation_error_handling(self, mock_function, mock_mcp, mock_provider):
        """Test error handling during elicitation."""
        price_info = {"price": 10, "currency": "USD"}

        # Create async mock function
        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test_func"

        wrapper = make_paid_wrapper(async_func, mock_mcp, mock_provider, price_info)

        with patch('src.paymcp.session.manager.SessionManager.get_storage') as mock_storage:
            storage = AsyncMock()
            storage.get.side_effect = Exception("Storage error")
            mock_storage.return_value = storage

            with patch('src.paymcp.payment.flows.elicitation.logger') as mock_logger:
                # Even with storage error, should create payment
                # Mock payment as paid
                mock_provider.get_payment_status.return_value = "paid"

                # Pass ctx for elicitation
                result = await wrapper(ctx=mock_mcp)
                assert result == "result"

                # Function was called despite storage error
                async_func.assert_called_once()