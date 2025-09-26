import inspect
from .responseSchema import SimpleActionSchema
from types import SimpleNamespace
import logging

logger = logging.getLogger(__name__)


async def run_elicitation_loop(
    ctx, func, message, provider, payment_id, max_attempts=5
):
    # Check if this payment is already completed (for pre-population on reconnect)
    try:
        initial_status = provider.get_payment_status(payment_id)
        if initial_status == "paid":
            logger.info(f"[run_elicitation_loop] Payment {payment_id} already paid")
            return "paid"
        elif initial_status == "canceled":
            logger.info(f"[run_elicitation_loop] Payment {payment_id} already canceled")
            return "canceled"
    except Exception as e:
        logger.debug(f"[run_elicitation_loop] Could not check initial payment status: {e}")
    
    # Quick mode: if PAYMCP_QUICK_MODE is set, do fewer attempts with shorter waits
    import os
    quick_mode = os.getenv("PAYMCP_QUICK_MODE", "false").lower() == "true"
    if quick_mode:
        max_attempts = min(2, max_attempts)  # Only 2 attempts in quick mode
    
    for attempt in range(max_attempts):
        try:
            # Try to check if response_type is supported
            try:
                sig = inspect.signature(ctx.elicit)
                has_response_type = "response_type" in sig.parameters
            except (TypeError, ValueError):
                # If we can't inspect (e.g., Mock object), assume it doesn't have response_type
                has_response_type = False

            if has_response_type:
                logger.debug(f"[run_elicitation_loop] Attempt {attempt+1}")
                elicitation = await ctx.elicit(message=message, response_type=None)
            else:
                elicitation = await ctx.elicit(
                    message=message, schema=SimpleActionSchema
                )
        except Exception as e:
            logger.warning(f"[run_elicitation_loop] Elicitation failed: {e}")
            msg = str(e).lower()
            if "unexpected elicitation action" in msg:
                if "accept" in msg:
                    logger.debug(
                        "[run_elicitation_loop] Treating 'accept' action as confirmation"
                    )
                    elicitation = SimpleNamespace(action="accept")
                elif any(x in msg for x in ("cancel", "decline")):
                    logger.debug(
                        "[run_elicitation_loop] Treating 'cancel/decline' action as user cancellation"
                    )
                    elicitation = SimpleNamespace(action="cancel")
                else:
                    raise RuntimeError(
                        "Elicitation failed during confirmation loop."
                    ) from e
            else:
                raise RuntimeError(
                    "Elicitation failed during confirmation loop."
                ) from e

        logger.debug(f"[run_elicitation_loop] Elicitation response: {elicitation}")

        if elicitation.action == "cancel" or elicitation.action == "decline":
            logger.debug("[run_elicitation_loop] User canceled payment")
            return "canceled"  # Return canceled status instead of raising

        status = provider.get_payment_status(payment_id)
        logger.debug(f"[run_elicitation_loop]: payment status = {status}")
        if status == "paid" or status == "canceled":
            return status
    return "pending"
