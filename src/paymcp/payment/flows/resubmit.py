# paymcp/payment/flows/resubmit.py
import functools
import logging
import inspect
from inspect import Parameter
from typing import Annotated, Optional
from pydantic import Field
from ...utils.context import get_ctx_from_server
from .state_utils import sanitize_state_args
from ...utils.disconnect import is_disconnected

logger = logging.getLogger(__name__)


def _create_payment_error(
    message: str,
    error_type: str,
    payment_id: str,
    retry_instructions: str,
    code: int = 402,
    payment_url: Optional[str] = None,
    status: Optional[str] = None
) -> RuntimeError:
    """Create a standardized payment error with consistent structure.

    Args:
        message: User-facing error message
        error_type: Error type identifier (e.g., 'payment_required', 'payment_pending')
        payment_id: Payment identifier
        retry_instructions: Instructions for retrying the operation
        code: HTTP status code (default: 402)
        payment_url: Optional payment URL (for payment_required errors)
        status: Optional payment status (for status-related errors)

    Returns:
        RuntimeError with standardized attributes
    """
    err = RuntimeError(message)
    err.code = code
    err.error = error_type
    err.data = {
        "payment_id": payment_id,
        "retry_instructions": retry_instructions,
    }

    if payment_url:
        err.data["payment_url"] = payment_url

    if status:
        err.data["annotations"] = {
            "payment": {"status": status, "payment_id": payment_id}
        }

    return err

def make_paid_wrapper(func, mcp, provider, price_info, state_store=None, config=None):
    """
    Resubmit payment flow .

    Note: state_store parameter is accepted for signature consistency
    but not used by RESUBMIT flow.
    """


    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        logger.debug(f"[PayMCP:Resubmit] wrapper invoked for provider={provider} argsLen={len(args) + len(kwargs)}")
        # Accept top-level kw-only payment_id (added to schema via __signature__) and do not forward it to the original tool
        top_level_payment_id = kwargs.pop("payment_id", None)
        # Expect ctx in kwargs to access payment parameters

        ctx = kwargs.get("ctx", None)
        if ctx is None and mcp is not None:
            try:
                ctx = get_ctx_from_server(mcp)
            except Exception:
                ctx = None

        # Extract tool args from kwargs (SDK-style) or from first positional arg (dict-style)
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            tool_args = kwargs["args"]
        elif len(args) > 0 and isinstance(args[0], dict):
            tool_args = args[0]
        else:
            tool_args = {}
        # Prefer top-level payment_id (schema kw-only), fallback to one nested in args dict
        existed_payment_id = top_level_payment_id or tool_args.get("payment_id") 

        if not existed_payment_id:
            # Create payment session
            logger.debug(f"[PayMCP:Resubmit] creating payment for {price_info}")
            payment_id, payment_url = provider.create_payment(
                amount=price_info["price"],
                currency=price_info["currency"],
                description=f"{func.__name__}() execution fee"
            )

            pid_str = str(payment_id)
            await state_store.set(pid_str, sanitize_state_args(kwargs))

            logger.debug(f"[PayMCP:Resubmit] created payment id={pid_str} url={payment_url}")

            raise _create_payment_error(
                message=(
                    "Payment required to execute this tool.\n"
                    "Follow the link to complete payment and retry with payment_id.\n\n"
                    f"Payment link: {payment_url}\n"
                    f"Payment ID: {pid_str}"
                ),
                error_type="payment_required",
                payment_id=pid_str,
                retry_instructions="Follow the link, complete payment, then retry with payment_id.",
                payment_url=payment_url,
                status="required"
            )

        # LOCK: Acquire per-payment-id lock to prevent concurrent access
        # This fixes both ENG-215 (race condition) and ENG-214 (payment loss)
        async with state_store.lock(existed_payment_id):
            logger.debug(f"[resubmit] Lock acquired for payment_id={existed_payment_id}")

            # Get state (don't delete yet)
            stored = await state_store.get(existed_payment_id)
            logger.info(f"[resubmit] State retrieved: {stored is not None}")

            if not stored:
                logger.warning(f"[resubmit] No state found for payment_id={existed_payment_id}")
                raise _create_payment_error(
                    message="Unknown or expired payment_id.",
                    error_type="payment_id_not_found",
                    payment_id=existed_payment_id,
                    retry_instructions="Payment ID not found or already used. Get a new link by calling this tool without payment_id.",
                    code=404
                )

            # Check payment status with provider
            raw = provider.get_payment_status(existed_payment_id)
            status = raw.lower() if isinstance(raw, str) else raw
            logger.debug(f"[PayMCP:Resubmit] paymentId {existed_payment_id}, poll status={raw} -> {status}")

            if status in ("canceled", "failed"):
                # Keep state so user can retry after resolving payment issue
                logger.info(f"[resubmit] Payment {status}, state kept for retry")
                raise _create_payment_error(
                    message=f"Payment {status}. User must complete payment to proceed.\nPayment ID: {existed_payment_id}",
                    error_type=f"payment_{status}",
                    payment_id=existed_payment_id,
                    retry_instructions=(
                        f"Payment {status}. Retry with the same payment_id after resolving the issue, "
                        "or get a new link by calling this tool without payment_id."
                    ),
                    status=status
                )

            if status == "pending":
                # Keep state so user can retry after payment completes
                logger.info(f"[resubmit] Payment pending, state kept for retry")
                raise _create_payment_error(
                    message=f"Payment is not confirmed yet.\nAsk user to complete payment and retry.\nPayment ID: {existed_payment_id}",
                    error_type="payment_pending",
                    payment_id=existed_payment_id,
                    retry_instructions="Wait for confirmation, then retry this tool with payment_id.",
                    status=status
                )

            if status != "paid":
                # Keep state for unknown status
                logger.info(f"[resubmit] Unknown payment status: {status}, state kept for retry")
                raise _create_payment_error(
                    message=f"Unrecognized payment status: {status}.\nRetry once payment is confirmed.\nPayment ID: {existed_payment_id}",
                    error_type="payment_unknown",
                    payment_id=existed_payment_id,
                    retry_instructions="Check payment status and retry once confirmed.",
                    status=status
                )

            # Payment confirmed - execute tool BEFORE deleting state
            logger.info(f"[PayMCP:Resubmit] payment confirmed; invoking original tool {func.__name__}")

            # Execute tool (may fail - state not deleted yet)
            result = await func(*args, **kwargs)

            # If client disconnected after payment but before sending result, keep state so they can retry fetch
            if await is_disconnected(ctx):
                logger.warning("[resubmit] Disconnected after payment confirmation; returning pending result")
                return {
                    "status": "pending",
                    "message": "Connection aborted. Call the tool again to retrieve the result.",
                    "payment_id": str(existed_payment_id),
                    "annotations": { "payment": { "status": "paid", "payment_id": str(existed_payment_id) } }
                }

            # Tool succeeded - now delete state to enforce single-use
            await state_store.delete(existed_payment_id)
            logger.info(f"[resubmit] Tool executed successfully, state deleted (single-use enforced)")

        # Return result without modifying it - don't change developer's original function return value
        return result


    payment_param = Parameter(
        "payment_id",
        kind=Parameter.KEYWORD_ONLY,
        default="",
        annotation=Annotated[str, Field(
            description="Optional payment identifier returned by a previous call when payment is required"
        )],
    )

    # Insert payment_param before any VAR_KEYWORD (**kwargs) parameter
    try:
        original_params = list(inspect.signature(func).parameters.values())
        new_params = []
        var_keyword_param = None

        for param in original_params:
            if param.kind == Parameter.VAR_KEYWORD:
                var_keyword_param = param
            else:
                new_params.append(param)

        # Add payment_id before **kwargs
        new_params.append(payment_param)

        # Add **kwargs at the end if it existed
        if var_keyword_param:
            new_params.append(var_keyword_param)

        wrapper.__signature__ = inspect.signature(func).replace(parameters=new_params)
    except Exception:
        # If signature inspection fails (e.g., non-function mocks), skip signature override
        pass

    return wrapper