# paymcp/payment/flows/elicitation.py
import functools
import time
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
import logging
from ...utils.elicitation import run_elicitation_loop
from ...session import SessionManager, SessionKey, SessionData

logger = logging.getLogger(__name__)

# Session storage for payment args
session_storage = SessionManager.get_storage()


def make_paid_wrapper(func, mcp, provider, price_info):
    """
    Single-step payment flow using elicitation during execution.
    Now with session support for handling timeouts.
    """

    confirm_tool_name = f"confirm_{func.__name__}_payment"

    # Register confirmation tool (like TWO_STEP)
    @mcp.tool(
        name=confirm_tool_name,
        description=f"Confirm payment and execute {func.__name__}() after elicitation timeout",
    )
    async def _confirm_tool(payment_id: str):
        logger.info(f"[elicitation_confirm_tool] Received payment_id={payment_id}")
        provider_name = provider.get_name()
        session_key = SessionKey(provider=provider_name, payment_id=str(payment_id))

        stored = await session_storage.get(session_key)
        logger.debug(
            f"[elicitation_confirm_tool] Looking up session with provider={provider_name} payment_id={payment_id}"
        )

        if stored is None:
            raise RuntimeError("Unknown or expired payment_id")

        status = provider.get_payment_status(payment_id)
        if status != "paid":
            raise RuntimeError(f"Payment status is {status}, expected 'paid'")
        logger.debug(
            f"[elicitation_confirm_tool] Calling {func.__name__} with stored args"
        )

        await session_storage.delete(session_key)
        stored_args = stored.args.get("args", ())
        stored_kwargs = stored.args.get("kwargs", {})
        return await func(*stored_args, **stored_kwargs)

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        logger.debug(f"[make_paid_wrapper] Starting tool: {func.__name__}")

        # 1. Initiate payment
        payment_id, payment_url = provider.create_payment(
            amount=price_info["price"],
            currency=price_info["currency"],
            description=f"{func.__name__}() execution fee",
        )
        logger.debug(f"[make_paid_wrapper] Created payment with ID: {payment_id}")

        # Store session for later confirmation (in case of timeout)
        provider_name = provider.get_name()
        session_key = SessionKey(provider=provider_name, payment_id=str(payment_id))
        session_data = SessionData(
            args={"args": args, "kwargs": kwargs},
            ts=int(time.time() * 1000),
            provider_name=provider_name,
        )
        await session_storage.set(session_key, session_data)
        logger.debug(f"[make_paid_wrapper] Stored session for payment_id={payment_id}")

        if open_payment_webview_if_available(payment_url):
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
            payment_status = await run_elicitation_loop(
                ctx, func, message, provider, payment_id
            )
        except Exception as e:
            logger.warning(f"[make_paid_wrapper] Payment confirmation failed: {e}")
            raise

        if payment_status == "paid":
            logger.info(
                f"[make_paid_wrapper] Payment confirmed, calling {func.__name__}"
            )
            # Clean up session after successful payment
            await session_storage.delete(session_key)
            return await func(*args, **kwargs)  # calling original function

        if payment_status == "canceled":
            logger.info(f"[make_paid_wrapper] Payment canceled")
            # Clean up session on cancellation
            await session_storage.delete(session_key)
            return {"status": "canceled", "message": "Payment canceled by user"}
        else:
            logger.info(f"[make_paid_wrapper] Payment not received after retries")
            # Session remains for later confirmation
            return {
                "status": "pending",
                "message": "We haven't received the payment yet. Click the button below to check again.",
                "next_step": confirm_tool_name,  # Use confirmation tool
                "payment_id": str(payment_id),
                "payment_url": payment_url,
            }

    return wrapper
