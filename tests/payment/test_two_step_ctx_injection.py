"""What the confirm step does with `ctx`, pinned against real functions.

`ctx` is stripped before the call arguments are persisted - it is not
serializable - and a fresh one is put back when the payment is confirmed. Which
tools get it is decided by inspecting their signature, so the cases are worth
stating: a tool that asked for a context gets the server's current one, a tool
that accepts anything gets it too, and a tool that asked for neither must not
be handed an argument it cannot take.
"""

import pytest
from unittest.mock import Mock, patch

from paymcp.payment.flows import two_step
from paymcp.providers.base import BasePaymentProvider


@pytest.fixture
def provider():
    p = Mock(spec=BasePaymentProvider)
    p.create_payment = Mock(return_value=("payment_123", "https://payment.url"))
    p.get_payment_status = Mock(return_value="paid")
    return p


@pytest.fixture
def state_store():
    from paymcp.state.memory import InMemoryStateStore
    return InMemoryStateStore()


async def _run(func, provider, state_store, server_ctx):
    """Initiate a payment for `func`, then confirm it, and return the call."""
    confirm = {}
    mcp = Mock()

    def capture_tool(*args, **kwargs):
        def decorator(f):
            confirm["f"] = f
            return f
        return decorator

    mcp.tool = capture_tool

    with patch.object(two_step, "get_ctx_from_server", return_value=server_ctx):
        wrapper = two_step.make_paid_wrapper(
            func, mcp, {"mock": provider}, {"price": 1.0, "currency": "USD"},
            state_store=state_store,
        )
        await wrapper(original_arg="value", ctx="the-context-at-initiate-time")
        return await confirm["f"]("payment_123")


@pytest.mark.asyncio
async def test_a_tool_that_asks_for_ctx_gets_the_current_one(provider, state_store):
    seen = {}

    async def tool(original_arg=None, ctx=None):
        seen["ctx"] = ctx
        return {"ok": True}

    tool.__name__ = "tool_with_ctx"

    assert await _run(tool, provider, state_store, "the-context-at-confirm-time") == {"ok": True}
    assert seen["ctx"] == "the-context-at-confirm-time"


@pytest.mark.asyncio
async def test_a_tool_that_accepts_anything_gets_ctx_too(provider, state_store):
    seen = {}

    async def tool(original_arg=None, **kwargs):
        seen.update(kwargs)
        return {"ok": True}

    tool.__name__ = "tool_with_kwargs"

    await _run(tool, provider, state_store, "the-context-at-confirm-time")
    assert seen["ctx"] == "the-context-at-confirm-time"


@pytest.mark.asyncio
async def test_a_tool_that_asks_for_neither_is_not_given_one(provider, state_store):
    """Passing it anyway would be a TypeError at the point the user has paid."""
    seen = {}

    async def tool(original_arg=None):
        seen["called_with"] = original_arg
        return {"ok": True}

    tool.__name__ = "tool_without_ctx"

    assert await _run(tool, provider, state_store, "the-context-at-confirm-time") == {"ok": True}
    assert seen["called_with"] == "value"
