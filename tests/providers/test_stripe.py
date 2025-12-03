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
            == "https://paymcp.info/paymentsuccess/?session_id={CHECKOUT_SESSION_ID}"
        )
        assert provider.cancel_url == "https://paymcp.info/paymentcanceled/"
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

    #     def test_get_name(self, stripe_provider):
    #         assert stripe_provider.get_name() == "stripe"
    # 
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


class TestStripeSubscriptions:
    """Test the Stripe subscription methods."""

    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def stripe_provider(self, mock_logger):
        provider = StripeProvider(
            api_key="test_api_key",
            logger=mock_logger,
        )
        provider._request = Mock()
        return provider

    def test_get_subscriptions(self, stripe_provider):
        """Test get_subscriptions returns both current and available subscriptions."""
        # Mock _list_available_subscription_plans
        available_plans = [
            {"planId": "price_basic", "title": "Basic", "currency": "usd", "price": 9.99, "interval": "month"}
        ]
        # Mock _list_user_subscriptions
        current_subs = [
            {"id": "sub_123", "status": "active", "planId": "price_pro"}
        ]

        with patch.object(stripe_provider, "_list_available_subscription_plans", return_value=available_plans):
            with patch.object(stripe_provider, "_list_user_subscriptions", return_value=current_subs):
                result = stripe_provider.get_subscriptions("user123", "user@example.com")

        assert result["current_subscriptions"] == current_subs
        assert result["available_subscriptions"] == available_plans

    def test_start_subscription_creates_checkout_session(self, stripe_provider):
        """Test start_subscription creates a new checkout session."""
        # start_subscription calls _list_user_subscriptions first, which calls _find_or_create_customer
        # Then if no resumable subscription, it calls _find_or_create_customer again and creates checkout session
        stripe_provider._request.side_effect = [
            # _list_user_subscriptions -> _find_or_create_customer: search by metadata
            {"data": []},
            # _list_user_subscriptions -> _find_or_create_customer: search by email
            {"data": []},
            # _list_user_subscriptions -> _find_or_create_customer: create customer
            {"id": "cus_new123"},
            # _list_user_subscriptions: list subscriptions
            {"data": []},
            # start_subscription: _find_or_create_customer for checkout session (returns cached)
            {"data": [{"id": "cus_new123"}]},
            # create checkout session
            {"id": "cs_sub_123", "url": "https://checkout.stripe.com/sub"}
        ]

        result = stripe_provider.start_subscription("price_pro", "user123", "user@example.com")

        assert "checkoutUrl" in result
        assert result["planId"] == "price_pro"

    def test_start_subscription_resumes_canceled(self, stripe_provider):
        """Test start_subscription resumes a subscription scheduled for cancellation."""
        # Mock _find_or_create_customer
        stripe_provider._request.side_effect = [
            # _find_or_create_customer search
            {"data": [{"id": "cus_existing"}]},
            # _list_user_subscriptions
            {
                "data": [
                    {
                        "id": "sub_existing",
                        "status": "active",
                        "cancel_at_period_end": True,
                        "items": {"data": [{"price": {"id": "price_pro", "recurring": {"interval": "month"}}}]}
                    }
                ]
            },
            # Update subscription (resume)
            {"id": "sub_existing", "cancel_at_period_end": False}
        ]

        result = stripe_provider.start_subscription("price_pro", "user123", "user@example.com")

        assert "reactivated" in result["message"]
        assert result["planId"] == "price_pro"

    def test_cancel_subscription_schedules_cancellation(self, stripe_provider):
        """Test cancel_subscription schedules cancellation at period end."""
        stripe_provider._request.side_effect = [
            # Get subscription
            {"id": "sub_123", "customer": "cus_user123", "cancel_at": None},
            # _find_or_create_customer search
            {"data": [{"id": "cus_user123"}]},
            # Update subscription
            {"id": "sub_123", "cancel_at_period_end": True, "cancel_at": 1735689600}
        ]

        result = stripe_provider.cancel_subscription("sub_123", "user123", "user@example.com")

        assert result["canceled"] is True
        assert "endDate" in result

    def test_cancel_subscription_wrong_customer(self, stripe_provider):
        """Test cancel_subscription fails when subscription belongs to different customer."""
        stripe_provider._request.side_effect = [
            # Get subscription - belongs to different customer
            {"id": "sub_123", "customer": "cus_different"},
            # _find_or_create_customer search - returns current user's customer
            {"data": [{"id": "cus_user123"}]}
        ]

        with pytest.raises(ValueError, match="subscription does not belong to current user"):
            stripe_provider.cancel_subscription("sub_123", "user123", "user@example.com")

    def test_list_available_subscription_plans(self, stripe_provider):
        """Test _list_available_subscription_plans returns active recurring prices."""
        stripe_provider._request.return_value = {
            "data": [
                {
                    "id": "price_basic",
                    "active": True,
                    "unit_amount": 999,
                    "currency": "usd",
                    "recurring": {"interval": "month"},
                    "product": {"name": "Basic Plan", "description": "Basic features", "active": True}
                },
                {
                    "id": "price_one_time",
                    "active": True,
                    "unit_amount": 1000,
                    "currency": "usd",
                    "recurring": None,  # Not recurring
                    "product": {"name": "One-time", "active": True}
                }
            ]
        }

        result = stripe_provider._list_available_subscription_plans()

        # Should only include recurring prices
        assert len(result) == 1
        assert result[0]["planId"] == "price_basic"
        assert result[0]["price"] == 9.99
        assert result[0]["interval"] == "month"

    def test_list_user_subscriptions(self, stripe_provider):
        """Test _list_user_subscriptions returns user's subscriptions."""
        stripe_provider._request.side_effect = [
            # _find_or_create_customer search
            {"data": [{"id": "cus_user123"}]},
            # List subscriptions
            {
                "data": [
                    {
                        "id": "sub_123",
                        "status": "active",
                        "created": 1700000000,
                        "cancel_at_period_end": False,
                        "items": {"data": [{"price": {"id": "price_pro", "unit_amount": 1999, "currency": "usd", "recurring": {"interval": "month"}}}]}
                    }
                ]
            }
        ]

        result = stripe_provider._list_user_subscriptions("user123", "user@example.com")

        assert len(result) == 1
        assert result[0]["id"] == "sub_123"
        assert result[0]["status"] == "active"
        assert result[0]["planId"] == "price_pro"

    def test_find_or_create_customer_existing_by_metadata(self, stripe_provider):
        """Test _find_or_create_customer finds existing customer by metadata."""
        stripe_provider._request.return_value = {
            "data": [{"id": "cus_existing_meta"}]
        }

        result = stripe_provider._find_or_create_customer("user123", "user@example.com")

        assert result == "cus_existing_meta"

    def test_find_or_create_customer_existing_by_email(self, stripe_provider):
        """Test _find_or_create_customer finds existing customer by email."""
        stripe_provider._request.side_effect = [
            # Search by metadata - not found
            {"data": []},
            # Search by email - found (without userId in metadata)
            {"data": [{"id": "cus_by_email", "metadata": {}}]},
            # Update customer to attach metadata.userId
            {"id": "cus_by_email"}
        ]

        result = stripe_provider._find_or_create_customer("user123", "user@example.com")

        assert result == "cus_by_email"

    def test_find_or_create_customer_creates_new(self, stripe_provider):
        """Test _find_or_create_customer creates new customer when none found."""
        stripe_provider._request.side_effect = [
            # Search by metadata - not found
            {"data": []},
            # Search by email - not found
            {"data": []},
            # Create customer
            {"id": "cus_new123"}
        ]

        result = stripe_provider._find_or_create_customer("user123", "user@example.com")

        assert result == "cus_new123"

    def test_find_or_create_customer_email_conflict(self, stripe_provider):
        """Test _find_or_create_customer raises error on email conflict with different userId."""
        stripe_provider._request.side_effect = [
            # Search by metadata - not found
            {"data": []},
            # Search by email - found with different userId
            {"data": [{"id": "cus_conflict", "metadata": {"userId": "different_user"}}]}
        ]

        with pytest.raises(ValueError, match="email is already associated with a different user account"):
            stripe_provider._find_or_create_customer("user123", "user@example.com")

    def test_map_stripe_subscription(self, stripe_provider):
        """Test _map_stripe_subscription correctly maps subscription data."""
        sub = {
            "id": "sub_test123",
            "status": "active",
            "created": 1700000000,
            "cancel_at_period_end": False,
            "cancel_at": None,
            "ended_at": None,
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_pro",
                            "unit_amount": 1999,
                            "currency": "usd",
                            "recurring": {"interval": "month"}
                        }
                    }
                ]
            }
        }

        result = stripe_provider._map_stripe_subscription(sub)

        assert result["id"] == "sub_test123"
        assert result["status"] == "active"
        assert result["planId"] == "price_pro"
        assert result["price"] == 19.99
        assert result["currency"] == "usd"
        assert result["interval"] == "month"
        assert result["cancelAtPeriodEnd"] is False

    def test_map_stripe_subscription_with_cancellation(self, stripe_provider):
        """Test _map_stripe_subscription handles canceled subscriptions."""
        sub = {
            "id": "sub_canceled",
            "status": "active",
            "created": 1700000000,
            "cancel_at_period_end": True,
            "cancel_at": 1735689600,
            "ended_at": None,
            "items": {"data": [{"price": {"id": "price_basic", "recurring": {"interval": "month"}}}]}
        }

        result = stripe_provider._map_stripe_subscription(sub)

        assert result["cancelAtPeriodEnd"] is True
        assert result["cancelAtDate"] is not None
