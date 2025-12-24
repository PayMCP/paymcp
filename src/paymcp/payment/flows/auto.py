# paymcp/payment/flows/auto.py
import functools
import inspect
import logging
from inspect import Parameter
from typing import Annotated
from pydantic import Field
from ...utils.context import get_ctx_from_server, capture_client_from_ctx
from .elicitation import make_paid_wrapper as make_elicitation_wrapper
from .resubmit import make_paid_wrapper as make_resubmit_wrapper

logger = logging.getLogger(__name__)


def make_paid_wrapper(func, mcp, provider, price_info, state_store=None, config=None):
    """
    Auto-select payment flow based on client capabilities.
    If the client supports elicitation, use the elicitation flow; otherwise, fall back to resubmit.
    """
    resubmit_wrapper = make_resubmit_wrapper(
        func=func,
        mcp=mcp,
        provider=provider,
        price_info=price_info,
        state_store=state_store,
        config=config,
    )
    elicitation_wrapper = make_elicitation_wrapper(
        func=func,
        mcp=mcp,
        provider=provider,
        price_info=price_info,
        state_store=state_store,
        config=config,
    )

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        if ctx is None and mcp is not None:
            try:
                ctx = get_ctx_from_server(mcp)
                if ctx is not None:
                    kwargs["ctx"] = ctx
            except Exception:
                ctx = None

        client_info = capture_client_from_ctx(ctx)
        capabilities = client_info.get("capabilities") or {}
        logger.debug(f"[PayMCP Auto] Client capabilities: {capabilities}")

        if capabilities.get("elicitation"):
            # payment_id is only needed for resubmit; drop it to avoid leaking to tools that don't expect it
            kwargs.pop("payment_id", None)
            logger.debug("[PayMCP Auto] Using elicitation flow")
            return await elicitation_wrapper(*args, **kwargs)

        logger.debug("[PayMCP Auto] Using resubmit flow")
        return await resubmit_wrapper(*args, **kwargs)

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
