import inspect
from types import SimpleNamespace

import pytest

from paymcp.payment.flows import auto


def _make_ctx(capabilities):
    client_caps = SimpleNamespace(model_dump=lambda: capabilities)
    client_params = SimpleNamespace(clientInfo=SimpleNamespace(name="client"), capabilities=client_caps)
    session = SimpleNamespace(_client_params=client_params)
    return SimpleNamespace(session=session)


@pytest.mark.asyncio
async def test_auto_uses_elicitation_when_capable(monkeypatch):
    called = {}

    async def fake_elicitation(*_args, **kwargs):
        called["kwargs"] = kwargs
        return "elicitation"

    def fake_elicitation_wrapper(**_kwargs):
        return fake_elicitation

    def fake_resubmit_wrapper(**_kwargs):
        async def _resubmit(*_a, **_k):
            return "resubmit"
        return _resubmit

    monkeypatch.setattr(auto, "make_elicitation_wrapper", fake_elicitation_wrapper)
    monkeypatch.setattr(auto, "make_resubmit_wrapper", fake_resubmit_wrapper)

    async def dummy_tool(**_kwargs):
        return "tool"

    ctx = _make_ctx({"elicitation": True})
    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        provider=object(),
        price_info={"price": 1, "currency": "USD"},
        state_store=object(),
        config=None,
    )

    # Signature should include optional payment_id kw-only arg
    params = inspect.signature(wrapper).parameters
    assert "payment_id" in params
    assert params["payment_id"].kind == inspect.Parameter.KEYWORD_ONLY

    result = await wrapper(ctx=ctx, payment_id="pid123")
    assert result == "elicitation"
    assert "payment_id" not in called["kwargs"]


@pytest.mark.asyncio
async def test_auto_falls_back_to_resubmit(monkeypatch):
    called = {}

    async def fake_resubmit(*_args, **kwargs):
        called["kwargs"] = kwargs
        return "resubmit"

    def fake_resubmit_wrapper(**_kwargs):
        return fake_resubmit

    def fake_elicitation_wrapper(**_kwargs):
        async def _elicitation(*_a, **_k):
            return "elicitation"
        return _elicitation

    monkeypatch.setattr(auto, "make_elicitation_wrapper", fake_elicitation_wrapper)
    monkeypatch.setattr(auto, "make_resubmit_wrapper", fake_resubmit_wrapper)

    async def dummy_tool(**_kwargs):
        return "tool"

    ctx = _make_ctx({})
    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        provider=object(),
        price_info={"price": 1, "currency": "USD"},
        state_store=object(),
        config=None,
    )

    result = await wrapper(ctx=ctx, payment_id="pid123")
    assert result == "resubmit"
    assert called["kwargs"]["payment_id"] == "pid123"
