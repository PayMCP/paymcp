import pytest
from unittest.mock import Mock, patch, MagicMock
import logging
from paymcp.providers.walleot import WalleotProvider, BASE_URL


class TestWalleotProvider:
    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def walleot_provider(self, mock_logger):
        provider = WalleotProvider(
            api_key="test_api_key",
            logger=mock_logger
        )
        provider._request = Mock()
        return provider

    def test_init_with_api_key(self, mock_logger):
        provider = WalleotProvider(api_key="test_key", logger=mock_logger)
        assert provider.api_key == "test_key"
        mock_logger.debug.assert_called_with("Walleot ready")

    def test_init_with_apiKey_fallback(self, mock_logger):
        provider = WalleotProvider(apiKey="fallback_key", logger=mock_logger)
        assert provider.api_key == "fallback_key"
        mock_logger.debug.assert_called_with("Walleot ready")

    def test_init_no_api_key(self, mock_logger):
        provider = WalleotProvider(logger=mock_logger)
        assert provider.api_key is None
        mock_logger.debug.assert_called_with("Walleot ready")

    def test_get_name(self, walleot_provider):
        assert walleot_provider.get_name() == "walleot"

    def test_build_headers(self, walleot_provider):
        headers = walleot_provider._build_headers()
        assert headers == {
            "Authorization": "Bearer test_api_key",
            "Content-Type": "application/json"
        }

    def test_build_headers_no_api_key(self, mock_logger):
        provider = WalleotProvider(logger=mock_logger)
        headers = provider._build_headers()
        assert headers == {
            "Authorization": "Bearer None",
            "Content-Type": "application/json"
        }

    def test_create_payment_success(self, walleot_provider, mock_logger):
        mock_response = {
            "sessionId": "SESSION123",
            "url": "https://pay.walleot.com/session/SESSION123",
            "status": "pending",
            "amount": 10000,
            "currency": "usd"
        }
        walleot_provider._request.return_value = mock_response

        session_id, session_url = walleot_provider.create_payment(
            amount=100.00,
            currency="USD",
            description="Test Payment"
        )

        assert session_id == "SESSION123"
        assert session_url == "https://pay.walleot.com/session/SESSION123"

        expected_data = {
            "amount": 10000,
            "currency": "usd",
            "description": "Test Payment"
        }

        walleot_provider._request.assert_called_once_with(
            "POST",
            f"{BASE_URL}/sessions",
            expected_data
        )
        mock_logger.debug.assert_called_with(
            "Creating Walleot payment session: 100.0 USD for 'Test Payment'"
        )

    def test_create_payment_different_currencies(self, walleot_provider):
        mock_response = {
            "sessionId": "SESSION456",
            "url": "https://pay.walleot.com/session/SESSION456"
        }
        walleot_provider._request.return_value = mock_response

        walleot_provider.create_payment(50.00, "EUR", "Euro Payment")

        call_data = walleot_provider._request.call_args[0][2]
        assert call_data["currency"] == "eur"
        assert call_data["amount"] == 5000

    def test_create_payment_zero_amount(self, walleot_provider):
        mock_response = {
            "sessionId": "SESSION789",
            "url": "https://pay.walleot.com/session/SESSION789"
        }
        walleot_provider._request.return_value = mock_response

        walleot_provider.create_payment(0, "USD", "Free Item")

        call_data = walleot_provider._request.call_args[0][2]
        assert call_data["amount"] == 0

    def test_create_payment_fractional_cents(self, walleot_provider):
        mock_response = {
            "sessionId": "SESSION999",
            "url": "https://pay.walleot.com/session/SESSION999"
        }
        walleot_provider._request.return_value = mock_response

        walleot_provider.create_payment(10.999, "USD", "Fractional")

        call_data = walleot_provider._request.call_args[0][2]
        assert call_data["amount"] == 1099

    def test_create_payment_large_amount(self, walleot_provider):
        mock_response = {
            "sessionId": "SESSION_BIG",
            "url": "https://pay.walleot.com/session/SESSION_BIG"
        }
        walleot_provider._request.return_value = mock_response

        walleot_provider.create_payment(999999.99, "USD", "Large Payment")

        call_data = walleot_provider._request.call_args[0][2]
        assert call_data["amount"] == 99999999

    def test_create_payment_uppercase_currency(self, walleot_provider):
        mock_response = {
            "sessionId": "SESSION_UP",
            "url": "https://pay.walleot.com/session/SESSION_UP"
        }
        walleot_provider._request.return_value = mock_response

        walleot_provider.create_payment(25.00, "GBP", "GBP Payment")

        call_data = walleot_provider._request.call_args[0][2]
        assert call_data["currency"] == "gbp"

    def test_create_payment_request_exception(self, walleot_provider):
        walleot_provider._request.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            walleot_provider.create_payment(100, "USD", "Test")

    def test_get_payment_status_paid(self, walleot_provider, mock_logger):
        mock_response = {
            "sessionId": "SESSION123",
            "status": "PAID",
            "amount": 10000,
            "currency": "usd"
        }
        walleot_provider._request.return_value = mock_response

        status = walleot_provider.get_payment_status("SESSION123")

        assert status == "paid"
        walleot_provider._request.assert_called_once_with(
            "GET",
            f"{BASE_URL}/sessions/SESSION123"
        )
        mock_logger.debug.assert_called_with(
            "Checking walleot payment status for: %s", "SESSION123"
        )

    def test_get_payment_status_pending(self, walleot_provider):
        mock_response = {
            "sessionId": "SESSION456",
            "status": "PENDING"
        }
        walleot_provider._request.return_value = mock_response

        status = walleot_provider.get_payment_status("SESSION456")
        assert status == "pending"

    def test_get_payment_status_cancelled(self, walleot_provider):
        mock_response = {
            "sessionId": "SESSION789",
            "status": "CANCELLED"
        }
        walleot_provider._request.return_value = mock_response

        status = walleot_provider.get_payment_status("SESSION789")
        assert status == "cancelled"

    def test_get_payment_status_mixed_case(self, walleot_provider):
        mock_response = {
            "sessionId": "SESSION999",
            "status": "Completed"
        }
        walleot_provider._request.return_value = mock_response

        status = walleot_provider.get_payment_status("SESSION999")
        assert status == "completed"

    def test_get_payment_status_request_exception(self, walleot_provider):
        walleot_provider._request.side_effect = Exception("Network Error")

        with pytest.raises(Exception, match="Network Error"):
            walleot_provider.get_payment_status("SESSION_ERROR")