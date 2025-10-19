
# paymcp/payment/flows/elicitation.py
import functools
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
import logging
from ...utils.elicitation import run_elicitation_loop

logger = logging.getLogger(__name__)

def make_paid_wrapper(func, mcp, provider, price_info, state_store=None):
    """
    Single-step payment flow using elicitation during execution.

    Note: state_store parameter is accepted for signature consistency
    but not used by ELICITATION flow.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        logger.debug(f"[make_paid_wrapper] Starting tool: {func.__name__}")

        # 1. Initiate payment
        payment_id, payment_url = provider.create_payment(
            amount=price_info["price"],
            currency=price_info["currency"],
            description=f"{func.__name__}() execution fee"
        )
        logger.debug(f"[make_paid_wrapper] Created payment with ID: {payment_id}")

        if (open_payment_webview_if_available(payment_url)):
            message = opened_webview_message(
                payment_url, price_info["price"], price_info["currency"]
            )
        else:
            message = open_link_message(
                payment_url, price_info["price"], price_info["currency"]
            )

        # 2. Ask the user to confirm payment
        logger.debug(f"[make_paid_wrapper] Calling elicitation {ctx}")
        
        try:
            payment_status = await run_elicitation_loop(ctx, func, message, provider, payment_id)
        except Exception as e:
            logger.warning(f"[make_paid_wrapper] Payment confirmation failed: {e}")
            raise

        if (payment_status=="paid"):
            logger.info(f"[make_paid_wrapper] Payment confirmed, calling {func.__name__}")
            return await func(*args,**kwargs) #calling original function

        if (payment_status=="canceled"):
            logger.info(f"[make_paid_wrapper] Payment canceled")
            return {
                "status": "canceled",
                "message": "Payment canceled by user"
            }
        else:
            logger.info(f"[make_paid_wrapper] Payment not received after retries")
            return {
                "status": "pending",
                "message": "We haven't received the payment yet. Click the button below to check again.",
                "next_step": func.__name__,
                "payment_id": str(payment_id)
            }

    return wrapper