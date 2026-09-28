# paymcp/payment/flows/progress.py
import asyncio
import functools
from typing import Optional
from ...utils.messages import open_link_message
from ...utils.disconnect import is_disconnected
from .state_utils import (
    RESULT_NS_SESSION,
    call_fingerprint,
    clear_completed_result,
    peek_completed_result,
    save_completed_result,
)
from ...utils.context import get_ctx_from_server, get_stable_session_id

DEFAULT_POLL_SECONDS = 3          # how often to poll provider.get_payment_status
MAX_WAIT_SECONDS = 15 * 60        # give up after 15 min 


def make_paid_wrapper(
    func,
    mcp,
    providers,
    price_info,
    state_store=None,
    config=None
):
    """
    One-step flow that *holds the tool open* and reports progress
    via ctx.report_progress() until the payment is completed.

    If state_store is provided, payment state is persisted per-session
    (func+session_id) so reconnects reuse an existing payment instead
    of creating a new one.
    """
    provider = next(
        (v for k, v in providers.items() if k != "x402"),
        None
    )
    if provider is None:
        raise RuntimeError("[PayMCP] No payment provider configured")

    @functools.wraps(func)
    async def _progress_wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        if ctx is None and mcp is not None:
            try:
                ctx = get_ctx_from_server(mcp)
            except Exception:
                ctx = None

        async def _notify(message: str, progress: Optional[int] = None):
            if ctx is not None and hasattr(ctx, "report_progress"):
                try:
                    await ctx.report_progress(
                        message=message,
                        progress=progress or 0,
                        total=100,
                    )
                except TypeError:
                    return

        session_id = get_stable_session_id(ctx)

        payment_id = None
        payment_url = None
        payment_status = None
        message = None
        state_key = f"{func.__name__}:{session_id}" if session_id is not None else None

        # The tool already ran and was paid for, but the client dropped before
        # receiving the result: return the stored one instead of polling for a
        # new payment and running the tool again. The state key covers every call
        # this session makes to this tool, so the result is only served back to
        # the call that produced it.
        fingerprint = call_fingerprint(kwargs, args)
        has_result, cached_result = await peek_completed_result(
            state_store, state_key, RESULT_NS_SESSION, func.__name__, fingerprint
        )
        if has_result:
            if await is_disconnected(ctx):
                return {
                    "status": "pending",
                    "message": "Connection aborted. Call the tool again to retrieve the result.",
                }
            # Unlike the payment-keyed flows, this key is reused by later calls,
            # so the result is dropped once delivered - otherwise the next
            # identical call would be served from cache instead of being paid for.
            await clear_completed_result(
                state_store, state_key, RESULT_NS_SESSION, func.__name__, fingerprint
            )
            await state_store.delete(state_key)
            return cached_result

        # Try to restore existing payment for this session
        if state_store is not None and state_key is not None:
            stored = await state_store.get(state_key)
            if stored:
                payment_id = stored.get("payment_id")
                payment_url = stored.get("payment_url")
                if payment_id and payment_url:
                    payment_status = provider.get_payment_status(payment_id)
                    if payment_status in ("paid", "pending"):
                        message = open_link_message(
                            payment_url, price_info["price"], price_info["currency"]
                        )
                    else:
                        await state_store.delete(state_key)
                        payment_id = None
                        payment_url = None
                        payment_status = None

        # No stored payment -> create new one
        if payment_id is None or payment_url is None:
            payment_id, payment_url, *_ = provider.create_payment(
                amount=price_info["price"],
                currency=price_info["currency"],
                description=f"{func.__name__}() execution fee"
            )
            message = open_link_message(
                payment_url, price_info["price"], price_info["currency"]
            )

            if state_store is not None and state_key is not None:
                await state_store.set(state_key, {"payment_id": payment_id, "payment_url": payment_url})
        else:
            # We found stored payment but no message built yet
            if message is None:
                message = open_link_message(
                    payment_url, price_info["price"], price_info["currency"]
                )

        # If not already paid, send initial progress and poll
        if payment_status != "paid":
            await _notify(message, progress=0)

            waited = 0
            while waited < MAX_WAIT_SECONDS:
                await asyncio.sleep(DEFAULT_POLL_SECONDS)
                waited += DEFAULT_POLL_SECONDS

                status = provider.get_payment_status(payment_id)

                if status == "paid":
                    await _notify("Payment received — generating result …", progress=100)
                    break

                if status in ("canceled", "expired", "failed"):
                    if state_store is not None and state_key is not None:
                        await state_store.delete(state_key)
                    raise RuntimeError(f"Payment status is {status}, expected 'paid'")

                await _notify(f"Waiting for payment … ({waited}s elapsed)")

            else:  # loop exhausted
                if state_store is not None and state_key is not None:
                    await state_store.delete(state_key)
                raise RuntimeError("Payment timeout reached; aborting")

        # Call the underlying tool with its original args/kwargs
        result = await func(*args, **kwargs)
        if await is_disconnected(ctx):
            await save_completed_result(
                state_store, state_key, result, RESULT_NS_SESSION,
                func.__name__, fingerprint,
            )
            return {
                "status": "pending",
                "message": "Connection aborted. Call the tool again to retrieve the result.",
                "payment_id": str(payment_id),
                "payment_url": payment_url,
                "annotations": { "payment": { "status": "paid", "payment_id": str(payment_id) } }
            }
        if state_store is not None and state_key is not None:
            await state_store.delete(state_key)

        return result

    return _progress_wrapper
