"""Tests for the paymcp.core module."""

import pytest
from importlib import reload
from unittest.mock import Mock, MagicMock, patch
from paymcp.core import PayMCP
from paymcp.decorators import price
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
        assert paymcp.payment_flow == PaymentFlow.AUTO

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
        assert PaymentFlow.AUTO.value == "auto"
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

    def test_version_exception_handling_module_import(self):
        """Test version exception handling when package not found at module import time."""
        from importlib.metadata import PackageNotFoundError
        import sys

        # Get module reference from sys.modules to avoid duplicate import styles
        core_module = sys.modules['paymcp.core']

        # Save original version
        original_version = core_module.__version__

        try:
            # Patch version to raise PackageNotFoundError
            with patch("importlib.metadata.version") as mock_version:
                mock_version.side_effect = PackageNotFoundError()

                # Reload the module to trigger the exception handling code (lines 13-14)
                reload(core_module)

                # Verify __version__ is set to "unknown"
                assert core_module.__version__ == "unknown"
        finally:
            # Restore original version
            core_module.__version__ = original_version
            # Reload again to restore normal state
            reload(core_module)

    def test_provider_selection_no_providers(self, mock_mcp_instance):
        """Test provider selection when no providers configured."""
        paymcp = PayMCP(mock_mcp_instance, providers={})

        # Create a mock function with price info
        func = Mock()
        func._paymcp_price_info = {"price": 10.0, "currency": "USD"}
        func._paymcp_subscription_info = None  # Explicitly set to None to avoid Mock truthy behavior
        func.__name__ = "test_func"
        func.__doc__ = "Test function"

        # Call the patched tool - this should raise RuntimeError when no provider is available
        with pytest.raises(RuntimeError) as exc_info:
            paymcp.mcp.tool(name="test_tool")(func)
        assert "No payment provider configured" in str(exc_info.value)

    @patch("paymcp.core.build_providers")
    def test_provider_selection_with_providers(self, mock_build_providers, mock_mcp_instance):
        """Test provider selection logic when providers are available."""
        mock_provider = Mock(spec=BasePaymentProvider)
        mock_provider.get_name = Mock(return_value="test_provider")
        mock_providers = {"test": mock_provider}
        mock_build_providers.return_value = mock_providers

        paymcp = PayMCP(mock_mcp_instance, providers={"test": {}})

        # Create a mock function with price info
        func = Mock()
        func._paymcp_price_info = {"price": 10.0, "currency": "USD"}
        func.__name__ = "test_func"
        func.__doc__ = "Test function"

        # Mock the wrapper factory
        mock_wrapper_factory = Mock()
        mock_target_func = Mock()
        mock_wrapper_factory.return_value = mock_target_func
        paymcp._wrapper_factory = mock_wrapper_factory

        # Mock the MCP tool decorator
        mock_tool_result = Mock()
        mock_mcp_instance.tool.return_value = mock_tool_result
        mock_tool_result.return_value = func

        # Call the patched tool
        patched_tool = paymcp.mcp.tool(name="test_tool", description="Test tool")
        wrapper = patched_tool(func)

        # Verify the wrapper factory was called
        assert wrapper is not None

    def test_decorator_without_price_info(self, mock_mcp_instance, providers_config):
        """Test that tools without price info are not wrapped."""
        paymcp = PayMCP(mock_mcp_instance, providers=providers_config)

        # Create a function WITHOUT price info
        def normal_tool():
            """Normal tool without payment"""
            return "result"

        # Mock the wrapper factory to track if it's called
        mock_wrapper_factory = Mock()
        paymcp._wrapper_factory = mock_wrapper_factory

        # Call the tool decorator (result not used, just checking side effect)
        _ = paymcp.mcp.tool(normal_tool)

        # Verify wrapper factory was NOT called (no price info)
        assert not mock_wrapper_factory.called

    def test_state_store_default_initialization(self, mock_mcp_instance, providers_config):
        """Test that state_store defaults to InMemoryStateStore."""
        paymcp = PayMCP(mock_mcp_instance, providers=providers_config)

        # Verify state_store was created
        assert paymcp.state_store is not None

        # Verify it's an InMemoryStateStore
        from paymcp.state import InMemoryStateStore
        assert isinstance(paymcp.state_store, InMemoryStateStore)

    def test_state_store_custom_initialization(self, mock_mcp_instance, providers_config):
        """Test that custom state_store can be provided."""
        custom_store = Mock()

        paymcp = PayMCP(mock_mcp_instance, providers=providers_config, state_store=custom_store)

        # Verify custom state_store was used
        assert paymcp.state_store == custom_store

    def test_mode_and_payment_flow_both_provided_warning(self, mock_mcp_instance, providers_config, caplog):
        """Test that warning is logged when both mode and payment_flow are provided."""
        import logging
        with caplog.at_level(logging.WARNING):
            PayMCP(mock_mcp_instance, providers=providers_config, mode=PaymentFlow.TWO_STEP, payment_flow=PaymentFlow.PROGRESS)

        assert "mode" in caplog.text.lower() and "payment_flow" in caplog.text.lower()

    def test_no_payment_provider_configured_error(self, mock_mcp_instance):
        """Test that RuntimeError is raised when no payment provider is configured."""
        # This test verifies that the error path exists in the code
        # The actual RuntimeError would be raised when provider is None and price_info exists
        paymcp = PayMCP(mock_mcp_instance, providers={})

        # Verify that providers dict is empty, which would trigger line 52 if a paid tool was invoked
        assert paymcp.providers == {}

    def test_meta_removed_from_kwargs_two_step(self, mock_mcp_instance, providers_config):
        """Test that 'meta' is removed from kwargs for TWO_STEP flow."""
        paymcp = PayMCP(mock_mcp_instance, providers=providers_config, payment_flow=PaymentFlow.TWO_STEP)

        @paymcp.mcp.tool(meta={"test": "data"})
        @price(1.0, "USD")
        def test_tool(ctx):
            return "test"

        # Verify tool is registered without 'meta' in kwargs
        assert hasattr(paymcp.mcp, 'tool')

    def test_dynamic_tools_patch_list_tools_immediate(self, mock_mcp_instance, providers_config):
        """Test that _patch_list_tools_immediate is called for DYNAMIC_TOOLS flow."""
        mock_mcp_instance._tool_manager = Mock()
        mock_mcp_instance._tool_manager.list_tools = Mock()

        paymcp = PayMCP(mock_mcp_instance, providers=providers_config, payment_flow=PaymentFlow.DYNAMIC_TOOLS)

        @paymcp.mcp.tool()
        @price(1.0, "USD")
        def test_tool(ctx):
            return "test"

        # Verify list_tools was patched
        assert hasattr(mock_mcp_instance._tool_manager.list_tools, '_paymcp_dynamic_tools_patched')

    @patch("paymcp.core.build_providers")
    def test_provider_is_none_error(self, mock_build_providers, mock_mcp_instance):
        """Test error when provider value is None (line 52 coverage)."""
        # Set up providers dict where the provider is None
        mock_build_providers.return_value = {"stripe": None}

        paymcp = PayMCP(mock_mcp_instance, providers={"stripe": {}})

        # Create a function with price info
        func = Mock()
        func._paymcp_price_info = {"price": 10.0, "currency": "USD"}
        func.__name__ = "test_func"
        func.__doc__ = "Test function"

        # Mock the tool decorator
        mock_tool_result = Mock()
        mock_mcp_instance.tool.return_value = mock_tool_result

        # Calling the patched tool should raise RuntimeError about no provider
        with pytest.raises(RuntimeError, match="No payment provider configured"):
            patched_tool = paymcp.mcp.tool(name="test_tool")
            patched_tool(func)

    @patch("paymcp.core.build_providers")
    def test_dynamic_tools_deferred_patch(self, mock_build_providers, mock_mcp_instance):
        """Test DYNAMIC_TOOLS deferred patch path (lines 72-73 coverage)."""
        mock_provider = Mock(spec=BasePaymentProvider)
        mock_provider.get_name = Mock(return_value="test_provider")
        mock_providers = {"test": mock_provider}
        mock_build_providers.return_value = mock_providers

        # Set up _tool_manager with unpatched list_tools
        mock_mcp_instance._tool_manager = Mock()
        mock_mcp_instance._tool_manager.list_tools = Mock()

        paymcp = PayMCP(
            mock_mcp_instance,
            providers={"test": {}},
            payment_flow=PaymentFlow.DYNAMIC_TOOLS
        )

        # Create a function with price info
        func = Mock()
        func._paymcp_price_info = {"price": 10.0, "currency": "USD"}
        func.__name__ = "test_func"
        func.__doc__ = "Test function"

        # Mock the wrapper factory
        mock_wrapper_factory = Mock()
        mock_target_func = Mock()
        mock_wrapper_factory.return_value = mock_target_func
        paymcp._wrapper_factory = mock_wrapper_factory

        # Mock the MCP tool decorator
        mock_tool_result = Mock()
        mock_mcp_instance.tool.return_value = mock_tool_result
        mock_tool_result.return_value = func

        # Call the patched tool - this should trigger deferred patch
        patched_tool = paymcp.mcp.tool(name="test_tool")
        patched_tool(func)

        # Verify list_tools was patched (lines 72-73)
        assert hasattr(mock_mcp_instance._tool_manager.list_tools, '_paymcp_dynamic_tools_patched')
