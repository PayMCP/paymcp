# paymcp/core.py
from enum import Enum
from .providers import build_providers
from .utils.messages import description_with_price
from .payment.flows import make_flow
from .payment.payment_flow import PaymentFlow, Mode
from importlib.metadata import version, PackageNotFoundError
import logging
logger = logging.getLogger(__name__)

try:
    __version__ = version("paymcp")
except PackageNotFoundError:
    __version__ = "unknown"

class PayMCP:
    def __init__(self, mcp_instance, providers=None, payment_flow: PaymentFlow = PaymentFlow.TWO_STEP, state_store=None, mode:Mode=None):
        logger.debug(f"PayMCP v{__version__}")
        if mode is not None and payment_flow is not None and mode != payment_flow:
            logger.warning("[PayMCP] Both 'mode' and 'payment_flow' were provided; 'mode' takes precedence.")
        self.payment_flow = mode if mode is not None else payment_flow
        if self.payment_flow is None:
            self.payment_flow = PaymentFlow.TWO_STEP
        flow_name = self.payment_flow.value
        self._wrapper_factory = make_flow(flow_name)
        self.mcp = mcp_instance
        self.providers = build_providers(providers or {})

        # Only TWO_STEP needs state_store - create default if needed
        if state_store is None and self.payment_flow == PaymentFlow.TWO_STEP:
            from .state import InMemoryStateStore
            state_store = InMemoryStateStore()
        self.state_store = state_store
        self._patch_tool()

        # DYNAMIC_TOOLS flow requires patching MCP internals
        if self.payment_flow == PaymentFlow.DYNAMIC_TOOLS:
            from .payment.flows.dynamic_tools import setup_flow
            setup_flow(mcp_instance, self, self.payment_flow)

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
                        func, self.mcp, provider, price_info, self.state_store, config=kwargs.copy()
                    )
                    if self.payment_flow in (PaymentFlow.TWO_STEP, PaymentFlow.DYNAMIC_TOOLS) and "meta" in kwargs:
                        kwargs.pop("meta", None)
                else:
                    target_func = func

                result = original_tool(*args, **kwargs)(target_func)

                # Apply deferred DYNAMIC_TOOLS list_tools patch after first tool registration
                if self.payment_flow == PaymentFlow.DYNAMIC_TOOLS:
                    if hasattr(self.mcp, '_tool_manager'):
                        if not hasattr(self.mcp._tool_manager.list_tools, '_paymcp_dynamic_tools_patched'):
                            from .payment.flows.dynamic_tools import _patch_list_tools_immediate
                            _patch_list_tools_immediate(self.mcp)

                return result
            return wrapper

        self.mcp.tool = patched_tool
