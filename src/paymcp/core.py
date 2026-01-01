# paymcp/core.py
from enum import Enum
from .providers import build_providers
from .utils.messages import description_with_price
from .payment.flows import make_flow
from .payment.payment_flow import PaymentFlow, Mode
from importlib.metadata import version, PackageNotFoundError
from .utils.context import capture_client_from_ctx
from .utils.x402 import build_x402_middleware
import logging
import json
logger = logging.getLogger(__name__)

try:
    __version__ = version("paymcp")
except PackageNotFoundError:
    __version__ = "unknown"

class PayMCP:
    def __init__(self, mcp_instance, providers=None, payment_flow: PaymentFlow = None, state_store=None, mode:Mode=None):
        logger.debug(f"PayMCP v{__version__}")
        if mode is not None and payment_flow is not None and mode != payment_flow:
            logger.warning("[PayMCP] Both 'mode' and 'payment_flow' were provided; 'mode' takes precedence.")
        self.payment_flow = mode if mode is not None else payment_flow
        if self.payment_flow is None:
            self.payment_flow = PaymentFlow.AUTO
        self.mcp = mcp_instance
        self.providers = build_providers(providers or {})
        provider_keys = set(self.providers.keys())

        if "x402" in provider_keys and self.payment_flow not in (PaymentFlow.X402, PaymentFlow.AUTO):
            new_mode = PaymentFlow.AUTO if len(provider_keys) > 1 else PaymentFlow.X402
            logger.warning(
                "[PayMCP] %s mode is not supported for x402 provider. Switching to %s mode.",
                self.payment_flow,
                new_mode,
            )
            self.payment_flow = new_mode

        if self.payment_flow == PaymentFlow.X402 and "x402" not in provider_keys:
            logger.warning(
                "[PayMCP] x402 mode is not supported for providers: '%s'. Switching to %s mode.",
                ", ".join(provider_keys),
                PaymentFlow.RESUBMIT,
            )
            self.payment_flow = PaymentFlow.RESUBMIT

        flow_name = self.payment_flow.value
        self._wrapper_factory = make_flow(flow_name)
        self._subscription_tools_registered = False

        if state_store is None:
            from .state import InMemoryStateStore
            state_store = InMemoryStateStore()
        self.state_store = state_store
        self.paidtools = {}
        self._patch_tool()

        # DYNAMIC_TOOLS flow requires patching MCP internals
        if self.payment_flow == PaymentFlow.DYNAMIC_TOOLS:
            from .payment.flows.dynamic_tools import setup_flow
            setup_flow(mcp_instance, self, self.payment_flow)

        if self.payment_flow == PaymentFlow.X402 or self.payment_flow == PaymentFlow.AUTO:
            self._patch_tool_call()

        if self.payment_flow == PaymentFlow.AUTO:
            self._patch_list_tool_for_auto() #removing payment_id parameter in case if client support ELICITATION or x402

    def _patch_tool(self):
        original_tool = self.mcp.tool
        def patched_tool(*args, **kwargs):
            def wrapper(func):
                price_info = getattr(func, "_paymcp_price_info", None)
                subscription_info = getattr(func, "_paymcp_subscription_info", None)

                # Determine tool name for logging and subscription wrappers
                tool_name = kwargs.get("name")
                if not tool_name and len(args) > 0 and isinstance(args[0], str):
                    tool_name = args[0]
                if not tool_name:
                    tool_name = func.__name__

                if subscription_info:
                    # --- Set up subscription guard and tools ---
                    # Register subscription tools once per PayMCP instance
                    if not getattr(self, "_subscription_tools_registered", False):
                        from .subscriptions.wrapper import register_subscription_tools
                        register_subscription_tools(self.mcp, self.providers)
                        self._subscription_tools_registered = True

                    # Build subscription wrapper around the original tool
                    from .subscriptions.wrapper import make_subscription_wrapper
                    target_func = make_subscription_wrapper(
                        func,
                        self.mcp,
                        self.providers,
                        subscription_info,
                        tool_name,
                        self.state_store,
                        config=kwargs.copy(),
                    )

                elif price_info:
                    # --- Create payment using provider ---
                    # Deferred payment creation, so do not call provider.create_payment here
                    kwargs["description"] = description_with_price(
                        kwargs.get("description") or func.__doc__ or "",
                        price_info,
                    )
                    target_func = self._wrapper_factory(
                        func,
                        self.mcp,
                        self.providers,
                        price_info,
                        self.state_store,
                        config=kwargs.copy(),
                    )
                    if self.payment_flow in (PaymentFlow.TWO_STEP, PaymentFlow.DYNAMIC_TOOLS) and "meta" in kwargs:
                        kwargs.pop("meta", None)
                    
                    self.paidtools[tool_name] = { "amount": price_info["price"], "currency": price_info["currency"], "description": kwargs["description"] }
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

    
    def _patch_tool_call(self):
        if not hasattr(self.mcp, "_tool_manager"):
            return
        
        tm = self.mcp._tool_manager

        if hasattr(tm.call_tool, "_paymcp_patched"): 
            return    # Only patch once

        original_call_tool = tm.call_tool

        async def patched_call_tool(name, arguments, context=None, convert_result: bool = False):
            try:
                res =  await original_call_tool(
                    name,
                    arguments,
                    context=context,
                    convert_result= convert_result,
                )
                content = None
                if isinstance(res, tuple) and len(res) > 0:
                    content = res[0]
                elif isinstance(res, list):
                    content = res

                if content and len(content) > 0:
                    first = content[0]

                    text = getattr(first, "text", None)
                    if isinstance(text, str):
                        try:
                            parsed = json.loads(text)
                        except Exception:
                            parsed = None


                    if isinstance(parsed, dict) and "error" in parsed:
                        error = parsed["error"]
                        raise RuntimeError(json.dumps(error)) #original fastmcp sdk adds string before error body - but we need keep clean json to return x402 error in body
                return res
            except Exception as e:
                raise

        patched_call_tool._paymcp_patched = True
        patched_call_tool._paymcp_original = original_call_tool

        tm.call_tool = patched_call_tool
        logger.debug("[PayMCP] Patched FastMCP ToolManager.call_tool")
    
    def _patch_list_tool_for_auto(self):
        if not hasattr(self.mcp, '_tool_manager'):
            logger.warning("[PayMCP] Error patching tools/list for Mode.AUTO - _tool_manager is not available ")
            return  # Should not happen, but guard anyway
        orig = self.mcp._tool_manager.list_tools
        if not orig:
            logger.warning("[PayMCP] Error patching tools/list for Mode.AUTO - list_tools handler is not registered")
            return  # Should not happen, but guard anyway    
    
        # Skip if already patched
        if hasattr(self.mcp._tool_manager.list_tools, '_paymcp_list_tools_patched'):
            return

        def wrapped():
            tools=orig()
            ctx = self.mcp._mcp_server.request_context
            client_info = capture_client_from_ctx(ctx)
            capabilities = client_info.get("capabilities") or {}
            if capabilities.get("elicitation"):
                def tool_name_from(tool):
                    if isinstance(tool, dict):
                        return tool.get("name")
                    return getattr(tool, "name", None)

                def strip_payment_id(tool):
                    if isinstance(tool, dict):
                        schema = tool.get("parameters") or tool.get("inputSchema") or tool.get("input_schema") or tool.get("schema")
                    else:
                        schema = getattr(tool, "parameters", None) or getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or getattr(tool, "schema", None)
                    if not isinstance(schema, dict):
                        return
                    props = schema.get("properties")
                    if not isinstance(props, dict) or "payment_id" not in props:
                        return
                    props = dict(props)
                    props.pop("payment_id", None)
                    schema["properties"] = props
                    required = schema.get("required")
                    if isinstance(required, list) and "payment_id" in required:
                        schema["required"] = [r for r in required if r != "payment_id"]
                    schema.pop("payment_id", None)

                filtered = []
                for tool in tools:
                    tool_name = tool_name_from(tool)
                    if tool_name and tool_name in self.paidtools:
                        strip_payment_id(tool)
                    filtered.append(tool)
                tools = filtered
            return tools
        wrapped._paymcp_list_tools_patched = True
        self.mcp._tool_manager.list_tools = wrapped
        logger.debug("[PayMCP] tools/list handler is patched for Mode.AUTO ")

    def get_x402_middleware(self):
        return build_x402_middleware(self.providers, self.state_store, self.paidtools, self.payment_flow, logger);
