# paymcp/payment/flows/resubmit.py
import functools
import logging
import inspect
from inspect import Parameter
from typing import Annotated
from pydantic import Field

logger = logging.getLogger(__name__)

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
            await state_store.set(pid_str, kwargs)

            logger.debug(f"[PayMCP:Resubmit] created payment id={pid_str} url={payment_url}")



            msg = (
                "Payment required to execute this tool.\n"
                "Follow the link to complete payment and retry with payment_id.\n\n"
                f"Payment link: {payment_url}\n"
                f"Payment ID: {pid_str}"
            )
            err = RuntimeError(msg)
            err.code = 402
            err.error = "payment_required"
            err.data = {
                "payment_id": pid_str,
                "payment_url": payment_url,
                "retry_instructions": "Follow the link, complete payment, then retry with payment_id.",
                "annotations": {"payment": {"status": "required", "payment_id": pid_str}}
            }
            raise err

        # LOCK: Acquire per-payment-id lock to prevent concurrent access
        # This fixes both ENG-215 (race condition) and ENG-214 (payment loss)
        async with state_store.lock(existed_payment_id):
            logger.debug(f"[resubmit] Lock acquired for payment_id={existed_payment_id}")

            # Get state (don't delete yet)
            stored = await state_store.get(existed_payment_id)
            logger.info(f"[resubmit] State retrieved: {stored is not None}")

            if not stored:
                logger.warning(f"[resubmit] No state found for payment_id={existed_payment_id}")
                err = RuntimeError("Unknown or expired payment_id.")
                err.code = 404
                err.error = "payment_id_not_found"
                err.data = {
                    "payment_id": existed_payment_id,
                    "retry_instructions": "Payment ID not found or already used. Get a new link by calling this tool without payment_id.",
                }
                raise err

            # Check payment status with provider
            raw = provider.get_payment_status(existed_payment_id)
            status = raw.lower() if isinstance(raw, str) else raw
            logger.debug(f"[PayMCP:Resubmit] paymentId {existed_payment_id}, poll status={raw} -> {status}")

            if status in ("canceled", "failed"):
                # Keep state so user can retry after resolving payment issue
                logger.info(f"[resubmit] Payment {status}, state kept for retry")

                err = RuntimeError(
                    f"Payment {status}. User must complete payment to proceed.\nPayment ID: {existed_payment_id}"
                )
                err.code = 402
                err.error = f"payment_{status}"
                err.data = {
                    "payment_id": existed_payment_id,
                    "retry_instructions": (
                        f"Payment {status}. Retry with the same payment_id after resolving the issue, "
                        "or get a new link by calling this tool without payment_id."
                    ),
                    "annotations": {"payment": {"status": status, "payment_id": existed_payment_id}}
                }
                raise err

            if status == "pending":
                # Keep state so user can retry after payment completes
                logger.info(f"[resubmit] Payment pending, state kept for retry")

                err = RuntimeError(
                    f"Payment is not confirmed yet.\nAsk user to complete payment and retry.\nPayment ID: {existed_payment_id}"
                )
                err.code = 402
                err.error = "payment_pending"
                err.data = {
                    "payment_id": existed_payment_id,
                    "retry_instructions": "Wait for confirmation, then retry this tool with payment_id.",
                    "annotations": {"payment": {"status": status, "payment_id": existed_payment_id}}
                }
                raise err

            if status != "paid":
                # Keep state for unknown status
                logger.info(f"[resubmit] Unknown payment status: {status}, state kept for retry")

                err = RuntimeError(
                    f"Unrecognized payment status: {status}.\nRetry once payment is confirmed.\nPayment ID: {existed_payment_id}"
                )
                err.code = 402
                err.error = "payment_unknown"
                err.data = {
                    "payment_id": existed_payment_id,
                    "retry_instructions": "Check payment status and retry once confirmed.",
                    "annotations": {"payment": {"status": status, "payment_id": existed_payment_id}}
                }
                raise err

            # Payment confirmed - execute tool BEFORE deleting state
            logger.info(f"[PayMCP:Resubmit] payment confirmed; invoking original tool {func.__name__}")

            # Execute tool (may fail - state not deleted yet)
            result = await func(*args, **kwargs)

            # Tool succeeded - now delete state to enforce single-use
            await state_store.delete(existed_payment_id)
            logger.info(f"[resubmit] Tool executed successfully, state deleted (single-use enforced)")

        try:
            annotations = getattr(result, "annotations", {}) or {}
            annotations["payment"] = {"status": "paid", "payment_id": existed_payment_id}
            setattr(result, "annotations", annotations)
        except Exception:
            return {
                "content": result,
                "annotations": {"payment": {"status": "paid", "payment_id": existed_payment_id}},
                "raw": result,
            }

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

    return wrapper