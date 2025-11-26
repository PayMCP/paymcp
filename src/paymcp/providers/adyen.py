from .base import BasePaymentProvider
import logging


class AdyenProvider(BasePaymentProvider):
    def __init__(
        self,
        api_key: str = None,
        apiKey: str = None,
        merchant_account: str = None,
        return_url: str = "https://paymcp.info/paymentinfo/",
        sandbox: bool = False,
        logger: logging.Logger = None,
    ):
        super().__init__(api_key, apiKey, logger=logger)
        self.merchant_account = merchant_account
        self.return_url = return_url
        if sandbox:
            self.base_url = "https://checkout-test.adyen.com/v71"
        else:
            self.base_url = "https://checkout-live.adyen.com/v71"
        self.logger.debug("Adyen ready")

    def _build_headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def create_payment(self, amount: float, currency: str, description: str):
        """Creates Adyen Pay-by-Link and returns (link_id, payment_url)."""
        self.logger.debug(f"Creating Adyen payment: {amount} {currency} for '{description}'")
        data = {
            "amount": {
                "currency": currency.upper(),
                "value": int(amount * 100),  # в минорных единицах (центы)
            },
            "reference": description,
            "merchantAccount": self.merchant_account,
            "returnUrl": self.return_url,
        }
        payment = self._request("POST", f"{self.base_url}/paymentLinks", data)
        return payment["id"], payment["url"]

    def get_payment_status(self, payment_id: str) -> str:
        """Returns payment status for the given link_id."""
        self.logger.debug("Checking Adyen payment status for: %s", payment_id)
        payment = self._request("GET", f"{self.base_url}/paymentLinks/{payment_id}")
        status = payment.get("status")

        if status == "completed":
            return "paid"
        elif status == "active":
            return "pending"
        elif status == "expired":
            return "failed"
        return status or "unknown"
