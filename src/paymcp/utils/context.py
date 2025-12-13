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
