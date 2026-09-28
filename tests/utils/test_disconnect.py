"""A context that cannot be read must not fail the call it belongs to.

FastMCP's `Context` exposes `request_context` and `session` as properties that
raise when there is no active request, and `getattr(ctx, name, None)` does not
cover that - its default only catches AttributeError.
"""

import pytest

from paymcp.utils.disconnect import is_disconnected


class ContextOutsideARequest:
    """Shaped like a FastMCP Context with no request context behind it."""

    @property
    def request_context(self):
        raise ValueError("Context is not available outside of a request")

    @property
    def session(self):
        raise ValueError("Context is not available outside of a request")


class ConnectedRequest:
    async def is_disconnected(self):
        return False


class DroppedRequest:
    async def is_disconnected(self):
        return True


class Ctx:
    def __init__(self, request):
        self.request_context = type("RC", (), {"request": request})()


@pytest.mark.asyncio
async def test_a_context_outside_a_request_reads_as_connected():
    assert await is_disconnected(ContextOutsideARequest()) is False


@pytest.mark.asyncio
async def test_no_context_reads_as_connected():
    assert await is_disconnected(None) is False


@pytest.mark.asyncio
async def test_a_live_request_is_reported_as_the_transport_sees_it():
    assert await is_disconnected(Ctx(ConnectedRequest())) is False
    assert await is_disconnected(Ctx(DroppedRequest())) is True
