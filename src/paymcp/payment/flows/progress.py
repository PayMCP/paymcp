# paymcp/payment/flows/progress.py
import asyncio
import functools
import logging
import time
from typing import Any, Dict, Optional
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
from ...session import SessionManager, SessionKey, SessionData
from ...utils.session import extract_session_id

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 3  # how often to poll provider.get_payment_status
MAX_WAIT_SECONDS = 15 * 60  # give up after 15 min

# Session storage for payment args
session_storage = SessionManager.get_storage()


def make_paid_wrapper(
    func,
    mcp,
    provider,
    price_info,
):
    """
    One-step flow that *holds the tool open* and reports progress
    via ctx.report_progress() until the payment is completed.
    Uses session storage for recovery if needed, but does NOT add confirmation tools.
    """

    # No tool registration here - pure progress flow

    @functools.wraps(func)
    async def _progress_wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        logger.debug(f"[make_paid_wrapper] Starting tool: {func.__name__}")

        # Try to extract MCP session ID from context if available
        mcp_session_id = None
        if ctx:
            try:
                mcp_session_id = extract_session_id(ctx)
                if mcp_session_id:
                    logger.debug(f"Extracted MCP session ID: {mcp_session_id}")
            except Exception as e:
                logger.debug(f"Could not extract session ID: {e}")

        # Check if there's a payment_id in kwargs (retry scenario)
        retry_payment_id = kwargs.get("_payment_id") or kwargs.get("payment_id")
        if retry_payment_id:
            logger.debug(
                f"[make_paid_wrapper] Retry detected for payment_id={retry_payment_id}"
            )
            # Check payment status for retry
            try:
                status = provider.get_payment_status(retry_payment_id)
                if status == "paid":
                    logger.info(
                        f"[make_paid_wrapper] Payment {retry_payment_id} already paid, executing tool"
                    )
                    # Remove payment_id from kwargs before calling original function
                    clean_kwargs = {
                        k: v
                        for k, v in kwargs.items()
                        if k not in ["_payment_id", "payment_id"]
                    }
                    return await func(*args, **clean_kwargs)
                elif status == "canceled":
                    logger.info(
                        f"[make_paid_wrapper] Payment {retry_payment_id} was canceled"
                    )
                    return {
                        "status": "canceled",
                        "message": "Previous payment was canceled",
                    }
            except Exception as e:
                logger.warning(
                    f"[make_paid_wrapper] Could not check retry payment status: {e}"
                )
                # Continue with new payment

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
            mcp_session_id=mcp_session_id,
        )
        session_data = SessionData(
            args={"args": args, "kwargs": kwargs},
            ts=int(time.time() * 1000),
            provider_name=provider_name,
            metadata={"tool_name": func.__name__, "for_retry": True},
        )
        await session_storage.set(
            session_key, session_data, ttl_seconds=300
        )  # 5 minute TTL for retries
        logger.debug(
            f"[make_paid_wrapper] Stored session for potential retry of payment_id={payment_id}"
        )

        # Helper to emit progress safely
        async def _notify(message: str, progress: Optional[int] = None):
            if ctx is not None and hasattr(ctx, "report_progress"):
                await ctx.report_progress(
                    message=message,
                    progress=progress or 0,
                    total=100,
                )

        if open_payment_webview_if_available(payment_url):
            message = opened_webview_message(
                payment_url, price_info["price"], price_info["currency"]
            )
        else:
            message = open_link_message(
                payment_url, price_info["price"], price_info["currency"]
            )

        # Initial message with the payment link
        await _notify(
            message,
            progress=0,
        )

        # Poll provider until paid, canceled, or timeout
        waited = 0
        while waited < MAX_WAIT_SECONDS:
            await asyncio.sleep(DEFAULT_POLL_SECONDS)
            waited += DEFAULT_POLL_SECONDS

            status = provider.get_payment_status(payment_id)

            if status == "paid":
                await _notify("Payment received — generating result …", progress=100)
                logger.info(
                    f"[make_paid_wrapper] Payment confirmed, calling {func.__name__}"
                )
                # Clean up session after successful payment
                await session_storage.delete(session_key)
                return await func(*args, **kwargs)

            if status in ("canceled", "expired", "failed"):
                logger.info(f"[make_paid_wrapper] Payment {status}")
                # Clean up session on cancellation/failure
                await session_storage.delete(session_key)
                return {
                    "status": status,
                    "message": f"Payment {status}",
                    "payment_id": str(payment_id),
                    "payment_url": payment_url,
                }

            # Still pending → ping progress
            await _notify(f"Waiting for payment … ({waited}s elapsed)")

        # Loop exhausted - timeout reached
        logger.info(f"[make_paid_wrapper] Payment not received after timeout")
        # Return pending status WITHOUT a tool reference
        # Client can retry the original tool if needed
        return {
            "status": "pending",
            "message": "Payment timeout reached. Please complete payment and try the tool again.",
            "payment_id": str(payment_id),
            "payment_url": payment_url,
            # No next_step tool - client retries original tool
        }

    return _progress_wrapper
