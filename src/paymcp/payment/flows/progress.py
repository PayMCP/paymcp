# paymcp/payment/flows/progress.py
import asyncio
import functools
import logging
import time
from typing import Any, Dict, Optional
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
from ...session import SessionManager, SessionKey, SessionData

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
    Now with session support for handling timeouts.
    """

    confirm_tool_name = f"confirm_{func.__name__}_payment"

    # Register confirmation tool (like TWO_STEP and ELICITATION)
    @mcp.tool(
        name=confirm_tool_name,
        description=f"Confirm payment and execute {func.__name__}() after progress timeout",
    )
    async def _confirm_tool(payment_id: str):
        logger.info(f"[progress_confirm_tool] Received payment_id={payment_id}")
        provider_name = provider.get_name()
        session_key = SessionKey(provider=provider_name, payment_id=str(payment_id))

        stored = await session_storage.get(session_key)
        logger.debug(
            f"[progress_confirm_tool] Looking up session with provider={provider_name} payment_id={payment_id}"
        )

        if stored is None:
            raise RuntimeError("Unknown or expired payment_id")

        status = provider.get_payment_status(payment_id)
        if status != "paid":
            raise RuntimeError(f"Payment status is {status}, expected 'paid'")
        logger.debug(
            f"[progress_confirm_tool] Calling {func.__name__} with stored args"
        )

        await session_storage.delete(session_key)
        stored_args = stored.args.get("args", ())
        stored_kwargs = stored.args.get("kwargs", {})
        return await func(*stored_args, **stored_kwargs)

    @functools.wraps(func)
    async def _progress_wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        logger.debug(f"[make_paid_wrapper] Starting tool: {func.__name__}")

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
        # Session remains for later confirmation
        return {
            "status": "pending",
            "message": "Payment timeout reached; tool execution pending payment completion.",
            "next_step": confirm_tool_name,
            "payment_id": str(payment_id),
            "payment_url": payment_url,
        }

    return _progress_wrapper
