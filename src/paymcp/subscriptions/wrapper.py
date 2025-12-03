# paymcp/subscriptions/wrapper.py
import logging
import json
import functools
import inspect
from typing import Any, Dict, List, Optional, Tuple, Callable, Awaitable
from ..utils.jwt import parse_jwt_paylod
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _safe_get(obj: Any, *keys: str) -> Any:
    """
    Retrieve a value from a dict/object by multiple possible keys/attributes.
    Returns the first non-empty value or None.
    """
    if obj is None:
        return None

    for key in keys:
        # attr
        if hasattr(obj, key):
            value = getattr(obj, key)
            if value is not None:
                return value
        # dict
        if isinstance(obj, dict) and key in obj:
            value = obj.get(key)
            if value is not None:
                return value
    return None



def _get_bearer_token_from_ctx(ctx: Any, log: logging.Logger) -> Optional[str]:
    """Best-effort extraction of a Bearer token from FastMCP-style Context.

    This avoids taking a hard dependency on FastMCP's auth_context and instead
    reads the Authorization header from the underlying Starlette Request.
    """
    if ctx is None:
        return None

    request_context = getattr(ctx, "request_context", None)
    if request_context is None:
        return None

    req = getattr(request_context, "request", None)
    if req is None:
        return None

    headers = getattr(req, "headers", None)
    if headers is None:
        return None

    try:
        auth = headers.get("authorization") or headers.get("Authorization")
    except Exception:
        auth = None

    if not auth:
        return None

    # Starlette headers are str, but be defensive
    if isinstance(auth, bytes):
        try:
            auth = auth.decode("latin1")
        except Exception:
            return None

    auth_str = auth.strip()
    if not auth_str.lower().startswith("bearer "):
        return None

    token = auth_str.split(" ", 1)[1].strip()
    if not token:
        return None

    log.info("[PayMCP:Subscriptions] extracted Bearer token from Authorization header")
    return token


def _extract_auth_identity(ctx: Any, tool_name: str, log: logging.Logger) -> Tuple[str, Optional[str]]:
    """
    Extracts userId and email from extra.authInfo and/or JWT.
    Raises an error if userId is not found.
    """
    # authInfo can be either an object attribute or a dict key (with different casings)
    auth_info = None

    # 1) Try to read authInfo directly from ctx (attribute or dict)
    if ctx is not None:
        auth_info = _safe_get(ctx, "authInfo", "auth_info", "AuthInfo")

    if auth_info is None and isinstance(ctx, dict):
        auth_info = (
            ctx.get("authInfo")
            or ctx.get("auth_info")
            or ctx.get("AuthInfo")
        )

    # 2) Try to read authInfo from ctx.request_context (attribute or dict)
    request_context = getattr(ctx, "request_context", None) if ctx is not None else None
    if auth_info is None and request_context is not None:
        auth_info = _safe_get(request_context, "authInfo", "auth_info", "AuthInfo")
        if auth_info is None and isinstance(request_context, dict):
            auth_info = (
                request_context.get("authInfo")
                or request_context.get("auth_info")
                or request_context.get("AuthInfo")
            )

    # 3) Try to read authInfo from ctx.request_context.meta (attribute or dict)
    if auth_info is None and request_context is not None:
        meta = getattr(request_context, "meta", None)
        if meta is not None:
            if isinstance(meta, dict):
                auth_info = (
                    meta.get("authInfo")
                    or meta.get("auth_info")
                    or meta.get("AuthInfo")
                )
            else:
                auth_info = (
                    getattr(meta, "authInfo", None)
                    or getattr(meta, "auth_info", None)
                    or getattr(meta, "AuthInfo", None)
                )

    token = _safe_get(auth_info, "token")
    user_id = _safe_get(auth_info, "userId", "user_id")
    email = _safe_get(auth_info, "email")

    # If still no token, try to get it from the Context's HTTP headers
    if not token:
        token = _get_bearer_token_from_ctx(ctx, log)

    token_data = None

    # Only parse JWT as a fallback when user_id or email are still missing
    if (not user_id or not email) and token:
        log.info(
            "[PayMCP:Subscriptions] user_id/email missing before JWT fallback: user_id=%r, email=%r",
            user_id,
            email,
        )
        token_data = parse_jwt_paylod(token)
        if token_data is not None:
            log.info(
                "[PayMCP:Subscriptions] parsed token data: %s",
                token_data,
            )

    if not user_id and token_data:
        user_id = token_data.get("sub")
    if not email and token_data:
        email = token_data.get("email") or token_data.get("username")

    log.info(
        "[PayMCP:Subscriptions] resolved identity: user_id=%r, email=%r",
        user_id,
        email,
    )

    if not user_id:
        log.error(
            "User ID is required in authInfo for subscription tools (tool: %s)",
            tool_name,
        )
        raise RuntimeError("Not authorized")

    return str(user_id), (str(email) if email is not None else None)


# ---------------------------------------------------------------------------
# Subscription checks
# ---------------------------------------------------------------------------

async def ensure_subscription_allowed(
    provider: Any,
    subscription_info: Any,
    user_id: str,
    email: Optional[str],
    tool_name: str,
    log: logging.Logger,
) -> None:
    """
    Checks that the user has at least one of the required subscription plans.

    subscription_info.plan can be:
      - a string (one required plan)
      - a list of strings (any of the listed plans)
    """
    if not subscription_info:
        return

    # get plan from dict or object
    raw = None
    if isinstance(subscription_info, dict):
        raw = subscription_info.get("plan")
    else:
        raw = getattr(subscription_info, "plan", None)

    required_plans: List[str] = []
    if isinstance(raw, list):
        required_plans = [
            str(pid)
            for pid in raw
            if isinstance(pid, str) and len(pid) > 0
        ]
    elif isinstance(raw, str) and raw:
        required_plans = [raw]

    if not required_plans:
        return

    # request subscriptions from provider
    try:
        subs_result = provider.get_subscriptions(user_id, email)
    except Exception as err:  # noqa: BLE001
        msg = str(getattr(err, "message", None) or err)

        if "Subscriptions are not supported for this payment provider" in msg:
            log.warning(
                "[PayMCP:Subscriptions] provider does not support subscriptions "
                "(tool=%s): %s",
                tool_name,
                msg,
            )
            raise RuntimeError(
                "Subscriptions are required for this tool, but the current payment "
                "provider does not support subscription checks."
            ) from err

        log.error(
            "[PayMCP:Subscriptions] error while checking subscriptions (tool=%s): %s",
            tool_name,
            msg,
        )
        raise

    current_subs = (
        subs_result.get("current_subscriptions")
        if isinstance(subs_result, dict)
        else None
    )
    if current_subs is None and isinstance(subs_result, dict):
        current_subs = subs_result.get("currentSubscriptions")

    if not isinstance(current_subs, list):
        current_subs = []

    # normalize: keep only planId + status
    normalized = []
    for sub in current_subs:
        if not isinstance(sub, dict):
            continue

        plan_id = (
            sub.get("planId")
            or sub.get("priceId")
            or sub.get("plan_id")
        )
        status = str(sub.get("status", "")).lower()
        if isinstance(plan_id, str) and plan_id:
            normalized.append({"planId": plan_id, "status": status})

    def _is_active_status(s: str) -> bool:
        return s in ("active", "trialing", "past_due")

    has_required = any(
        _is_active_status(s["status"]) and s["planId"] in required_plans
        for s in normalized
    )

    if not has_required:
        available = (
            subs_result.get("available_subscriptions")
            if isinstance(subs_result, dict)
            else None
        )
        if available is None and isinstance(subs_result, dict):
            available = subs_result.get("availableSubscriptions") or []

        if not isinstance(available, list):
            available = []

        log.info(
            "[PayMCP:Subscriptions] subscription required for tool=%s, "
            "userId=%s, requiredPlans=%s",
            tool_name,
            user_id,
            ",".join(required_plans),
        )

        error_payload = {
            "error": "subscription_required",
            "message": (
                "A subscription is required to use this tool. "
                "Please purchase one of the required plans."
            ),
            "tool": tool_name,
            "available_subscriptions": available,
        }

        # the caller expects JSON in the error text
        raise RuntimeError(json.dumps(error_payload))



# ---------------------------------------------------------------------------
# Main wrapper for subscriptions
# ---------------------------------------------------------------------------

def make_subscription_wrapper(
    func: Callable[..., Awaitable[Any]],
    mcp: Any,
    provider: Any,
    subscription_info: Any,
    tool_name: str,
    state_store: Any = None,  # currently unused, for signature compatibility
    config: Any = None,       # currently unused, for signature compatibility
    custom_logger: Optional[logging.Logger] = None,
) -> Callable[..., Awaitable[Any]]:
    """
    Wraps an MCP tool, checking for a suitable subscription
    before executing the original function.

    This wrapper is designed for FastMCP-style tools that accept:
      - original positional/keyword arguments
      - a context object passed as the `ctx` keyword argument
    """

    log: logging.Logger = custom_logger or getattr(provider, "logger", logger)

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any):
        ctx = kwargs.get("ctx", None)
        if ctx is None and args:
            # Fallback: if ctx is passed positionally as the last argument
            ctx = args[-1]

        # Additional fallback: try to obtain a context-like object from the MCP server
        if ctx is None and mcp is not None:
            try:
                ctx = _get_ctx_from_server(mcp)
            except Exception:
                ctx = None

        if ctx is None:
            log.error(
                "[PayMCP:Subscriptions] Context (ctx) is required for subscription tools (tool: %s)",
                tool_name,
            )
            raise RuntimeError("Context (ctx) is required")

        log.debug(
            "[PayMCP:Subscriptions] wrapper invoked for tool=%s argsLen=%d",
            tool_name,
            len(args) + len(kwargs),
        )

        # Extract userId/email from ctx
        user_id, email = _extract_auth_identity(ctx, tool_name, log)

        # Check subscription
        await ensure_subscription_allowed(
            provider,
            subscription_info,
            user_id,
            email,
            tool_name,
            log,
        )

        # Call original handler with the same args/kwargs
        return await func(*args, **kwargs)

    # Preserve original call signature for schema generation (e.g., FastMCP)
    try:
        wrapper.__signature__ = inspect.signature(func)
    except (TypeError, ValueError):
        pass
    return wrapper

def _tool_with_pydantic_input(
    server: Any,
    *,
    name: str,
    description: str,
    input_model: Optional[type[BaseModel]] = None,
):
    """
    Wrapper around server.tool that:
      - For low-level MCP Server: passes input_schema from a Pydantic model
      - For FastMCP: omits input_schema (schema is inferred from type hints)
    """
    import inspect

    tool_fn = server.tool
    sig = inspect.signature(tool_fn)

    kwargs: Dict[str, Any] = {"name": name, "description": description}
    if input_model is not None and "input_schema" in sig.parameters:
        # Low-level MCP server: use explicit JSON schema
        kwargs["input_schema"] = input_model.model_json_schema()

    return tool_fn(**kwargs)

class StartSubscriptionInput(BaseModel):
    planId: str = Field(
        ...,
        description="Plan identifier to start a subscription for.",
    )


class CancelSubscriptionInput(BaseModel):
    subscriptionId: str = Field(
        ...,
        description="Identifier of the subscription to cancel.",
    )

def _get_ctx_from_server(server: Any) -> Any:
    """
    Best-effort retrieval of a context-like object from the server.

    For FastMCP, this uses server.get_context() if available.
    For other servers, this returns None and callers must handle the absence of context.
    """
    get_ctx = getattr(server, "get_context", None)
    if callable(get_ctx):
        try:
            return get_ctx()
        except Exception:
            return None
    return None

def register_subscription_tools(
    server: Any,
    provider: Any,
    logger: Optional[logging.Logger] = None,
):
    """
    Registers subscription‑related tools:
      - list_subscriptions
      - start_subscription
      - cancel_subscription
    """

    srv = server
    log: logging.Logger = logger or getattr(provider, "logger", logging.getLogger(__name__))

    @_tool_with_pydantic_input(
        srv,
        name="list_subscriptions",
        description="List current subscriptions and available subscription plans for the authenticated user.",
    )
    async def _list_subscriptions():
        ctx = _get_ctx_from_server(srv)
        user_id, email = _extract_auth_identity(ctx, "list_subscriptions", log)

        log.info("[PayMCP Subscription] User: id: %s email %s ",user_id,email)

        payload = provider.get_subscriptions(str(user_id), email)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, indent=2),
                }
            ]
        }

    @_tool_with_pydantic_input(
        srv,
        name="start_subscription",
        description="Start a subscription for the authenticated user for the given plan, or resume an existing one.",
        input_model=StartSubscriptionInput,
    )
    async def _start_subscription(planId: str):
        plan_id = planId
        if not plan_id:
            raise RuntimeError("planId is required to start a subscription")

        ctx = _get_ctx_from_server(srv)
        user_id, email = _extract_auth_identity(ctx, "start_subscription", log)

        result = provider.start_subscription(plan_id, str(user_id), email)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result),
                }
            ]
        }

    @_tool_with_pydantic_input(
        srv,
        name="cancel_subscription",
        description="Cancel a subscription for the authenticated user by subscription ID.",
        input_model=CancelSubscriptionInput,
    )
    async def _cancel_subscription(subscriptionId: str):
        sub_id = subscriptionId
        if not sub_id:
            raise RuntimeError("subscriptionId is required to cancel a subscription")

        ctx = _get_ctx_from_server(srv)
        user_id, email = _extract_auth_identity(ctx, "cancel_subscription", log)

        result = provider.cancel_subscription(sub_id, str(user_id), email)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, indent=2),
                }
            ]
        }