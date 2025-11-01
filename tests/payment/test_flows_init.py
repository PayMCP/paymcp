"""Tests for payment flow factory functionality."""

import pytest
from unittest.mock import Mock, patch
from paymcp.payment.flows import make_flow


class TestFlowFactory:
    """Test the payment flow factory."""

    def test_make_flow_valid_flow(self):
        """Test make_flow with a valid flow name."""
        # Mock the import_module to return a module with make_paid_wrapper
        mock_module = Mock()
        mock_make_paid_wrapper = Mock()
        mock_module.make_paid_wrapper = mock_make_paid_wrapper

        with patch("paymcp.payment.flows.import_module") as mock_import:
            mock_import.return_value = mock_module

            wrapper_factory = make_flow("two_step")

            # Verify import was called correctly
            mock_import.assert_called_once_with(".two_step", "paymcp.payment.flows")

            # Test the returned wrapper factory
            mock_func = Mock()
            mock_mcp = Mock()
            mock_provider = Mock()
            mock_price_info = {"price": 10.0, "currency": "USD"}

            result = wrapper_factory(mock_func, mock_mcp, mock_provider, mock_price_info)

            # Verify make_paid_wrapper was called with correct arguments
            # All flows now accept state_store and config parameters for consistency
            mock_make_paid_wrapper.assert_called_once_with(
                func=mock_func,
                mcp=mock_mcp,
                provider=mock_provider,
                price_info=mock_price_info,
                state_store=None,
                config=None
            )

            assert result == mock_make_paid_wrapper.return_value

    def test_make_flow_invalid_flow(self):
        """Test make_flow with an invalid flow name."""
        with patch("paymcp.payment.flows.import_module") as mock_import:
            mock_import.side_effect = ModuleNotFoundError("No module named 'invalid_flow'")

            with pytest.raises(ValueError, match="Unknown payment flow: invalid_flow"):
                make_flow("invalid_flow")

            # Verify import was attempted
            mock_import.assert_called_once_with(".invalid_flow", "paymcp.payment.flows")

    def test_make_flow_elicitation(self):
        """Test make_flow with elicitation flow."""
        mock_module = Mock()
        mock_make_paid_wrapper = Mock()
        mock_module.make_paid_wrapper = mock_make_paid_wrapper

        with patch("paymcp.payment.flows.import_module") as mock_import:
            mock_import.return_value = mock_module

            wrapper_factory = make_flow("elicitation")

            # Verify correct module was imported
            mock_import.assert_called_once_with(".elicitation", "paymcp.payment.flows")

            # Test wrapper factory functionality
            mock_func = Mock()
            mock_mcp = Mock()
            mock_provider = Mock()
            mock_price_info = {"price": 25.0, "currency": "EUR"}

            wrapper_factory(mock_func, mock_mcp, mock_provider, mock_price_info)

            # All flows now accept state_store and config parameters for consistency
            mock_make_paid_wrapper.assert_called_once_with(
                func=mock_func,
                mcp=mock_mcp,
                provider=mock_provider,
                price_info=mock_price_info,
                state_store=None,
                config=None
            )

    def test_make_flow_progress(self):
        """Test make_flow with progress flow."""
        mock_module = Mock()
        mock_make_paid_wrapper = Mock()
        mock_module.make_paid_wrapper = mock_make_paid_wrapper

        with patch("paymcp.payment.flows.import_module") as mock_import:
            mock_import.return_value = mock_module

            wrapper_factory = make_flow("progress")

            # Verify correct module was imported
            mock_import.assert_called_once_with(".progress", "paymcp.payment.flows")

            # Test wrapper factory with all required parameters
            wrapper_factory(
                func=Mock(),
                mcp=Mock(),
                provider=Mock(),
                price_info={"price": 5.0, "currency": "USD"}
            )

            assert mock_make_paid_wrapper.called

    def test_wrapper_factory_parameter_passing(self):
        """Test that wrapper factory correctly passes all parameters."""
        mock_module = Mock()
        mock_make_paid_wrapper = Mock()
        mock_module.make_paid_wrapper = mock_make_paid_wrapper

        with patch("paymcp.payment.flows.import_module") as mock_import:
            mock_import.return_value = mock_module

            wrapper_factory = make_flow("test_flow")

            # Create specific mock objects to verify parameter passing
            specific_func = Mock()
            specific_func.__name__ = "test_function"
            specific_mcp = Mock()
            specific_provider = Mock()
            specific_price_info = {"price": 15.50, "currency": "GBP"}

            wrapper_factory(specific_func, specific_mcp, specific_provider, specific_price_info)

            # Verify exact parameter matching (all flows now include state_store and config)
            mock_make_paid_wrapper.assert_called_once_with(
                func=specific_func,
                mcp=specific_mcp,
                provider=specific_provider,
                price_info=specific_price_info,
                state_store=None,
                config=None
            )

    def test_wrapper_factory_returns_result(self):
        """Test that wrapper factory returns the result from make_paid_wrapper."""
        mock_module = Mock()
        mock_wrapper = Mock()
        mock_module.make_paid_wrapper = Mock(return_value=mock_wrapper)

        with patch("paymcp.payment.flows.import_module") as mock_import:
            mock_import.return_value = mock_module

            wrapper_factory = make_flow("test_flow")
            result = wrapper_factory(Mock(), Mock(), Mock(), {})

            assert result == mock_wrapper

    def test_make_flow_module_without_make_paid_wrapper(self):
        """Test make_flow with a module that doesn't have make_paid_wrapper."""
        mock_module = Mock()
        # Remove make_paid_wrapper attribute if it exists
        if hasattr(mock_module, 'make_paid_wrapper'):
            delattr(mock_module, 'make_paid_wrapper')

        with patch("paymcp.payment.flows.import_module") as mock_import:
            mock_import.return_value = mock_module

            # This should raise AttributeError when trying to get make_paid_wrapper
            with pytest.raises(AttributeError):
                make_flow("invalid_module")