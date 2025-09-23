import pytest
from unittest.mock import Mock, patch, MagicMock
import logging
from paymcp.providers.stripe import StripeProvider, BASE_URL


class TestStripeProvider:
    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def stripe_provider(self, mock_logger):
        provider = StripeProvider(
            api_key="test_api_key",
            success_url="https://test.com/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://test.com/cancel",
            logger=mock_logger,
        )
        provider._request = Mock()
        return provider

    def test_init_with_api_key(self, mock_logger):
        provider = StripeProvider(api_key="test_key", logger=mock_logger)
        assert provider.api_key == "test_key"
        assert (
            provider.success_url
            == "https://yoururl.com/success?session_id={CHECKOUT_SESSION_ID}"
        )
        assert provider.cancel_url == "https://yoururl.com/cancel"
        mock_logger.debug.assert_called_with("Stripe ready")

    def test_init_with_apiKey_fallback(self, mock_logger):
        provider = StripeProvider(apiKey="test_key_fallback", logger=mock_logger)
        assert provider.api_key == "test_key_fallback"
        mock_logger.debug.assert_called_with("Stripe ready")

    def test_init_custom_urls(self, mock_logger):
        provider = StripeProvider(
            api_key="test_key",
            success_url="https://custom.com/success",
            cancel_url="https://custom.com/cancel",
            logger=mock_logger,
        )
        assert provider.success_url == "https://custom.com/success"
        assert provider.cancel_url == "https://custom.com/cancel"

    def test_get_name(self, stripe_provider):
        assert stripe_provider.get_name() == "stripe"
    def test_create_payment_success(self, stripe_provider, mock_logger):
        mock_response = {
            "id": "cs_test_123",
            "url": "https://checkout.stripe.com/pay/cs_test_123",
        }
        stripe_provider._request.return_value = mock_response

        session_id, session_url = stripe_provider.create_payment(
            amount=100.50, currency="USD", description="Test Payment"
        )

        assert session_id == "cs_test_123"
        assert session_url == "https://checkout.stripe.com/pay/cs_test_123"

        expected_data = {
            "mode": "payment",
            "success_url": stripe_provider.success_url,
            "cancel_url": stripe_provider.cancel_url,
            "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][unit_amount]": 10050,
            "line_items[0][price_data][product_data][name]": "Test Payment",
            "line_items[0][quantity]": 1,
        }

        stripe_provider._request.assert_called_once_with(
            "POST", f"{BASE_URL}/checkout/sessions", expected_data
        )
        mock_logger.debug.assert_called_with(
            "Creating Stripe payment: 100.5 USD for 'Test Payment'"
        )

    def test_create_payment_different_currencies(self, stripe_provider):
        mock_response = {"id": "cs_test", "url": "https://stripe.com/pay"}
        stripe_provider._request.return_value = mock_response

        stripe_provider.create_payment(50.00, "EUR", "Euro payment")

        call_args = stripe_provider._request.call_args[0]
        data = stripe_provider._request.call_args[0][2]
        assert data["line_items[0][price_data][currency]"] == "eur"
        assert data["line_items[0][price_data][unit_amount]"] == 5000

    def test_create_payment_zero_amount(self, stripe_provider):
        mock_response = {"id": "cs_test", "url": "https://stripe.com/pay"}
        stripe_provider._request.return_value = mock_response

        stripe_provider.create_payment(0, "USD", "Free item")

        data = stripe_provider._request.call_args[0][2]
        assert data["line_items[0][price_data][unit_amount]"] == 0

    def test_create_payment_fractional_cents(self, stripe_provider):
        mock_response = {"id": "cs_test", "url": "https://stripe.com/pay"}
        stripe_provider._request.return_value = mock_response

        stripe_provider.create_payment(10.999, "USD", "Fractional payment")

        data = stripe_provider._request.call_args[0][2]
        assert data["line_items[0][price_data][unit_amount]"] == 1099

    def test_get_payment_status_paid(self, stripe_provider, mock_logger):
        mock_response = {"id": "cs_test_123", "payment_status": "paid"}
        stripe_provider._request.return_value = mock_response

        status = stripe_provider.get_payment_status("cs_test_123")

        assert status == "paid"
        stripe_provider._request.assert_called_once_with(
            "GET", f"{BASE_URL}/checkout/sessions/cs_test_123"
        )
        mock_logger.debug.assert_called_with(
            "Checking Stripe payment status for: %s", "cs_test_123"
        )

    def test_get_payment_status_unpaid(self, stripe_provider):
        mock_response = {"id": "cs_test_456", "payment_status": "unpaid"}
        stripe_provider._request.return_value = mock_response

        status = stripe_provider.get_payment_status("cs_test_456")

        assert status == "unpaid"

    def test_get_payment_status_no_payment_required(self, stripe_provider):
        mock_response = {"id": "cs_test_789", "payment_status": "no_payment_required"}
        stripe_provider._request.return_value = mock_response

        status = stripe_provider.get_payment_status("cs_test_789")

        assert status == "no_payment_required"

    def test_create_payment_request_exception(self, stripe_provider):
        stripe_provider._request.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            stripe_provider.create_payment(100, "USD", "Test")

    def test_get_payment_status_request_exception(self, stripe_provider):
        stripe_provider._request.side_effect = Exception("Network Error")

        with pytest.raises(Exception, match="Network Error"):
            stripe_provider.get_payment_status("cs_test_error")
