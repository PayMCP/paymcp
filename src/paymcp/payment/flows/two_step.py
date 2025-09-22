# paymcp/payment/flows/two_step.py
import functools
from typing import Dict, Any
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
from ...session import SessionManager, SessionKey, SessionData
import logging
import time
logger = logging.getLogger(__name__)

# Session storage for payment args
session_storage = SessionManager.get_storage()


def make_paid_wrapper(func, mcp, provider, price_info):
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
        provider_name = provider.get_name()
        session_key = SessionKey(provider=provider_name, payment_id=str(payment_id))

        stored = await session_storage.get(session_key)
        logger.debug(f"[confirm_tool] Looking up session with provider={provider_name} payment_id={payment_id}")

        if stored is None:
            raise RuntimeError("Unknown or expired payment_id")

        status = provider.get_payment_status(payment_id)
        if status != "paid":
            raise RuntimeError(
                f"Payment status is {status}, expected 'paid'"
            )
        logger.debug(f"[confirm_tool] Calling {func.__name__} with args: {stored.args}")

        await session_storage.delete(session_key)

        # Call the original tool with its initial arguments
        stored_args = stored.args.get('args', ())
        stored_kwargs = stored.args.get('kwargs', {})
        return await func(*stored_args, **stored_kwargs)

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
        provider_name = provider.get_name()
        session_key = SessionKey(provider=provider_name, payment_id=pid_str)

        # Stash original args with session storage (15 minutes TTL)
        session_data = SessionData(
            args={'args': args, 'kwargs': kwargs},
            ts=int(time.time() * 1000),
            provider_name=provider_name,
            metadata={"tool_name": func.__name__}
        )
        await session_storage.set(session_key, session_data, 900)  # 15 minutes TTL

        # Return data for the user / LLM
        return {
            "status": "pending",
            "message": message,
            "payment_url": payment_url,
            "payment_id": pid_str,
            "next_step": confirm_tool_name,
        }

    return _initiate_wrapper