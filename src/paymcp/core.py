# paymcp/core.py
from enum import Enum
from .providers import build_providers
from .utils.messages import description_with_price
from .payment.flows import make_flow
from .payment.payment_flow import PaymentFlow
from importlib.metadata import version, PackageNotFoundError
import logging
logger = logging.getLogger(__name__)

try:
    __version__ = version("paymcp")
except PackageNotFoundError:
    __version__ = "unknown"

class PayMCP:
    def __init__(self, mcp_instance, providers=None, payment_flow: PaymentFlow = PaymentFlow.TWO_STEP, state_store=None):
        logger.debug(f"PayMCP v{__version__}")
        flow_name = payment_flow.value
        self._wrapper_factory = make_flow(flow_name)
        self.mcp = mcp_instance
        self.providers = build_providers(providers or {})
        # Only TWO_STEP needs state_store - create default if needed
        if state_store is None and payment_flow == PaymentFlow.TWO_STEP:
            from .state import InMemoryStateStore
            state_store = InMemoryStateStore()
        self.state_store = state_store
        self._patch_tool()

    def _patch_tool(self):
        original_tool = self.mcp.tool
        def patched_tool(*args, **kwargs):
            def wrapper(func):
                # Read @price decorator
                price_info = getattr(func, "_paymcp_price_info", None)

                if price_info:
                    # --- Create payment using provider ---
                    provider = next(iter(self.providers.values())) #get first one - TODO allow to choose
                    if provider is None:
                        raise RuntimeError(
                            f"No payment provider configured"
                        )

                    # Deferred payment creation, so do not call provider.create_payment here
                    kwargs["description"] = description_with_price(kwargs.get("description") or func.__doc__ or "", price_info)
                    target_func = self._wrapper_factory(
                        func, self.mcp, provider, price_info, self.state_store
                    )
                else:
                    target_func = func

                return original_tool(*args, **kwargs)(target_func)
            return wrapper

        self.mcp.tool = patched_tool