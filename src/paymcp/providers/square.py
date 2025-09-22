import requests
from .base import BasePaymentProvider
import logging
import time
import random
import string
import os

SANDBOX_URL = "https://connect.squareupsandbox.com"
PRODUCTION_URL = "https://connect.squareup.com"

class SquareProvider(BasePaymentProvider):
    def __init__(self,
                access_token: str,
                location_id: str,
                logger: logging.Logger = None,
                redirect_url: str = 'https://example.com/success',
                sandbox: bool = True,
                api_version: str = None):
        self.access_token = access_token
        self.location_id = location_id
        self.redirect_url = redirect_url
        self.base_url = SANDBOX_URL if sandbox else PRODUCTION_URL
        # Use provided version, then env var, then default to latest
        self.api_version = api_version or os.environ.get('SQUARE_API_VERSION', '2025-03-19')
        super().__init__(logger=logger)
        self.logger.debug(f"Square ready (API version: {self.api_version})")

    def get_name(self) -> str:
        return "square"

    def _build_headers(self) -> dict:
        """Square uses Bearer token authentication."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Square-Version": self.api_version,
        }

    def _generate_idempotency_key(self) -> str:
        """Generate unique idempotency key for Square API calls."""
        timestamp = str(int(time.time() * 1000))
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"{timestamp}-{random_str}"

    def create_payment(self, amount: float, currency: str, description: str):
        """Creates a Square Payment Link and returns (payment_id, payment_url)."""
        self.logger.debug(f"Creating Square payment: {amount} {currency} for '{description}'")

        # Convert to cents
        amount_cents = int(amount * 100)

        idempotency_key = self._generate_idempotency_key()

        # Use Payment Links API - the current recommended approach
        payload = {
            "idempotency_key": idempotency_key,
            "quick_pay": {
                "name": description,
                "price_money": {
                    "amount": amount_cents,
                    "currency": currency.upper()
                },
                "location_id": self.location_id
            }
        }

        resp = requests.post(
            f"{self.base_url}/v2/online-checkout/payment-links",
            headers=self._build_headers(),
            json=payload
        )
        resp.raise_for_status()
        data = resp.json()

        payment_link = data.get("payment_link", {})
        payment_id = payment_link.get("id")
        payment_url = payment_link.get("url")

        if not payment_id or not payment_url:
            raise ValueError("Invalid response from Square Payment Links API")

        return payment_id, payment_url

    def get_payment_status(self, payment_id: str) -> str:
        """Returns payment status for the given payment link ID."""
        self.logger.debug(f"Checking Square payment status for: {payment_id}")

        try:
            # Get the payment link to find the order ID
            resp = requests.get(
                f"{self.base_url}/v2/online-checkout/payment-links/{payment_id}",
                headers=self._build_headers()
            )
            resp.raise_for_status()
            payment_data = resp.json()

            payment_link = payment_data.get("payment_link", {})
            order_id = payment_link.get("order_id")

            if not order_id:
                return "pending"

            # Check the order status
            order_resp = requests.get(
                f"{self.base_url}/v2/orders/{order_id}?location_id={self.location_id}",
                headers=self._build_headers()
            )
            order_resp.raise_for_status()
            order_data = order_resp.json()

            order = order_data.get("order", {})
            order_state = order.get("state", "")

            # Check if order is fully paid by looking at net_amount_due
            net_amount_due = order.get("net_amount_due_money", {}).get("amount")

            # If net amount due is 0, the order is fully paid
            if net_amount_due == 0:
                return "paid"

            # Map Square order state to standard status
            if order_state == "COMPLETED":
                return "paid"
            elif order_state == "CANCELED":
                return "canceled"
            else:
                return "pending"

        except Exception as e:
            self.logger.error(f"Error checking Square payment status: {e}")
            return "pending"