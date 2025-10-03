# paymcp/payment/flows/two_step.py
import functools
from typing import Dict, Any, Optional
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
from ...state import StateStore, InMemoryStateStore
import logging
logger = logging.getLogger(__name__)

# Default in-memory store (can be overridden with state_store parameter)
_default_state_store: Optional[StateStore] = None


def make_paid_wrapper(func, mcp, provider, price_info, state_store: Optional[StateStore] = None):
    """
    Implements the two‑step payment flow:

    1. The original tool is wrapped by an *initiate* step that returns
       `payment_url` and `payment_id` to the client.
    2. A dynamically registered tool `confirm_<tool>` waits for payment,
       validates it, and only then calls the original function.

    Args:
        func: The original tool function to wrap
        mcp: MCP server instance
        provider: Payment provider instance
        price_info: Dictionary with 'price' and 'currency' keys
        state_store: Optional StateStore for persisting pending args (defaults to InMemoryStateStore)
    """
    # Initialize state store if not provided
    global _default_state_store
    if state_store is None:
        if _default_state_store is None:
            _default_state_store = InMemoryStateStore()
        state_store = _default_state_store

    confirm_tool_name = f"confirm_{func.__name__}_payment"

    # --- Step 2: payment confirmation -----------------------------------------
    @mcp.tool(
        name=confirm_tool_name,
        description=f"Confirm payment and execute {func.__name__}()"
    )
    async def _confirm_tool(payment_id: str):
        logger.info(f"[confirm_tool] Received payment_id={payment_id}")

        # Retrieve from state store
        stored_data = await state_store.get(str(payment_id))
        logger.debug(f"[confirm_tool] Retrieved data: {stored_data}")

        if stored_data is None:
            raise RuntimeError("Unknown or expired payment_id")

        original_args = stored_data.get('args')
        if original_args is None:  # pragma: no cover
            raise RuntimeError("Invalid stored data for payment_id")

        status = provider.get_payment_status(payment_id)
        if status != "paid":
            raise RuntimeError(
                f"Payment status is {status}, expected 'paid'"
            )
        logger.debug(f"[confirm_tool] Calling {func.__name__} with args: {original_args}")

        # Delete from state store
        await state_store.delete(str(payment_id))

        # Call the original tool with its initial arguments
        return await func(**original_args)

    # --- Step 1: payment initiation -------------------------------------------
    @functools.wraps(func)
    async def _initiate_wrapper(*args, **kwargs):
        payment_id, payment_url = provider.create_payment(
            amount=price_info["price"],
            currency=price_info["currency"],
            description=f"{func.__name__}() execution fee"
        )

        if (open_payment_webview_if_available(payment_url)):
            message = opened_webview_message(
                payment_url, price_info["price"], price_info["currency"]
            )
        else:
            message = open_link_message(
                payment_url, price_info["price"], price_info["currency"]
            )

        pid_str = str(payment_id)
        # Store args in state store
        await state_store.set(pid_str, kwargs)

        # Return data for the user / LLM
        return {
            "message": message,
            "payment_url": payment_url,
            "payment_id": pid_str,
            "next_step": confirm_tool_name,
        }

    return _initiate_wrapper
