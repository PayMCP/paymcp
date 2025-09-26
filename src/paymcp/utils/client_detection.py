"""Utilities for detecting MCP client type and extracting appropriate session identifiers."""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def detect_client_and_session(ctx) -> Tuple[str, Optional[str]]:
    """
    Detect MCP client type and extract the appropriate session identifier.
    
    Returns:
        Tuple of (client_type, session_identifier)
        
        client_type: "mcp-inspector", "claude-desktop", or "unknown"
        session_identifier: 
            - For MCP Inspector: proxy auth token (stable across reconnects)
            - For Claude Desktop: MCP session ID (per conversation)
            - For unknown: fallback to MCP session ID if available
    """
    if ctx is None:
        return ("unknown", None)
    
    # Check headers for client identification
    headers = {}
    
    # Extract headers from context
    if hasattr(ctx, "headers"):
        headers = ctx.headers
    elif hasattr(ctx, "request") and hasattr(ctx.request, "headers"):
        headers = ctx.request.headers
    
    # Convert to dict if needed
    if hasattr(headers, "items"):
        headers = dict(headers.items())
    elif hasattr(headers, "__iter__") and not isinstance(headers, dict):
        headers = {k.lower(): v for k, v in headers}
    else:
        headers = {}
    
    # Normalize header keys to lowercase
    headers = {k.lower(): v for k, v in headers.items()}
    
    # Detect MCP Inspector by proxy auth token
    proxy_auth = headers.get("x-proxy-authorization") or headers.get("proxy-authorization")
    if proxy_auth:
        # MCP Inspector detected - use proxy auth token as stable identifier
        logger.debug(f"Detected MCP Inspector with proxy auth: {proxy_auth[:20]}...")
        return ("mcp-inspector", proxy_auth)
    
    # Detect Claude Desktop by user agent or other headers
    user_agent = headers.get("user-agent", "")
    if "claude" in user_agent.lower() or "anthropic" in user_agent.lower():
        # Claude Desktop detected - use MCP session ID
        mcp_session = headers.get("mcp-session-id")
        logger.debug(f"Detected Claude Desktop with session: {mcp_session}")
        return ("claude-desktop", mcp_session)
    
    # Check for MCP session ID as fallback
    mcp_session = headers.get("mcp-session-id")
    if mcp_session:
        # Has MCP session but unknown client
        logger.debug(f"Unknown client with MCP session: {mcp_session}")
        return ("unknown", mcp_session)
    
    # No identifying information found
    logger.debug("Could not detect client type or session")
    return ("unknown", None)


def get_stable_client_id(ctx) -> Optional[str]:
    """
    Get a stable identifier for the client that persists across timeouts.
    
    For MCP Inspector: Returns proxy auth token
    For Claude Desktop: Returns MCP session ID (stable within conversation)
    For others: Returns None or best available identifier
    """
    client_type, session_id = detect_client_and_session(ctx)
    
    if client_type == "mcp-inspector" and session_id:
        # Proxy auth token is stable across reconnects
        return f"mcp-inspector:{session_id[:30]}"  # Truncate for storage efficiency
    elif client_type == "claude-desktop" and session_id:
        # Session ID is stable within a conversation
        return f"claude-desktop:{session_id[:30]}"
    elif session_id:
        # Unknown client but has session
        return f"unknown:{session_id[:30]}"
    
    return None