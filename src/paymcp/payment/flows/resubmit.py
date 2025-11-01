# paymcp/payment/flows/resubmit.py
import functools
from ...utils.messages import open_link_message
import logging

logger = logging.getLogger(__name__)

def make_paid_wrapper(func, mcp, provider, price_info, state_store=None):
    """
    Resubmit payment flow .

    Note: state_store parameter is accepted for signature consistency
    but not used by RESUBMIT flow.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        logger.debug(f"[PayMCP:Resubmit] wrapper invoked for provider={provider} argsLen={len(args) + len(kwargs)}")

        # Expect ctx in kwargs to access payment parameters

        # Extract tool args from kwargs (SDK-style) or from first positional arg (dict-style)
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            tool_args = kwargs["args"]
        elif len(args) > 0 and isinstance(args[0], dict):
            tool_args = args[0]
        else:
            tool_args = {}
        existed_payment_id = tool_args.get("payment_id") 

        if not existed_payment_id:
            # Create payment session
            payment_id, payment_url = provider.create_payment(
                amount=price_info["amount"],
                currency=price_info["currency"],
                description=f"{func.__name__}() execution fee"
            )
            logger.debug(f"[PayMCP:Resubmit] created payment id={payment_id} url={payment_url}")

            msg = (
                "Payment required to execute this tool.\n"
                "Follow the link to complete payment and retry with payment_id.\n\n"
                f"Payment link: {payment_url}\n"
                f"Payment ID: {payment_id}"
            )
            err = RuntimeError(msg)
            err.code = 402
            err.error = "payment_required"
            err.data = {
                "payment_id": payment_id,
                "payment_url": payment_url,
                "retry_instructions": "Follow the link, complete payment, then retry with payment_id.",
                "annotations": {"payment": {"status": "required", "payment_id": payment_id}}
            }
            raise err

        raw = provider.get_payment_status(existed_payment_id)
        status = raw.lower() if isinstance(raw, str) else raw
        logger.debug(f"[PayMCP:Resubmit] paymentId {existed_payment_id}, poll status={raw} -> {status}")

        if status in ("canceled", "failed"):
            err = RuntimeError(
                f"Payment {status}. User must complete payment to proceed.\nPayment ID: {existed_payment_id}"
            )
            err.code = 402
            err.error = f"payment_{status}"
            err.data = {
                "payment_id": existed_payment_id,
                "retry_instructions": (
                    "User canceled or failed payment. If they want to continue, "
                    "get the new link by calling this tool without payment_id."
                ),
                "annotations": {"payment": {"status": status, "payment_id": existed_payment_id}}
            }
            raise err

        if status == "pending":
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

        # Otherwise status == "paid", execute original tool
        logger.info(f"[PayMCP:Resubmit] payment confirmed; invoking original tool {func.__name__}")
        result = await func(*args, **kwargs)

        try:
            annotations = getattr(result, "annotations", {}) or {}
            annotations["payment"] = {"status": "paid", "payment_id": existed_payment_id}
            setattr(result, "annotations", annotations)
        except Exception:
            return {
                "content": [{"type": "text", "text": "Tool completed after payment."}],
                "annotations": {"payment": {"status": "paid", "payment_id": existed_payment_id}},
                "raw": result,
            }

        return result

    return wrapper