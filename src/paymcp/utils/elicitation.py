import inspect
from .responseSchema import SimpleActionSchema
from types import SimpleNamespace
import logging
import asyncio
from .context import capture_client_from_ctx
logger = logging.getLogger(__name__)

PROGRESS_INTERVAL_SECONDS = 3

async def _send_progress(ctx):
    if ctx is not None and hasattr(ctx, "report_progress"):
        logger.debug(f"[run_elicitation_loop] sending progress nitification,")
        await ctx.report_progress(
            message="Waiting for payment confirmation...",
            progress=5,
            total=100,
         )

async def _progress_reporter(ctx, stop_event: asyncio.Event, interval: int = PROGRESS_INTERVAL_SECONDS):
    """Background task that emits progress until stop_event is set."""
    try:
        while not stop_event.is_set():
            await asyncio.sleep(interval)
            if stop_event.is_set():
                break
            await _send_progress(ctx)
    except asyncio.CancelledError:
        # Normal on shutdown
        pass

async def run_elicitation_loop(ctx, func, message, provider, payment_id, max_attempts=5):

    client_info = capture_client_from_ctx(ctx)
    logger.debug(f"[PayMCP] Client info: {client_info}")

    for attempt in range(max_attempts):
        stop_event = None
        progress_task = None
        try:
            if ctx is not None and hasattr(ctx, "report_progress"):
                stop_event = asyncio.Event()
                progress_task = asyncio.create_task(_progress_reporter(ctx, stop_event))

            if "response_type" in inspect.signature(ctx.elicit).parameters:
                logger.debug(f"[run_elicitation_loop] Attempt {attempt+1},")
                elicitation = await ctx.elicit(
                    message=message,
                    response_type=None
                )
            else:
                elicitation = await ctx.elicit(
                    message=message,
                    schema=SimpleActionSchema
                )
        except Exception as e:
            logger.warning(f"[run_elicitation_loop] Elicitation failed: {e}")
            msg = str(e).lower()
            if "unexpected elicitation action" in msg:
                if "accept" in msg:
                    logger.debug("[run_elicitation_loop] Treating 'accept' action as confirmation")
                    elicitation = SimpleNamespace(action="accept")
                elif any(x in msg for x in ("cancel", "decline")):
                    logger.debug("[run_elicitation_loop] Treating 'cancel/decline' action as user cancellation")
                    elicitation = SimpleNamespace(action="cancel")
                else:
                    raise RuntimeError("Elicitation failed during confirmation loop.") from e
            else:
                raise RuntimeError("Elicitation failed during confirmation loop.") from e
        except asyncio.CancelledError as ae:
            logger.debug(f"[run_elicitation_loop] Elicitation timeout")
            raise
        finally:
            if stop_event is not None:
                stop_event.set()
            if progress_task is not None:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
        
        logger.debug(f"[run_elicitation_loop] Elicitation response: {elicitation}")

        if elicitation.action == "cancel" or elicitation.action == "decline":
            logger.debug("[run_elicitation_loop] User canceled payment")
            raise RuntimeError("Payment canceled by user")

        status = provider.get_payment_status(payment_id)
        logger.debug(f"[run_elicitation_loop]: payment status = {status}")
        if status == "paid" or status == "canceled":
            return status 
    return "pending"
