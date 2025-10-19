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
        self._register_capabilities(payment_flow)
        self._patch_tool()
        if payment_flow == PaymentFlow.LIST_CHANGE:
            self._patch_list_tools()

    def _get_provider(self):
        """Get the first available payment provider"""
        if not self.providers:
            raise RuntimeError("No payment provider configured")
        return next(iter(self.providers.values()))

    def _register_capabilities(self, payment_flow: PaymentFlow):
        """
        Register MCP capabilities based on payment flow.

        **WHY THIS PATCHING EXISTS**:
        The MCP SDK (as of v1.x) has NO library-level API for capability registration.
        To advertise capabilities like 'elicitation' and 'tools_changed' (required for LIST_CHANGE flow),
        we must patch the server's create_initialization_options() method.

        **RISKS AND LIMITATIONS**:
        - INVASIVE: Modifies internal SDK methods
        - RE-INITIALIZATION: If developers manually re-initialize the server, this patch may conflict
        - SDK UPDATES: Future SDK versions might change internal APIs, breaking this approach

        **ALTERNATIVES CONSIDERED**:
        1. Manual capability setting by developers - Rejected: Poor developer experience
        2. Wait for SDK library-level API - Rejected: No ETA from SDK team
        3. Current approach - Chosen: Works today, documented risks

        **FUTURE IMPROVEMENT**:
        TODO: Create ticket to explore cleaner capability registration when SDK provides API
        See: https://github.com/modelcontextprotocol/sdk/issues/XXX (TODO: Create issue)

        **OFFICIAL SDK PATTERN**:
        Session tracking uses the official SDK pattern:
        ```python
        from mcp.server.lowlevel.server import request_ctx
        req_ctx = request_ctx.get()
        session_id = id(req_ctx.session)
        ```
        This is NOT custom complexity - it's the recommended approach per SDK documentation.
        """
        try:
            # Access the underlying low-level MCP server
            if hasattr(self.mcp, '_mcp_server'):
                server = self.mcp._mcp_server

                # Guard against double-patching on re-initialization
                if hasattr(server.create_initialization_options, '_paymcp_patched'):
                    logger.debug("[PayMCP] create_initialization_options already patched, skipping")
                    return

                # Build experimental capabilities dict
                experimental_capabilities = {}

                # Always advertise elicitation capability (all flows can use it)
                experimental_capabilities['elicitation'] = {'enabled': True}

                # Save reference to original method
                original_create_init_options = server.create_initialization_options

                def patched_create_init_options(notification_options=None, experimental_caps=None):
                    # Import NotificationOptions from MCP SDK
                    from mcp.server.lowlevel.server import NotificationOptions

                    # Create or modify notification_options for LIST_CHANGE flow
                    if payment_flow == PaymentFlow.LIST_CHANGE:
                        if notification_options is None:
                            notification_options = NotificationOptions(tools_changed=True)
                        else:
                            # Update existing notification_options
                            notification_options.tools_changed = True

                    # Merge our experimental_capabilities with any provided ones
                    merged_caps = {**experimental_capabilities, **(experimental_caps or {})}
                    return original_create_init_options(notification_options, merged_caps)

                # Mark as patched to prevent double-patching
                patched_create_init_options._paymcp_patched = True

                server.create_initialization_options = patched_create_init_options

                logger.debug(f"✅ Registered capabilities for {payment_flow.value} flow: {experimental_capabilities}")
                logger.debug("[PayMCP] ⚠️  Patched create_initialization_options() - avoid manual server re-initialization")
        except Exception as e:
            logger.warning(f"⚠️ Could not register capabilities: {e}")

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
                    # --- Create payment using provider ---
                    provider = self._get_provider()

                    # Deferred payment creation, so do not call provider.create_payment here
                    kwargs["description"] = description_with_price(kwargs.get("description") or func.__doc__ or "", price_info)

                    # Pass state_store only to TWO_STEP flow
                    if self.payment_flow == PaymentFlow.TWO_STEP:
                        target_func = self._wrapper_factory(
                            func, self.mcp, provider, price_info, self.state_store
                        )
                    else:
                        target_func = self._wrapper_factory(
                            func, self.mcp, provider, price_info
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
                        # --- Create payment using provider ---
                        provider = self._get_provider()

                        # Deferred payment creation, so do not call provider.create_payment here
                        kwargs["description"] = description_with_price(kwargs.get("description") or func.__doc__ or "", price_info)

                        # Pass state_store only to TWO_STEP flow
                        if self.payment_flow == PaymentFlow.TWO_STEP:
                            target_func = self._wrapper_factory(
                                func, self.mcp, provider, price_info, self.state_store
                            )
                        else:
                            target_func = self._wrapper_factory(
                                func, self.mcp, provider, price_info
                            )
                    else:
                        target_func = func

                    return original_tool(*args, **kwargs)(target_func)
                return wrapper

        self.mcp.tool = patched_tool

    def _patch_list_tools(self):
        """
        Patch tool_manager.list_tools() to filter out hidden tools for LIST_CHANGE flow.

        This enables per-session tool visibility by checking the HIDDEN_TOOLS dict
        from the list_change flow module and filtering tools accordingly.
        """
        logger.debug("[PayMCP] Patching list_tools() for LIST_CHANGE flow")

        try:
            # Access the tool manager
            if not hasattr(self.mcp, '_tool_manager'):
                logger.warning("[PayMCP] No _tool_manager found, cannot patch list_tools()")
                return

            tool_manager = self.mcp._tool_manager
            original_list_tools = tool_manager.list_tools

            def filtered_list_tools():
                """Filtered version of list_tools that respects HIDDEN_TOOLS per session"""
                # Get all tools from original method (synchronous)
                all_tools = original_list_tools()

                # Get session ID to check for hidden tools
                session_id = None
                try:
                    from mcp.server.lowlevel.server import request_ctx
                    req_ctx = request_ctx.get()
                    session_id = id(req_ctx.session)
                except Exception as e:
                    logger.debug(f"[PayMCP] Could not get session ID in list_tools: {e}")

                if session_id is None:
                    # No session context - return all tools unfiltered
                    logger.debug("[PayMCP] list_tools: No session context, returning all tools")
                    return all_tools

                # Import HIDDEN_TOOLS and SESSION_CONFIRMATION_TOOLS from list_change flow
                try:
                    from .payment.flows.list_change import HIDDEN_TOOLS, SESSION_CONFIRMATION_TOOLS
                except ImportError:
                    logger.warning("[PayMCP] Could not import HIDDEN_TOOLS from list_change flow")
                    return all_tools

                # Filter out hidden tools for this session
                session_hidden = HIDDEN_TOOLS.get(session_id, {})

                # Filter tools:
                # 1. Remove tools in session_hidden (original tools that are hidden for this session)
                # 2. Remove confirmation tools that belong to OTHER sessions
                filtered_tools = []
                for tool in all_tools:
                    # Hide original tools marked as hidden for this session
                    if tool.name in session_hidden:
                        continue

                    # If this is a confirmation tool, only show it to the owning session
                    if tool.name in SESSION_CONFIRMATION_TOOLS:
                        tool_owner_session = SESSION_CONFIRMATION_TOOLS[tool.name]
                        if tool_owner_session != session_id:
                            # This confirmation tool belongs to a different session - hide it
                            continue

                    filtered_tools.append(tool)

                hidden_count = len(all_tools) - len(filtered_tools)
                logger.debug(f"[PayMCP] list_tools: Session {session_id} filtered {hidden_count} tools")

                return filtered_tools

            # Replace the list_tools method
            tool_manager.list_tools = filtered_list_tools
            logger.debug("[PayMCP] ✅ list_tools() patched for per-session filtering")

        except Exception as e:
            logger.error(f"[PayMCP] Failed to patch list_tools(): {e}")
