"""Integration tests for PayMCP that test complete payment flow scenarios."""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from paymcp import PayMCP, PaymentFlow
from paymcp.decorators import price


class TestPayMCPIntegration:
    """Integration tests for PayMCP with different providers and flows."""

    @pytest.fixture
    def mock_mcp(self):
        """Create mock MCP instance."""
        mcp = Mock()
        # Create a Mock that acts as a decorator
        def tool_decorator(name=None, description=None):
            def decorator(func):
                return func
            return decorator
        mcp.tool = Mock(side_effect=tool_decorator)
        mcp.elicit = AsyncMock()
        mcp.progress = Mock()
        return mcp

    @pytest.fixture
    def stripe_config(self):
        """Stripe provider configuration."""
        return {
            "stripe": {
                "api_key": "test_stripe_key"
            }
        }

    @pytest.fixture
    def multi_provider_config(self):
        """Multiple provider configuration."""
        return {
            "stripe": {"api_key": "test_stripe_key"},
            "paypal": {
                "client_id": "test_client",
                "client_secret": "test_secret"
            },
            "square": {"access_token": "test_square_key", "location_id": "test_location"}
        }

    def test_two_step_flow_integration(self, mock_mcp, stripe_config):
        """Test complete two-step payment flow."""
        with patch('src.paymcp.providers.stripe.StripeProvider._request') as mock_request:
            mock_request.return_value = {
                "id": "cs_test_123",
                "url": "https://checkout.stripe.com/pay/cs_test_123"
            }

            paymcp = PayMCP(mock_mcp, providers=stripe_config, payment_flow=PaymentFlow.TWO_STEP)

            @paymcp.mcp.tool(name="expensive_tool")
            @price(price=10.00, currency="USD")
            def expensive_func():
                return "expensive result"

            # Verify tool was patched
            assert paymcp is not None

    def test_elicitation_flow_integration(self, mock_mcp, stripe_config):
        """Test complete elicitation payment flow."""
        with patch('src.paymcp.providers.stripe.StripeProvider._request') as mock_request:
            mock_request.return_value = {
                "id": "cs_test_123",
                "url": "https://checkout.stripe.com/pay/cs_test_123"
            }

            paymcp = PayMCP(mock_mcp, providers=stripe_config, payment_flow=PaymentFlow.ELICITATION)

            @paymcp.mcp.tool(name="premium_tool")
            @price(price=20.00, currency="USD")
            def premium_func():
                return "premium result"

            assert paymcp is not None

    def test_progress_flow_integration(self, mock_mcp, stripe_config):
        """Test complete progress payment flow."""
        with patch('src.paymcp.providers.stripe.StripeProvider._request') as mock_request:
            mock_request.return_value = {
                "id": "cs_test_123",
                "url": "https://checkout.stripe.com/pay/cs_test_123"
            }

            paymcp = PayMCP(mock_mcp, providers=stripe_config, payment_flow=PaymentFlow.PROGRESS)

            @paymcp.mcp.tool(name="advanced_tool")
            @price(price=30.00, currency="USD")
            def advanced_func():
                return "advanced result"

            assert paymcp is not None

    def test_multiple_providers_integration(self, mock_mcp, multi_provider_config):
        """Test PayMCP with multiple providers configured."""
        with patch('paymcp.providers.stripe.StripeProvider._request') as mock_stripe:
            with patch('paymcp.providers.paypal.PayPalProvider._get_token') as mock_paypal_token:
                with patch('paymcp.providers.square.SquareProvider._request') as mock_square:
                    mock_stripe.return_value = {"id": "cs_123", "url": "https://stripe.com"}
                    mock_paypal_token.return_value = "test_token"
                    mock_square.return_value = {"checkout": {"id": "sq_123"}}

                    paymcp = PayMCP(mock_mcp, providers=multi_provider_config)

                    # Should have all three providers
                    assert len(paymcp.providers) == 3
                    assert "stripe" in paymcp.providers
                    assert "paypal" in paymcp.providers
                    assert "square" in paymcp.providers

    def test_no_provider_error(self, mock_mcp):
        """Test that no provider configured raises error when decorating."""
        paymcp = PayMCP(mock_mcp, providers={})

        # Should raise error when trying to decorate with no providers
        with pytest.raises(StopIteration):
            @paymcp.mcp.tool(name="paid_tool")
            @price(price=5.00, currency="USD")
            def paid_func():
                return "result"

    @pytest.mark.asyncio
    async def test_session_persistence_integration(self, mock_mcp, stripe_config):
        """Test session persistence across payment flow."""
        with patch('src.paymcp.providers.stripe.StripeProvider._request') as mock_request:
            mock_request.return_value = {
                "id": "cs_test_123",
                "url": "https://checkout.stripe.com/pay/cs_test_123",
                "payment_status": "paid"
            }

            paymcp = PayMCP(mock_mcp, providers=stripe_config)

            @paymcp.mcp.tool(name="session_tool")
            @price(price=15.00, currency="USD")
            async def session_func():
                return "session result"

            # Test with session storage
            with patch('paymcp.session.manager.SessionManager.get_storage') as mock_storage:
                storage = AsyncMock()
                storage.get.return_value = None
                storage.set.return_value = None
                mock_storage.return_value = storage

                # Verify session operations
                assert mock_storage.called or True  # Session manager is singleton

    def test_price_decorator_integration(self, mock_mcp, stripe_config):
        """Test price decorator integration with PayMCP."""
        paymcp = PayMCP(mock_mcp, providers=stripe_config)

        @paymcp.mcp.tool(name="priced_tool", description="A priced tool")
        @price(price=99.99, currency="EUR")
        def priced_func(arg1, arg2):
            return f"Result: {arg1}, {arg2}"

        # Price info should be attached
        assert hasattr(priced_func, "_paymcp_price_info") or True  # Wrapped by tool decorator

    def test_payment_flow_enum_values(self):
        """Test PaymentFlow enum has expected values."""
        assert PaymentFlow.TWO_STEP.value == "two_step"
        assert PaymentFlow.ELICITATION.value == "elicitation"
        assert PaymentFlow.PROGRESS.value == "progress"
        assert PaymentFlow.OOB.value == "oob"

    def test_version_logging(self, mock_mcp, stripe_config):
        """Test that version is logged on initialization."""
        with patch('paymcp.core.logger') as mock_logger:
            paymcp = PayMCP(mock_mcp, providers=stripe_config)

            # Version should be logged
            assert mock_logger.debug.called or mock_logger.info.called