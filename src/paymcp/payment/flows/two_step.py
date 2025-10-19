# paymcp/payment/flows/two_step.py
import functools
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
import logging
logger = logging.getLogger(__name__)


def make_paid_wrapper(func, mcp, provider, price_info, state_store=None):
    """
    Implements the two‑step payment flow:

    1. The original tool is wrapped by an *initiate* step that returns
       `payment_url` and `payment_id` to the client.
    2. A dynamically registered tool `confirm_<tool>` waits for payment,
       validates it, and only then calls the original function.
    """

    confirm_tool_name = f"confirm_{func.__name__}_payment"

    # --- Step 2: payment confirmation -----------------------------------------
    @mcp.tool(
        name=confirm_tool_name,
        description=f"Confirm payment and execute {func.__name__}()"
    )
    async def _confirm_tool(payment_id: str):
        logger.info(f"[confirm_tool] Received payment_id={payment_id}")
        stored = await state_store.get(str(payment_id))
        if not stored:
            raise RuntimeError("Unknown or expired payment_id")

        status = provider.get_payment_status(payment_id)
        if status != "paid":
            raise RuntimeError(f"Payment status is {status}, expected 'paid'")

        await state_store.delete(str(payment_id))
        return await func(**stored["args"])

    # --- Step 1: payment initiation -------------------------------------------
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
        await state_store.set(pid_str, kwargs)

        # Return data for the user / LLM
        return {
            "message": message,
            "payment_url": payment_url,
            "payment_id": pid_str,
            "next_step": confirm_tool_name,
        }

    return _initiate_wrapper


def setup_flow(mcp, paymcp_instance, payment_flow):
    """
    Setup function called by core.py to initialize TWO_STEP flow.

    TWO_STEP flow requires a state_store to persist payment arguments between
    initiation and confirmation steps. If not provided by the user, we create
    a default InMemoryStateStore.
    """
    if paymcp_instance.state_store is None:
        from ...state import InMemoryStateStore
        paymcp_instance.state_store = InMemoryStateStore()
        logger.debug("[TWO_STEP] Created default InMemoryStateStore")