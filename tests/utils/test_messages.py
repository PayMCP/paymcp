import pytest
from paymcp.utils.messages import (
    open_link_message,
    opened_webview_message,
    description_with_price
)


class TestOpenLinkMessage:
    def test_open_link_message_usd(self):
        result = open_link_message("https://pay.test.com/123", 10.99, "USD")
        expected = (
            "To run this tool, please pay 10.99 USD using the link below:\n\n"
            "https://pay.test.com/123\n\n"
            "After completing the payment, come back and confirm."
        )
        assert result == expected

    def test_open_link_message_eur(self):
        result = open_link_message("https://payment.eu/456", 25.00, "EUR")
        expected = (
            "To run this tool, please pay 25.0 EUR using the link below:\n\n"
            "https://payment.eu/456\n\n"
            "After completing the payment, come back and confirm."
        )
        assert result == expected

    def test_open_link_message_zero_amount(self):
        result = open_link_message("https://free.com/789", 0, "USD")
        expected = (
            "To run this tool, please pay 0 USD using the link below:\n\n"
            "https://free.com/789\n\n"
            "After completing the payment, come back and confirm."
        )
        assert result == expected

    def test_open_link_message_large_amount(self):
        result = open_link_message("https://expensive.com/999", 99999.99, "GBP")
        expected = (
            "To run this tool, please pay 99999.99 GBP using the link below:\n\n"
            "https://expensive.com/999\n\n"
            "After completing the payment, come back and confirm."
        )
        assert result == expected

    def test_open_link_message_different_currencies(self):
        currencies = ["JPY", "CAD", "AUD", "CHF"]
        for currency in currencies:
            result = open_link_message("https://test.com", 50, currency)
            assert f"50 {currency}" in result
            assert "https://test.com" in result


class TestOpenedWebviewMessage:
    def test_opened_webview_message_usd(self):
        result = opened_webview_message("https://pay.test.com/123", 10.99, "USD")
        expected = (
            "To run this tool, please pay 10.99 USD.\n"
            "A payment window should be open. If not, you can use this link:\n\n"
            "https://pay.test.com/123\n\n"
            "After completing the payment, come back and confirm."
        )
        assert result == expected

    def test_opened_webview_message_eur(self):
        result = opened_webview_message("https://payment.eu/456", 25.00, "EUR")
        expected = (
            "To run this tool, please pay 25.0 EUR.\n"
            "A payment window should be open. If not, you can use this link:\n\n"
            "https://payment.eu/456\n\n"
            "After completing the payment, come back and confirm."
        )
        assert result == expected

    def test_opened_webview_message_zero_amount(self):
        result = opened_webview_message("https://free.com/789", 0, "USD")
        expected = (
            "To run this tool, please pay 0 USD.\n"
            "A payment window should be open. If not, you can use this link:\n\n"
            "https://free.com/789\n\n"
            "After completing the payment, come back and confirm."
        )
        assert result == expected

    def test_opened_webview_message_fractional_amount(self):
        result = opened_webview_message("https://test.com", 12.345, "USD")
        assert "12.345 USD" in result
        assert "A payment window should be open" in result
        assert "https://test.com" in result

    def test_opened_webview_message_different_urls(self):
        urls = [
            "https://stripe.com/pay/cs_123",
            "https://paypal.com/checkout/456",
            "https://square.link/u/789",
            "http://localhost:3000/pay"
        ]
        for url in urls:
            result = opened_webview_message(url, 100, "USD")
            assert url in result
            assert "100 USD" in result


class TestDescriptionWithPrice:
    def test_description_with_price_basic(self):
        price_info = {"price": 10, "currency": "USD"}
        result = description_with_price("Original description", price_info)
        expected = (
            "Original description"
            "\nThis is a paid function: 10 USD."
            " Payment will be requested during execution."
        )
        assert result == expected

    def test_description_with_price_strips_whitespace(self):
        price_info = {"price": 5.99, "currency": "EUR"}
        result = description_with_price("  Description with spaces  \n", price_info)
        expected = (
            "Description with spaces"
            "\nThis is a paid function: 5.99 EUR."
            " Payment will be requested during execution."
        )
        assert result == expected

    def test_description_with_price_empty_description(self):
        price_info = {"price": 20, "currency": "GBP"}
        result = description_with_price("", price_info)
        expected = (
            "\nThis is a paid function: 20 GBP."
            " Payment will be requested during execution."
        )
        assert result == expected

    def test_description_with_price_whitespace_only_description(self):
        price_info = {"price": 15, "currency": "CAD"}
        result = description_with_price("   \n\t  ", price_info)
        expected = (
            "\nThis is a paid function: 15 CAD."
            " Payment will be requested during execution."
        )
        assert result == expected

    def test_description_with_price_multiline_description(self):
        price_info = {"price": 100, "currency": "AUD"}
        description = "This is a\nmultiline\ndescription"
        result = description_with_price(description, price_info)
        expected = (
            "This is a\nmultiline\ndescription"
            "\nThis is a paid function: 100 AUD."
            " Payment will be requested during execution."
        )
        assert result == expected

    def test_description_with_price_zero_price(self):
        price_info = {"price": 0, "currency": "USD"}
        result = description_with_price("Free function", price_info)
        expected = (
            "Free function"
            "\nThis is a paid function: 0 USD."
            " Payment will be requested during execution."
        )
        assert result == expected

    def test_description_with_price_float_price(self):
        price_info = {"price": 99.99, "currency": "USD"}
        result = description_with_price("Premium function", price_info)
        assert "99.99 USD" in result

    def test_description_with_price_string_price(self):
        price_info = {"price": "25.50", "currency": "EUR"}
        result = description_with_price("Service", price_info)
        assert "25.50 EUR" in result

    def test_description_with_price_different_currencies(self):
        currencies = ["JPY", "CNY", "INR", "KRW", "BTC", "ETH"]
        for currency in currencies:
            price_info = {"price": 50, "currency": currency}
            result = description_with_price("Test", price_info)
            assert f"50 {currency}" in result
            assert "This is a paid function" in result
            assert "Payment will be requested during execution" in result