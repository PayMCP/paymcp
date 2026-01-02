"""DYNAMIC_TOOLS flow: dynamically hide/show tools per-session during payment.

MCP SDK Compatibility: This implementation patches MCP SDK internals because:
1. SDK has no post-init capability registration API (v1.x)
2. SDK has no dynamic per-session tool filtering hooks (v1.x)

Monitor: https://github.com/modelcontextprotocol/python-sdk for future APIs.
If SDK adds hooks/filters, we can remove patches and use official APIs.
"""
import functools
import uuid
from typing import Dict, Any, Set, NamedTuple
from ...utils.messages import open_link_message
import logging
from ...utils.context import get_ctx_from_server
from ...utils.disconnect import is_disconnected

logger = logging.getLogger(__name__)

# State: payment_id -> (session_id, args)
class PaymentSession(NamedTuple):
    session_id: int  # Session object ID (integer for consistent lookup)
    args: Dict[str, Any]

PAYMENTS: Dict[str, PaymentSession] = {}  # payment_id -> PaymentSession
HIDDEN_TOOLS: Dict[int, Set[str]] = {}  # session_id (int) -> {hidden_tool_names}
CONFIRMATION_TOOLS: Dict[str, int] = {}  # confirm_tool_name -> session_id (int)


async def _send_notification(ctx):
    """Send tools/list_changed notification, ignore failures.

    Uses request_ctx.session.send_tool_list_changed() - official SDK method.
    Failures ignored because notifications are optional (client may not support).
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
        await request_ctx.get().session.send_tool_list_changed()
        logger.info("[dynamic_tools] Sent tools/list_changed notification")
    except Exception:
        # Ignore notification failures - notifications are optional and client may not support them
        # Common failures: AttributeError (no request_ctx), RuntimeError (no session), etc.
        pass


def make_paid_wrapper(func, mcp, providers, price_info, state_store=None, config=None):
    """Wrap tool: initiate payment -> hide tool -> register confirm tool."""
    provider = next(
        (v for k, v in providers.items() if k != "x402"),
        None
    )
    if provider is None:
        raise RuntimeError("[PayMCP] No payment provider configured")

    tool_name = func.__name__
    if hasattr(func, '_paymcp_price_info'):
        delattr(func, '_paymcp_price_info')

    @functools.wraps(func)
    async def _initiate_wrapper(*args, **kwargs):
        # Create payment
        payment_id, payment_url, *_ = provider.create_payment(
            amount=price_info["price"], currency=price_info["currency"], description=f"{tool_name}() execution fee"
        )

        pid = str(payment_id)
        # Extract session ID from ctx parameter (use integer ID for consistency with filter)
        ctx = kwargs.get("ctx", None)
        if ctx is None and mcp is not None:
            try:
                ctx = get_ctx_from_server(mcp)
            except Exception:
                ctx = None
        session_id = id(ctx.session) if ctx and hasattr(ctx, 'session') and ctx.session else uuid.uuid4().int
        confirm_name = f"confirm_{tool_name}_{pid}"

        logger.info(f"[DYNAMIC_TOOLS] Payment initiated: tool={tool_name}, session={session_id}, payment_id={pid}")

        # Store state: payment session, hide tool, track confirm tool
        PAYMENTS[pid] = PaymentSession(session_id, kwargs)
        HIDDEN_TOOLS.setdefault(session_id, set()).add(tool_name)
        CONFIRMATION_TOOLS[confirm_name] = session_id

        logger.info(f"[DYNAMIC_TOOLS] Hidden tools for session {session_id}: {HIDDEN_TOOLS.get(session_id, set())}")

        confirm_tool_args = {
            "name": confirm_name,
            "description": f"Confirm payment {pid} and execute {tool_name}()"
        }

        if config and "meta" in config:
            confirm_tool_args["meta"] = dict(config["meta"])
            confirm_tool_args["meta"].pop("price",None)

        # Register confirmation tool
        @mcp.tool(**confirm_tool_args)
        async def _confirm(ctx=None):
            ps = PAYMENTS.get(pid)
            if not ps:
                return {
                    "content": [{"type": "text", "text": f"Inform user: Payment session {pid} is unknown or has expired. They may need to initiate a new payment."}],
                    "status": "error",
                    "message": "Payment session unknown or expired - inform user to start new payment",
                    "payment_id": pid
                }

            try:
                status = provider.get_payment_status(payment_id)
                if status != "paid":
                    return {
                        "content": [{"type": "text", "text": f"Inform user: Payment not yet completed. Current status: {status}. Ask them to complete payment at: {payment_url}"}],
                        "status": "error",
                        "message": f"Payment status '{status}' - ask user to complete payment",
                        "payment_id": pid
                    }

                # Execute original, cleanup state
                result = await func(**ps.args)

                if await is_disconnected(ctx):
                    logger.warning("[dynamic_tools] Disconnected after payment confirmation; returning pending result")
                    return {
                        "status": "pending",
                        "message": "Connection aborted. Call the tool again to retrieve the result.",
                        "payment_id": pid,
                        "payment_url": payment_url,
                        "annotations": { "payment": { "status": "paid", "payment_id": pid } }
                    }

                del PAYMENTS[pid]

                # Cleanup hidden tools
                if ps.session_id in HIDDEN_TOOLS:
                    HIDDEN_TOOLS[ps.session_id].discard(tool_name)
                    if not HIDDEN_TOOLS[ps.session_id]:
                        del HIDDEN_TOOLS[ps.session_id]

                # Remove confirmation tool
                if hasattr(mcp, '_tool_manager') and confirm_name in mcp._tool_manager._tools:
                    del mcp._tool_manager._tools[confirm_name]
                CONFIRMATION_TOOLS.pop(confirm_name, None)

                await _send_notification(ctx)
                return result

            except Exception as e:
                # Cleanup on error
                if ps.session_id in HIDDEN_TOOLS:
                    HIDDEN_TOOLS[ps.session_id].discard(tool_name)
                    if not HIDDEN_TOOLS[ps.session_id]:
                        del HIDDEN_TOOLS[ps.session_id]
                return {
                    "content": [{"type": "text", "text": f"Inform user: Unable to verify payment status due to technical error: {str(e)}. Ask them to retry or contact support."}],
                    "status": "error",
                    "message": "Technical error checking payment - inform user to retry or contact support",
                    "payment_id": pid
                }

        await _send_notification(ctx)

        # Return payment response (webview removed - STDIO not supported)
        return {
            "message": open_link_message(payment_url, price_info["price"], price_info["currency"]),
            "payment_url": payment_url,
            "payment_id": pid,
            "next_tool": confirm_name,
            "instructions": f"Ask user to complete payment at {payment_url}, then call {confirm_name}"
        }

    return _initiate_wrapper


def setup_flow(mcp, paymcp_instance, payment_flow):
    """Setup: register capabilities and patch tool filtering."""
    _register_capabilities(mcp, payment_flow)
    _patch_list_tools(mcp)


def _register_capabilities(mcp, payment_flow):
    """Patch MCP to advertise tools_changed capability.

    WHY: MCP SDK has no API to register capabilities post-initialization.
    We must patch create_initialization_options() to advertise tools_changed
    so clients know we can emit notifications/tools/list_changed events.

    SDK PR: Not submitted - this is payment flow specific, not SDK's concern.
    The SDK correctly provides tools_changed capability; we just need to enable it.
    """
    if not hasattr(mcp, '_mcp_server') or hasattr(mcp._mcp_server.create_initialization_options, '_paymcp_dynamic_tools_patched'):
        return

    orig = mcp._mcp_server.create_initialization_options

    def patched(notification_options=None, experimental_caps=None):
        # Import NotificationOptions from MCP SDK
        from mcp.server import NotificationOptions

        # Create new NotificationOptions if not provided
        if notification_options is None:
            notification_options = NotificationOptions()

        # Enable tool change notifications
        notification_options.tools_changed = True
        notification_options.prompts_changed = True
        notification_options.resources_changed = True

        return orig(notification_options, {'elicitation': {'enabled': True}, **(experimental_caps or {})})

    patched._paymcp_dynamic_tools_patched = True
    mcp._mcp_server.create_initialization_options = patched


def _defer_list_tools_patch(mcp):
    """Defer list_tools patching until after first tool registration.

    WHY: FastMCP lazy-initializes _tool_manager when first tool is registered.
    If we try to patch before any tools exist, _tool_manager won't exist yet.
    This wrapper ensures patching happens after the first tool is registered.
    """
    original_tool_decorator = mcp.tool

    def wrapped_tool(*args, **kwargs):
        """Wrap mcp.tool() to trigger deferred patch after registration."""
        result = original_tool_decorator(*args, **kwargs)

        # After first tool is registered, _tool_manager should exist
        if hasattr(mcp, '_tool_manager') and not hasattr(mcp._tool_manager.list_tools, '_paymcp_dynamic_tools_patched'):
            logger.debug("First tool registered, applying deferred list_tools patch")
            _patch_list_tools_immediate(mcp)

        return result

    wrapped_tool._paymcp_deferred_patch_applied = True
    mcp.tool = wrapped_tool


def _patch_list_tools_immediate(mcp):
    """Immediately patch list_tools (called after _tool_manager exists)."""
    if not hasattr(mcp, '_tool_manager'):
        return  # Should not happen, but guard anyway

    # Skip if already patched
    if hasattr(mcp._tool_manager.list_tools, '_paymcp_dynamic_tools_patched'):
        return

    orig = mcp._tool_manager.list_tools

    def filtered():
        tools = orig()
        try:
            sid = id(mcp._mcp_server.request_context.session)
            logger.info(f"[DYNAMIC_TOOLS] Filtering tools for session {sid}, HIDDEN_TOOLS={dict(HIDDEN_TOOLS)}, CONFIRMATION_TOOLS={dict(CONFIRMATION_TOOLS)}")
        except LookupError:
            logger.info("[DYNAMIC_TOOLS] No session context (LookupError) - returning all tools")
            return tools  # No session context
        except Exception as e:
            logger.info(f"[DYNAMIC_TOOLS] Session retrieval error: {e} - returning all tools")
            return tools

        hidden = HIDDEN_TOOLS.get(sid, set())
        filtered_tools = [t for t in tools if t.name not in hidden and (t.name not in CONFIRMATION_TOOLS or CONFIRMATION_TOOLS[t.name] == sid)]
        logger.info(f"[DYNAMIC_TOOLS] Session {sid}: {len(tools)} tools -> {len(filtered_tools)} after filtering (hidden={hidden})")
        return filtered_tools

    filtered._paymcp_dynamic_tools_patched = True
    mcp._tool_manager.list_tools = filtered


def _patch_list_tools(mcp):
    """Patch list_tools() to filter per-session hidden tools.

    WHY: MCP SDK has no API for dynamic per-session tool visibility.
    We must patch list_tools() to filter the tool list based on session state,
    hiding original tools during payment and showing confirmation tools only
    to the session that owns them. This enables multi-user isolation.

    SDK PR: COULD submit feature request for list_tools(context) hook/filter.
    However, this is payment-specific logic. SDK should stay generic.
    Current approach: well-isolated, documented, and testable monkey-patch.
    """
    # If _tool_manager doesn't exist yet, defer patching until first tool registered
    if not hasattr(mcp, '_tool_manager'):
        logger.debug("_tool_manager not found, will retry after tool registration")
        # Patch the tool registration to apply list_tools patch after first tool
        if hasattr(mcp, 'tool') and not hasattr(mcp.tool, '_paymcp_deferred_patch_applied'):
            _defer_list_tools_patch(mcp)
        return

    # Skip if already patched (idempotent)
    if hasattr(mcp._tool_manager.list_tools, '_paymcp_dynamic_tools_patched'):
        return

    orig = mcp._tool_manager.list_tools

    def filtered():
        tools = orig()
        # WHY: Use the server's public request_context to get the session ID
        # request_context is a stable property that wraps the SDK's internal ContextVar
        # We use id(session) because session objects are reused per connection
        # This avoids importing low-level symbols like request_ctx
        try:
            # Use the public Server.request_context property to fetch the current session
            # Avoids importing request_ctx from low-level internals.
            sid = id(mcp._mcp_server.request_context.session)
        except LookupError:
            return tools  # No session context (e.g., during testing)
        except Exception:
            return tools

        hidden = HIDDEN_TOOLS.get(sid, set())
        return [t for t in tools if t.name not in hidden and (t.name not in CONFIRMATION_TOOLS or CONFIRMATION_TOOLS[t.name] == sid)]

    filtered._paymcp_dynamic_tools_patched = True
    mcp._tool_manager.list_tools = filtered
