from typing import Any
import uuid

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

    session = getattr(ctx, "session", None)
    client_params = getattr(session, "_client_params", None)

    client_info = getattr(client_params, "clientInfo", None)
    capabilities = getattr(client_params, "capabilities", None)

    request_context = getattr(ctx, "request_context", None) if ctx is not None else None
    req = getattr(request_context, "request", None) if request_context is not None else None
    headers = getattr(req, "headers", None) if req is not None else None
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
        getattr(ctx, "client_id", None),
        getattr(getattr(ctx, "session", None), "client_id", None),
        getattr(getattr(ctx, "session", None), "id", None),
    ):
        if value is not None and str(value):
            return str(value)

    request_context = getattr(ctx, "request_context", None)
    req = getattr(request_context, "request", None) if request_context is not None else None
    headers = getattr(req, "headers", None) if req is not None else None
    header_sid = headers.get("mcp-session-id") if headers else None
    if header_sid:
        return str(header_sid)

    # Fallback: persist UUID on the session object, stable for that object lifetime.
    session = getattr(ctx, "session", None)
    if session is None:
        return None
    sid = getattr(session, "_paymcp_session_uuid", None)
    if sid is None:
        sid = str(uuid.uuid4())
        try:
            setattr(session, "_paymcp_session_uuid", sid)
        except Exception:
            return None
    return str(sid)
