

from .base import BasePaymentProvider
import logging

BASE_URL = "https://api.commerce.coinbase.com"


class CoinbaseProvider(BasePaymentProvider):
    def __init__(
        self,
        api_key: str = None,
        apiKey: str = None,
        success_url: str = 'https://example.com/success',
        cancel_url: str = 'https://example.com/cancel',
        logger: logging.Logger = None,
        # If set to True, payments will be confirmed faster (on PENDING), 
        # but there is a small chance something may still go wrong with the payment.
        confirm_on_pending: bool = False,
    ):
        super().__init__(api_key, apiKey, logger=logger)
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.confirm_on_pending = confirm_on_pending
        self.logger.debug("Coinbase Commerce ready")

    def get_name(self) -> str:
        return "coinbase"

    def _build_headers(self) -> dict:
        headers = {
            "X-CC-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

        return headers

    def create_payment(self, amount: float, currency: str, description: str):
        """Creates a Coinbase Commerce charge and returns (code, hosted_url)."""
        self.logger.debug(f"Creating Coinbase charge: {amount} {currency} for '{description}'")

        fiat_currency = (currency or "USD").upper()
        if fiat_currency == "USDC":
            fiat_currency = "USD"

        data = {
            "name": (description or "Payment")[:100],
            "description": description or "",
            "pricing_type": "fixed_price",
            "local_price": {
                "amount": f"{amount:.2f}",
                "currency": fiat_currency,
            },
            "redirect_url": self.success_url,
            "cancel_url": self.cancel_url,
            "metadata": {"reference": description or ""},
        }
        charge = self._request("POST", f"{BASE_URL}/charges", data)
        cdata = charge.get("data", {})
        return cdata.get("code"), cdata.get("hosted_url")

    def get_payment_status(self, payment_id: str) -> str:
        """Returns payment status for the given charge code (paid|pending|failed)."""
        self.logger.debug("Checking Coinbase charge status for: %s", payment_id)
        charge = self._request("GET", f"{BASE_URL}/charges/{payment_id}")

        data = charge.get("data", {})

        timeline = data.get("timeline", []) or []
        last_status = timeline[-1].get("status") if timeline else None

        # Coinbase Commerce docs: last timeline entry is the current status.
        # PENDING indicates funds are received on-chain and is typically safe to treat as paid.
        if last_status in {"COMPLETED", "RESOLVED"} or (last_status == "PENDING" and self.confirm_on_pending):
            return "paid"
        if last_status in {"EXPIRED", "CANCELED"}:
            return "failed"
        # Fallbacks
        if data.get("completed_at") or data.get("confirmed_at"):
            return "paid"
        return "pending"