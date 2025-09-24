"""Utilities for extracting MCP session ID from context."""

import logging

logger = logging.getLogger(__name__)


def extract_session_id(ctx):
    """
    Extract MCP session ID from the context object.

    For HTTP transport, the session ID comes from Mcp-Session-Id header.
    For STDIO transport, there is no session ID (returns None).

    According to MCP spec:
    - Server returns Mcp-Session-Id header during initialization
    - Client must include it in all subsequent requests

    Args:
        ctx: The MCP context object (e.g., FastMCP Context)

    Returns:
        str or None: The session ID if available, None otherwise
    """
    if ctx is None:
        return None

    # Try different ways to get session ID based on the MCP implementation

    # 1. FastMCP HTTP: Check if ctx has headers with Mcp-Session-Id
    if hasattr(ctx, "headers"):
        headers = ctx.headers
        if isinstance(headers, dict):
            # Check for Mcp-Session-Id header (case-insensitive)
            for key, value in headers.items():
                if key.lower() == "mcp-session-id":
                    logger.debug(f"Found MCP session ID in headers: {value}")
                    return value
        # Also check if headers is a Headers-like object with get method
        elif hasattr(headers, "get"):
            session_id = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
            if session_id:
                logger.debug(f"Found MCP session ID via headers.get: {session_id}")
                return session_id

    # 2. Check if ctx has a request object with headers (ASGI/Starlette style)
    if hasattr(ctx, "request"):
        request = ctx.request
        if hasattr(request, "headers"):
            headers = request.headers
            if isinstance(headers, dict):
                for key, value in headers.items():
                    if key.lower() == "mcp-session-id":
                        logger.debug(
                            f"Found MCP session ID in request.headers: {value}"
                        )
                        return value
            elif hasattr(headers, "get"):
                session_id = headers.get("Mcp-Session-Id") or headers.get(
                    "mcp-session-id"
                )
                if session_id:
                    logger.debug(
                        f"Found MCP session ID via request.headers.get: {session_id}"
                    )
                    return session_id

    # 3. Check if ctx has direct session_id attribute (some MCP implementations)
    if hasattr(ctx, "session_id"):
        logger.debug(f"Found MCP session ID in ctx.session_id: {ctx.session_id}")
        return ctx.session_id

    # 4. Check if ctx has _session_id (internal attribute)
    if hasattr(ctx, "_session_id"):
        logger.debug(f"Found MCP session ID in ctx._session_id: {ctx._session_id}")
        return ctx._session_id

    # No session ID found
    # Check if this looks like HTTP context (has headers)
    if (
        hasattr(ctx, "headers")
        or (hasattr(ctx, "request") and hasattr(ctx.request, "headers"))
        or (hasattr(ctx, "_meta") and hasattr(ctx._meta, "headers"))
    ):
        # HTTP context but no session ID - log warning
        logger.warning(
            "MCP session ID not found in HTTP context. "
            "This may cause issues with multi-client scenarios. "
            "Ensure your MCP server provides Mcp-Session-Id header."
        )
    else:
        # STDIO transport - no session ID expected
        logger.debug("No MCP session ID found (STDIO transport)")

    return None
