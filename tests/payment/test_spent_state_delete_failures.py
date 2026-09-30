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


@pytest.mark.asyncio
async def test_a_call_does_not_delete_a_payment_another_call_just_filed():
    """Session-keyed flows file every call under one key and hold no lock.

    Deleting by key alone throws away a payment a concurrent call may already
    have sent the user to make, and they are then asked for a second one.
    """
    from paymcp.payment.flows.state_utils import discard_payment_state

    store = InMemoryStateStore()
    key = "expensive_tool:session-1"

    await store.set(key, {"payment_id": "mine", "payment_url": "u"})
    # A concurrent call replaces it with its own before we clean up.
    await store.set(key, {"payment_id": "theirs", "payment_url": "u"})

    await discard_payment_state(store, key, "mine")

    surviving = await store.get(key)
    assert surviving is not None, "the other call's payment was deleted"
    assert surviving["args"]["payment_id"] == "theirs"

    await discard_payment_state(store, key, "theirs")
    assert await store.get(key) is None


@pytest.mark.asyncio
async def test_a_call_with_no_payment_of_its_own_deletes_nothing():
    """The cached-result path never read a payment record, so it has no claim
    on whatever is under the key by the time it finishes."""
    from paymcp.payment.flows.state_utils import discard_payment_state

    store = InMemoryStateStore()
    key = "expensive_tool:session-1"
    await store.set(key, {"payment_id": "someone-elses"})

    await discard_payment_state(store, key, None)

    assert await store.get(key) is not None


@pytest.mark.asyncio
async def test_a_store_that_does_not_wrap_its_payload_is_still_cleaned():
    """`state_store` is an advertised extension point, and a hand-written one
    need not copy the bundled stores' envelope. Not recognising its shape would
    leave the record behind for ever, and every later call would run free."""
    from paymcp.payment.flows.state_utils import discard_payment_state

    class PlainStore(InMemoryStateStore):
        async def get(self, key):
            entry = await super().get(key)
            return entry["args"] if entry else None

    store = PlainStore()
    key = "expensive_tool:session-1"
    await store.set(key, {"payment_id": "mine"})

    await discard_payment_state(store, key, "mine")

    assert await store.get(key) is None, "the record was not recognised and stayed"


class ReadFails(InMemoryStateStore):
    """Reads are down; deletes still work."""

    async def get(self, key):
        raise ConnectionError("state store unreachable for reads")


class ReadFailsOnce(InMemoryStateStore):
    """A store that blips on one read and works either side of it.

    Which read is chosen matters: a flow that can no longer read at all fails
    before it charges anybody, so the harm here needs a store that recovers.
    """

    def __init__(self, fail_on):
        super().__init__()
        self.fail_on = fail_on
        self.reads = 0
        self.failed = False

    async def get(self, key):
        self.reads += 1
        if self.reads == self.fail_on:
            self.failed = True
            raise ConnectionError("state store unreachable for reads")
        return await super().get(key)


@pytest.mark.asyncio
async def test_a_record_that_cannot_be_read_is_removed_rather_than_left():
    """A read that fails must not turn into "leave the payment behind".

    The record being cleaned up has been spent, and skipping the delete because
    the check could not be made leaves it under the session's key for the next
    call to find.
    """
    from paymcp.payment.flows.state_utils import discard_payment_state

    store = ReadFails()
    key = "expensive_tool:session-1"
    await store.set(key, {"payment_id": "mine"})

    await discard_payment_state(store, key, "mine")

    # Read through the parent, since this store's own get is the broken one.
    assert await InMemoryStateStore.get(store, key) is None, (
        "the spent payment was left behind"
    )


@pytest.mark.asyncio
async def test_a_blip_while_clearing_a_payment_does_not_buy_a_second_call(
    provider, price_info
):
    """What the record left behind is worth, through a flow rather than a helper.

    ELICITATION resumes a payment it finds under the session's key, so a spent
    one left there is honoured: the next call is not asked to pay, and the paid
    tool runs on a payment that has already been used.
    """
    from paymcp.payment.flows import elicitation

    # The cleanup read, which is the third this flow makes: the cached-result
    # peek, the payment record, then the check before deleting it.
    store = ReadFailsOnce(fail_on=3)
    tool = CountingTool()

    with patch.object(elicitation, "run_elicitation_loop", AsyncMock(return_value="paid")):
        wrapper = elicitation.make_paid_wrapper(
            tool, Mock(), {"mock": provider}, price_info, state_store=store
        )
        assert await wrapper(ctx=FakeCtx()) == {"report": "result #1"}
        assert await wrapper(ctx=FakeCtx()) == {"report": "result #2"}

    assert store.failed, (
        "the cleanup read never failed, so this test no longer covers anything"
    )
    assert tool.calls == 2
    assert provider.create_payment.call_count == 2, (
        "the second call was served on the first call's spent payment"
    )


@pytest.mark.asyncio
async def test_a_store_that_can_neither_read_nor_delete_does_not_raise():
    """The fallback is the forgiving delete, not a bare one.

    This runs past the point where the caller has been charged, so a store that
    cannot do it either must not take the result away with it.
    """
    from paymcp.payment.flows.state_utils import discard_payment_state

    class NothingWorks(InMemoryStateStore):
        async def get(self, key):
            raise ConnectionError("state store unreachable for reads")

        async def delete(self, key):
            raise ConnectionError("state store unreachable for writes")

    store = NothingWorks()
    key = "expensive_tool:session-1"
    await store.set(key, {"payment_id": "mine"})

    await discard_payment_state(store, key, "mine")

    assert await InMemoryStateStore.get(store, key) is not None, (
        "nothing could have removed it"
    )
