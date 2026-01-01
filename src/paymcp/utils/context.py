from typing import Any

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
    session_id = headers.get("mcp-session-id")


    return {
        "name": getattr(client_info, "name", None) or "unknown",
        "capabilities": capabilities.model_dump() if capabilities else {},
        "sessionId": session_id or str(id(session))
    }