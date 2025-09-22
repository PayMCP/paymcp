from .base import BasePaymentProvider
import logging

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

    def get_name(self) -> str:
        return "stripe"

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