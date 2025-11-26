from .base import BasePaymentProvider
import logging
from urllib.parse import urlencode

BASE_URL = "https://api.stripe.com/v1"

class StripeProvider(BasePaymentProvider):
    def __init__(
        self,
        api_key: str = None, 
        apiKey: str = None,
        success_url: str = 'https://yoururl.com/success?session_id={CHECKOUT_SESSION_ID}',
        cancel_url: str = 'https://yoururl.com/cancel',
        logger: logging.Logger = None,
    ):
        super().__init__(api_key, apiKey, logger=logger)
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.logger.debug("Stripe ready")

    def create_payment(self, amount: float, currency: str, description: str):
        """Creates a Stripe Checkout session and returns (session_id, session_url)."""
        self.logger.debug(f"Creating Stripe payment: {amount} {currency} for '{description}'")
        data = {
            "mode": "payment",
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": int(amount * 100),
            "line_items[0][price_data][product_data][name]": description,
            "line_items[0][quantity]": 1,
        }
        session = self._request("POST", f"{BASE_URL}/checkout/sessions", data)
        return session["id"], session["url"]

    def get_payment_status(self, payment_id: str) -> str:
        """Returns payment status for the given session_id."""
        self.logger.debug("Checking Stripe payment status for: %s", payment_id)
        session = self._request("GET", f"{BASE_URL}/checkout/sessions/{payment_id}")
        return session["payment_status"]


    def get_subscriptions(self, user_id: str, email: str = None):
        """
        Returns current subscriptions for a given user and available subscription plans.
          - list available subscription plans (active recurring prices)
          - list current user subscriptions, resolved via Stripe Customer.
        """
        self.logger.debug("Stripe get_subscriptions for user_id=%s", user_id)

        available = self._list_available_subscription_plans()
        current = self._list_user_subscriptions(user_id, email)

        return {
            "current_subscriptions": current,
            "available_subscriptions": available,
        }

    def start_subscription(self, plan_id: str, user_id: str, email: str = None):
        """
        Start (or resume) a subscription for the given user and plan.

        Behaviour:
          - If there is an existing subscription for this plan that is active/trialing
            and scheduled to cancel at period end, we simply resume it by clearing
            cancel_at_period_end.
          - Otherwise, create a Checkout Session in mode=subscription and return its URL
            so that the user can complete the flow in the browser.
        """
        self.logger.debug(
            "Stripe start_subscription plan_id=%s user_id=%s email=%s",
            plan_id,
            user_id,
            email or "n/a",
        )

        # Check for an existing resumable subscription
        existing = self._list_user_subscriptions(user_id, email)

        resumable = None
        for sub in existing:
            status = str(sub.get("status", "")).lower()
            if (
                sub.get("planId") == plan_id
                and sub.get("cancelAtPeriodEnd")
                and status in ("active", "trialing")
            ):
                resumable = sub
                break

        if resumable:
            self.logger.debug(
                "Stripe resuming existing subscription %s for user_id=%s plan_id=%s",
                resumable.get("id"),
                user_id,
                plan_id,
            )

            self._request(
                "POST",
                f"{BASE_URL}/subscriptions/{resumable.get('id')}",
                {"cancel_at_period_end": "false"},
            )

            return {
                "message": (
                    "Existing subscription was scheduled to be canceled at period end "
                    "and has been reactivated. Billing will continue as normal."
                ),
                "planId": plan_id,
            }

        # Otherwise, create a new Checkout Session for a fresh subscription.
        customer_id = self._find_or_create_customer(user_id, email)

        data = {
            "mode": "subscription",
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
            "customer": customer_id,
            "line_items[0][price]": plan_id,
            "line_items[0][quantity]": "1",
            # Ensure the resulting subscription carries our userId in metadata
            "subscription_data[metadata][userId]": user_id,
        }

        session = self._request("POST", f"{BASE_URL}/checkout/sessions", data)

        if not isinstance(session, dict) or "id" not in session or "url" not in session:
            raise ValueError(
                "Stripe: invalid response from /checkout/sessions (missing id/url)"
            )

        return {
            "message": (
                "Subscription checkout session created. Please follow the link to set up "
                "your subscription, complete the payment flow, and then confirm when you are done."
            ),
            # Echo the requested planId back to the caller; Stripe does not return planId on the session.
            "planId": plan_id,
            "sessionId": str(session["id"]),
            "checkoutUrl": str(session["url"]),
        }

    def cancel_subscription(self, subscription_id: str, user_id: str, email: str = None):
        """
        Schedule cancellation of a subscription at the end of the current period.

        We:
          - fetch the subscription
          - ensure it belongs to the resolved Stripe customer for this user
          - update cancel_at_period_end=true so that it remains active until the end of the period
          - return information about when access will actually end
        """
        self.logger.debug(
            "Stripe cancel_subscription subscription_id=%s user_id=%s",
            subscription_id,
            user_id,
        )

        # Fetch the subscription first to validate ownership
        sub = self._request("GET", f"{BASE_URL}/subscriptions/{subscription_id}")

        # Resolve the customer for this user
        customer_id = self._find_or_create_customer(user_id, email)
        sub_customer = str(sub.get("customer", "")) if isinstance(sub, dict) else ""

        if sub_customer != customer_id:
            self.logger.debug(
                "Stripe subscription %s does not belong to customer %s (found customer=%s)",
                subscription_id,
                customer_id,
                sub_customer or "n/a",
            )
            raise ValueError("Stripe: subscription does not belong to current user")

        # Schedule cancellation at the end of the current period instead of immediate cancel.
        updated = self._request(
            "POST",
            f"{BASE_URL}/subscriptions/{subscription_id}",
            {"cancel_at_period_end": "true"},
        )

        # cancel_at is a Unix timestamp (seconds). Normalize it to an ISO date string.
        end_date = None
        raw_cancel_at = None
        if isinstance(updated, dict) and "cancel_at" in updated:
            raw_cancel_at = updated.get("cancel_at")
        elif isinstance(sub, dict) and "cancel_at" in sub:
            raw_cancel_at = sub.get("cancel_at")

        if isinstance(raw_cancel_at, (int, float)):
            end_date = __import__("datetime").datetime.utcfromtimestamp(
                raw_cancel_at
            ).isoformat() + "Z"
        elif isinstance(raw_cancel_at, str):
            try:
                ts = float(raw_cancel_at)
                end_date = __import__("datetime").datetime.utcfromtimestamp(ts).isoformat() + "Z"
            except ValueError:
                end_date = None

        self.logger.debug(
            "Stripe subscription %s cancellation scheduled; end_date=%s",
            subscription_id,
            end_date,
        )

        return {
            "message": f"subscription {subscription_id} cancellation scheduled; endDate={end_date}",
            "canceled": True,
            "endDate": end_date,
        }

    def _list_available_subscription_plans(self):
        """
        List available subscription plans (active recurring prices).
        """
        self.logger.debug("Stripe list_available_subscription_plans")

        params = {
            "active": "true",
            "limit": "100",
            "expand[]": "data.product",
        }

        url = f"{BASE_URL}/prices?{urlencode(params)}"
        res = self._request("GET", url)

        data = []
        if isinstance(res, dict):
            data = res.get("data", []) or []

        plans = []
        for price in data:
            if not isinstance(price, dict):
                continue

            recurring = price.get("recurring")
            product = price.get("product") or {}

            if not recurring or not price.get("active") or not product.get("active"):
                continue

            plan_id = str(price.get("id", ""))
            raw_amount = price.get("unit_amount")
            major_amount = (
                raw_amount / 100.0
                if isinstance(raw_amount, (int, float))
                else None
            )

            plans.append(
                {
                    "planId": plan_id,
                    "title": str(product.get("name", "")),
                    "description": product.get("description"),
                    "currency": str(price.get("currency", "")),
                    "price": major_amount,
                    "interval": recurring.get("interval"),
                }
            )

        return plans

    def _list_user_subscriptions(self, user_id: str, email: str = None):
        """
        List subscriptions for a user by their Stripe customer.

        We:
          - resolve (or create) a Customer for the given userId via _find_or_create_customer
          - list subscriptions with /v1/subscriptions?customer=cus_xxx&amp;status=all
          - expand data.items.data.price to map plan details
        """
        self.logger.debug(
            "Stripe _list_user_subscriptions user_id=%s email=%s",
            user_id,
            email or "n/a",
        )

        customer_id = self._find_or_create_customer(user_id, email)

        params = {
            "customer": customer_id,
            "status": "all",
            "limit": "100",
            "expand[]": "data.items.data.price",
        }

        url = f"{BASE_URL}/subscriptions?{urlencode(params)}"
        res = self._request("GET", url)

        data = []
        if isinstance(res, dict):
            data = res.get("data", []) or []

        subscriptions = []
        for sub in data:
            if not isinstance(sub, dict):
                continue
            subscriptions.append(self._map_stripe_subscription(sub))

        return subscriptions

    def _find_or_create_customer(self, user_id: str, email: str = None) -> str:
        """
        Find or create a Stripe Customer for the given user.

        Strategy:
          - if email is provided, try to find an existing customer by email
          - otherwise, or if not found, search by metadata.userId
          - if still not found, create a new customer with metadata[userId]
        """
        self.logger.debug(
            "Stripe _find_or_create_customer user_id=%s email=%s",
            user_id,
            email or "n/a",
        )

        # 1) If we have an email, try to find by email via /customers?email=...
        if email:
            params = {
                "email": email,
                "limit": "1",
            }
            url = f"{BASE_URL}/customers?{urlencode(params)}"
            res = self._request("GET", url)

            if isinstance(res, dict):
                data = res.get("data", []) or []
                if isinstance(data, list) and data:
                    customer = data[0]
                    if isinstance(customer, dict) and "id" in customer:
                        self.logger.debug(
                            "Stripe reusing existing customer via email: %s",
                            customer["id"],
                        )
                        return str(customer["id"])

        # 2) Try to find an existing customer by our own userId in metadata
        search_params = {
            "query": f"metadata['userId']:'{user_id}'",
            "limit": "1",
        }
        search_url = f"{BASE_URL}/customers/search?{urlencode(search_params)}"
        search_res = self._request("GET", search_url)

        if isinstance(search_res, dict):
            sdata = search_res.get("data", []) or []
            if isinstance(sdata, list) and sdata:
                existing = sdata[0]
                if isinstance(existing, dict) and "id" in existing:
                    self.logger.debug(
                        "Stripe reusing existing customer via metadata.userId: %s",
                        existing["id"],
                    )
                    return str(existing["id"])

        # 3) Otherwise, create a new customer and always store our userId in metadata
        body = {
            "metadata[userId]": user_id,
        }
        if email:
            body["email"] = email

        customer = self._request("POST", f"{BASE_URL}/customers", body)

        if not isinstance(customer, dict) or "id" not in customer:
            raise ValueError("Stripe: failed to create customer")

        self.logger.debug(
            "Stripe created new customer %s for user_id=%s",
            customer["id"],
            user_id,
        )

        return str(customer["id"])

    def _map_stripe_subscription(self, sub: dict):
        """
        Map a Stripe Subscription object into a dict 
        StripeUserSubscription shape.

        Expects items[0].price to be expanded.
        """
        items = []
        if isinstance(sub.get("items"), dict):
            items = sub["items"].get("data", []) or []

        first_price = None
        if items and isinstance(items[0], dict):
            first_price = items[0].get("price")

        price_obj = first_price or {}

        # Expose a single logical planId to callers.
        plan_id = str(price_obj.get("id", ""))

        # Price in major currency units (e.g. dollars) for the primary item.
        raw_amount = price_obj.get("unit_amount")
        major_amount = (
            raw_amount / 100.0
            if isinstance(raw_amount, (int, float))
            else None
        )

        # Creation time as a single ISO string
        created_at = None
        created = sub.get("created")
        if isinstance(created, (int, float)):
            created_at = __import__("datetime").datetime.utcfromtimestamp(
                created
            ).isoformat() + "Z"
        elif isinstance(created, str):
            try:
                ts = float(created)
                created_at = __import__("datetime").datetime.utcfromtimestamp(
                    ts
                ).isoformat() + "Z"
            except ValueError:
                created_at = None

        # Cancellation-related fields
        cancel_at_period_end = bool(sub.get("cancel_at_period_end"))

        def _parse_ts(value):
            if isinstance(value, (int, float)):
                return value
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    return None
            return None

        cancel_at_ts = _parse_ts(sub.get("cancel_at"))
        ended_at_ts = _parse_ts(sub.get("ended_at"))

        cancel_at_date = (
            __import__("datetime").datetime.utcfromtimestamp(cancel_at_ts).isoformat() + "Z"
            if cancel_at_ts is not None
            else None
        )
        ended_at_date = (
            __import__("datetime").datetime.utcfromtimestamp(ended_at_ts).isoformat() + "Z"
            if ended_at_ts is not None
            else None
        )

        return {
            "id": str(sub.get("id", "")),
            "status": str(sub.get("status", "unknown")),
            "planId": plan_id,
            "currency": str(price_obj.get("currency", "")),
            "price": major_amount,
            "interval": (price_obj.get("recurring") or {}).get("interval"),
            "createdAt": created_at,
            "cancelAtPeriodEnd": cancel_at_period_end,
            "cancelAtDate": cancel_at_date,
            "endedAtDate": ended_at_date,
        }