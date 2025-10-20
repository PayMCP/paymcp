"""LIST_CHANGE flow: dynamically hide/show tools per-session during payment.

MCP SDK Compatibility: This implementation patches MCP SDK internals because:
1. SDK has no post-init capability registration API (v1.x)
2. SDK has no dynamic per-session tool filtering hooks (v1.x)

Monitor: https://github.com/modelcontextprotocol/python-sdk for future APIs.
If SDK adds hooks/filters, we can remove patches and use official APIs.
"""
import functools
import uuid
from typing import Dict, Any, Set, NamedTuple
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
import logging

logger = logging.getLogger(__name__)

# State: payment_id -> (session_id, args)
class PaymentSession(NamedTuple):
    session_id: str
    args: Dict[str, Any]

PAYMENTS: Dict[str, PaymentSession] = {}  # payment_id -> PaymentSession
HIDDEN_TOOLS: Dict[str, Set[str]] = {}  # session_id -> {hidden_tool_names}
CONFIRMATION_TOOLS: Dict[str, str] = {}  # confirm_tool_name -> session_id


def _get_session_id() -> str:
    """Get session ID from MCP context, fallback to UUID.

    Uses request_ctx (official SDK pattern) to get session object.
    Returns id(session) as unique identifier per connection.
    Fallback to UUID for servers without session support.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
        return str(id(request_ctx.get().session))
    except Exception:
        return str(uuid.uuid4())


async def _send_notification():
    """Send tools/list_changed notification, ignore failures.

    Uses request_ctx.session.send_tool_list_changed() - official SDK method.
    Failures ignored because notifications are optional (client may not support).
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
        await request_ctx.get().session.send_tool_list_changed()
        logger.info("[list_change] Sent tools/list_changed notification")
    except Exception:
        pass


def make_paid_wrapper(func, mcp, provider, price_info, state_store=None):
    """Wrap tool: initiate payment -> hide tool -> register confirm tool."""
    tool_name = func.__name__
    if hasattr(func, '_paymcp_price_info'):
        delattr(func, '_paymcp_price_info')

    @functools.wraps(func)
    async def _initiate_wrapper(*args, **kwargs):
        # Create payment
        payment_id, payment_url = provider.create_payment(
            amount=price_info["price"], currency=price_info["currency"], description=f"{tool_name}() execution fee"
        )

        pid = str(payment_id)
        session_id = _get_session_id()
        confirm_name = f"confirm_{tool_name}_{pid}"

        # Store state: payment session, hide tool, track confirm tool
        PAYMENTS[pid] = PaymentSession(session_id, kwargs)
        HIDDEN_TOOLS.setdefault(session_id, set()).add(tool_name)
        CONFIRMATION_TOOLS[confirm_name] = session_id

        # Register confirmation tool
        @mcp.tool(name=confirm_name, description=f"Confirm payment {pid} and execute {tool_name}()")
        async def _confirm(ctx=None):
            ps = PAYMENTS.get(pid)
            if not ps:
                return {
                    "content": [{"type": "text", "text": f"Unknown or expired payment_id: {pid}"}],
                    "status": "error",
                    "message": "Unknown or expired payment_id",
                    "payment_id": pid
                }

            try:
                status = provider.get_payment_status(payment_id)
                if status != "paid":
                    return {
                        "content": [{"type": "text", "text": f"Payment not completed. Status: {status}\\nPayment URL: {payment_url}"}],
                        "status": "error",
                        "message": f"Payment status is {status}, expected 'paid'",
                        "payment_id": pid
                    }

                # Execute original, cleanup state
                result = await func(**ps.args)
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

                await _send_notification()
                return result

            except Exception as e:
                # Cleanup on error
                if ps.session_id in HIDDEN_TOOLS:
                    HIDDEN_TOOLS[ps.session_id].discard(tool_name)
                    if not HIDDEN_TOOLS[ps.session_id]:
                        del HIDDEN_TOOLS[ps.session_id]
                return {
                    "content": [{"type": "text", "text": f"Error confirming payment: {str(e)}"}],
                    "status": "error",
                    "message": "Failed to confirm payment",
                    "payment_id": pid
                }

        await _send_notification()

        # Return payment response
        msg_fn = opened_webview_message if open_payment_webview_if_available(payment_url) else open_link_message
        return {
            "message": msg_fn(payment_url, price_info["price"], price_info["currency"]),
            "payment_url": payment_url,
            "payment_id": pid,
            "next_tool": confirm_name,
            "instructions": f"Complete payment at {payment_url}, then call {confirm_name}"
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
    if not hasattr(mcp, '_mcp_server') or hasattr(mcp._mcp_server.create_initialization_options, '_paymcp_list_change_patched'):
        return

    orig = mcp._mcp_server.create_initialization_options

    def patched(notification_options=None, experimental_caps=None):
        from mcp.server.lowlevel.server import NotificationOptions
        notification_options = notification_options or NotificationOptions(tools_changed=True)
        notification_options.tools_changed = True
        return orig(notification_options, {'elicitation': {'enabled': True}, **(experimental_caps or {})})

    patched._paymcp_list_change_patched = True
    mcp._mcp_server.create_initialization_options = patched


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
    if not hasattr(mcp, '_tool_manager') or hasattr(mcp._tool_manager.list_tools, '_paymcp_list_change_patched'):
        return

    orig = mcp._tool_manager.list_tools

    def filtered():
        tools = orig()
        # WHY: Use request_ctx to get session ID - this IS the official SDK pattern
        # request_ctx is a ContextVar that tracks current request's session object
        # We use id(session) because session objects are reused per connection
        # SDK PR: Not needed - this is correct usage per SDK design
        try:
            from mcp.server.lowlevel.server import request_ctx
            sid = id(request_ctx.get().session)
        except Exception:
            return tools  # No session context (e.g., during testing)

        hidden = HIDDEN_TOOLS.get(sid, set())
        return [t for t in tools if t.name not in hidden and (t.name not in CONFIRMATION_TOOLS or CONFIRMATION_TOOLS[t.name] == sid)]

    filtered._paymcp_list_change_patched = True
    mcp._tool_manager.list_tools = filtered
