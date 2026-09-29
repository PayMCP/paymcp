import logging
from typing import Any
import uuid

logger = logging.getLogger(__name__)


def read(obj: Any, name: str) -> Any:
    """Read an attribute that may not merely be missing, but angry.

    A FastMCP `Context` exposes `request_context` and `session` as properties
    that raise when there is no active request, and `getattr`'s default only
    covers AttributeError. Everything here is best-effort identification, so an
    attribute we cannot read is the same as one that is not there.
    """
    try:
        return getattr(obj, name, None)
    except Exception:
        logger.debug("[PayMCP] Could not read %r off %r", name, type(obj).__name__, exc_info=True)
        return None

def get_ctx_from_server(server: Any) -> Any:
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

def capture_client_from_ctx(ctx):
    if not ctx:
        return {
            "name": "unknown",
            "capabilities": {},
            "sessionId": None,
        }

    session = read(ctx, "session")
    client_params = read(session, "_client_params")

    client_info = read(client_params, "clientInfo")
    capabilities = read(client_params, "capabilities")

    request_context = read(ctx, "request_context")
    req = read(request_context, "request")
    headers = read(req, "headers")
    session_id = headers.get("mcp-session-id") if headers else None


    return {
        "name": getattr(client_info, "name", None) or "unknown",
        "capabilities": capabilities.model_dump() if capabilities else {},
        "sessionId": session_id or get_stable_session_id(ctx)
    }


def get_stable_session_id(ctx: Any) -> str | None:
    """Return a stable, non-recycled session identifier for payment/session state.

    Order of preference:
    1) Explicit client/session identifiers exposed by SDK/runtime
    2) MCP session header value (when available)
    3) A UUID memoized on the session object for its lifetime
    """
    if not ctx:
        return None

    # Prefer explicit identifiers from the SDK/runtime.
    for value in (
        read(ctx, "client_id"),
        read(read(ctx, "session"), "client_id"),
        read(read(ctx, "session"), "id"),
    ):
        if value is not None and str(value):
            return str(value)

    request_context = read(ctx, "request_context")
    req = read(request_context, "request")
    headers = read(req, "headers")
    header_sid = headers.get("mcp-session-id") if headers else None
    if header_sid:
        return str(header_sid)

    # Fallback: persist UUID on the session object, stable for that object lifetime.
    session = read(ctx, "session")
    if session is None:
        return None
    sid = read(session, "_paymcp_session_uuid")
    if sid is None:
        sid = str(uuid.uuid4())
        try:
            setattr(session, "_paymcp_session_uuid", sid)
        except Exception:
            return None
    return str(sid)
