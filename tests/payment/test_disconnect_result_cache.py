"""A paid tool must not run twice when the client drops before it gets the result.

Every flow that detects a disconnect after execution tells the caller to "call
the tool again to retrieve the result". These tests pin down that the retry
actually retrieves it instead of running - and charging for - the tool again.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from paymcp.payment.flows import dynamic_tools
from paymcp.payment.flows.state_utils import (
    clear_completed_result,
    peek_completed_result,
    save_completed_result,
)
from paymcp.providers.base import BasePaymentProvider
from paymcp.state.memory import InMemoryStateStore


class FakeRequest:
    def __init__(self):
        self.dropped = False
        self.headers = {}

    async def is_disconnected(self):
        return self.dropped


class FakeRequestContext:
    def __init__(self, request):
        self.request = request


class FakeSession:
    def __init__(self, session_id):
        self.id = session_id


class FakeCtx:
    """Context whose connection can be dropped and restored between calls."""

    def __init__(self, session_id="session-1"):
        self.request = FakeRequest()
        self.request_context = FakeRequestContext(self.request)
        self.session = FakeSession(session_id)

    def drop(self):
        self.request.dropped = True

    def restore(self):
        self.request.dropped = False


class CountingTool:
    """Stands in for a paid tool, counting how often it actually runs."""

    __name__ = "expensive_tool"

    def __init__(self, result=None):
        self.calls = 0
        self._result = result

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if self._result is not None:
            return self._result
        return {"report": f"result #{self.calls}"}


@pytest.fixture
def provider():
    p = Mock(spec=BasePaymentProvider)
    p.create_payment = Mock(return_value=("payment_123", "https://payment.url"))
    p.get_payment_status = Mock(return_value="paid")
    return p


@pytest.fixture
def price_info():
    return {"price": 10.0, "currency": "USD"}


@pytest.fixture
def state_store():
    return InMemoryStateStore()


def _pending(result):
    return isinstance(result, dict) and result.get("status") == "pending"


# ===== RESUBMIT =====

async def _resubmit_paid_then_dropped(tool, provider, price_info, state_store, ctx):
    """Run the resubmit flow up to a paid execution the client never received."""
    from paymcp.payment.flows.resubmit import make_paid_wrapper

    wrapper = make_paid_wrapper(tool, None, {"mock": provider}, price_info, state_store=state_store)

    with pytest.raises(RuntimeError) as exc:
        await wrapper(ctx=ctx)
    payment_id = exc.value.data["payment_id"]

    ctx.drop()
    pending = await wrapper(ctx=ctx, payment_id=payment_id)
    assert _pending(pending)
    assert tool.calls == 1
    return wrapper, payment_id


@pytest.mark.asyncio
async def test_resubmit_retry_returns_result_without_re_executing(
    provider, price_info, state_store
):
    tool = CountingTool()
    ctx = FakeCtx()
    wrapper, payment_id = await _resubmit_paid_then_dropped(
        tool, provider, price_info, state_store, ctx
    )

    ctx.restore()
    result = await wrapper(ctx=ctx, payment_id=payment_id)

    assert result == {"report": "result #1"}
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_resubmit_keeps_result_while_client_is_still_disconnected(
    provider, price_info, state_store
):
    tool = CountingTool()
    ctx = FakeCtx()
    wrapper, payment_id = await _resubmit_paid_then_dropped(
        tool, provider, price_info, state_store, ctx
    )

    # Client retries but drops again: the result must survive for the next try.
    assert _pending(await wrapper(ctx=ctx, payment_id=payment_id))
    assert tool.calls == 1

    ctx.restore()
    assert await wrapper(ctx=ctx, payment_id=payment_id) == {"report": "result #1"}
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_resubmit_payment_is_single_use_after_result_delivery(
    provider, price_info, state_store
):
    tool = CountingTool()
    ctx = FakeCtx()
    wrapper, payment_id = await _resubmit_paid_then_dropped(
        tool, provider, price_info, state_store, ctx
    )

    ctx.restore()
    await wrapper(ctx=ctx, payment_id=payment_id)

    with pytest.raises(RuntimeError) as exc:
        await wrapper(ctx=ctx, payment_id=payment_id)
    assert exc.value.error == "payment_id_not_found"
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_resubmit_falls_back_to_re_execution_for_unserializable_results(
    provider, price_info, state_store
):
    """Results that cannot be persisted keep the old behaviour, by design."""
    tool = CountingTool(result=object())
    ctx = FakeCtx()
    wrapper, payment_id = await _resubmit_paid_then_dropped(
        tool, provider, price_info, state_store, ctx
    )

    ctx.restore()
    await wrapper(ctx=ctx, payment_id=payment_id)
    assert tool.calls == 2


# ===== TWO_STEP =====

@pytest.mark.asyncio
async def test_two_step_retry_returns_result_without_re_executing(
    provider, price_info, state_store
):
    from paymcp.payment.flows import two_step

    tool = CountingTool()
    ctx = FakeCtx()
    mcp = Mock()
    confirm = {}

    def capture_tool(*args, **kwargs):
        def decorator(func):
            confirm["func"] = func
            return func
        return decorator

    mcp.tool = capture_tool

    with patch.object(two_step, "get_ctx_from_server", return_value=ctx):
        wrapper = two_step.make_paid_wrapper(
            tool, mcp, {"mock": provider}, price_info, state_store=state_store
        )
        await wrapper(original_arg="value")

        ctx.drop()
        assert _pending(await confirm["func"]("payment_123"))
        assert tool.calls == 1

        ctx.restore()
        result = await confirm["func"]("payment_123")

    assert result == {"report": "result #1"}
    assert tool.calls == 1


# ===== ELICITATION =====

@pytest.mark.asyncio
async def test_elicitation_retry_returns_result_without_re_executing(
    provider, price_info, state_store
):
    from paymcp.payment.flows import elicitation

    tool = CountingTool()
    ctx = FakeCtx()

    with patch.object(elicitation, "run_elicitation_loop", AsyncMock(return_value="paid")):
        wrapper = elicitation.make_paid_wrapper(
            tool, Mock(), {"mock": provider}, price_info, state_store=state_store
        )

        ctx.drop()
        assert _pending(await wrapper(ctx=ctx))
        assert tool.calls == 1

        ctx.restore()
        result = await wrapper(ctx=ctx)

    assert result == {"report": "result #1"}
    assert tool.calls == 1


# ===== PROGRESS =====

@pytest.mark.asyncio
async def test_progress_retry_returns_result_without_re_executing(
    provider, price_info, state_store
):
    from paymcp.payment.flows import progress

    tool = CountingTool()
    ctx = FakeCtx()

    with patch.object(progress.asyncio, "sleep", AsyncMock()):
        wrapper = progress.make_paid_wrapper(
            tool, Mock(), {"mock": provider}, price_info, state_store=state_store
        )

        ctx.drop()
        assert _pending(await wrapper(ctx=ctx))
        assert tool.calls == 1

        ctx.restore()
        result = await wrapper(ctx=ctx)

    assert result == {"report": "result #1"}
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_progress_restores_a_stored_payment_instead_of_creating_another(
    provider, price_info, state_store
):
    """State is stored wrapped under "args"; restoring has to read it back."""
    from paymcp.payment.flows import progress

    tool = CountingTool()
    ctx = FakeCtx()

    wrapper = progress.make_paid_wrapper(
        tool, Mock(), {"mock": provider}, price_info, state_store=state_store
    )

    # The caller goes away while the flow is polling, so the payment stays stored.
    with patch.object(progress.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            await wrapper(ctx=ctx)

    # The next call must pick that payment back up, not open a second one.
    with patch.object(progress.asyncio, "sleep", AsyncMock()):
        result = await wrapper(ctx=ctx)

    assert provider.create_payment.call_count == 1
    assert result == {"report": "result #1"}


# ===== DYNAMIC_TOOLS =====

@pytest.fixture
def clean_dynamic_tools_state():
    dynamic_tools.PAYMENTS.clear()
    dynamic_tools.HIDDEN_TOOLS.clear()
    dynamic_tools.CONFIRMATION_TOOLS.clear()
    yield
    dynamic_tools.PAYMENTS.clear()
    dynamic_tools.HIDDEN_TOOLS.clear()
    dynamic_tools.CONFIRMATION_TOOLS.clear()


@pytest.mark.asyncio
async def test_dynamic_tools_retry_returns_result_without_re_executing(
    provider, price_info, clean_dynamic_tools_state
):
    tool = CountingTool()
    ctx = FakeCtx()
    mcp = MagicMock()
    registered = {}

    def tool_decorator(name=None, description=None, **kwargs):
        def decorator(func):
            registered[name] = func
            return func
        return decorator

    mcp.tool = tool_decorator

    wrapper = dynamic_tools.make_paid_wrapper(tool, mcp, {"mock": provider}, price_info)
    initiated = await wrapper(ctx=ctx)
    confirm = registered[initiated["next_tool"]]

    ctx.drop()
    assert _pending(await confirm(ctx=ctx))
    assert tool.calls == 1

    ctx.restore()
    result = await confirm(ctx=ctx)

    assert result == {"report": "result #1"}
    assert tool.calls == 1


# ===== helpers =====

@pytest.mark.asyncio
async def test_peek_returns_nothing_when_no_result_was_stored(state_store):
    assert await peek_completed_result(state_store, "payment_1") == (False, None)


@pytest.mark.asyncio
async def test_save_peek_and_clear_round_trip(state_store):
    assert await save_completed_result(state_store, "payment_1", {"ok": True}) is True
    assert await peek_completed_result(state_store, "payment_1") == (True, {"ok": True})

    await clear_completed_result(state_store, "payment_1")
    assert await peek_completed_result(state_store, "payment_1") == (False, None)


@pytest.mark.asyncio
async def test_save_reports_failure_for_unserializable_results(state_store):
    assert await save_completed_result(state_store, "payment_1", object()) is False
    assert await peek_completed_result(state_store, "payment_1") == (False, None)


@pytest.mark.asyncio
async def test_helpers_tolerate_a_missing_store_or_key(state_store):
    assert await save_completed_result(None, "payment_1", {"ok": True}) is False
    assert await save_completed_result(state_store, None, {"ok": True}) is False
    assert await peek_completed_result(None, "payment_1") == (False, None)
    await clear_completed_result(None, "payment_1")


@pytest.mark.asyncio
async def test_result_cache_does_not_collide_with_the_payment_state(state_store):
    await state_store.set("payment_1", {"original": "args"})
    await save_completed_result(state_store, "payment_1", {"ok": True})

    stored = await state_store.get("payment_1")
    assert stored["args"] == {"original": "args"}
