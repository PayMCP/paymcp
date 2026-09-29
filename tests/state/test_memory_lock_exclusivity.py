"""The per-payment lock has to be exclusive for callers that arrive at any time.

The registry entry used to be discarded as soon as its holder finished, so a
caller arriving after that built a second lock for the same key and ran
alongside whoever was still queued on the first.
"""

import asyncio

import pytest

from paymcp.state.memory import InMemoryStateStore


class Counter:
    """Records how many callers were inside the guarded section at once."""

    def __init__(self):
        self.inside = 0
        self.peak = 0

    async def hold(self, store, key, seconds):
        async with store.lock(key):
            self.inside += 1
            self.peak = max(self.peak, self.inside)
            await asyncio.sleep(seconds)
            self.inside -= 1


@pytest.mark.asyncio
async def test_a_caller_arriving_after_a_release_still_waits():
    """The case the old implementation let through."""
    store = InMemoryStateStore()
    counter = Counter()

    first = asyncio.create_task(counter.hold(store, "payment_1", 0.05))
    await asyncio.sleep(0.01)
    queued = asyncio.create_task(counter.hold(store, "payment_1", 0.05))
    # By now the first caller has finished and released the entry, while the
    # queued one is still inside it.
    await asyncio.sleep(0.05)
    late = asyncio.create_task(counter.hold(store, "payment_1", 0.05))

    await asyncio.gather(first, queued, late)

    assert counter.peak == 1
    assert store._payment_locks == {}


@pytest.mark.asyncio
async def test_many_staggered_callers_are_serialised():
    store = InMemoryStateStore()
    counter = Counter()

    async def staggered(delay):
        await asyncio.sleep(delay)
        await counter.hold(store, "payment_1", 0.01)

    await asyncio.gather(*(staggered(i * 0.005) for i in range(12)))

    assert counter.peak == 1
    assert store._payment_locks == {}


@pytest.mark.asyncio
async def test_different_payments_do_not_wait_for_each_other():
    store = InMemoryStateStore()
    counter = Counter()

    await asyncio.gather(
        counter.hold(store, "payment_1", 0.02),
        counter.hold(store, "payment_2", 0.02),
    )

    assert counter.peak == 2


@pytest.mark.asyncio
async def test_the_lock_is_released_and_dropped_when_the_body_raises():
    store = InMemoryStateStore()

    with pytest.raises(RuntimeError):
        async with store.lock("payment_1"):
            raise RuntimeError("boom")

    assert store._payment_locks == {}
    async with store.lock("payment_1"):
        pass


@pytest.mark.asyncio
async def test_a_caller_cancelled_while_waiting_leaves_nothing_behind():
    """A client that disconnects mid-flight cancels a caller that is queueing.

    That caller never reaches the body, so nothing else will account for it:
    if it does not, the entry is stranded with a live user for the life of the
    process, and nothing reclaims it.
    """
    store = InMemoryStateStore()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with store.lock("payment_1"):
            entered.set()
            await release.wait()

    held = asyncio.create_task(holder())
    await entered.wait()

    async def waiter():
        async with store.lock("payment_1"):
            pass

    queued = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued

    release.set()
    await held

    assert store._payment_locks == {}
    # And the key is still usable afterwards.
    async with store.lock("payment_1"):
        pass


@pytest.mark.asyncio
async def test_a_third_caller_still_waits_while_two_are_queued():
    """The invariant behind the bookkeeping, without asserting on the counters."""
    store = InMemoryStateStore()
    counter = Counter()

    first = asyncio.create_task(counter.hold(store, "payment_1", 0.04))
    await asyncio.sleep(0.005)
    second = asyncio.create_task(counter.hold(store, "payment_1", 0.04))
    await asyncio.sleep(0.005)
    third = asyncio.create_task(counter.hold(store, "payment_1", 0.04))

    await asyncio.gather(first, second, third)

    assert counter.peak == 1
    assert store._payment_locks == {}
