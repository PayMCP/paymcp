# paymcp/payment/flows/elicitation.py
import functools
import time
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
import logging
from ...utils.elicitation import run_elicitation_loop
from ...session import SessionManager, SessionKey, SessionData
from ...utils.session import extract_session_id

logger = logging.getLogger(__name__)

# Session storage for payment args
session_storage = SessionManager.get_storage()


def make_paid_wrapper(func, mcp, provider, price_info):
    """
    Single-step payment flow using elicitation during execution.
    Uses elicitation to handle payment confirmation without adding tools.
    Session storage provides recovery mechanism for timeouts.
    """

    # No tool registration here - pure elicitation flow

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        logger.debug(f"[make_paid_wrapper] Starting tool: {func.__name__}")

        # Try to extract MCP session ID from context if available
        mcp_session_id = None
        if ctx:
            try:
                mcp_session_id = extract_session_id(ctx)
                logger.debug(f"Extracted MCP session ID: {mcp_session_id}")
            except Exception as e:
                logger.debug(f"Could not extract session ID: {e}")

        # Check if there's a payment_id in kwargs (retry scenario)
        retry_payment_id = kwargs.get("_payment_id") or kwargs.get("payment_id")
        if retry_payment_id:
            logger.debug(f"[make_paid_wrapper] Retry detected for payment_id={retry_payment_id}")
            # Check payment status for retry
            try:
                status = provider.get_payment_status(retry_payment_id)
                if status == "paid":
                    logger.info(f"[make_paid_wrapper] Payment {retry_payment_id} already paid, executing tool")
                    # Remove payment_id from kwargs before calling original function
                    clean_kwargs = {k: v for k, v in kwargs.items() if k not in ["_payment_id", "payment_id"]}
                    return await func(*args, **clean_kwargs)
                elif status == "canceled":
                    logger.info(f"[make_paid_wrapper] Payment {retry_payment_id} was canceled")
                    return {"status": "canceled", "message": "Previous payment was canceled"}
            except Exception as e:
                logger.warning(f"[make_paid_wrapper] Could not check retry payment status: {e}")
                # Continue with new payment

        # 1. Initiate payment
        payment_id, payment_url = provider.create_payment(
            amount=price_info["price"],
            currency=price_info["currency"],
            description=f"{func.__name__}() execution fee",
        )
        logger.debug(f"[make_paid_wrapper] Created payment with ID: {payment_id}")

        # Store session for recovery (if client needs to retry after timeout)
        # But NOT for a confirmation tool - just for potential retry
        provider_name = provider.get_name()
        session_key = SessionKey(
            provider=provider_name, 
            payment_id=str(payment_id),
            mcp_session_id=mcp_session_id
        )
        session_data = SessionData(
            args={"args": args, "kwargs": kwargs},
            ts=int(time.time() * 1000),
            provider_name=provider_name,
            metadata={"tool_name": func.__name__, "for_retry": True},
        )
        await session_storage.set(session_key, session_data, ttl_seconds=300)  # 5 minute TTL for retries
        logger.debug(f"[make_paid_wrapper] Stored session for potential retry of payment_id={payment_id}")

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
            # Return pending status WITHOUT a tool reference
            # Client can retry the original tool if needed
            return {
                "status": "pending",
                "message": "Payment pending. Please complete payment and try the tool again.",
                "payment_id": str(payment_id),
                "payment_url": payment_url,
                # No next_step tool - client retries original tool
            }

    return wrapper
