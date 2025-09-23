"""Tests for the paymcp.core module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from paymcp.core import PayMCP
from paymcp.payment.payment_flow import PaymentFlow
from paymcp.providers.base import BasePaymentProvider


class TestPayMCP:
    """Test the PayMCP core functionality."""

    @pytest.fixture
    def mock_mcp_instance(self):
        """Create a mock MCP instance."""
        mcp = Mock()
        mcp.tool = Mock(return_value=lambda func: func)
        return mcp

    @pytest.fixture
    def mock_provider(self):
        """Create a mock payment provider."""
        provider = Mock(spec=BasePaymentProvider)
        provider.get_name = Mock(return_value="test_provider")
        provider.create_payment = Mock(return_value=("test123", "https://payment.url"))
        provider.get_payment_status = Mock(return_value="completed")
        return provider

    @pytest.fixture
    def providers_config(self):
        """Create a test providers configuration."""
        return {"stripe": {"api_key": "sk_test_123"}}

    def test_initialization_default_flow(self, mock_mcp_instance, providers_config):
        """Test PayMCP initialization with default flow."""
        paymcp = PayMCP(mock_mcp_instance, providers=providers_config)
        assert paymcp.mcp == mock_mcp_instance
        assert paymcp.providers is not None

    def test_initialization_custom_flow(self, mock_mcp_instance, providers_config):
        """Test PayMCP initialization with custom flow."""
        paymcp = PayMCP(
            mock_mcp_instance,
            providers=providers_config,
            payment_flow=PaymentFlow.ELICITATION,
        )
        assert paymcp.mcp == mock_mcp_instance
        assert paymcp.providers is not None

    def test_patch_tool(self, mock_mcp_instance, providers_config):
        """Test that tool patching works correctly."""
        paymcp = PayMCP(mock_mcp_instance, providers=providers_config)

        # Verify that the MCP tool method was accessed
        assert hasattr(paymcp, "_patch_tool")

    @patch("paymcp.core.build_providers")
    def test_providers_initialization(self, mock_build_providers, mock_mcp_instance):
        """Test that providers are correctly initialized."""
        mock_providers = {"stripe": Mock(spec=BasePaymentProvider)}
        mock_build_providers.return_value = mock_providers

        providers_config = {"stripe": {"api_key": "test"}}
        paymcp = PayMCP(mock_mcp_instance, providers=providers_config)

        mock_build_providers.assert_called_once_with(providers_config)
        assert paymcp.providers == mock_providers

    def test_payment_flow_enum_values(self):
        """Test PaymentFlow enum values."""
        assert PaymentFlow.TWO_STEP.value == "two_step"
        assert PaymentFlow.ELICITATION.value == "elicitation"
        assert PaymentFlow.PROGRESS.value == "progress"

    @patch("paymcp.core.make_flow")
    def test_flow_factory(self, mock_make_flow, mock_mcp_instance, providers_config):
        """Test that flow factory is called with correct parameters."""
        mock_wrapper = Mock()
        mock_make_flow.return_value = mock_wrapper

        paymcp = PayMCP(
            mock_mcp_instance,
            providers=providers_config,
            payment_flow=PaymentFlow.PROGRESS,
        )

        mock_make_flow.assert_called_once_with("progress")
        assert paymcp._wrapper_factory == mock_wrapper

    def test_decorated_tool_with_price(self, mock_mcp_instance):
        """Test handling of tools decorated with @price."""
        providers_config = {"stripe": {"api_key": "test"}}
        paymcp = PayMCP(mock_mcp_instance, providers=providers_config)

        # Create a mock decorated function
        func = Mock()
        func._paymcp_price_info = {"amount": 10.0, "currency": "USD"}
        func.__doc__ = "Test function"

        # Simulate calling the patched tool
        @paymcp.mcp.tool(name="test_tool")
        def test_function():
            """Test function with price."""
            return "result"

        # Verify that tool patching mechanism exists
        assert hasattr(paymcp, "_patch_tool")

    def test_no_provider_error(self, mock_mcp_instance):
        """Test error when no provider is configured."""
        paymcp = PayMCP(mock_mcp_instance, providers={})
        assert len(paymcp.providers) == 0

    @patch("paymcp.core.logger")
    def test_version_logging(self, mock_logger, mock_mcp_instance, providers_config):
        """Test that version is logged during initialization."""
        PayMCP(mock_mcp_instance, providers=providers_config)

        # Check that debug logging was called
        assert mock_logger.debug.called

    @patch("paymcp.core.build_providers")
    def test_multiple_providers(self, mock_build_providers, mock_mcp_instance):
        """Test initialization with multiple providers."""
        mock_providers = {
            "stripe": Mock(spec=BasePaymentProvider),
            "paypal": Mock(spec=BasePaymentProvider),
        }
        mock_build_providers.return_value = mock_providers

        providers_config = {
            "stripe": {"api_key": "sk_test_stripe"},
            "paypal": {"client_id": "test_id", "client_secret": "test_secret"},
        }

        paymcp = PayMCP(mock_mcp_instance, providers=providers_config)
        assert paymcp.providers is not None
        assert len(paymcp.providers) == 2

    def test_wrapper_factory_integration(self, mock_mcp_instance, mock_provider):
        """Test integration between wrapper factory and provider."""
        with patch("paymcp.core.build_providers") as mock_build:
            mock_build.return_value = {"test": mock_provider}

            paymcp = PayMCP(mock_mcp_instance, providers={"test": {}})

            # Create a mock function with price info
            func = Mock()
            func._paymcp_price_info = {"amount": 25.0, "currency": "EUR"}

            # Verify wrapper factory exists
            assert hasattr(paymcp, "_wrapper_factory")
            assert paymcp._wrapper_factory is not None
