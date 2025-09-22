import pytest
from unittest.mock import Mock, patch, MagicMock
import logging
import requests
from paymcp.providers.paypal import PayPalProvider


class TestPayPalProvider:
    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def mock_token_response(self):
        mock_resp = Mock()
        mock_resp.json.return_value = {"access_token": "test_token_12345"}
        mock_resp.raise_for_status = Mock()
        return mock_resp

    @pytest.fixture
    def paypal_provider(self, mock_logger, mock_token_response):
        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_token_response):
            provider = PayPalProvider(
                client_id="test_client_id",
                client_secret="test_client_secret",
                logger=mock_logger,
                success_url="https://test.com/success",
                cancel_url="https://test.com/cancel",
                sandbox=True
            )
            return provider

    def test_init_sandbox_mode(self, mock_logger, mock_token_response):
        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_token_response):
            provider = PayPalProvider(
                client_id="test_client",
                client_secret="test_secret",
                logger=mock_logger,
                sandbox=True
            )
            assert provider.base_url == "https://api-m.sandbox.paypal.com"
            assert provider._token == "test_token_12345"
            mock_logger.debug.assert_called_with("PayPal ready")

    def test_init_production_mode(self, mock_logger, mock_token_response):
        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_token_response):
            provider = PayPalProvider(
                client_id="test_client",
                client_secret="test_secret",
                logger=mock_logger,
                sandbox=False
            )
            assert provider.base_url == "https://api-m.paypal.com"

    def test_init_custom_urls(self, mock_logger, mock_token_response):
        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_token_response):
            provider = PayPalProvider(
                client_id="test_client",
                client_secret="test_secret",
                logger=mock_logger,
                success_url="https://custom.com/ok",
                cancel_url="https://custom.com/no",
                sandbox=True
            )
            assert provider.success_url == "https://custom.com/ok"
            assert provider.cancel_url == "https://custom.com/no"

    def test_get_name(self, paypal_provider):
        assert paypal_provider.get_name() == "paypal"

    def test_get_token_success(self, mock_logger):
        mock_resp = Mock()
        mock_resp.json.return_value = {"access_token": "new_token_abc"}
        mock_resp.raise_for_status = Mock()

        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_resp):
            provider = PayPalProvider(
                client_id="client",
                client_secret="secret",
                logger=mock_logger
            )
            assert provider._token == "new_token_abc"

    def test_get_token_failure(self, mock_logger):
        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")

        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                PayPalProvider(
                    client_id="bad_client",
                    client_secret="bad_secret",
                    logger=mock_logger
                )

    def test_create_payment_success(self, paypal_provider, mock_logger):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "id": "ORDER123",
            "links": [
                {"rel": "self", "href": "https://api.paypal.com/v2/checkout/orders/ORDER123"},
                {"rel": "approve", "href": "https://www.paypal.com/checkoutnow?token=ORDER123"},
                {"rel": "update", "href": "https://api.paypal.com/v2/checkout/orders/ORDER123"}
            ]
        }
        mock_resp.raise_for_status = Mock()

        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_resp) as mock_post:
            order_id, approval_url = paypal_provider.create_payment(
                amount=99.99,
                currency="USD",
                description="Test Product"
            )

            assert order_id == "ORDER123"
            assert approval_url == "https://www.paypal.com/checkoutnow?token=ORDER123"

            expected_headers = {"Authorization": "Bearer test_token_12345"}
            expected_payload = {
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {"currency_code": "USD", "value": "99.99"},
                    "description": "Test Product"
                }],
                "application_context": {
                    "return_url": "https://test.com/success",
                    "cancel_url": "https://test.com/cancel",
                    "user_action": "PAY_NOW"
                }
            }

            mock_post.assert_called_with(
                "https://api-m.sandbox.paypal.com/v2/checkout/orders",
                headers=expected_headers,
                json=expected_payload
            )
            mock_logger.debug.assert_called_with(
                "Creating PayPal payment: 99.99 USD for 'Test Product'"
            )

    def test_create_payment_different_currencies(self, paypal_provider):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "id": "ORDER456",
            "links": [{"rel": "approve", "href": "https://paypal.com/pay"}]
        }
        mock_resp.raise_for_status = Mock()

        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_resp) as mock_post:
            paypal_provider.create_payment(50.00, "EUR", "Euro Payment")

            call_payload = mock_post.call_args.kwargs['json']
            assert call_payload["purchase_units"][0]["amount"]["currency_code"] == "EUR"
            assert call_payload["purchase_units"][0]["amount"]["value"] == "50.00"

    def test_create_payment_formatting(self, paypal_provider):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "id": "ORDER789",
            "links": [{"rel": "approve", "href": "https://paypal.com/pay"}]
        }
        mock_resp.raise_for_status = Mock()

        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_resp) as mock_post:
            paypal_provider.create_payment(10.5, "USD", "Test")

            call_payload = mock_post.call_args.kwargs['json']
            assert call_payload["purchase_units"][0]["amount"]["value"] == "10.50"

    def test_create_payment_http_error(self, paypal_provider):
        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")

        with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                paypal_provider.create_payment(100, "USD", "Test")

    def test_get_payment_status_completed(self, paypal_provider, mock_logger):
        mock_resp = Mock()
        mock_resp.json.return_value = {"status": "COMPLETED"}
        mock_resp.raise_for_status = Mock()

        with patch('src.paymcp.providers.paypal.requests.get', return_value=mock_resp):
            status = paypal_provider.get_payment_status("ORDER123")

            assert status == "paid"
            mock_logger.debug.assert_called_with("Checking PayPal payment status for: ORDER123")

    def test_get_payment_status_approved_capture_success(self, paypal_provider, mock_logger):
        mock_get_resp = Mock()
        mock_get_resp.json.return_value = {"status": "APPROVED"}
        mock_get_resp.raise_for_status = Mock()

        mock_capture_resp = Mock()
        mock_capture_resp.json.return_value = {"status": "COMPLETED"}
        mock_capture_resp.raise_for_status = Mock()

        with patch('src.paymcp.providers.paypal.requests.get', return_value=mock_get_resp):
            with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_capture_resp) as mock_post:
                status = paypal_provider.get_payment_status("ORDER456")

                assert status == "paid"
                mock_logger.debug.assert_any_call("Checking PayPal payment status for: ORDER456")
                mock_logger.debug.assert_any_call("Auto-capturing payment: ORDER456")

                mock_post.assert_called_with(
                    "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER456/capture",
                    headers={"Authorization": "Bearer test_token_12345"},
                    json={}
                )

    def test_get_payment_status_approved_capture_pending(self, paypal_provider):
        mock_get_resp = Mock()
        mock_get_resp.json.return_value = {"status": "APPROVED"}
        mock_get_resp.raise_for_status = Mock()

        mock_capture_resp = Mock()
        mock_capture_resp.json.return_value = {"status": "PENDING"}
        mock_capture_resp.raise_for_status = Mock()

        with patch('src.paymcp.providers.paypal.requests.get', return_value=mock_get_resp):
            with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_capture_resp):
                status = paypal_provider.get_payment_status("ORDER789")
                assert status == "pending"

    def test_get_payment_status_approved_capture_failure(self, paypal_provider, mock_logger):
        mock_get_resp = Mock()
        mock_get_resp.json.return_value = {"status": "APPROVED"}
        mock_get_resp.raise_for_status = Mock()

        mock_capture_resp = Mock()
        mock_capture_resp.raise_for_status.side_effect = requests.HTTPError("422 Unprocessable Entity")

        with patch('src.paymcp.providers.paypal.requests.get', return_value=mock_get_resp):
            with patch('src.paymcp.providers.paypal.requests.post', return_value=mock_capture_resp):
                status = paypal_provider.get_payment_status("ORDER_FAIL")

                assert status == "pending"
                mock_logger.error.assert_called()
                error_call_args = mock_logger.error.call_args[0][0]
                assert "Capture failed for ORDER_FAIL" in error_call_args

    def test_get_payment_status_other_status(self, paypal_provider):
        mock_resp = Mock()
        mock_resp.json.return_value = {"status": "VOIDED"}
        mock_resp.raise_for_status = Mock()

        with patch('src.paymcp.providers.paypal.requests.get', return_value=mock_resp):
            status = paypal_provider.get_payment_status("ORDER_VOID")
            assert status == "pending"

    def test_get_payment_status_http_error(self, paypal_provider):
        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch('src.paymcp.providers.paypal.requests.get', return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                paypal_provider.get_payment_status("NONEXISTENT")