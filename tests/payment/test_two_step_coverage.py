"""Tests for covering missing lines in two_step.py for 95%+ coverage."""

import pytest
from unittest.mock import Mock, AsyncMock
from paymcp.payment.flows.two_step import make_paid_wrapper
from paymcp.providers.base import BasePaymentProvider


class TestTwoStepFlowCoverage:
    """Test coverage for two_step.py edge cases."""

    @pytest.fixture
    def mock_state_store(self):
        """Create a mock state store."""
        store = AsyncMock()
        store.set = AsyncMock()
        store.get = AsyncMock()
        store.delete = AsyncMock()
        return store

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock MCP instance."""
        mcp = Mock()
        mcp.tool = Mock(return_value=lambda func: func)
        return mcp

    @pytest.fixture
    def mock_provider(self):
        """Create a mock payment provider."""
        provider = Mock(spec=BasePaymentProvider)
        provider.create_payment = Mock(return_value=("payment_123", "https://pay.example.com"))
        provider.get_payment_status = Mock(return_value="paid")
        return provider

    def test_confirm_tool_registration_with_meta_in_config(self, mock_mcp, mock_provider, mock_state_store):
        """Test that confirm tool includes meta when provided in config."""
        mock_func = Mock(__name__="analyze_document")
        price_info = {"price": 2.50, "currency": "USD"}

        # Config with meta field - this should trigger line 27
        config = {
            "description": "Analyze a document",
            "meta": {
                "version": "2.0",
                "category": "text-processing",
                "premium": True
            }
        }

        # Call make_paid_wrapper with config containing meta
        make_paid_wrapper(
            func=mock_func,
            mcp=mock_mcp,
            provider=mock_provider,
            price_info=price_info,
            state_store=mock_state_store,
            config=config
        )

        # Verify that mcp.tool was called with meta in the arguments
        calls = mock_mcp.tool.call_args_list
        assert len(calls) > 0

        # Find the confirm tool registration (first call)
        confirm_tool_call = calls[0]
        confirm_tool_kwargs = confirm_tool_call.kwargs

        # Check that meta is included in the tool registration
        assert "meta" in confirm_tool_kwargs
        assert confirm_tool_kwargs["meta"] == config["meta"]

    def test_confirm_tool_registration_without_meta(self, mock_mcp, mock_provider, mock_state_store):
        """Test confirm tool registration when config has no meta field."""
        mock_func = Mock(__name__="process_image")
        price_info = {"price": 1.00, "currency": "USD"}

        # Config without meta field
        config = {
            "description": "Process an image"
        }

        # Call make_paid_wrapper with config without meta
        make_paid_wrapper(
            func=mock_func,
            mcp=mock_mcp,
            provider=mock_provider,
            price_info=price_info,
            state_store=mock_state_store,
            config=config
        )

        # Verify that mcp.tool was called
        calls = mock_mcp.tool.call_args_list
        assert len(calls) > 0

        # Check the confirm tool registration
        confirm_tool_call = calls[0]
        confirm_tool_kwargs = confirm_tool_call.kwargs

        # Meta should NOT be in the tool registration when not provided
        assert "meta" not in confirm_tool_kwargs or confirm_tool_kwargs.get("meta") is None

    def test_confirm_tool_registration_with_none_config(self, mock_mcp, mock_provider, mock_state_store):
        """Test confirm tool registration when config is None."""
        mock_func = Mock(__name__="generate_text")
        price_info = {"price": 0.75, "currency": "USD"}

        # Call make_paid_wrapper with None config (no meta handling)
        make_paid_wrapper(
            func=mock_func,
            mcp=mock_mcp,
            provider=mock_provider,
            price_info=price_info,
            state_store=mock_state_store,
            config=None  # Explicitly None
        )

        # Verify that mcp.tool was called
        calls = mock_mcp.tool.call_args_list
        assert len(calls) > 0

        # Check the confirm tool registration
        confirm_tool_call = calls[0]
        confirm_tool_kwargs = confirm_tool_call.kwargs

        # Meta should NOT be in the tool registration when config is None
        assert "meta" not in confirm_tool_kwargs

    def test_confirm_tool_registration_empty_config(self, mock_mcp, mock_provider, mock_state_store):
        """Test confirm tool registration when config is empty dict."""
        mock_func = Mock(__name__="translate_text")
        price_info = {"price": 0.50, "currency": "USD"}

        # Empty config dict
        config = {}

        # Call make_paid_wrapper with empty config
        make_paid_wrapper(
            func=mock_func,
            mcp=mock_mcp,
            provider=mock_provider,
            price_info=price_info,
            state_store=mock_state_store,
            config=config
        )

        # Verify that mcp.tool was called
        calls = mock_mcp.tool.call_args_list
        assert len(calls) > 0

        # Check the confirm tool registration
        confirm_tool_call = calls[0]
        confirm_tool_kwargs = confirm_tool_call.kwargs

        # Meta should NOT be in the tool registration
        assert "meta" not in confirm_tool_kwargs
