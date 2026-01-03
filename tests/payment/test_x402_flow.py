import base64
import json
from unittest.mock import AsyncMock, Mock

import pytest

from paymcp.payment.flows import x402 as x402_flow
from paymcp.payment.flows.x402 import (
    _get_header,
    _get_headers,
    _get_meta,
    make_paid_wrapper,
)


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


def test_get_headers_with_mapping_like():
    class Headers:
        def __init__(self):
            self._data = {"x": "1", "Y": "2"}

        def keys(self):
            return self._data.keys()

        def get(self, key):
            return self._data.get(key)

    ctx = DummyCtx(
        request_context=DummyRequestContext(request=DummyRequest(headers=Headers())),
        session=DummySession(),
    )
    headers = _get_headers(ctx)
    assert headers["x"] == "1"
    assert headers["Y"] == "2"


def test_get_meta_model_dump_and_dict():
    class MetaV2:
        def model_dump(self):
            return {"x": 1}

    ctx = DummyCtx(request_context=DummyRequestContext(meta=MetaV2()), session=DummySession())
    assert _get_meta(ctx) == {"x": 1}

    class MetaV1:
        def dict(self):
            return {"y": 2}

    ctx = DummyCtx(request_context=DummyRequestContext(meta=MetaV1()), session=DummySession())
    assert _get_meta(ctx) == {"y": 2}


def test_get_header_case_insensitive():
    headers = {"PAYMENT-SIGNATURE": "sig"}
    assert _get_header(headers, "payment-signature") == "sig"


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


def test_x402_missing_state_store_raises():
    async def tool(**_kwargs):
        return "ok"

    with pytest.raises(RuntimeError, match="StateStore is required"):
        make_paid_wrapper(
            func=tool,
            mcp=None,
            providers={"x402": Mock()},
            price_info={"price": 1.0, "currency": "USD"},
            state_store=None,
        )


def test_x402_missing_price_info_raises():
    async def tool(**_kwargs):
        return "ok"

    with pytest.raises(RuntimeError, match="Invalid price info"):
        make_paid_wrapper(
            func=tool,
            mcp=None,
            providers={"x402": Mock()},
            price_info=None,
            state_store=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_x402_unknown_challenge_id_raises():
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
    state_store.get = AsyncMock(return_value=None)

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

    with pytest.raises(RuntimeError, match="Unknown challenge ID"):
        await wrapper(ctx=ctx)


@pytest.mark.asyncio
async def test_x402_payment_pending_raises():
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
    provider.get_payment_status = Mock(return_value="pending")

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

    with pytest.raises(RuntimeError, match="Payment is not confirmed yet"):
        await wrapper(ctx=ctx)


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
