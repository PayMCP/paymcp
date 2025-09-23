import pytest
from unittest.mock import Mock, patch, MagicMock
import logging
from paymcp.providers.adyen import AdyenProvider


class TestAdyenProvider:
    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def adyen_provider(self, mock_logger):
        provider = AdyenProvider(
            api_key="test_api_key",
            merchant_account="test_merchant",
            return_url="https://test.com/return",
            sandbox=True,
            logger=mock_logger,
        )
        provider._request = Mock()
        return provider

    def test_init_sandbox_mode(self, mock_logger):
        provider = AdyenProvider(
            api_key="test_key",
            merchant_account="merchant123",
            logger=mock_logger,
            sandbox=True,
        )
        assert provider.api_key == "test_key"
        assert provider.merchant_account == "merchant123"
        assert provider.return_url == "https://yoururl.com/return"
        assert provider.base_url == "https://checkout-test.adyen.com/v71"
        mock_logger.debug.assert_called_with("Adyen ready")

    def test_init_production_mode(self, mock_logger):
        provider = AdyenProvider(
            api_key="prod_key",
            merchant_account="merchant456",
            logger=mock_logger,
            sandbox=False,
        )
        assert provider.base_url == "https://checkout-live.adyen.com/v71"

    def test_init_with_apiKey_fallback(self, mock_logger):
        provider = AdyenProvider(
            apiKey="fallback_key", merchant_account="merchant789", logger=mock_logger
        )
        assert provider.api_key == "fallback_key"

    def test_init_custom_return_url(self, mock_logger):
        provider = AdyenProvider(
            api_key="test_key",
            merchant_account="merchant",
            return_url="https://custom.com/payment-complete",
            logger=mock_logger,
        )
        assert provider.return_url == "https://custom.com/payment-complete"

    def test_get_name(self, adyen_provider):
        assert adyen_provider.get_name() == "adyen"

    def test_build_headers(self, adyen_provider):
        headers = adyen_provider._build_headers()
        assert headers == {
            "X-API-Key": "test_api_key",
            "Content-Type": "application/json",
        }

    def test_create_payment_success(self, adyen_provider, mock_logger):
        mock_response = {
            "id": "LINK123ABC",
            "url": "https://checkout-test.adyen.com/v71/payByLink/LINK123ABC",
            "status": "active",
            "expiresAt": "2024-12-31T23:59:59Z",
        }
        adyen_provider._request.return_value = mock_response

        link_id, payment_url = adyen_provider.create_payment(
            amount=75.50, currency="USD", description="Test Payment"
        )

        assert link_id == "LINK123ABC"
        assert payment_url == "https://checkout-test.adyen.com/v71/payByLink/LINK123ABC"

        expected_data = {
            "amount": {"currency": "USD", "value": 7550},
            "reference": "Test Payment",
            "merchantAccount": "test_merchant",
            "returnUrl": "https://test.com/return",
        }

        adyen_provider._request.assert_called_once_with(
            "POST", "https://checkout-test.adyen.com/v71/paymentLinks", expected_data
        )
        mock_logger.debug.assert_called_with(
            "Creating Adyen payment: 75.5 USD for 'Test Payment'"
        )

    def test_create_payment_different_currencies(self, adyen_provider):
        mock_response = {"id": "LINK456", "url": "https://adyen.com/pay/LINK456"}
        adyen_provider._request.return_value = mock_response

        adyen_provider.create_payment(100.00, "eur", "Euro Payment")

        call_data = adyen_provider._request.call_args[0][2]
        assert call_data["amount"]["currency"] == "EUR"
        assert call_data["amount"]["value"] == 10000

    def test_create_payment_zero_amount(self, adyen_provider):
        mock_response = {"id": "LINK789", "url": "https://adyen.com/pay/LINK789"}
        adyen_provider._request.return_value = mock_response

        adyen_provider.create_payment(0, "USD", "Free Item")

        call_data = adyen_provider._request.call_args[0][2]
        assert call_data["amount"]["value"] == 0

    def test_create_payment_fractional_cents(self, adyen_provider):
        mock_response = {"id": "LINK999", "url": "https://adyen.com/pay/LINK999"}
        adyen_provider._request.return_value = mock_response

        adyen_provider.create_payment(12.999, "USD", "Fractional")

        call_data = adyen_provider._request.call_args[0][2]
        assert call_data["amount"]["value"] == 1299

    def test_create_payment_large_amount(self, adyen_provider):
        mock_response = {"id": "LINKBIG", "url": "https://adyen.com/pay/LINKBIG"}
        adyen_provider._request.return_value = mock_response

        adyen_provider.create_payment(999999.99, "USD", "Large Payment")

        call_data = adyen_provider._request.call_args[0][2]
        assert call_data["amount"]["value"] == 99999999

    def test_create_payment_request_exception(self, adyen_provider):
        adyen_provider._request.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            adyen_provider.create_payment(100, "USD", "Test")

    def test_get_payment_status_completed(self, adyen_provider, mock_logger):
        mock_response = {
            "id": "LINK123",
            "status": "completed",
            "amount": {"currency": "USD", "value": 5000},
        }
        adyen_provider._request.return_value = mock_response

        status = adyen_provider.get_payment_status("LINK123")

        assert status == "paid"
        adyen_provider._request.assert_called_once_with(
            "GET", "https://checkout-test.adyen.com/v71/paymentLinks/LINK123"
        )
        mock_logger.debug.assert_called_with(
            "Checking Adyen payment status for: %s", "LINK123"
        )

    def test_get_payment_status_active(self, adyen_provider):
        mock_response = {"id": "LINK456", "status": "active"}
        adyen_provider._request.return_value = mock_response

        status = adyen_provider.get_payment_status("LINK456")
        assert status == "pending"

    def test_get_payment_status_expired(self, adyen_provider):
        mock_response = {"id": "LINK789", "status": "expired"}
        adyen_provider._request.return_value = mock_response

        status = adyen_provider.get_payment_status("LINK789")
        assert status == "failed"

    def test_get_payment_status_other(self, adyen_provider):
        mock_response = {"id": "LINK999", "status": "paymentPending"}
        adyen_provider._request.return_value = mock_response

        status = adyen_provider.get_payment_status("LINK999")
        assert status == "paymentPending"

    def test_get_payment_status_missing_status(self, adyen_provider):
        mock_response = {"id": "LINK_NO_STATUS"}
        adyen_provider._request.return_value = mock_response

        status = adyen_provider.get_payment_status("LINK_NO_STATUS")
        assert status == "unknown"

    def test_get_payment_status_none_status(self, adyen_provider):
        mock_response = {"id": "LINK_NONE", "status": None}
        adyen_provider._request.return_value = mock_response

        status = adyen_provider.get_payment_status("LINK_NONE")
        assert status == "unknown"

    def test_get_payment_status_request_exception(self, adyen_provider):
        adyen_provider._request.side_effect = Exception("Network Error")

        with pytest.raises(Exception, match="Network Error"):
            adyen_provider.get_payment_status("LINK_ERROR")
