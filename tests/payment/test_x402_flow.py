import base64
import json
from unittest.mock import AsyncMock, Mock

import pytest

from paymcp.payment.flows import x402 as x402_flow
from paymcp.payment.flows.x402 import make_paid_wrapper


class DummyRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


class DummyRequestContext:
    def __init__(self, request=None, meta=None):
        self.request = request
        self.meta = meta or {}


class DummyCtx:
    def __init__(self, request_context=None, session=None):
        self.request_context = request_context
        self.session = session


class DummySession:
    pass


def _build_sig(payment_data):
    accept = payment_data["accepts"][0]
    return {
        "x402Version": payment_data.get("x402Version"),
        "accepted": {
            "amount": accept.get("amount"),
            "network": accept.get("network"),
            "asset": accept.get("asset"),
            "payTo": accept.get("payTo"),
            "extra": accept.get("extra"),
        },
        "payload": {"authorization": {"to": accept.get("payTo")}},
    }


@pytest.mark.asyncio
async def test_x402_creates_payment_when_no_signature():
    payment_data = {
        "x402Version": 2,
        "accepts": [
            {
                "amount": "100",
                "network": "eip155:8453",
                "asset": "USDC",
                "payTo": "0xabc",
                "extra": {"challengeId": "cid-123"},
            }
        ],
    }
    provider = Mock()
    provider.create_payment = Mock(return_value=("pid-123", "", payment_data))

    state_store = AsyncMock()
    state_store.set = AsyncMock()

    async def tool(**_kwargs):
        return "ok"

    ctx = DummyCtx(request_context=DummyRequestContext(request=DummyRequest({})), session=DummySession())

    wrapper = make_paid_wrapper(
        func=tool,
        mcp=None,
        providers={"x402": provider},
        price_info={"price": 1.0, "currency": "USD"},
        state_store=state_store,
    )

    result = await wrapper(ctx=ctx)
    assert result["error"]["code"] == 402
    assert result["error"]["data"] == payment_data
    state_store.set.assert_called_once_with("cid-123", {"paymentData": payment_data})
    provider.create_payment.assert_called_once()


@pytest.mark.asyncio
async def test_x402_accepts_meta_signature_and_executes_tool():
    payment_data = {
        "x402Version": 2,
        "accepts": [
            {
                "amount": "100",
                "network": "eip155:8453",
                "asset": "USDC",
                "payTo": "0xabc",
                "extra": {"challengeId": "cid-123"},
            }
        ],
    }
    sig = _build_sig(payment_data)
    meta = {"x402/payment": sig}

    provider = Mock()
    provider.get_payment_status = Mock(return_value="paid")

    state_store = AsyncMock()
    state_store.get = AsyncMock(return_value={"args": {"paymentData": payment_data}})
    state_store.delete = AsyncMock()

    async def tool(**_kwargs):
        return "ok"

    ctx = DummyCtx(
        request_context=DummyRequestContext(request=DummyRequest({}), meta=meta),
        session=DummySession(),
    )

    wrapper = make_paid_wrapper(
        func=tool,
        mcp=None,
        providers={"x402": provider},
        price_info={"price": 1.0, "currency": "USD"},
        state_store=state_store,
    )

    result = await wrapper(ctx=ctx)
    assert result == "ok"
    state_store.delete.assert_called_once_with("cid-123")
    provider.get_payment_status.assert_called_once()


@pytest.mark.asyncio
async def test_x402_accepts_x_payment_header_and_executes_tool():
    payment_data = {
        "x402Version": 2,
        "accepts": [
            {
                "amount": "100",
                "network": "eip155:8453",
                "asset": "USDC",
                "payTo": "0xabc",
                "extra": {"challengeId": "cid-123"},
            }
        ],
    }
    sig = _build_sig(payment_data)
    sig_b64 = base64.b64encode(json.dumps(sig).encode("utf-8")).decode("utf-8")

    provider = Mock()
    provider.get_payment_status = Mock(return_value="paid")

    state_store = AsyncMock()
    state_store.get = AsyncMock(return_value={"args": {"paymentData": payment_data}})
    state_store.delete = AsyncMock()

    async def tool(**_kwargs):
        return "ok"

    headers = {"x-payment": sig_b64}
    ctx = DummyCtx(request_context=DummyRequestContext(request=DummyRequest(headers)), session=DummySession())

    wrapper = make_paid_wrapper(
        func=tool,
        mcp=None,
        providers={"x402": provider},
        price_info={"price": 1.0, "currency": "USD"},
        state_store=state_store,
    )

    result = await wrapper(ctx=ctx)
    assert result == "ok"
    state_store.delete.assert_called_once_with("cid-123")
    provider.get_payment_status.assert_called_once()


@pytest.mark.asyncio
async def test_x402_rejects_incorrect_signature():
    payment_data = {
        "x402Version": 2,
        "accepts": [
            {
                "amount": "100",
                "network": "eip155:8453",
                "asset": "USDC",
                "payTo": "0xabc",
                "extra": {"challengeId": "cid-123"},
            }
        ],
    }
    sig = _build_sig(payment_data)
    sig["accepted"]["amount"] = "200"
    sig_b64 = base64.b64encode(json.dumps(sig).encode("utf-8")).decode("utf-8")

    provider = Mock()
    provider.get_payment_status = Mock(return_value="paid")

    state_store = AsyncMock()
    state_store.get = AsyncMock(return_value={"args": {"paymentData": payment_data}})

    async def tool(**_kwargs):
        return "ok"

    headers = {"payment-signature": sig_b64}
    ctx = DummyCtx(request_context=DummyRequestContext(request=DummyRequest(headers)), session=DummySession())

    wrapper = make_paid_wrapper(
        func=tool,
        mcp=None,
        providers={"x402": provider},
        price_info={"price": 1.0, "currency": "USD"},
        state_store=state_store,
    )

    with pytest.raises(RuntimeError, match="Incorrect signature"):
        await wrapper(ctx=ctx)


@pytest.mark.asyncio
async def test_x402_payment_error_cleans_state():
    payment_data = {
        "x402Version": 2,
        "accepts": [
            {
                "amount": "100",
                "network": "eip155:8453",
                "asset": "USDC",
                "payTo": "0xabc",
                "extra": {"challengeId": "cid-123"},
            }
        ],
    }
    sig = _build_sig(payment_data)
    sig_b64 = base64.b64encode(json.dumps(sig).encode("utf-8")).decode("utf-8")

    provider = Mock()
    provider.get_payment_status = Mock(return_value="error")

    state_store = AsyncMock()
    state_store.get = AsyncMock(return_value={"args": {"paymentData": payment_data}})
    state_store.delete = AsyncMock()

    async def tool(**_kwargs):
        return "ok"

    headers = {"payment-signature": sig_b64}
    ctx = DummyCtx(request_context=DummyRequestContext(request=DummyRequest(headers)), session=DummySession())

    wrapper = make_paid_wrapper(
        func=tool,
        mcp=None,
        providers={"x402": provider},
        price_info={"price": 1.0, "currency": "USD"},
        state_store=state_store,
    )

    with pytest.raises(RuntimeError, match="Payment failed"):
        await wrapper(ctx=ctx)
    state_store.delete.assert_called_once_with("cid-123")


@pytest.mark.asyncio
async def test_x402_v1_sets_session_challenge_id(monkeypatch):
    payment_data = {
        "x402Version": 1,
        "accepts": [
            {
                "amount": "100",
                "network": "base",
                "asset": "USDC",
                "payTo": "0xabc",
            }
        ],
    }
    provider = Mock()
    provider.create_payment = Mock(return_value=("pid-123", "", payment_data))

    state_store = AsyncMock()
    state_store.set = AsyncMock()

    async def tool(**_kwargs):
        return "ok"

    monkeypatch.setattr(x402_flow, "capture_client_from_ctx", lambda _ctx: {"sessionId": "sess-1"})
    ctx = DummyCtx(request_context=DummyRequestContext(request=DummyRequest({})), session=DummySession())

    wrapper = make_paid_wrapper(
        func=tool,
        mcp=None,
        providers={"x402": provider},
        price_info={"price": 1.0, "currency": "USD"},
        state_store=state_store,
    )

    result = await wrapper(ctx=ctx)
    assert result["error"]["code"] == 402
    state_store.set.assert_called_once_with("sess-1-tool", {"paymentData": payment_data})


@pytest.mark.asyncio
async def test_x402_v1_requires_session_id(monkeypatch):
    payment_data = {
        "x402Version": 1,
        "accepts": [
            {
                "amount": "100",
                "network": "base",
                "asset": "USDC",
                "payTo": "0xabc",
            }
        ],
    }
    provider = Mock()
    provider.create_payment = Mock(return_value=("pid-123", "", payment_data))

    state_store = AsyncMock()

    async def tool(**_kwargs):
        return "ok"

    monkeypatch.setattr(x402_flow, "capture_client_from_ctx", lambda _ctx: {"sessionId": None})
    ctx = DummyCtx(request_context=DummyRequestContext(request=DummyRequest({})), session=DummySession())

    wrapper = make_paid_wrapper(
        func=tool,
        mcp=None,
        providers={"x402": provider},
        price_info={"price": 1.0, "currency": "USD"},
        state_store=state_store,
    )

    with pytest.raises(RuntimeError, match="Session ID is not found"):
        await wrapper(ctx=ctx)
