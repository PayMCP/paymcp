import inspect
from .responseSchema import SimpleActionSchema
from types import SimpleNamespace
import logging

logger = logging.getLogger(__name__)


async def run_elicitation_loop(
    ctx, func, message, provider, payment_id, max_attempts=5
):
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
                logger.debug(f"[run_elicitation_loop] Attempt {attempt+1},")
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
            raise RuntimeError("Payment canceled by user")

        status = provider.get_payment_status(payment_id)
        logger.debug(f"[run_elicitation_loop]: payment status = {status}")
        if status == "paid" or status == "canceled":
            return status
    return "pending"
