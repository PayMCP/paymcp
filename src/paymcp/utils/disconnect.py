async def is_disconnected(ctx=None) -> bool:
    if ctx is None:
        return False

    req = getattr(getattr(ctx, "request_context", None), "request", None)
    if req and hasattr(req, "is_disconnected"):
        try:
            result = await req.is_disconnected()
            if result is True:
                return True
        except Exception:
            # If the attribute isn't awaitable or errors, treat as connected
            pass

    session = getattr(ctx, "session", None)
    for stream_name in ("_read_stream", "_write_stream"):
        stream = getattr(session, stream_name, None)
        state = getattr(stream, "_state", None)
        state_closed = getattr(state, "_closed", None)
        if state_closed is True:
            return True

    return False
