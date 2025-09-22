from .base import BasePaymentProvider
import logging
logger = logging.getLogger(__name__)

BASE_URL = "https://api.walleot.com/v1"


class WalleotProvider(BasePaymentProvider):
    def __init__(
        self,
        api_key: str = None, 
        apiKey: str = None,
        logger: logging.Logger = None,
    ):
        super().__init__(api_key, apiKey, logger=logger)
        self.logger.debug(f"Walleot ready")

    def get_name(self) -> str:
        return "walleot"

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_payment(self, amount: float, currency: str, description: str):
        """Creates a Walleot payment session and returns (session_id, session_url)."""
        self.logger.debug(f"Creating Walleot payment session: {amount} {currency} for '{description}'")
        data = {
            "amount": int(amount * 100),
            "currency": currency.lower(),
            "description": description,
        }
        session = self._request("POST", f"{BASE_URL}/sessions", data)

        return session["sessionId"], session["url"]

    def get_payment_status(self, payment_id: str) -> str:
        """Returns payment status for the given session_id."""
        self.logger.debug("Checking walleot payment status for: %s", payment_id)
        session = self._request("GET", f"{BASE_URL}/sessions/{payment_id}")
        return session["status"].lower()