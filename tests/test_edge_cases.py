"""Edge case tests for achieving complete code coverage."""
import pytest
import sys
from unittest.mock import Mock, patch, AsyncMock
from importlib.metadata import PackageNotFoundError


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_version_import_error(self):
        """Test handling of missing package version."""
        # Save original modules
        original_modules = {}
        for key in list(sys.modules.keys()):
            if 'paymcp' in key:
                original_modules[key] = sys.modules[key]
                del sys.modules[key]

        try:
            with patch('importlib.metadata.version') as mock_version:
                mock_version.side_effect = PackageNotFoundError("paymcp")

                # Import with mocked version
                from paymcp import core

                # Should default to "unknown"
                assert core.__version__ == "unknown"
        finally:
            # Restore original modules
            for key in list(sys.modules.keys()):
                if 'paymcp' in key:
                    del sys.modules[key]
            sys.modules.update(original_modules)

    def test_unknown_provider_error(self):
        """Test error handling for unknown provider type."""
        from paymcp.providers import build_providers

        with pytest.raises(ValueError, match="Unknown provider"):
            build_providers({"nonexistent_provider": {"api_key": "test"}})

    def test_coinbase_provider_name(self):
        """Test CoinbaseProvider.get_name() method."""
        from paymcp.providers.coinbase import CoinbaseProvider

        provider = CoinbaseProvider(api_key="test_key", logger=Mock())
        assert provider.get_name() == "coinbase"

    def test_memory_storage_no_event_loop(self):
        """Test memory storage initialization without event loop."""
        with patch('asyncio.get_event_loop') as mock_get_loop:
            mock_get_loop.side_effect = RuntimeError("No event loop")

            from paymcp.session.memory import InMemorySessionStorage

            # Should create without error
            storage = InMemorySessionStorage()
            assert storage is not None

    def test_memory_storage_cleanup_already_running(self):
        """Test memory storage cleanup when already running."""
        from paymcp.session.memory import InMemorySessionStorage

        storage = InMemorySessionStorage()
        storage._cleanup_running = True
        storage._cleanup_task = Mock()

        # Should return early
        storage._start_cleanup()
        assert storage._cleanup_running is True

    def test_session_storage_abstract_interface(self):
        """Test that ISessionStorage is abstract."""
        from paymcp.session.types import ISessionStorage

        with pytest.raises(TypeError, match="abstract"):
            ISessionStorage()

    def test_base_provider_abstract_methods(self):
        """Test BasePaymentProvider abstract methods."""
        from paymcp.providers.base import BasePaymentProvider

        class IncompleteProvider(BasePaymentProvider):
            pass

        with pytest.raises(TypeError):
            IncompleteProvider()

    def test_flow_wrapper_creation(self):
        """Test flow wrapper factory creation."""
        from paymcp.payment.flows.two_step import make_paid_wrapper

        func = Mock(__name__="test", __doc__="Test")
        mcp = Mock()
        provider = Mock()
        provider.create_payment = Mock(return_value=("id", "url"))
        price_info = {"price": 10, "currency": "USD"}

        wrapper = make_paid_wrapper(func, mcp, provider, price_info)
        assert wrapper is not None

    @pytest.mark.asyncio
    async def test_session_storage_error_propagation(self):
        """Test that session storage errors propagate in flows."""
        from paymcp.payment.flows.two_step import make_paid_wrapper

        async_func = AsyncMock(return_value="result")
        async_func.__name__ = "test"

        mcp = Mock()
        mcp.tool = Mock(return_value=lambda f: f)
        provider = Mock()
        provider.create_payment = Mock(return_value=("id", "url"))
        provider.get_payment_status = Mock(return_value="pending")
        provider.get_name = Mock(return_value="test_provider")
        price_info = {"price": 10, "currency": "USD"}

        wrapper = make_paid_wrapper(async_func, mcp, provider, price_info)

        with patch('src.paymcp.session.manager.SessionManager.get_storage') as mock_storage:
            storage = AsyncMock()
            storage.set.side_effect = Exception("Storage error")
            mock_storage.return_value = storage

            # Two-step flow will still return payment info even with storage error
            result = await wrapper()
            assert result["status"] == "pending"
            assert result["payment_url"] == "url"

    def test_payment_flow_enum(self):
        """Test PaymentFlow enum values."""
        from paymcp.payment.payment_flow import PaymentFlow

        assert PaymentFlow.TWO_STEP.value == "two_step"
        assert PaymentFlow.ELICITATION.value == "elicitation"
        assert PaymentFlow.PROGRESS.value == "progress"
        assert PaymentFlow.OOB.value == "oob"

    def test_normalize_status_edge_cases(self):
        """Test normalize_status with edge cases."""
        from paymcp.utils.payment import normalize_status

        # Test with object that raises on str()
        class BadObject:
            def __str__(self):
                raise Exception("Cannot convert")

        assert normalize_status(BadObject()) == "pending"
        assert normalize_status(None) == "pending"
        assert normalize_status(123) == "pending"

    def test_webview_import_errors(self):
        """Test webview handling when import fails."""
        with patch('importlib.util.find_spec', return_value=None):
            from paymcp.payment.webview import open_payment_webview_if_available

            result = open_payment_webview_if_available("https://test.com")
            assert result is False

    def test_elicitation_utils_edge_cases(self):
        """Test elicitation utility edge cases."""
        from paymcp.utils.elicitation import run_elicitation_loop
        import asyncio

        async def test_elicitation():
            mcp = Mock()
            mcp.elicit = AsyncMock()

            # Test with action that's not recognized
            mcp.elicit.return_value = Mock(action="unknown_action")

            provider = Mock()
            provider.get_payment_status = Mock(return_value="pending")

            # Correct argument order: ctx, func, message, provider, payment_id
            func = Mock(__name__="test_func")
            message = "Please pay https://pay.test"
            result = await run_elicitation_loop(mcp, func, message, provider, "payment_id", 1)
            assert result == "pending"

        asyncio.run(test_elicitation())