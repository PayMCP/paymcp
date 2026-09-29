"""Every reader that walks a context must survive one it cannot walk.

FastMCP exposes `request_context` and `session` as properties that raise when
there is no active request. Each of these functions is reached with a context
that came from `get_ctx_from_server`, which hands back exactly such an object
when nothing is in flight, and each one used to take the tool call down with it.
"""

import logging

import pytest

from paymcp.payment.flows.x402 import _get_headers, _get_meta
from paymcp.subscriptions.wrapper import _extract_auth_identity, _get_bearer_token_from_ctx
from paymcp.utils.context import capture_client_from_ctx, get_stable_session_id
from paymcp.utils.disconnect import is_disconnected


class OutsideARequest:
    """Shaped like a Context with nothing behind it."""

    @property
    def request_context(self):
        raise ValueError("Context is not available outside of a request")

    @property
    def session(self):
        raise ValueError("Context is not available outside of a request")

    @property
    def client_id(self):
        raise ValueError("Context is not available outside of a request")


@pytest.mark.parametrize(
    "reader",
    [
        pytest.param(lambda ctx: get_stable_session_id(ctx), id="session_id"),
        pytest.param(lambda ctx: capture_client_from_ctx(ctx), id="client"),
        pytest.param(lambda ctx: _get_headers(ctx), id="x402_headers"),
        pytest.param(lambda ctx: _get_meta(ctx), id="x402_meta"),
        pytest.param(
            lambda ctx: _get_bearer_token_from_ctx(ctx, logging.getLogger()), id="bearer_token"
        ),
    ],
)
def test_a_reader_gives_up_instead_of_raising(reader):
    reader(OutsideARequest())


def test_identity_refuses_rather_than_crashing():
    """The one that does raise raises its own answer, not the context's."""
    with pytest.raises(RuntimeError, match="Not authorized"):
        _extract_auth_identity(OutsideARequest(), "a_tool", logging.getLogger())


@pytest.mark.asyncio
async def test_a_context_we_cannot_read_counts_as_connected():
    assert await is_disconnected(OutsideARequest()) is False
