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
        self.mcp = mcp_instance
        self.providers = build_providers(providers or {})
        self.payment_flow = payment_flow
        self.state_store = state_store
        self._wrapper_factory = make_flow(payment_flow.value)

        # Allow flows to initialize themselves (e.g., TWO_STEP needs state_store, LIST_CHANGE needs patching)
        self._setup_flow()
        self._patch_tool()

    def _get_provider(self):
        """Get the first available payment provider"""
        if not self.providers:
            raise RuntimeError("No payment provider configured")
        return next(iter(self.providers.values()))

    def _setup_flow(self):
        """Call flow's setup_flow() if it exists"""
        try:
            from importlib import import_module
            flow_module = import_module(f".payment.flows.{self.payment_flow.value}", __package__)
            if hasattr(flow_module, 'setup_flow'):
                flow_module.setup_flow(self.mcp, self, self.payment_flow)
        except Exception as e:
            logger.debug(f"No setup_flow() for {self.payment_flow.value}: {e}")

    def _create_paid_tool_wrapper(self, func, price_info):
        """Create payment-gated wrapper for a tool function"""
        provider = self._get_provider()
        return self._wrapper_factory(func, self.mcp, provider, price_info, self.state_store)

    def _patch_tool(self):
        """Intercept tool registration to add payment gating for @price decorated tools"""
        original_tool = self.mcp.tool

        def patched_tool(*args, **kwargs):
            # Handle @mcp.tool(func) - function as first arg
            if args and callable(args[0]) and not isinstance(args[0], str):
                func = args[0]
                if price_info := getattr(func, "_paymcp_price_info", None):
                    kwargs["description"] = description_with_price(
                        kwargs.get("description") or func.__doc__ or "", price_info
                    )
                    func = self._create_paid_tool_wrapper(func, price_info)
                return original_tool(func, *args[1:], **kwargs)

            # Handle @mcp.tool() or @mcp.tool(description="...") - returns decorator
            def decorator(func):
                if price_info := getattr(func, "_paymcp_price_info", None):
                    kwargs["description"] = description_with_price(
                        kwargs.get("description") or func.__doc__ or "", price_info
                    )
                    func = self._create_paid_tool_wrapper(func, price_info)
                return original_tool(*args, **kwargs)(func)
            return decorator

        self.mcp.tool = patched_tool
