# paymcp/payment/flows/two_step.py
import functools
import logging
from ...utils.messages import open_link_message
from ...utils.context import get_ctx_from_server
from ...utils.disconnect import is_disconnected

logger = logging.getLogger(__name__)


def make_paid_wrapper(func, mcp, provider, price_info, state_store=None, config=None):
    """
    Implements the two‑step payment flow:

    1. The original tool is wrapped by an *initiate* step that returns
       `payment_url` and `payment_id` to the client.
    2. A dynamically registered tool `confirm_<tool>` waits for payment,
       validates it, and only then calls the original function.
    """

    confirm_tool_name = f"confirm_{func.__name__}_payment"

    confirm_tool_args = {
        "name": confirm_tool_name,
        "description": f"Confirm payment and execute {func.__name__}(). Call this only after the user confirms the payment"
    }

    if config and "meta" in config:
        confirm_tool_args["meta"] = config["meta"]

    # --- Step 2: payment confirmation -----------------------------------------
    @mcp.tool(**confirm_tool_args)
    async def _confirm_tool(payment_id: str):
        logger.info(f"[confirm_tool] Received payment_id={payment_id}")
        ctx = get_ctx_from_server(mcp)
        if not payment_id:
            return {
                "content": [{"type": "text", "text": "Missing payment_id."}],
                "status": "error",
                "message": "Missing payment_id"
            }

        stored = await state_store.get(str(payment_id))
        logger.info(f"[confirm_tool] State retrieved: {stored is not None}")
        if not stored:
            logger.warning(f"[confirm_tool] No state found for payment_id={payment_id}")
            return {
                "content": [{"type": "text", "text": "Unknown or expired payment_id."}],
                "status": "error",
                "message": "Unknown or expired payment_id",
                "payment_id": payment_id
            }

        status = provider.get_payment_status(payment_id)
        logger.info(f"[confirm_tool] Payment status: {status}")
        if status != "paid":
            return {
                "content": [{"type": "text", "text": f"Payment status is {status}, expected 'paid'."}],
                "status": "error",
                "message": f"Payment status is {status}, expected 'paid'",
                "payment_id": payment_id
            }

        logger.info(f"[confirm_tool] Deleting state for payment_id={payment_id}")
        result = await func(**stored["args"])
        if await is_disconnected(ctx):
            logger.warning("[PAYMCP Elicitation] aborted after payment confirmation but before returning tool result.")
            return {
                "status": "pending",
                "message": "Connection aborted. Call the tool again to retrieve the result.",
                "payment_id": str(payment_id),
                "annotations": { "payment": { "status": "paid", "payment_id": str(payment_id) } }
            }
        await state_store.delete(str(payment_id))
        logger.info(f"[confirm_tool] State deleted, executing tool")
        return result

    # --- Step 1: payment initiation -------------------------------------------
    @functools.wraps(func)
    async def _initiate_wrapper(*args, **kwargs):
        payment_id, payment_url = provider.create_payment(
            amount=price_info["price"],
            currency=price_info["currency"],
            description=f"{func.__name__}() execution fee"
        )

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
