"""A paid tool must not run twice when the client drops before it gets the result.

Every flow that detects a disconnect after execution tells the caller to "call
the tool again to retrieve the result". These tests pin down that the retry
actually retrieves it instead of running - and charging for - the tool again.
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from paymcp.payment.flows import dynamic_tools
from paymcp.payment.flows.state_utils import (
    RESULT_NS_PAYMENT,
    RESULT_NS_SESSION,
    call_fingerprint,
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
async def test_resubmit_payment_buys_exactly_one_execution(
    provider, price_info, state_store
):
    """The payment is spent on delivery, but the result stays fetchable.

    Handing the result back can fail to reach the caller just like the first
    attempt did, and they have already paid for it - so further retries return
    the same result rather than a 404, and never a second execution.
    """
    tool = CountingTool()
    ctx = FakeCtx()
    wrapper, payment_id = await _resubmit_paid_then_dropped(
        tool, provider, price_info, state_store, ctx
    )

    ctx.restore()
    assert await wrapper(ctx=ctx, payment_id=payment_id) == {"report": "result #1"}
    assert await state_store.get(payment_id) is None

    assert await wrapper(ctx=ctx, payment_id=payment_id) == {"report": "result #1"}
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_resubmit_caches_results_the_store_can_hold_as_they_are(
    provider, price_info, state_store
):
    """The in-memory store keeps the object itself, so results that could never
    be serialized are still returned without a second execution."""
    sentinel = object()
    tool = CountingTool(result=sentinel)
    ctx = FakeCtx()
    wrapper, payment_id = await _resubmit_paid_then_dropped(
        tool, provider, price_info, state_store, ctx
    )

    ctx.restore()
    assert await wrapper(ctx=ctx, payment_id=payment_id) is sentinel
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_resubmit_falls_back_to_re_execution_when_the_store_rejects_the_result(
    provider, price_info
):
    """A durable store persists as JSON. What it cannot hold is not cached, and
    the flow keeps its previous behaviour rather than failing the call."""
    class JsonOnlyStore(InMemoryStateStore):
        async def set(self, key, args, ttl_seconds=None):
            json.dumps(args)  # what RedisStateStore does before writing
            await super().set(key, args, ttl_seconds)

    state_store = JsonOnlyStore()
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
    assert await peek_completed_result(state_store, "payment_1", RESULT_NS_PAYMENT) == (False, None)


@pytest.mark.asyncio
async def test_save_peek_and_clear_round_trip(state_store):
    assert await save_completed_result(state_store, "payment_1", {"ok": True}, RESULT_NS_PAYMENT) is True
    assert await peek_completed_result(state_store, "payment_1", RESULT_NS_PAYMENT) == (True, {"ok": True})

    await clear_completed_result(state_store, "payment_1", RESULT_NS_PAYMENT)
    assert await peek_completed_result(state_store, "payment_1", RESULT_NS_PAYMENT) == (False, None)


@pytest.mark.asyncio
async def test_save_reports_failure_when_the_store_refuses_the_result():
    class RejectingStore(InMemoryStateStore):
        async def set(self, key, args, ttl_seconds=None):
            raise TypeError("not JSON serializable")

    store = RejectingStore()
    assert await save_completed_result(store, "payment_1", object(), RESULT_NS_PAYMENT) is False
    assert await peek_completed_result(store, "payment_1", RESULT_NS_PAYMENT) == (False, None)


@pytest.mark.asyncio
async def test_helpers_tolerate_a_missing_store_or_key(state_store):
    assert await save_completed_result(None, "payment_1", {"ok": True}, RESULT_NS_PAYMENT) is False
    assert await save_completed_result(state_store, None, {"ok": True}, RESULT_NS_PAYMENT) is False
    assert await peek_completed_result(None, "payment_1", RESULT_NS_PAYMENT) == (False, None)
    await clear_completed_result(None, "payment_1", RESULT_NS_PAYMENT)


@pytest.mark.asyncio
async def test_result_cache_does_not_collide_with_the_payment_state(state_store):
    await state_store.set("payment_1", {"original": "args"})
    await save_completed_result(state_store, "payment_1", {"ok": True}, RESULT_NS_PAYMENT)

    stored = await state_store.get("payment_1")
    assert stored["args"] == {"original": "args"}


# ===== the cache must not answer calls it was not produced for =====

@pytest.mark.asyncio
async def test_elicitation_does_not_answer_a_different_call_from_cache(
    provider, price_info, state_store
):
    """A session-keyed cache covers every call to the tool, so it is pinned to
    the arguments that paid for it: a later call with different arguments must
    be charged and executed, not answered with the earlier result."""
    from paymcp.payment.flows import elicitation

    tool = CountingTool()
    ctx = FakeCtx()

    with patch.object(elicitation, "run_elicitation_loop", AsyncMock(return_value="paid")):
        wrapper = elicitation.make_paid_wrapper(
            tool, Mock(), {"mock": provider}, price_info, state_store=state_store
        )

        ctx.drop()
        assert _pending(await wrapper(ctx=ctx, text="A"))

        ctx.restore()
        result = await wrapper(ctx=ctx, text="B")

    assert result == {"report": "result #2"}
    assert tool.calls == 2


@pytest.mark.asyncio
async def test_progress_does_not_answer_a_different_call_from_cache(
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
        assert _pending(await wrapper(ctx=ctx, text="A"))

        ctx.restore()
        result = await wrapper(ctx=ctx, text="B")

    assert result == {"report": "result #2"}
    assert tool.calls == 2


@pytest.mark.asyncio
async def test_a_caller_supplied_payment_id_cannot_reach_a_session_keyed_result(
    provider, price_info, state_store
):
    """payment_id comes from the client, so it must not be able to name the key
    another flow cached its result under."""
    from paymcp.payment.flows import elicitation, resubmit

    paid_tool = CountingTool()
    victim_ctx = FakeCtx("SESS1")

    with patch.object(elicitation, "run_elicitation_loop", AsyncMock(return_value="paid")):
        paid_wrapper = elicitation.make_paid_wrapper(
            paid_tool, Mock(), {"mock": provider}, price_info, state_store=state_store
        )
        victim_ctx.drop()
        await paid_wrapper(ctx=victim_ctx, text="SECRET")

    other_tool = CountingTool()
    other_tool.__name__ = "other_tool"
    other_provider = Mock(spec=BasePaymentProvider)
    other_provider.create_payment = Mock(return_value=("payment_999", "https://payment.url"))
    other_provider.get_payment_status = Mock(
        side_effect=lambda pid: "paid" if pid == "payment_999" else "failed"
    )

    wrapper = resubmit.make_paid_wrapper(
        other_tool, None, {"mock": other_provider}, price_info, state_store=state_store
    )

    # Name the elicitation flow's state key as a payment id.
    with pytest.raises(RuntimeError):
        await wrapper(ctx=FakeCtx("SESS9"), payment_id="expensive_tool:SESS1")

    # No result handed out, nothing executed, and the victim's state untouched.
    assert other_tool.calls == 0
    assert await state_store.get("expensive_tool:SESS1") is not None
    assert await peek_completed_result(
        state_store, "expensive_tool:SESS1", RESULT_NS_SESSION,
        call_fingerprint({"text": "SECRET"}),
    ) == (True, {"report": "result #1"})


@pytest.mark.asyncio
async def test_result_namespaces_do_not_overlap(state_store):
    await save_completed_result(state_store, "k", {"from": "session"}, RESULT_NS_SESSION)

    assert await peek_completed_result(state_store, "k", RESULT_NS_PAYMENT) == (False, None)
    assert await peek_completed_result(state_store, "k", RESULT_NS_SESSION) == (
        True,
        {"from": "session"},
    )


@pytest.mark.asyncio
async def test_a_cached_result_is_only_served_to_a_matching_call(state_store):
    fingerprint = call_fingerprint({"text": "A"})
    await save_completed_result(
        state_store, "k", {"ok": True}, RESULT_NS_SESSION, fingerprint
    )

    other = call_fingerprint({"text": "B"})
    assert await peek_completed_result(state_store, "k", RESULT_NS_SESSION, other) == (False, None)
    assert await peek_completed_result(state_store, "k", RESULT_NS_SESSION, fingerprint) == (
        True,
        {"ok": True},
    )


@pytest.mark.asyncio
async def test_call_fingerprint_ignores_context_and_argument_order():
    ctx = FakeCtx()
    assert call_fingerprint({"a": 1, "b": 2, "ctx": ctx}) == call_fingerprint({"b": 2, "a": 1})
    assert call_fingerprint({"a": 1}) != call_fingerprint({"a": 2})
