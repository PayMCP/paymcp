import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from paymcp.payment.flows import make_flow


class TestMakeFlow:
    @pytest.fixture
    def mock_module(self):
        mock_mod = MagicMock()
        mock_wrapper = Mock()
        mock_mod.make_paid_wrapper = mock_wrapper
        return mock_mod, mock_wrapper

    def test_make_flow_two_step(self, mock_module):
        mock_mod, mock_wrapper = mock_module
        mock_wrapper.return_value = "wrapped_func"

        with patch('paymcp.payment.flows.import_module', return_value=mock_mod) as mock_import:
            wrapper_factory = make_flow("two_step")

            # Verify import was called correctly
            mock_import.assert_called_once_with(".two_step", "paymcp.payment.flows")

            # Test the wrapper factory
            mock_func = Mock()
            mock_mcp = Mock()
            mock_provider = Mock()
            mock_price_info = {"amount": 10, "currency": "USD"}

            result = wrapper_factory(mock_func, mock_mcp, mock_provider, mock_price_info)

            mock_wrapper.assert_called_once_with(
                func=mock_func,
                mcp=mock_mcp,
                provider=mock_provider,
                price_info=mock_price_info
            )
            assert result == "wrapped_func"

    def test_make_flow_progress(self, mock_module):
        mock_mod, mock_wrapper = mock_module
        mock_wrapper.return_value = "progress_wrapper"

        with patch('paymcp.payment.flows.import_module', return_value=mock_mod) as mock_import:
            wrapper_factory = make_flow("progress")

            mock_import.assert_called_once_with(".progress", "paymcp.payment.flows")

            # Test wrapper factory functionality
            result = wrapper_factory(Mock(), Mock(), Mock(), {})
            assert result == "progress_wrapper"

    def test_make_flow_elicitation(self, mock_module):
        mock_mod, mock_wrapper = mock_module
        mock_wrapper.return_value = "elicitation_wrapper"

        with patch('paymcp.payment.flows.import_module', return_value=mock_mod) as mock_import:
            wrapper_factory = make_flow("elicitation")

            mock_import.assert_called_once_with(".elicitation", "paymcp.payment.flows")

            result = wrapper_factory(Mock(), Mock(), Mock(), {})
            assert result == "elicitation_wrapper"

    def test_make_flow_oob(self, mock_module):
        mock_mod, mock_wrapper = mock_module

        with patch('paymcp.payment.flows.import_module', return_value=mock_mod) as mock_import:
            wrapper_factory = make_flow("oob")

            mock_import.assert_called_once_with(".oob", "paymcp.payment.flows")
            assert callable(wrapper_factory)

    def test_make_flow_unknown_flow(self):
        with patch('src.paymcp.payment.flows.import_module', side_effect=ModuleNotFoundError()):
            with pytest.raises(ValueError, match="Unknown payment flow: nonexistent"):
                make_flow("nonexistent")

    def test_make_flow_module_missing_make_paid_wrapper(self):
        mock_mod = MagicMock()
        # Remove make_paid_wrapper attribute
        del mock_mod.make_paid_wrapper

        with patch('paymcp.payment.flows.import_module', return_value=mock_mod):
            with pytest.raises(AttributeError):
                wrapper_factory = make_flow("broken")
                # Try to use the wrapper factory
                wrapper_factory(Mock(), Mock(), Mock(), {})

    def test_make_flow_wrapper_factory_preserves_arguments(self, mock_module):
        mock_mod, mock_wrapper = mock_module

        with patch('paymcp.payment.flows.import_module', return_value=mock_mod):
            wrapper_factory = make_flow("test_flow")

            # Test with specific arguments
            func = Mock(name="test_func")
            mcp = Mock(name="test_mcp")
            provider = Mock(name="test_provider")
            price_info = {"amount": 99.99, "currency": "EUR", "description": "Test"}

            wrapper_factory(func, mcp, provider, price_info)

            # Verify exact arguments were passed
            call_args = mock_wrapper.call_args
            assert call_args.kwargs["func"] is func
            assert call_args.kwargs["mcp"] is mcp
            assert call_args.kwargs["provider"] is provider
            assert call_args.kwargs["price_info"] is price_info

    def test_make_flow_multiple_calls_same_flow(self, mock_module):
        mock_mod, mock_wrapper = mock_module

        with patch('paymcp.payment.flows.import_module', return_value=mock_mod) as mock_import:
            # Get wrapper factory twice for same flow
            wrapper_factory1 = make_flow("two_step")
            wrapper_factory2 = make_flow("two_step")

            # Both should import the module
            assert mock_import.call_count == 2

            # Both should be functional
            wrapper_factory1(Mock(), Mock(), Mock(), {})
            wrapper_factory2(Mock(), Mock(), Mock(), {})
            assert mock_wrapper.call_count == 2

    def test_make_flow_different_flows(self):
        mock_mod1 = MagicMock()
        mock_mod1.make_paid_wrapper = Mock(return_value="wrapper1")

        mock_mod2 = MagicMock()
        mock_mod2.make_paid_wrapper = Mock(return_value="wrapper2")

        with patch('paymcp.payment.flows.import_module') as mock_import:
            mock_import.side_effect = [mock_mod1, mock_mod2]

            wrapper1 = make_flow("two_step")
            wrapper2 = make_flow("elicitation")

            result1 = wrapper1(Mock(), Mock(), Mock(), {})
            result2 = wrapper2(Mock(), Mock(), Mock(), {})

            assert result1 == "wrapper1"
            assert result2 == "wrapper2"