import pytest
from unittest.mock import Mock, patch, MagicMock
import logging
import requests
import os
from paymcp.providers.square import SquareProvider, SANDBOX_URL, PRODUCTION_URL


class TestSquareProvider:
    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def square_provider(self, mock_logger):
        provider = SquareProvider(
            access_token="test_access_token",
            location_id="test_location_id",
            logger=mock_logger,
            redirect_url="https://test.com/success",
            sandbox=True,
            api_version="2025-03-19",
        )
        return provider

    def test_init_sandbox_mode(self, mock_logger):
        provider = SquareProvider(
            access_token="token", location_id="loc123", logger=mock_logger, sandbox=True
        )
        assert provider.base_url == SANDBOX_URL
        assert provider.access_token == "token"
        assert provider.location_id == "loc123"
        assert provider.redirect_url == "https://example.com/success"
        mock_logger.debug.assert_called_with("Square ready (API version: 2025-03-19)")

    def test_init_production_mode(self, mock_logger):
        provider = SquareProvider(
            access_token="token",
            location_id="loc123",
            logger=mock_logger,
            sandbox=False,
        )
        assert provider.base_url == PRODUCTION_URL

    def test_init_custom_redirect_url(self, mock_logger):
        provider = SquareProvider(
            access_token="token",
            location_id="loc123",
            logger=mock_logger,
            redirect_url="https://custom.com/payment-success",
        )
        assert provider.redirect_url == "https://custom.com/payment-success"

    def test_init_custom_api_version(self, mock_logger):
        provider = SquareProvider(
            access_token="token",
            location_id="loc123",
            logger=mock_logger,
            api_version="2025-01-01",
        )
        assert provider.api_version == "2025-01-01"
        mock_logger.debug.assert_called_with("Square ready (API version: 2025-01-01)")

    @patch.dict(os.environ, {"SQUARE_API_VERSION": "2024-12-01"})
    def test_init_api_version_from_env(self, mock_logger):
        provider = SquareProvider(
            access_token="token", location_id="loc123", logger=mock_logger
        )
        assert provider.api_version == "2024-12-01"

    def test_get_name(self, square_provider):
        assert square_provider.get_name() == "square"

    def test_build_headers(self, square_provider):
        headers = square_provider._build_headers()
        assert headers == {
            "Authorization": "Bearer test_access_token",
            "Content-Type": "application/json",
            "Square-Version": "2025-03-19",
        }

    def test_generate_idempotency_key(self, square_provider):
        key1 = square_provider._generate_idempotency_key()
        key2 = square_provider._generate_idempotency_key()

        assert key1 != key2
        assert "-" in key1
        parts = key1.split("-")
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert len(parts[1]) == 8

    @patch("src.paymcp.providers.square.requests.post")
    def test_create_payment_success(self, mock_post, square_provider, mock_logger):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "payment_link": {
                "id": "LINK123",
                "url": "https://square.link/u/LINK123",
                "created_at": "2024-01-01T00:00:00Z",
            }
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        payment_id, payment_url = square_provider.create_payment(
            amount=49.99, currency="USD", description="Test Product"
        )

        assert payment_id == "LINK123"
        assert payment_url == "https://square.link/u/LINK123"

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == f"{SANDBOX_URL}/v2/online-checkout/payment-links"

        payload = call_args.kwargs["json"]
        assert "idempotency_key" in payload
        assert payload["quick_pay"]["name"] == "Test Product"
        assert payload["quick_pay"]["price_money"]["amount"] == 4999
        assert payload["quick_pay"]["price_money"]["currency"] == "USD"
        assert payload["quick_pay"]["location_id"] == "test_location_id"

        mock_logger.debug.assert_called_with(
            "Creating Square payment: 49.99 USD for 'Test Product'"
        )

    @patch("src.paymcp.providers.square.requests.post")
    def test_create_payment_different_currencies(self, mock_post, square_provider):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "payment_link": {"id": "LINK456", "url": "https://square.link/u/LINK456"}
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        square_provider.create_payment(25.00, "eur", "Euro Product")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["quick_pay"]["price_money"]["currency"] == "EUR"
        assert payload["quick_pay"]["price_money"]["amount"] == 2500

    @patch("src.paymcp.providers.square.requests.post")
    def test_create_payment_zero_amount(self, mock_post, square_provider):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "payment_link": {"id": "LINK789", "url": "https://square.link/u/LINK789"}
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        square_provider.create_payment(0, "USD", "Free Item")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["quick_pay"]["price_money"]["amount"] == 0

    @patch("src.paymcp.providers.square.requests.post")
    def test_create_payment_fractional_cents(self, mock_post, square_provider):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "payment_link": {"id": "LINK999", "url": "https://square.link/u/LINK999"}
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        square_provider.create_payment(10.999, "USD", "Fractional")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["quick_pay"]["price_money"]["amount"] == 1099

    @patch("src.paymcp.providers.square.requests.post")
    def test_create_payment_missing_id(self, mock_post, square_provider):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "payment_link": {"url": "https://square.link/u/TEST"}
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        with pytest.raises(
            ValueError, match="Invalid response from Square Payment Links API"
        ):
            square_provider.create_payment(50.00, "USD", "Test")

    @patch("src.paymcp.providers.square.requests.post")
    def test_create_payment_missing_url(self, mock_post, square_provider):
        mock_resp = Mock()
        mock_resp.json.return_value = {"payment_link": {"id": "LINK123"}}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        with pytest.raises(
            ValueError, match="Invalid response from Square Payment Links API"
        ):
            square_provider.create_payment(50.00, "USD", "Test")

    @patch("src.paymcp.providers.square.requests.post")
    def test_create_payment_http_error(self, mock_post, square_provider):
        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
        mock_post.return_value = mock_resp

        with pytest.raises(requests.HTTPError):
            square_provider.create_payment(100.00, "USD", "Test")

    @patch("src.paymcp.providers.square.requests.get")
    def test_get_payment_status_paid_net_zero(
        self, mock_get, square_provider, mock_logger
    ):
        # Mock payment link response
        payment_link_resp = Mock()
        payment_link_resp.json.return_value = {
            "payment_link": {"id": "LINK123", "order_id": "ORDER123"}
        }
        payment_link_resp.raise_for_status = Mock()

        # Mock order response with net_amount_due = 0
        order_resp = Mock()
        order_resp.json.return_value = {
            "order": {
                "state": "OPEN",
                "net_amount_due_money": {"amount": 0, "currency": "USD"},
            }
        }
        order_resp.raise_for_status = Mock()

        mock_get.side_effect = [payment_link_resp, order_resp]

        status = square_provider.get_payment_status("LINK123")

        assert status == "paid"
        assert mock_get.call_count == 2
        mock_logger.debug.assert_called_with(
            "Checking Square payment status for: LINK123"
        )

    @patch("src.paymcp.providers.square.requests.get")
    def test_get_payment_status_completed(self, mock_get, square_provider):
        payment_link_resp = Mock()
        payment_link_resp.json.return_value = {
            "payment_link": {"id": "LINK456", "order_id": "ORDER456"}
        }
        payment_link_resp.raise_for_status = Mock()

        order_resp = Mock()
        order_resp.json.return_value = {
            "order": {
                "state": "COMPLETED",
                "net_amount_due_money": {"amount": 100, "currency": "USD"},
            }
        }
        order_resp.raise_for_status = Mock()

        mock_get.side_effect = [payment_link_resp, order_resp]

        status = square_provider.get_payment_status("LINK456")
        assert status == "paid"

    @patch("src.paymcp.providers.square.requests.get")
    def test_get_payment_status_canceled(self, mock_get, square_provider):
        payment_link_resp = Mock()
        payment_link_resp.json.return_value = {
            "payment_link": {"id": "LINK789", "order_id": "ORDER789"}
        }
        payment_link_resp.raise_for_status = Mock()

        order_resp = Mock()
        order_resp.json.return_value = {
            "order": {
                "state": "CANCELED",
                "net_amount_due_money": {"amount": 5000, "currency": "USD"},
            }
        }
        order_resp.raise_for_status = Mock()

        mock_get.side_effect = [payment_link_resp, order_resp]

        status = square_provider.get_payment_status("LINK789")
        assert status == "canceled"

    @patch("src.paymcp.providers.square.requests.get")
    def test_get_payment_status_pending(self, mock_get, square_provider):
        payment_link_resp = Mock()
        payment_link_resp.json.return_value = {
            "payment_link": {"id": "LINK999", "order_id": "ORDER999"}
        }
        payment_link_resp.raise_for_status = Mock()

        order_resp = Mock()
        order_resp.json.return_value = {
            "order": {
                "state": "OPEN",
                "net_amount_due_money": {"amount": 2500, "currency": "USD"},
            }
        }
        order_resp.raise_for_status = Mock()

        mock_get.side_effect = [payment_link_resp, order_resp]

        status = square_provider.get_payment_status("LINK999")
        assert status == "pending"

    @patch("src.paymcp.providers.square.requests.get")
    def test_get_payment_status_no_order_id(self, mock_get, square_provider):
        payment_link_resp = Mock()
        payment_link_resp.json.return_value = {"payment_link": {"id": "LINK_NO_ORDER"}}
        payment_link_resp.raise_for_status = Mock()

        mock_get.return_value = payment_link_resp

        status = square_provider.get_payment_status("LINK_NO_ORDER")
        assert status == "pending"
        assert mock_get.call_count == 1

    @patch("src.paymcp.providers.square.requests.get")
    def test_get_payment_status_exception(self, mock_get, square_provider, mock_logger):
        mock_get.side_effect = requests.HTTPError("404 Not Found")

        status = square_provider.get_payment_status("NONEXISTENT")

        assert status == "pending"
        mock_logger.error.assert_called()
        error_msg = mock_logger.error.call_args[0][0]
        assert "Error checking Square payment status" in error_msg

    @patch("src.paymcp.providers.square.requests.get")
    def test_get_payment_status_order_request_failure(
        self, mock_get, square_provider, mock_logger
    ):
        payment_link_resp = Mock()
        payment_link_resp.json.return_value = {
            "payment_link": {"id": "LINK_ERR", "order_id": "ORDER_ERR"}
        }
        payment_link_resp.raise_for_status = Mock()

        order_resp = Mock()
        order_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

        mock_get.side_effect = [payment_link_resp, order_resp]

        status = square_provider.get_payment_status("LINK_ERR")

        assert status == "pending"
        mock_logger.error.assert_called()
