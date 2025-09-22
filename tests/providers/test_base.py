import pytest
from unittest.mock import Mock, patch, MagicMock
import logging
import requests
from paymcp.providers.base import BasePaymentProvider


class ConcreteProvider(BasePaymentProvider):
    """Concrete implementation for testing abstract base class."""

    def get_name(self) -> str:
        return "test_provider"

    def create_payment(self, amount: float, currency: str, description: str):
        return ("payment_123", "https://test.com/pay/123")

    def get_payment_status(self, payment_id: str) -> str:
        return "paid"


class TestBasePaymentProvider:
    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def provider(self, mock_logger):
        return ConcreteProvider(api_key="test_api_key", logger=mock_logger)

    def test_init_with_api_key(self, mock_logger):
        provider = ConcreteProvider(api_key="test_key", logger=mock_logger)
        assert provider.api_key == "test_key"
        assert provider.logger == mock_logger

    def test_init_with_apiKey_fallback(self, mock_logger):
        provider = ConcreteProvider(apiKey="fallback_key", logger=mock_logger)
        assert provider.api_key == "fallback_key"

    def test_init_api_key_priority(self, mock_logger):
        provider = ConcreteProvider(api_key="primary", apiKey="fallback", logger=mock_logger)
        assert provider.api_key == "primary"

    def test_init_no_api_key(self, mock_logger):
        provider = ConcreteProvider(logger=mock_logger)
        assert provider.api_key is None

    def test_init_default_logger(self):
        with patch('logging.getLogger') as mock_get_logger:
            mock_logger = Mock(spec=logging.Logger)
            mock_get_logger.return_value = mock_logger

            provider = ConcreteProvider(api_key="test_key")

            mock_get_logger.assert_called_once_with('ConcreteProvider')
            assert provider.logger == mock_logger

    def test_build_headers_default(self, provider):
        headers = provider._build_headers()
        assert headers == {
            "Authorization": "Bearer test_api_key",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    def test_build_headers_no_api_key(self, mock_logger):
        provider = ConcreteProvider(logger=mock_logger)
        headers = provider._build_headers()
        assert headers == {
            "Authorization": "Bearer None",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    @patch('src.paymcp.providers.base.requests.get')
    def test_request_get_success(self, mock_get, provider, mock_logger):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "success"}
        mock_resp.raise_for_status = Mock()
        mock_get.return_value = mock_resp

        result = provider._request("GET", "https://api.test.com/endpoint", {"param": "value"})

        assert result == {"result": "success"}
        mock_get.assert_called_once_with(
            "https://api.test.com/endpoint",
            headers=provider._build_headers(),
            params={"param": "value"}
        )
        mock_logger.debug.assert_called_with(
            "HTTP GET https://api.test.com/endpoint succeeded with status 200"
        )

    @patch('src.paymcp.providers.base.requests.post')
    def test_request_post_form_data(self, mock_post, provider, mock_logger):
        mock_resp = Mock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": "123"}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        result = provider._request("POST", "https://api.test.com/create", {"key": "value"})

        assert result == {"id": "123"}
        mock_post.assert_called_once_with(
            "https://api.test.com/create",
            headers=provider._build_headers(),
            data={"key": "value"}
        )
        mock_logger.debug.assert_called_with(
            "HTTP POST https://api.test.com/create succeeded with status 201"
        )

    @patch('src.paymcp.providers.base.requests.post')
    def test_request_post_json(self, mock_post, provider, mock_logger):
        # Override _build_headers to return JSON content type
        provider._build_headers = Mock(return_value={
            "Authorization": "Bearer test_api_key",
            "Content-Type": "application/json"
        })

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        result = provider._request("POST", "https://api.test.com/json", {"data": "test"})

        assert result == {"status": "ok"}
        mock_post.assert_called_once_with(
            "https://api.test.com/json",
            headers={"Authorization": "Bearer test_api_key", "Content-Type": "application/json"},
            json={"data": "test"}
        )

    @patch('src.paymcp.providers.base.requests.get')
    def test_request_case_insensitive_method(self, mock_get, provider):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"test": "data"}
        mock_resp.raise_for_status = Mock()
        mock_get.return_value = mock_resp

        # Test lowercase
        result = provider._request("get", "https://api.test.com/test")
        assert result == {"test": "data"}

        # Test mixed case
        result = provider._request("GeT", "https://api.test.com/test")
        assert result == {"test": "data"}

    def test_request_unsupported_method(self, provider, mock_logger):
        with pytest.raises(RuntimeError, match="Value error: Unsupported HTTP method: DELETE"):
            provider._request("DELETE", "https://api.test.com/delete")

        mock_logger.error.assert_called_with("Value error occurred: Unsupported HTTP method: DELETE")

    @patch('src.paymcp.providers.base.requests.get')
    def test_request_http_error(self, mock_get, provider, mock_logger):
        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_get.return_value = mock_resp

        with pytest.raises(RuntimeError, match="HTTP error: 404 Not Found"):
            provider._request("GET", "https://api.test.com/notfound")

        mock_logger.error.assert_called_with("HTTP error occurred: 404 Not Found")

    @patch('src.paymcp.providers.base.requests.post')
    def test_request_connection_error(self, mock_post, provider, mock_logger):
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with pytest.raises(RuntimeError, match="Request error: Connection refused"):
            provider._request("POST", "https://api.test.com/endpoint")

        mock_logger.error.assert_called_with("Request exception occurred: Connection refused")

    @patch('src.paymcp.providers.base.requests.get')
    def test_request_timeout_error(self, mock_get, provider, mock_logger):
        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

        with pytest.raises(RuntimeError, match="Request error: Request timed out"):
            provider._request("GET", "https://api.test.com/slow")

        mock_logger.error.assert_called_with("Request exception occurred: Request timed out")

    @patch('src.paymcp.providers.base.requests.post')
    def test_request_json_decode_error(self, mock_post, provider, mock_logger):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="Value error: Invalid JSON"):
            provider._request("POST", "https://api.test.com/badjson")

        mock_logger.error.assert_called_with("Value error occurred: Invalid JSON")

    def test_abstract_methods_implementation(self, provider):
        # Test that concrete implementation works
        assert provider.get_name() == "test_provider"

        payment_id, payment_url = provider.create_payment(100, "USD", "Test")
        assert payment_id == "payment_123"
        assert payment_url == "https://test.com/pay/123"

        status = provider.get_payment_status("payment_123")
        assert status == "paid"

    def test_abstract_base_class_cannot_instantiate(self):
        # Test that abstract base class cannot be instantiated
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BasePaymentProvider(api_key="test")