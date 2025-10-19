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
        self.payment_flow = payment_flow
        # Only TWO_STEP needs state_store - create default if needed
        if state_store is None and payment_flow == PaymentFlow.TWO_STEP:
            from .state import InMemoryStateStore
            state_store = InMemoryStateStore()
        self.state_store = state_store
        self._patch_tool()
        # Allow flows to perform their own setup (e.g., LIST_CHANGE needs to patch tool filtering)
        self._setup_flow(payment_flow)

    def _get_provider(self):
        """Get the first available payment provider"""
        if not self.providers:
            raise RuntimeError("No payment provider configured")
        return next(iter(self.providers.values()))

    def _setup_flow(self, payment_flow: PaymentFlow):
        """
        Allow payment flows to perform their own setup.

        This hook lets flows handle their own initialization without polluting core.py.
        For example, LIST_CHANGE flow needs to patch tool filtering and register capabilities.
        """
        try:
            from importlib import import_module
            flow_module = import_module(f".payment.flows.{payment_flow.value}", __package__)
            if hasattr(flow_module, 'setup_flow'):
                logger.debug(f"[PayMCP] Calling setup_flow() for {payment_flow.value}")
                flow_module.setup_flow(self.mcp, self, payment_flow)
        except Exception as e:
            logger.debug(f"[PayMCP] No setup_flow() for {payment_flow.value}: {e}")

    def _patch_tool(self):
        original_tool = self.mcp.tool
        def patched_tool(*args, **kwargs):
            # Handle FastMCP's flexible calling patterns
            # Case 1: @mcp.tool (without parentheses) - first arg is the function
            # Case 2: @mcp.tool() (with empty parentheses) - no args, returns decorator
            # Case 3: @mcp.tool(description="...") - kwargs only, returns decorator

            # Check if first argument is a callable function (Case 1)
            if len(args) > 0 and callable(args[0]) and not isinstance(args[0], str):
                func = args[0]
                # Read @price decorator
                price_info = getattr(func, "_paymcp_price_info", None)

                if price_info:
                    provider = self._get_provider()
                    # Deferred payment creation, so do not call provider.create_payment here
                    kwargs["description"] = description_with_price(kwargs.get("description") or func.__doc__ or "", price_info)
                    # All flows now accept uniform signature with state_store parameter
                    target_func = self._wrapper_factory(
                        func, self.mcp, provider, price_info, self.state_store
                    )
                else:
                    target_func = func

                # Call original_tool with function as first argument
                return original_tool(target_func, *args[1:], **kwargs)
            else:
                # Case 2 & 3: Return a decorator
                def wrapper(func):
                    # Read @price decorator
                    price_info = getattr(func, "_paymcp_price_info", None)

                    if price_info:
                        provider = self._get_provider()
                        # Deferred payment creation, so do not call provider.create_payment here
                        kwargs["description"] = description_with_price(kwargs.get("description") or func.__doc__ or "", price_info)
                        # All flows now accept uniform signature with state_store parameter
                        target_func = self._wrapper_factory(
                            func, self.mcp, provider, price_info, self.state_store
                        )
                    else:
                        target_func = func

                    return original_tool(*args, **kwargs)(target_func)
                return wrapper

        self.mcp.tool = patched_tool
