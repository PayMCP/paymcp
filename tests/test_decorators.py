"""Tests for the paymcp.decorators module."""

import pytest
from paymcp.decorators import price, subscription


class TestPriceDecorator:
    """Test the @price decorator."""

    def test_price_decorator_basic(self):
        """Test basic price decorator functionality."""

        @price(10.99, "USD")
        def test_function():
            return "result"

        assert hasattr(test_function, "_paymcp_price_info")
        assert test_function._paymcp_price_info["price"] == 10.99
        assert test_function._paymcp_price_info["currency"] == "USD"

    def test_price_decorator_default_currency(self):
        """Test price decorator with default currency."""

        @price(25.50)
        def test_function():
            return "result"

        assert test_function._paymcp_price_info["price"] == 25.50
        assert test_function._paymcp_price_info["currency"] == "USD"

    def test_price_decorator_different_currencies(self):
        """Test price decorator with different currencies."""

        @price(100.00, "EUR")
        def euro_function():
            return "euro"

        @price(1000.00, "JPY")
        def yen_function():
            return "yen"

        assert euro_function._paymcp_price_info["currency"] == "EUR"
        assert yen_function._paymcp_price_info["currency"] == "JPY"

    def test_price_decorator_preserves_function(self):
        """Test that decorator preserves original function behavior."""

        @price(5.00, "GBP")
        def calculate(a, b):
            return a + b

        # Function should still work normally
        result = calculate(2, 3)
        assert result == 5

        # But also have price info
        assert hasattr(calculate, "_paymcp_price_info")
        assert calculate._paymcp_price_info["price"] == 5.00

    def test_price_decorator_on_class_method(self):
        """Test price decorator on class methods."""

        class PaymentService:
            @price(50.00, "USD")
            def process_payment(self):
                return "processed"

        service = PaymentService()
        assert hasattr(service.process_payment, "_paymcp_price_info")
        assert service.process_payment._paymcp_price_info["price"] == 50.00

    def test_price_decorator_stacking(self):
        """Test that only the outermost price decorator takes effect."""

        @price(20.00, "USD")
        @price(30.00, "EUR")  # This will be overwritten
        def stacked_function():
            return "stacked"

        # Only the outermost decorator should apply
        assert stacked_function._paymcp_price_info["price"] == 20.00
        assert stacked_function._paymcp_price_info["currency"] == "USD"

    def test_price_decorator_with_zero_price(self):
        """Test price decorator with zero price."""

        @price(0.00, "USD")
        def free_function():
            return "free"

        assert free_function._paymcp_price_info["price"] == 0.00

    def test_price_decorator_with_negative_price(self):
        """Test price decorator with negative price (should be allowed for refunds/credits)."""

        @price(-10.00, "USD")
        def refund_function():
            return "refund"

        assert refund_function._paymcp_price_info["price"] == -10.00

    def test_price_decorator_with_async_function(self):
        """Test price decorator with async functions."""

        @price(15.00, "CAD")
        async def async_function():
            return "async result"

        assert hasattr(async_function, "_paymcp_price_info")
        assert async_function._paymcp_price_info["price"] == 15.00
        assert async_function._paymcp_price_info["currency"] == "CAD"

    def test_multiple_functions_independent(self):
        """Test that multiple decorated functions maintain independent price info."""

        @price(10.00, "USD")
        def func1():
            return "func1"

        @price(20.00, "EUR")
        def func2():
            return "func2"

        assert func1._paymcp_price_info["price"] == 10.00
        assert func1._paymcp_price_info["currency"] == "USD"
        assert func2._paymcp_price_info["price"] == 20.00
        assert func2._paymcp_price_info["currency"] == "EUR"


class TestSubscriptionDecorator:
    """Test the @subscription decorator."""

    def test_subscription_decorator_single_plan(self):
        """Test subscription decorator with a single plan."""

        @subscription("price_pro_monthly")
        def test_function():
            return "result"

        assert hasattr(test_function, "_paymcp_subscription_info")
        assert test_function._paymcp_subscription_info["plan"] == "price_pro_monthly"

    def test_subscription_decorator_multiple_plans(self):
        """Test subscription decorator with multiple plans."""

        @subscription(["price_pro_monthly", "price_enterprise"])
        def test_function():
            return "result"

        assert hasattr(test_function, "_paymcp_subscription_info")
        assert test_function._paymcp_subscription_info["plan"] == ["price_pro_monthly", "price_enterprise"]

    def test_subscription_decorator_preserves_function(self):
        """Test that decorator preserves original function behavior."""

        @subscription("price_basic")
        def calculate(a, b):
            return a + b

        # Function should still work normally
        result = calculate(2, 3)
        assert result == 5

        # But also have subscription info
        assert hasattr(calculate, "_paymcp_subscription_info")
        assert calculate._paymcp_subscription_info["plan"] == "price_basic"

    def test_subscription_decorator_with_async_function(self):
        """Test subscription decorator with async functions."""

        @subscription("price_premium")
        async def async_function():
            return "async result"

        assert hasattr(async_function, "_paymcp_subscription_info")
        assert async_function._paymcp_subscription_info["plan"] == "price_premium"

    def test_multiple_subscription_functions_independent(self):
        """Test that multiple decorated functions maintain independent subscription info."""

        @subscription("price_basic")
        def func1():
            return "func1"

        @subscription(["price_pro", "price_enterprise"])
        def func2():
            return "func2"

        assert func1._paymcp_subscription_info["plan"] == "price_basic"
        assert func2._paymcp_subscription_info["plan"] == ["price_pro", "price_enterprise"]
