import requests
from requests.auth import HTTPBasicAuth
from .base import BasePaymentProvider
import logging


class PayPalProvider(BasePaymentProvider):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        logger: logging.Logger = None,
        success_url: str = "https://example.com/success",
        cancel_url: str = "https://example.com/cancel",
        sandbox: bool = True,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.base_url = (
            "https://api-m.sandbox.paypal.com"
            if sandbox
            else "https://api-m.paypal.com"
        )
        self._token = self._get_token()
        super().__init__(logger=logger)
        self.logger.debug("PayPal ready")

    def get_name(self) -> str:
        return "paypal"

    def _get_token(self):
        """Get OAuth token from PayPal."""
        resp = requests.post(
            f"{self.base_url}/v1/oauth2/token",
            auth=HTTPBasicAuth(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def create_payment(self, amount: float, currency: str, description: str):
        """Creates a PayPal checkout and returns (order_id, approval_url)."""
        self.logger.debug(
            f"Creating PayPal payment: {amount} {currency} for '{description}'"
        )

        headers = {"Authorization": f"Bearer {self._token}"}
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
                    "description": description,
                }
            ],
            "application_context": {
                "return_url": self.success_url,
                "cancel_url": self.cancel_url,
                "user_action": "PAY_NOW",  # Critical: Shows "Pay Now" instead of "Continue"
            },
        }

        resp = requests.post(
            f"{self.base_url}/v2/checkout/orders", headers=headers, json=payload
        )
        resp.raise_for_status()
        data = resp.json()

        approve_url = next(
            link["href"] for link in data["links"] if link["rel"] == "approve"
        )
        return data["id"], approve_url

    def get_payment_status(self, payment_id: str) -> str:
        """Returns payment status, auto-capturing if approved."""
        self.logger.debug(f"Checking PayPal payment status for: {payment_id}")

        headers = {"Authorization": f"Bearer {self._token}"}
        resp = requests.get(
            f"{self.base_url}/v2/checkout/orders/{payment_id}", headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

        # Auto-capture approved payments
        if data["status"] == "APPROVED":
            try:
                self.logger.debug(f"Auto-capturing payment: {payment_id}")
                capture_resp = requests.post(
                    f"{self.base_url}/v2/checkout/orders/{payment_id}/capture",
                    headers=headers,
                    json={},
                )
                capture_resp.raise_for_status()
                return (
                    "paid"
                    if capture_resp.json()["status"] == "COMPLETED"
                    else "pending"
                )
            except Exception as e:
                self.logger.error(f"Capture failed for {payment_id}: {e}")
                return "pending"

        return "paid" if data["status"] == "COMPLETED" else "pending"
