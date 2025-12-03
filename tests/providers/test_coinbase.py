import pytest
from unittest.mock import Mock, patch, MagicMock
import logging
from paymcp.providers.coinbase import CoinbaseProvider, BASE_URL


class TestCoinbaseProvider:
    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def coinbase_provider(self, mock_logger):
        provider = CoinbaseProvider(
            api_key="test_api_key",
            success_url="https://test.com/success",
            cancel_url="https://test.com/cancel",
            logger=mock_logger,
            confirm_on_pending=False,
        )
        provider._request = Mock()
        return provider

    def test_init_with_api_key(self, mock_logger):
        provider = CoinbaseProvider(api_key="test_key", logger=mock_logger)
        assert provider.api_key == "test_key"
        assert provider.success_url == "https://paymcp.info/paymentsuccess/"
        assert provider.cancel_url == "https://paymcp.info/paymentcanceled/"
        assert provider.confirm_on_pending is False
        mock_logger.debug.assert_called_with("Coinbase Commerce ready")

    def test_init_with_apiKey_fallback(self, mock_logger):
        provider = CoinbaseProvider(apiKey="fallback_key", logger=mock_logger)
        assert provider.api_key == "fallback_key"

    def test_init_custom_urls(self, mock_logger):
        provider = CoinbaseProvider(
            api_key="test_key",
            success_url="https://custom.com/ok",
            cancel_url="https://custom.com/no",
            logger=mock_logger,
        )
        assert provider.success_url == "https://custom.com/ok"
        assert provider.cancel_url == "https://custom.com/no"

    def test_init_confirm_on_pending_true(self, mock_logger):
        provider = CoinbaseProvider(
            api_key="test_key", logger=mock_logger, confirm_on_pending=True
        )
        assert provider.confirm_on_pending is True

    def test_build_headers(self, coinbase_provider):
        headers = coinbase_provider._build_headers()
        assert headers == {
            "X-CC-Api-Key": "test_api_key",
            "Content-Type": "application/json",
        }

    def test_create_payment_success(self, coinbase_provider, mock_logger):
        mock_response = {
            "data": {
                "code": "CHARGE123",
                "hosted_url": "https://commerce.coinbase.com/charges/CHARGE123",
                "pricing_type": "fixed_price",
            }
        }
        coinbase_provider._request.return_value = mock_response

        code, hosted_url = coinbase_provider.create_payment(
            amount=50.00, currency="USD", description="Test Product"
        )

        assert code == "CHARGE123"
        assert hosted_url == "https://commerce.coinbase.com/charges/CHARGE123"

        expected_data = {
            "name": "Test Product",
            "description": "Test Product",
            "pricing_type": "fixed_price",
            "local_price": {"amount": "50.00", "currency": "USD"},
            "redirect_url": "https://test.com/success",
            "cancel_url": "https://test.com/cancel",
            "metadata": {"reference": "Test Product"},
        }

        coinbase_provider._request.assert_called_once_with(
            "POST", f"{BASE_URL}/charges", expected_data
        )
        mock_logger.debug.assert_called_with(
            "Creating Coinbase charge: 50.0 USD for 'Test Product'"
        )

    def test_create_payment_usdc_to_usd(self, coinbase_provider):
        mock_response = {
            "data": {"code": "CHARGE456", "hosted_url": "https://coinbase.com/pay"}
        }
        coinbase_provider._request.return_value = mock_response

        coinbase_provider.create_payment(100.00, "USDC", "USDC Payment")

        call_data = coinbase_provider._request.call_args[0][2]
        assert call_data["local_price"]["currency"] == "USD"

    def test_create_payment_lowercase_currency(self, coinbase_provider):
        mock_response = {
            "data": {"code": "CHARGE789", "hosted_url": "https://coinbase.com/pay"}
        }
        coinbase_provider._request.return_value = mock_response

        coinbase_provider.create_payment(25.00, "eur", "Euro Payment")

        call_data = coinbase_provider._request.call_args[0][2]
        assert call_data["local_price"]["currency"] == "EUR"

    def test_create_payment_long_description_truncated(self, coinbase_provider):
        mock_response = {
            "data": {"code": "CHARGE999", "hosted_url": "https://coinbase.com/pay"}
        }
        coinbase_provider._request.return_value = mock_response

        long_desc = "A" * 150
        coinbase_provider.create_payment(10.00, "USD", long_desc)

        call_data = coinbase_provider._request.call_args[0][2]
        assert len(call_data["name"]) == 100
        assert call_data["name"] == "A" * 100
        assert call_data["description"] == long_desc

    def test_create_payment_empty_description(self, coinbase_provider):
        mock_response = {
            "data": {"code": "CHARGE_EMPTY", "hosted_url": "https://coinbase.com/pay"}
        }
        coinbase_provider._request.return_value = mock_response

        coinbase_provider.create_payment(75.50, "USD", "")

        call_data = coinbase_provider._request.call_args[0][2]
        assert call_data["name"] == "Payment"
        assert call_data["description"] == ""
        assert call_data["metadata"]["reference"] == ""

    def test_create_payment_none_description(self, coinbase_provider):
        mock_response = {
            "data": {"code": "CHARGE_NONE", "hosted_url": "https://coinbase.com/pay"}
        }
        coinbase_provider._request.return_value = mock_response

        coinbase_provider.create_payment(20.00, "USD", None)

        call_data = coinbase_provider._request.call_args[0][2]
        assert call_data["name"] == "Payment"
        assert call_data["description"] == ""

    def test_create_payment_formatting(self, coinbase_provider):
        mock_response = {
            "data": {"code": "CHARGE_FORMAT", "hosted_url": "https://coinbase.com/pay"}
        }
        coinbase_provider._request.return_value = mock_response

        coinbase_provider.create_payment(10.5, "USD", "Test")

        call_data = coinbase_provider._request.call_args[0][2]
        assert call_data["local_price"]["amount"] == "10.50"

    def test_create_payment_request_exception(self, coinbase_provider):
        coinbase_provider._request.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            coinbase_provider.create_payment(100, "USD", "Test")

    def test_get_payment_status_completed(self, coinbase_provider, mock_logger):
        mock_response = {
            "data": {
                "timeline": [
                    {"status": "NEW", "time": "2024-01-01T00:00:00Z"},
                    {"status": "PENDING", "time": "2024-01-01T00:05:00Z"},
                    {"status": "COMPLETED", "time": "2024-01-01T00:10:00Z"},
                ]
            }
        }
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE123")

        assert status == "paid"
        coinbase_provider._request.assert_called_once_with(
            "GET", f"{BASE_URL}/charges/CHARGE123"
        )
        mock_logger.debug.assert_called_with(
            "Checking Coinbase charge status for: %s", "CHARGE123"
        )

    def test_get_payment_status_resolved(self, coinbase_provider):
        mock_response = {
            "data": {"timeline": [{"status": "NEW"}, {"status": "RESOLVED"}]}
        }
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE456")
        assert status == "paid"

    def test_get_payment_status_pending_with_confirm_on_pending(self, mock_logger):
        with patch.object(CoinbaseProvider, "_request") as mock_request:
            provider = CoinbaseProvider(
                api_key="test_key", logger=mock_logger, confirm_on_pending=True
            )
            mock_request.return_value = {"data": {"timeline": [{"status": "PENDING"}]}}

            status = provider.get_payment_status("CHARGE789")
            assert status == "paid"

    def test_get_payment_status_pending_without_confirm_on_pending(
        self, coinbase_provider
    ):
        mock_response = {"data": {"timeline": [{"status": "PENDING"}]}}
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE999")
        assert status == "pending"

    def test_get_payment_status_expired(self, coinbase_provider):
        mock_response = {
            "data": {"timeline": [{"status": "NEW"}, {"status": "EXPIRED"}]}
        }
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE_EXP")
        assert status == "failed"

    def test_get_payment_status_canceled(self, coinbase_provider):
        mock_response = {"data": {"timeline": [{"status": "CANCELED"}]}}
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE_CANCEL")
        assert status == "failed"

    def test_get_payment_status_empty_timeline_with_completed_at(
        self, coinbase_provider
    ):
        mock_response = {
            "data": {"timeline": [], "completed_at": "2024-01-01T00:00:00Z"}
        }
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE_COMP")
        assert status == "paid"

    def test_get_payment_status_none_timeline_with_confirmed_at(
        self, coinbase_provider
    ):
        mock_response = {
            "data": {"timeline": None, "confirmed_at": "2024-01-01T00:00:00Z"}
        }
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE_CONF")
        assert status == "paid"

    def test_get_payment_status_empty_timeline_no_fallback(self, coinbase_provider):
        mock_response = {"data": {"timeline": []}}
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE_EMPTY")
        assert status == "pending"

    def test_get_payment_status_no_data(self, coinbase_provider):
        mock_response = {}
        coinbase_provider._request.return_value = mock_response

        status = coinbase_provider.get_payment_status("CHARGE_NODATA")
        assert status == "pending"

    def test_get_payment_status_request_exception(self, coinbase_provider):
        coinbase_provider._request.side_effect = Exception("Network Error")

        with pytest.raises(Exception, match="Network Error"):
            coinbase_provider.get_payment_status("CHARGE_ERROR")
