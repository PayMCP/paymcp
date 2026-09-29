"""A store that cannot delete must not cost the caller a result they paid for.

These deletes all run past the point where the paid tool has executed. The
caller has been charged and the result is in hand; letting a store error out of
the flow there throws the result away, and the retry runs the tool again.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from paymcp.providers.base import BasePaymentProvider
from paymcp.state.memory import InMemoryStateStore


class FailsToDelete(InMemoryStateStore):
    """Shaped like a store whose backend is unreachable for writes."""

    async def delete(self, key):
        raise ConnectionError("state store unreachable")


class CountingTool:
    __name__ = "expensive_tool"

    def __init__(self):
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
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


class FakeSession:
    def __init__(self, session_id):
        self.id = session_id


class FakeCtx:
    def __init__(self, session_id="session-1"):
        self.session = FakeSession(session_id)


@pytest.mark.asyncio
async def test_resubmit_returns_the_result_when_the_spent_state_cannot_be_deleted(
    provider, price_info
):
    from paymcp.payment.flows.resubmit import make_paid_wrapper

    store = FailsToDelete()
    tool = CountingTool()
    wrapper = make_paid_wrapper(tool, None, {"mock": provider}, price_info, state_store=store)

    with pytest.raises(RuntimeError) as exc:
        await wrapper()
    payment_id = exc.value.data["payment_id"]

    assert await wrapper(payment_id=payment_id) == {"report": "result #1"}
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_two_step_returns_the_result_when_the_spent_state_cannot_be_deleted(
    provider, price_info
):
    from paymcp.payment.flows import two_step

    store = FailsToDelete()
    tool = CountingTool()
    confirm = {}
    mcp = Mock()

    def capture_tool(*args, **kwargs):
        def decorator(f):
            confirm["f"] = f
            return f
        return decorator

    mcp.tool = capture_tool

    with patch.object(two_step, "get_ctx_from_server", return_value=None):
        wrapper = two_step.make_paid_wrapper(
            tool, mcp, {"mock": provider}, price_info, state_store=store
        )
        await wrapper(original_arg="value")
        assert await confirm["f"]("payment_123") == {"report": "result #1"}

    assert tool.calls == 1


@pytest.mark.asyncio
async def test_elicitation_returns_the_result_when_the_spent_state_cannot_be_deleted(
    provider, price_info
):
    from paymcp.payment.flows import elicitation

    store = FailsToDelete()
    tool = CountingTool()

    with patch.object(elicitation, "run_elicitation_loop", AsyncMock(return_value="paid")):
        wrapper = elicitation.make_paid_wrapper(
            tool, Mock(), {"mock": provider}, price_info, state_store=store
        )
        assert await wrapper(ctx=FakeCtx()) == {"report": "result #1"}

    assert tool.calls == 1


@pytest.mark.asyncio
async def test_progress_returns_the_result_when_the_spent_state_cannot_be_deleted(
    provider, price_info
):
    from paymcp.payment.flows import progress

    store = FailsToDelete()
    tool = CountingTool()

    with patch.object(progress.asyncio, "sleep", AsyncMock()):
        wrapper = progress.make_paid_wrapper(
            tool, Mock(), {"mock": provider}, price_info, state_store=store
        )
        assert await wrapper(ctx=FakeCtx()) == {"report": "result #1"}

    assert tool.calls == 1


@pytest.mark.asyncio
async def test_a_payment_that_could_not_be_cleared_stays_reusable(provider, price_info):
    """The trade-off, stated: carrying on leaves the payment spendable again.

    That is the better of the two outcomes - the alternative takes the result
    away from someone who has paid for it - but it should not be a surprise.
    """
    from paymcp.payment.flows.resubmit import make_paid_wrapper

    store = FailsToDelete()
    tool = CountingTool()
    wrapper = make_paid_wrapper(tool, None, {"mock": provider}, price_info, state_store=store)

    with pytest.raises(RuntimeError) as exc:
        await wrapper()
    payment_id = exc.value.data["payment_id"]

    await wrapper(payment_id=payment_id)
    await wrapper(payment_id=payment_id)

    assert tool.calls == 2


@pytest.mark.asyncio
async def test_a_delete_before_anything_is_charged_still_reports_its_failure(
    provider, price_info
):
    """Only the deletes past a charge are forgiving.

    Discarding a stale, unpaid payment costs nothing but the call, and hiding a
    store failure there would leave the caller believing a fresh payment was
    created. The assertion is on the store's own error type, so routing this
    delete through the forgiving helper makes the test fail.
    """
    from paymcp.payment.flows import elicitation

    store = FailsToDelete()
    tool = CountingTool()

    # A payment from an earlier call that the provider now reports as dead.
    await store.set("expensive_tool:session-1", {"payment_id": "old", "payment_url": "u"})
    provider.get_payment_status = Mock(return_value="canceled")

    with patch.object(elicitation, "run_elicitation_loop", AsyncMock(return_value="paid")):
        wrapper = elicitation.make_paid_wrapper(
            tool, Mock(), {"mock": provider}, price_info, state_store=store
        )
        with pytest.raises(ConnectionError):
            await wrapper(ctx=FakeCtx())

    assert tool.calls == 0
