"""Utilities for extracting MCP session ID from context."""

import logging
import hashlib
import json
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


def detect_transport_type(ctx) -> str:
    """
    Detect the MCP transport type from context.
    
    Returns:
        str: 'http', 'sse', 'stdio', or 'unknown'
    """
    if ctx is None:
        return "unknown"
    
    # Check for HTTP/SSE headers
    if hasattr(ctx, "headers") or (hasattr(ctx, "request") and hasattr(ctx.request, "headers")):
        headers = ctx.headers if hasattr(ctx, "headers") else ctx.request.headers
        if isinstance(headers, dict):
            # Check for SSE-specific headers
            for key in headers:
                if key.lower() in ["x-sse-session-id", "last-event-id", "event-stream"]:
                    return "sse"
            # Check content-type for SSE
            content_type = headers.get("content-type", "")
            if "event-stream" in content_type.lower():
                return "sse"
        return "http"
    
    # Check for STDIO indicators
    if hasattr(ctx, "_transport_type"):
        return ctx._transport_type.lower()
    
    # No headers typically means STDIO
    if not hasattr(ctx, "headers") and not hasattr(ctx, "request"):
        return "stdio"
    
    return "unknown"


def extract_session_info(ctx) -> Dict[str, Any]:
    """
    Extract comprehensive session information from MCP context.
    
    Returns a dictionary with:
    - session_id: The MCP session ID
    - transport_type: The transport type (http, sse, stdio)
    - client_id: A stable client identifier
    - headers: Relevant headers (if available)
    - metadata: Additional context metadata
    """
    info = {
        "session_id": None,
        "transport_type": detect_transport_type(ctx),
        "client_id": None,
        "headers": {},
        "metadata": {}
    }
    
    if ctx is None:
        return info
    
    # Extract headers if available
    headers = {}
    if hasattr(ctx, "headers"):
        headers = ctx.headers
    elif hasattr(ctx, "request") and hasattr(ctx.request, "headers"):
        headers = ctx.request.headers
    
    # Store sanitized headers (exclude sensitive data)
    if isinstance(headers, dict):
        info["headers"] = {
            k: v for k, v in headers.items() 
            if not any(sensitive in k.lower() for sensitive in ["authorization", "token", "secret", "password"])
        }
    elif hasattr(headers, "items"):
        info["headers"] = {
            k: v for k, v in headers.items() 
            if not any(sensitive in k.lower() for sensitive in ["authorization", "token", "secret", "password"])
        }
    
    # Extract session ID based on transport type
    if info["transport_type"] == "sse":
        # SSE-specific session extraction
        for key, value in info["headers"].items():
            if key.lower() in ["x-sse-session-id", "sse-session-id"]:
                info["session_id"] = value
                break
            elif key.lower() == "last-event-id":
                # Use Last-Event-ID as fallback
                info["session_id"] = value
                info["metadata"]["session_source"] = "last-event-id"
        
        # Generate session from connection if not found
        if not info["session_id"] and info["headers"]:
            stable_parts = []
            for header in ["user-agent", "x-forwarded-for", "x-real-ip", "remote-addr"]:
                if header in info["headers"]:
                    stable_parts.append(info["headers"][header])
            if stable_parts:
                info["session_id"] = hashlib.md5(":".join(stable_parts).encode()).hexdigest()[:16]
                info["metadata"]["session_source"] = "generated-sse"
    
    elif info["transport_type"] == "http":
        # HTTP session extraction (existing logic)
        for key, value in info["headers"].items():
            if key.lower() == "mcp-session-id":
                info["session_id"] = value
                info["metadata"]["session_source"] = "mcp-header"
                break
    
    # Check for direct session attributes
    if not info["session_id"]:
        if hasattr(ctx, "session_id"):
            info["session_id"] = ctx.session_id
            info["metadata"]["session_source"] = "ctx-attribute"
        elif hasattr(ctx, "_session_id"):
            info["session_id"] = ctx._session_id
            info["metadata"]["session_source"] = "ctx-internal"
    
    # Generate stable client ID
    if info["headers"]:
        # Use combination of stable headers
        client_parts = []
        for header in ["user-agent", "x-proxy-authorization", "x-forwarded-for"]:
            if header in info["headers"]:
                client_parts.append(info["headers"][header])
        if client_parts:
            info["client_id"] = hashlib.md5(":".join(client_parts).encode()).hexdigest()[:16]
    
    # Add transport-specific metadata
    info["metadata"]["transport"] = info["transport_type"]
    if info["transport_type"] == "stdio":
        info["metadata"]["note"] = "STDIO transport does not maintain session IDs"
    
    return info


def extract_session_id(ctx):
    """
    Extract MCP session ID from the context object.
    
    Backward-compatible function that uses the new comprehensive extraction.
    
    For HTTP transport, the session ID comes from Mcp-Session-Id header.
    For SSE transport, it comes from X-SSE-Session-Id or is generated.
    For STDIO transport, there is no session ID (returns None).

    Args:
        ctx: The MCP context object (e.g., FastMCP Context)

    Returns:
        str or None: The session ID if available, None otherwise
    """
    session_info = extract_session_info(ctx)
    session_id = session_info.get("session_id")
    
    if session_id:
        logger.debug(
            f"Found session ID: {session_id} "
            f"(transport: {session_info['transport_type']}, "
            f"source: {session_info['metadata'].get('session_source', 'unknown')})"
        )
    else:
        transport = session_info.get('transport_type', 'unknown')
        if transport in ['http', 'sse']:
            logger.warning(
                f"No session ID found for {transport} transport. "
                "This may cause issues with multi-client scenarios."
            )
        else:
            logger.debug(f"No session ID found ({transport} transport)")
    
    return session_id
