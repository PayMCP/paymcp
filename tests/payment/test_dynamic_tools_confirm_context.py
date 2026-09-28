"""The dynamic_tools confirm tool has to resolve its own context.

`_confirm(ctx=None)` carries no Context annotation, so FastMCP never injects
one: called the way the model calls it, ctx is None and every ctx-dependent
branch is skipped - including the disconnect handling that keeps a paid result
from being produced twice.
"""

import inspect

import pytest
from unittest.mock import MagicMock, Mock

from paymcp.payment.flows import dynamic_tools
from paymcp.providers.base import BasePaymentProvider


class FakeRequest:
    def __init__(self):
        self.dropped = False
        self.headers = {}

    async def is_disconnected(self):
        return self.dropped


class FakeCtx:
    def __init__(self, session_id="session-1"):
        self.request = FakeRequest()
        self.request_context = type("RC", (), {"request": self.request})()
        self.session = type("S", (), {"id": session_id})()


class CountingTool:
    __name__ = "expensive_tool"

    def __init__(self):
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        return {"report": f"result #{self.calls}"}


@pytest.fixture
def clean_state():
    for store in (dynamic_tools.PAYMENTS, dynamic_tools.HIDDEN_TOOLS, dynamic_tools.CONFIRMATION_TOOLS):
        store.clear()
    yield
    for store in (dynamic_tools.PAYMENTS, dynamic_tools.HIDDEN_TOOLS, dynamic_tools.CONFIRMATION_TOOLS):
        store.clear()


@pytest.mark.asyncio
async def test_confirm_detects_a_disconnect_without_being_handed_a_context(clean_state):
    ctx = FakeCtx()
    provider = Mock(spec=BasePaymentProvider)
    provider.create_payment = Mock(return_value=("payment_123", "https://payment.url"))
    provider.get_payment_status = Mock(return_value="paid")

    registered = {}
    mcp = MagicMock()
    mcp.get_context = Mock(return_value=ctx)

    def tool_decorator(name=None, description=None, **kwargs):
        def decorator(func):
            registered[name] = func
            return func
        return decorator

    mcp.tool = tool_decorator

    tool = CountingTool()
    wrapper = dynamic_tools.make_paid_wrapper(
        tool, mcp, {"mock": provider}, {"price": 1.0, "currency": "USD"}
    )
    initiated = await wrapper(ctx=ctx)
    confirm = registered[initiated["next_tool"]]

    # Called the way FastMCP calls it: no ctx argument at all.
    ctx.request.dropped = True
    pending = await confirm()
    assert pending["status"] == "pending"
    assert tool.calls == 1

    ctx.request.dropped = False
    assert await confirm() == {"report": "result #1"}
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_confirm_tool_takes_no_arguments(clean_state):
    """An unannotated `ctx` parameter is not filled in by FastMCP - it is just
    advertised to the model as an argument to guess at, and a model that guesses
    it puts the flow back on the path where no disconnect is ever detected."""
    provider = Mock(spec=BasePaymentProvider)
    provider.create_payment = Mock(return_value=("payment_123", "https://payment.url"))
    provider.get_payment_status = Mock(return_value="paid")

    registered = {}
    mcp = MagicMock()
    mcp.get_context = Mock(return_value=FakeCtx())

    def tool_decorator(name=None, description=None, **kwargs):
        def decorator(func):
            registered[name] = func
            return func
        return decorator

    mcp.tool = tool_decorator

    wrapper = dynamic_tools.make_paid_wrapper(
        CountingTool(), mcp, {"mock": provider}, {"price": 1.0, "currency": "USD"}
    )
    initiated = await wrapper(ctx=FakeCtx())

    confirm = registered[initiated["next_tool"]]
    assert list(inspect.signature(confirm).parameters) == []
