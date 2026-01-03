from abc import ABC, abstractmethod
from typing import Tuple, Optional, Any
import logging
import requests

class BasePaymentProvider(ABC):
    """Minimal interface every provider must implement."""

    def __init__(self, api_key: str = None, apiKey: str = None, logger: logging.Logger = None):
        self.api_key = api_key if api_key is not None else apiKey
        self.logger = logger or logging.getLogger(self.__class__.__name__)

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _request(self, method: str, url: str, data: dict = None, idempotency_key: str = None):
        headers = self._build_headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers, params=data)
            elif method.upper() == "POST":
                if headers.get("Content-Type") == "application/json":
                    resp = requests.post(url, headers=headers, json=data)
                else:
                    resp = requests.post(url, headers=headers, data=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            resp.raise_for_status()
            self.logger.debug(f"HTTP {method} {url} succeeded with status {resp.status_code}")
            return resp.json()
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error occurred: {e}")
            raise RuntimeError(f"HTTP error: {e}") from e
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request exception occurred: {e}")
            raise RuntimeError(f"Request error: {e}") from e
        except ValueError as e:
            self.logger.error(f"Value error occurred: {e}")
            raise RuntimeError(f"Value error: {e}") from e

    @abstractmethod
    def create_payment(
        self, amount: float, currency: str, description: str
    ) -> Tuple[str, str, Optional[Any]]:
        """
        Return (payment_id, payment_url[, payment_data]) that the user should visit.
        """

    @abstractmethod
    def get_payment_status(self, payment_id: str) -> str:
        """Return payment status."""

    def get_subscriptions(self, user_id: str, email: str = None):
        """
        Optional subscription support hook.

        Providers that support subscriptions should override this method and return a dict with:
          - current_subscriptions: list of current user subscriptions
          - available_subscriptions: list of available subscription plans

        Default implementation: signal that subscriptions are not supported.
        """
        raise RuntimeError("Subscriptions are not supported for this payment provider")

    def start_subscription(self, plan_id: str, user_id: str, email: str = None):
        """
        Start a subscription for the given user and plan.

        Providers that support subscriptions should override this method and return
        a structure describing the created or resumed subscription/checkout session.

        Default implementation: signal that subscriptions are not supported.
        """
        raise RuntimeError("Subscriptions are not supported for this payment provider")

    def cancel_subscription(self, subscription_id: str, user_id: str, email: str = None):
        """
        Cancel (or schedule cancellation for) a subscription.

        Providers that support subscriptions should override this method and return
        a structure describing the cancellation result.

        Default implementation: signal that subscriptions are not supported.
        """
        raise RuntimeError("Subscriptions are not supported for this payment provider")
