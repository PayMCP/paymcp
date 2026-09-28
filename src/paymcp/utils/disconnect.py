async def is_disconnected(ctx=None) -> bool:
    """True only when the transport positively reports the client is gone.

    Every attribute here can be a property that raises rather than a plain
    value - `Context.request_context` and `Context.session` both raise when
    there is no active request, and `getattr`'s default does not cover that.
    Anything we cannot read means we do not know, and not knowing has to read
    as connected: the alternative is telling callers their result is pending
    when it is on its way to them, or failing their call outright.
    """
    if ctx is None:
        return False

    try:
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
    except Exception:
        return False

    return False
