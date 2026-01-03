import json
import sys
import types
from unittest.mock import AsyncMock, Mock

import pytest

from paymcp.payment.payment_flow import Mode
from paymcp.utils.x402 import build_x402_middleware


def test_build_x402_middleware_requires_starlette(monkeypatch):
    import builtins
    import sys

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("starlette"):
            raise ImportError("no starlette")
        return original_import(name, *args, **kwargs)

    for mod in list(sys.modules):
        if mod.startswith("starlette"):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="Starlette is required"):
        build_x402_middleware({}, None, {}, Mode.X402, None)


def _install_fake_starlette(monkeypatch):
    starlette_pkg = types.ModuleType("starlette")
    middleware_pkg = types.ModuleType("starlette.middleware")
    middleware_base = types.ModuleType("starlette.middleware.base")

    class BaseHTTPMiddleware:
        def __init__(self, app=None):
            self.app = app

    middleware_base.BaseHTTPMiddleware = BaseHTTPMiddleware

    requests_mod = types.ModuleType("starlette.requests")

    class Request:
        pass

    requests_mod.Request = Request

    responses_mod = types.ModuleType("starlette.responses")

    class JSONResponse:
        def __init__(self, content, status_code=200):
            self.content = content
            self.status_code = status_code
            self.headers = {}

    responses_mod.JSONResponse = JSONResponse

    monkeypatch.setitem(sys.modules, "starlette", starlette_pkg)
    monkeypatch.setitem(sys.modules, "starlette.middleware", middleware_pkg)
    monkeypatch.setitem(sys.modules, "starlette.middleware.base", middleware_base)
    monkeypatch.setitem(sys.modules, "starlette.requests", requests_mod)
    monkeypatch.setitem(sys.modules, "starlette.responses", responses_mod)


def _make_request(body, headers=None, method="POST"):
    class DummyRequest:
        def __init__(self):
            self.method = method
            self.headers = headers or {}

        async def json(self):
            return body

    return DummyRequest()


@pytest.mark.asyncio
async def test_x402_middleware_returns_payment_required(monkeypatch):
    _install_fake_starlette(monkeypatch)
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
    provider.create_payment = Mock(return_value=("cid-123", "", payment_data))

    state_store = AsyncMock()
    paidtools = {"paid_tool": {"amount": 1.0, "currency": "USD", "description": "test"}}

    Middleware = build_x402_middleware(
        providers={"x402": provider},
        state_store=state_store,
        paidtools=paidtools,
        mode=Mode.X402,
        logger=Mock(),
    )

    async def call_next(_request):
        return Mock(status_code=200)

    request = _make_request({"method": "tools/call", "params": {"name": "paid_tool"}})
    response = await Middleware(Mock()).dispatch(request, call_next)

    assert response.status_code == 402
    assert "PAYMENT-REQUIRED" in response.headers
    state_store.set.assert_called_once_with("cid-123", {"paymentData": payment_data})


@pytest.mark.asyncio
async def test_x402_middleware_passes_through_with_signature(monkeypatch):
    _install_fake_starlette(monkeypatch)
    provider = Mock()
    state_store = AsyncMock()
    paidtools = {"paid_tool": {"amount": 1.0, "currency": "USD", "description": "test"}}

    Middleware = build_x402_middleware(
        providers={"x402": provider},
        state_store=state_store,
        paidtools=paidtools,
        mode=Mode.X402,
        logger=Mock(),
    )

    call_next = AsyncMock(return_value=Mock(status_code=200))
    request = _make_request(
        {"method": "tools/call", "params": {"name": "paid_tool"}},
        headers={"payment-signature": "sig"},
    )

    response = await Middleware(Mock()).dispatch(request, call_next)
    assert response.status_code == 200
    call_next.assert_awaited_once()
    state_store.set.assert_not_called()


@pytest.mark.asyncio
async def test_x402_middleware_v1_uses_session_key(monkeypatch):
    _install_fake_starlette(monkeypatch)
    payment_data = {
        "x402Version": 1,
        "accepts": [
            {
                "amount": "100",
                "network": "base",
                "asset": "USDC",
                "payTo": "0xabc",
                "extra": {"name": "USDC", "version": "2"},
            }
        ],
    }
    provider = Mock()
    provider.create_payment = Mock(return_value=("pid-1", "", payment_data))

    state_store = AsyncMock()
    paidtools = {"paid_tool": {"amount": 1.0, "currency": "USD", "description": "test"}}

    Middleware = build_x402_middleware(
        providers={"x402": provider},
        state_store=state_store,
        paidtools=paidtools,
        mode=Mode.X402,
        logger=Mock(),
    )

    request = _make_request(
        {"method": "tools/call", "params": {"name": "paid_tool"}},
        headers={"mcp-session-id": "sess-1"},
    )
    response = await Middleware(Mock()).dispatch(request, AsyncMock())

    assert response.status_code == 402
    state_store.set.assert_called_once_with("sess-1-paid_tool", {"paymentData": payment_data})


@pytest.mark.asyncio
async def test_x402_middleware_passes_non_post_and_non_tool_calls(monkeypatch):
    _install_fake_starlette(monkeypatch)
    provider = Mock()
    state_store = AsyncMock()

    Middleware = build_x402_middleware(
        providers={"x402": provider},
        state_store=state_store,
        paidtools={"paid_tool": {"amount": 1.0, "currency": "USD"}},
        mode=Mode.X402,
        logger=Mock(),
    )

    call_next = AsyncMock(return_value=Mock(status_code=200))

    request = _make_request({"method": "tools/call", "params": {"name": "paid_tool"}}, method="GET")
    response = await Middleware(Mock()).dispatch(request, call_next)
    assert response.status_code == 200

    request = _make_request({"method": "tools/list"}, method="POST")
    response = await Middleware(Mock()).dispatch(request, call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_x402_middleware_skips_when_no_provider_or_mode(monkeypatch):
    _install_fake_starlette(monkeypatch)
    state_store = AsyncMock()
    call_next = AsyncMock(return_value=Mock(status_code=200))

    Middleware = build_x402_middleware(
        providers={},
        state_store=state_store,
        paidtools={},
        mode=Mode.X402,
        logger=Mock(),
    )
    request = _make_request({"method": "tools/call", "params": {"name": "paid_tool"}})
    response = await Middleware(Mock()).dispatch(request, call_next)
    assert response.status_code == 200

    provider = Mock()
    Middleware = build_x402_middleware(
        providers={"x402": provider},
        state_store=state_store,
        paidtools={"paid_tool": {"amount": 1.0, "currency": "USD"}},
        mode=Mode.AUTO,
        logger=Mock(),
    )
    response = await Middleware(Mock()).dispatch(request, call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_x402_middleware_handles_bad_json(monkeypatch):
    _install_fake_starlette(monkeypatch)
    provider = Mock()
    state_store = AsyncMock()

    class BadJsonRequest:
        method = "POST"
        headers = {}

        async def json(self):
            raise ValueError("bad json")

    Middleware = build_x402_middleware(
        providers={"x402": provider},
        state_store=state_store,
        paidtools={"paid_tool": {"amount": 1.0, "currency": "USD"}},
        mode=Mode.X402,
        logger=Mock(),
    )

    call_next = AsyncMock(return_value=Mock(status_code=200))
    response = await Middleware(Mock()).dispatch(BadJsonRequest(), call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_x402_middleware_handles_internal_exception(monkeypatch):
    _install_fake_starlette(monkeypatch)
    provider = Mock()
    provider.create_payment = Mock(side_effect=RuntimeError("boom"))
    state_store = AsyncMock()

    Middleware = build_x402_middleware(
        providers={"x402": provider},
        state_store=state_store,
        paidtools={"paid_tool": {"amount": 1.0, "currency": "USD"}},
        mode=Mode.X402,
        logger=Mock(),
    )

    call_next = AsyncMock(return_value=Mock(status_code=200))
    request = _make_request({"method": "tools/call", "params": {"name": "paid_tool"}})
    response = await Middleware(Mock()).dispatch(request, call_next)
    assert response.status_code == 200
