# paymcp/payment/flows/elicitation.py
import functools
import logging
from ...utils.disconnect import is_disconnected
from ...utils.messages import open_link_message
from ...utils.elicitation import run_elicitation_loop
from ...utils.context import get_ctx_from_server

logger = logging.getLogger(__name__)


def make_paid_wrapper(func, mcp, provider, price_info, state_store=None, config=None):
    """
    Single-step payment flow using elicitation during execution.

    Note: state_store is required to resume a payment after reconnects.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        if ctx is None and mcp is not None:
            try:
                ctx = get_ctx_from_server(mcp)
            except Exception:
                ctx = None
        logger.debug(f"[PAYMCP Elicitation] Starting tool: {func.__name__}")
        session_id = id(ctx.session) if ctx and hasattr(ctx, 'session') and ctx.session else None

        if (session_id is None):
            logger.debug(f"[PayMCP Elicitation]. Can't initiate a payment: No session_id provided")
            raise RuntimeError("No Session ID provided.")

        if state_store is None:
            raise RuntimeError("No state store provided for elicitation flow.")

        payment_id = None
        payment_url = None
        payment_status = None
        message = None
        state_key = f"{func.__name__}:{session_id}"

        logger.debug(f"[PAYMCP Elicitation] Checking for previous payments (state_key={state_key}) ")
        stored = await state_store.get(state_key)
        if stored:
            payment=stored.get("args")
            payment_id = payment.get("payment_id")
            payment_url = payment.get("payment_url")
            if payment_id and payment_url:
                payment_status = provider.get_payment_status(payment_id)
                if payment_status in ("paid", "pending"):
                    message = open_link_message(
                        payment_url, price_info["price"], price_info["currency"]
                    )
                    logger.debug(f"[PAYMCP Elicitation] Reusing existing payment {payment_id} with status={payment_status}")
                else:
                    logger.debug(f"[PAYMCP Elicitation] Discarding stale payment {payment_id} with status={payment_status}")
                    await state_store.delete(state_key)
                    payment_id = None
                    payment_url = None
                    payment_status = None

        # Initiate or re-use payment
        if (payment_id is None or payment_url is None):
            payment_id, payment_url = provider.create_payment(
                amount=price_info["price"],
                currency=price_info["currency"],
                description=f"{func.__name__}() execution fee"
            )
            message = open_link_message(
                payment_url, price_info["price"], price_info["currency"]
            )
            await state_store.set(state_key, {"payment_id": payment_id, "payment_url": payment_url})
            logger.debug(f"[PAYMCP Elicitation] Created payment with ID: {payment_id} (state_key={state_key}) ")
        else:
            logger.debug(f"[PAYMCP Elicitation] reusing existed payment_url {payment_url}")

        if (payment_status!='paid'):
            logger.debug(f"[PAYMCP Elicitation] Calling elicitation {ctx}")
            try:
                # Ask the user to complete payment
                payment_status = await run_elicitation_loop(ctx, func, message, provider, payment_id)
            except Exception as e:
                logger.warning(f"[PAYMCP Elicitation] Payment confirmation failed: {e}")
                raise

        if (payment_status=="paid"):
            logger.info(f"[PAYMCP Elicitation] Payment confirmed, calling {func.__name__}")
            result = await func(*args,**kwargs) # calling original function
            if await is_disconnected(ctx):
                logger.warning("[PAYMCP Elicitation] aborted after payment confirmation but before returning tool result.")
                return {
                    "status": "pending",
                    "message": "Connection aborted. Call the tool again to retrieve the result.",
                    "payment_id": str(payment_id),
                    "payment_url": payment_url,
                    "annotations": { "payment": { "status": "paid", "payment_id": str(payment_id) } }
                }
            await state_store.delete(state_key)
            return result

        if (payment_status=="canceled"):
            logger.info(f"[PAYMCP Elicitation] Payment canceled")
            await state_store.delete(state_key)
            return {
                "status": "canceled",
                "message": "Payment canceled by user"
            }
        else:
            logger.info(f"[PAYMCP Elicitation] Payment not received after retries")
            return {
                "status": "pending",
                "message": "We haven't received the payment yet.",
                "payment_id": str(payment_id),
                "payment_url": payment_url
            }

    return wrapper
