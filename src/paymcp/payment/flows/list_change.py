# paymcp/payment/flows/list_change.py
"""
LIST_CHANGE payment flow implementation.

Dynamically changes the exposed MCP toolset by hiding/showing tools:
1. Initial: Only original tool visible
2. Payment initiated: Hide original, show confirm tool, emit list_changed
3. Payment completed: Remove confirm, restore original, emit list_changed

MULTI-USER SUPPORT:
This flow supports multiple concurrent users via per-session tool filtering:
- State tracking: HIDDEN_TOOLS is keyed by session_id to isolate user state
- Tool filtering: list_tools() responses are filtered per-session (configured in core.py)
- Session IDs: Obtained from FastMCP Context.session_id (or generated as fallback)

Each session sees only their own tool visibility changes. When User A hides a tool,
it remains visible to User B. This is achieved by filtering the tool list response
based on the requesting session's hidden tools, without modifying the global registry.
"""
import functools
from typing import Dict, Any
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
import logging

logger = logging.getLogger(__name__)

# Storage for pending arguments and tool states
# Now keyed by session_id to support multiple concurrent users
PENDING_ARGS: Dict[str, Dict[str, Any]] = {}  # payment_id -> args
HIDDEN_TOOLS: Dict[str, Dict[str, Any]] = {}  # session_id -> {tool_name: tool_info}
SESSION_PAYMENTS: Dict[str, str] = {}  # payment_id -> session_id
SESSION_CONFIRMATION_TOOLS: Dict[str, str] = {}  # confirmation_tool_name -> session_id


def make_paid_wrapper(func, mcp, provider, price_info, state_store=None):
    """
    Implements the LIST_CHANGE payment flow:

    1. Original tool is visible initially
    2. When payment is initiated:
       - Hide the original tool
       - Register confirmation tool
       - Emit tools/list_changed notification
    3. After payment confirmation:
       - Remove confirmation tool
       - Restore original tool
       - Emit tools/list_changed notification
    """

    original_tool_name = func.__name__

    # Store the ORIGINAL function without payment wrapping
    # This is crucial - we need to call the unwrapped version in confirmation
    # Remove the payment metadata to prevent PayMCP from re-wrapping on subsequent calls
    original_unwrapped_func = func
    if hasattr(original_unwrapped_func, '_paymcp_price_info'):
        delattr(original_unwrapped_func, '_paymcp_price_info')

    @functools.wraps(func)
    async def _initiate_wrapper(*args, **kwargs):
        # Extract context if available (FastMCP may pass as kwarg or positional arg)
        ctx = kwargs.get('ctx')

        # If not in kwargs, check if it's the last positional argument and is a Context object
        if ctx is None and args:
            # Check if last arg looks like a Context object
            potential_ctx = args[-1]
            if hasattr(potential_ctx, '_queue_tool_list_changed'):
                ctx = potential_ctx
                logger.debug(f"[list_change] Found context in args[-1]")

        logger.debug(f"[list_change] Wrapper called with {len(args)} args, {len(kwargs)} kwargs")
        logger.debug(f"[list_change] ctx={ctx}, type={type(ctx) if ctx else None}")

        # Get session ID - for StreamableHTTP, use the session object itself as ID
        # The session ID is managed by the transport layer, not the MCP protocol layer
        # We'll use the ServerSession object's identity as the session key
        session_id = None
        try:
            from mcp.server.lowlevel.server import request_ctx
            req_ctx = request_ctx.get()

            # Use the session object itself as the session identifier
            # This works because the same ServerSession object is reused for all requests in a session
            session_id = id(req_ctx.session)
            logger.debug(f"[list_change] Using session object ID: {session_id}")
        except Exception as e:
            logger.warning(f"[list_change] Could not get session ID from request context: {e}")

        # Fallback to random UUID for unsupported servers (multi-user isolation)
        if session_id is None:
            import uuid
            session_id = str(uuid.uuid4())
            logger.warning(f"[list_change] No session ID found, using random UUID: {session_id}")

        # Create payment with provider
        payment_id, payment_url = provider.create_payment(
            amount=price_info["price"],
            currency=price_info["currency"],
            description=f"{func.__name__}() execution fee"
        )

        pid_str = str(payment_id)
        # Store kwargs for replay during confirmation
        # Keep 'ctx' parameter as it's required by Python tool signatures
        PENDING_ARGS[pid_str] = kwargs
        SESSION_PAYMENTS[pid_str] = session_id  # Track which session owns this payment

        # Create confirmation tool name with FULL payment ID
        confirm_tool_name = f"confirm_{original_tool_name}_{pid_str}"

        logger.info(f"[list_change] Session {session_id}: Hiding tool: {original_tool_name}")
        logger.info(f"[list_change] Session {session_id}: Registering confirmation tool: {confirm_tool_name}")

        # STEP 1: Mark the original tool as hidden for this session
        # Initialize session storage if needed
        if session_id not in HIDDEN_TOOLS:
            HIDDEN_TOOLS[session_id] = {}

        # Mark tool as hidden for this session (per-session filtering in core.py will handle visibility)
        HIDDEN_TOOLS[session_id][original_tool_name] = True
        logger.debug(f"[list_change] Session {session_id}: Tool {original_tool_name} marked as hidden (per-session filtering active)")

        # Track that this confirmation tool belongs to this session
        SESSION_CONFIRMATION_TOOLS[confirm_tool_name] = session_id
        logger.debug(f"[list_change] Session {session_id}: Confirmation tool {confirm_tool_name} registered for session")

        # STEP 2: Register confirmation tool
        @mcp.tool(
            name=confirm_tool_name,
            description=f"Confirm payment {pid_str} and execute {func.__name__}()"
        )
        async def _confirm_tool(ctx=None):
            """Confirmation tool for this specific payment."""
            logger.info(f"[list_change_confirm] Confirming payment_id={pid_str}")

            # Get the session ID that owns this payment
            owner_session_id = SESSION_PAYMENTS.get(pid_str)
            if owner_session_id is None:
                logger.error(f"[list_change_confirm] No session found for payment_id={pid_str}")
                return {
                    "error": f"Unknown or expired payment_id: {pid_str}",
                    "status": "failed"
                }

            # Retrieve stored arguments
            original_args = PENDING_ARGS.get(pid_str)
            if original_args is None:
                logger.error(f"[list_change_confirm] No pending args for payment_id={pid_str}")
                return {
                    "error": f"Unknown or expired payment_id: {pid_str}",
                    "status": "failed"
                }

            try:
                # Check payment status with provider
                status = provider.get_payment_status(payment_id)
                logger.debug(f"[list_change_confirm] Payment status: {status}")

                if status != "paid":
                    return {
                        "error": f"Payment not completed. Status: {status}",
                        "status": "pending",
                        "payment_url": payment_url
                    }

                # Payment successful - execute original function
                # FIXME: This triggers a new payment creation instead of executing the original function
                # Root cause unknown - needs debugger investigation
                # - original_unwrapped_func is the function with @price decorator metadata
                # - Calling it directly should NOT go through payment wrapping
                # - But somehow it creates a new payment with different payment_id
                logger.info(f"[list_change_confirm] Payment confirmed, executing {original_unwrapped_func.__name__}")
                result = await original_unwrapped_func(**original_args)

                # Clean up stored arguments and session tracking
                del PENDING_ARGS[pid_str]
                del SESSION_PAYMENTS[pid_str]

                # STEP 3: Restore original tool and remove confirmation tool
                logger.info(f"[list_change] Session {owner_session_id}: Restoring tool: {original_tool_name}")
                logger.info(f"[list_change] Session {owner_session_id}: Removing confirmation tool: {confirm_tool_name}")

                # Unmark tool as hidden for this session (per-session filtering will show it again)
                if owner_session_id in HIDDEN_TOOLS and original_tool_name in HIDDEN_TOOLS[owner_session_id]:
                    del HIDDEN_TOOLS[owner_session_id][original_tool_name]
                    # Clean up empty session dict
                    if not HIDDEN_TOOLS[owner_session_id]:
                        del HIDDEN_TOOLS[owner_session_id]
                    logger.debug(f"[list_change] Session {owner_session_id}: Tool {original_tool_name} unmarked (will be visible again)")

                # Remove confirmation tool from global registry
                if hasattr(mcp, '_tool_manager'):
                    tools_dict = mcp._tool_manager._tools
                    if confirm_tool_name in tools_dict:
                        del tools_dict[confirm_tool_name]
                        logger.debug(f"[list_change] Session {owner_session_id}: Confirmation tool {confirm_tool_name} removed")

                # Remove from session confirmation tracking
                if confirm_tool_name in SESSION_CONFIRMATION_TOOLS:
                    del SESSION_CONFIRMATION_TOOLS[confirm_tool_name]
                    logger.debug(f"[list_change] Session {owner_session_id}: Removed confirmation tool from session tracking")

                # Emit tools/list_changed notification after restoring tools
                try:
                    from mcp.server.lowlevel.server import request_ctx
                    req_ctx = request_ctx.get()
                    await req_ctx.session.send_tool_list_changed()
                    logger.info("[list_change_confirm] ✅ Sent tools/list_changed notification after restore")
                except Exception as e:
                    logger.warning(f"[list_change_confirm] Failed to send notification after restore: {e}")

                return result

            except Exception as e:
                logger.error(f"[list_change_confirm] Error checking payment: {e}")

                # On error, still try to restore state
                if owner_session_id in HIDDEN_TOOLS and original_tool_name in HIDDEN_TOOLS[owner_session_id]:
                    del HIDDEN_TOOLS[owner_session_id][original_tool_name]
                    # Clean up empty session dict
                    if not HIDDEN_TOOLS[owner_session_id]:
                        del HIDDEN_TOOLS[owner_session_id]

                return {
                    "error": f"Error confirming payment: {str(e)}",
                    "status": "error"
                }

        # STEP 4: Emit tools/list_changed notification after hiding original tool
        # Access the session via context variable to send notification
        try:
            from mcp.server.lowlevel.server import request_ctx
            req_ctx = request_ctx.get()
            await req_ctx.session.send_tool_list_changed()
            logger.info("[list_change] ✅ Sent tools/list_changed notification")
        except Exception as e:
            logger.warning(f"[list_change] Failed to send tools/list_changed notification: {e}")

        # Prepare response message
        if open_payment_webview_if_available(payment_url):
            message = opened_webview_message(
                payment_url, price_info["price"], price_info["currency"]
            )
        else:
            message = open_link_message(
                payment_url, price_info["price"], price_info["currency"]
            )

        # Return payment initiation response
        return {
            "message": message,
            "payment_url": payment_url,
            "payment_id": pid_str,
            "next_tool": confirm_tool_name,
            "instructions": f"Complete payment at {payment_url}, then call {confirm_tool_name}"
        }

    return _initiate_wrapper
