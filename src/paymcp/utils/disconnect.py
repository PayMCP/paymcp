async def is_disconnected(ctx=None) -> bool:
    if ctx is None:
        return False

    req = getattr(getattr(ctx, "request_context", None), "request", None)
    if req and hasattr(req, "is_disconnected"):
        try:
            if await req.is_disconnected():
                return True
        except Exception:
            pass

    session = getattr(ctx, "session", None)
    for stream_name in ("_read_stream", "_write_stream"):
        stream = getattr(session, stream_name, None)
        state = getattr(stream, "_state", None)
        if getattr(state, "_closed", False):
            return True

    return False
