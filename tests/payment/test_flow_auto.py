import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paymcp.payment.flows import auto


def _make_ctx(capabilities):
    """Helper to create a mock context with given capabilities."""
    if capabilities is None:
        client_caps = None
    else:
        client_caps = SimpleNamespace(model_dump=lambda: capabilities)
    client_params = SimpleNamespace(
        clientInfo=SimpleNamespace(name="client"),
        capabilities=client_caps
    )
    session = SimpleNamespace(_client_params=client_params)
    return SimpleNamespace(session=session)


def _async_return(value):
    """Helper to create a simple async function returning a value."""
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _make_wrappers(monkeypatch, elicitation_fn=None, resubmit_fn=None, x402_fn=None):
    """Helper to set up mock wrappers."""
    if elicitation_fn is None:
        elicitation_fn = _async_return("elicitation")
    if resubmit_fn is None:
        resubmit_fn = _async_return("resubmit")
    if x402_fn is None:
        x402_fn = _async_return("x402")

    monkeypatch.setattr(auto, "make_elicitation_wrapper", lambda **_: elicitation_fn)
    monkeypatch.setattr(auto, "make_resubmit_wrapper", lambda **_: resubmit_fn)
    monkeypatch.setattr(auto, "make_x402_wrapper", lambda **_: x402_fn)


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
    monkeypatch.setattr(auto, "make_x402_wrapper", lambda **_: _async_return("x402"))

    async def dummy_tool(**_kwargs):
        return "tool"

    ctx = _make_ctx({"elicitation": True})
    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
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
    monkeypatch.setattr(auto, "make_x402_wrapper", lambda **_: _async_return("x402"))

    async def dummy_tool(**_kwargs):
        return "tool"

    ctx = _make_ctx({})
    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
        state_store=object(),
        config=None,
    )

    result = await wrapper(ctx=ctx, payment_id="pid123")
    assert result == "resubmit"
    assert called["kwargs"]["payment_id"] == "pid123"


# =============================================================================
# Context Retrieval Tests
# =============================================================================


@pytest.mark.asyncio
async def test_auto_uses_x402_when_capable(monkeypatch):
    called = {}

    async def fake_x402(*_args, **kwargs):
        called["kwargs"] = kwargs
        return "x402"

    def fake_x402_wrapper(**_kwargs):
        return fake_x402

    def fake_elicitation_wrapper(**_kwargs):
        async def _elicitation(*_a, **_k):
            return "elicitation"
        return _elicitation

    def fake_resubmit_wrapper(**_kwargs):
        async def _resubmit(*_a, **_k):
            return "resubmit"
        return _resubmit

    monkeypatch.setattr(auto, "make_x402_wrapper", fake_x402_wrapper)
    monkeypatch.setattr(auto, "make_elicitation_wrapper", fake_elicitation_wrapper)
    monkeypatch.setattr(auto, "make_resubmit_wrapper", fake_resubmit_wrapper)

    async def dummy_tool(**_kwargs):
        return "tool"

    ctx = _make_ctx({"x402": True, "elicitation": True})
    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
        state_store=object(),
        config=None,
    )

    result = await wrapper(ctx=ctx, payment_id="pid123")
    assert result == "x402"
    assert "payment_id" not in called["kwargs"]


@pytest.mark.asyncio
async def test_auto_retrieves_ctx_from_mcp_when_not_in_kwargs(monkeypatch):
    """Test that ctx is fetched from mcp.get_context() when not provided in kwargs."""
    called = {"get_ctx": False}
    fake_ctx = _make_ctx({"elicitation": True})

    def fake_get_ctx_from_server(mcp):
        called["get_ctx"] = True
        return fake_ctx

    monkeypatch.setattr(auto, "get_ctx_from_server", fake_get_ctx_from_server)
    _make_wrappers(monkeypatch)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    # Call WITHOUT ctx in kwargs
    result = await wrapper()
    assert called["get_ctx"] is True
    assert result == "elicitation"


@pytest.mark.asyncio
async def test_auto_handles_get_ctx_exception_gracefully(monkeypatch):
    """Test fallback when get_ctx_from_server raises an exception."""
    def raise_error(mcp):
        raise RuntimeError("Server error")

    monkeypatch.setattr(auto, "get_ctx_from_server", raise_error)
    _make_wrappers(monkeypatch)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    # Should fall back to resubmit (no elicitation capability detected)
    result = await wrapper()
    assert result == "resubmit"


@pytest.mark.asyncio
async def test_auto_ctx_injected_into_kwargs_when_retrieved(monkeypatch):
    """Test that ctx is added to kwargs when retrieved from server."""
    received = {}
    fake_ctx = _make_ctx({})

    async def capture_resubmit(*args, **kwargs):
        received["kwargs"] = kwargs
        return "resubmit"

    monkeypatch.setattr(auto, "get_ctx_from_server", lambda _: fake_ctx)
    _make_wrappers(monkeypatch, resubmit_fn=capture_resubmit)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    await wrapper()  # No ctx provided
    assert received["kwargs"]["ctx"] is fake_ctx


# =============================================================================
# No Context Fallback Tests
# =============================================================================


@pytest.mark.asyncio
async def test_auto_falls_back_to_resubmit_when_ctx_is_none(monkeypatch):
    """Test fallback to resubmit when ctx cannot be obtained."""
    monkeypatch.setattr(auto, "get_ctx_from_server", lambda _: None)
    _make_wrappers(monkeypatch)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    result = await wrapper()  # No ctx provided, get_ctx returns None
    assert result == "resubmit"


@pytest.mark.asyncio
async def test_auto_falls_back_when_mcp_is_none(monkeypatch):
    """Test behavior when mcp instance is None."""
    _make_wrappers(monkeypatch)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=None,  # mcp is None
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    result = await wrapper()  # Should not try get_ctx_from_server
    assert result == "resubmit"


# =============================================================================
# Capabilities Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_auto_handles_capabilities_none(monkeypatch):
    """Test when capabilities is explicitly None."""
    ctx = _make_ctx(None)  # capabilities=None
    _make_wrappers(monkeypatch)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    result = await wrapper(ctx=ctx)
    assert result == "resubmit"


@pytest.mark.asyncio
async def test_auto_handles_elicitation_false(monkeypatch):
    """Test when elicitation capability is explicitly False."""
    ctx = _make_ctx({"elicitation": False})
    _make_wrappers(monkeypatch)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    result = await wrapper(ctx=ctx)
    assert result == "resubmit"


@pytest.mark.asyncio
async def test_auto_handles_other_capabilities_without_elicitation(monkeypatch):
    """Test when capabilities has other values but not elicitation."""
    ctx = _make_ctx({"sampling": True, "roots": True})
    _make_wrappers(monkeypatch)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    result = await wrapper(ctx=ctx)
    assert result == "resubmit"


# =============================================================================
# Signature Handling Tests
# =============================================================================


def test_signature_with_var_keyword_params(monkeypatch):
    """Test signature modification when original function has **kwargs."""
    _make_wrappers(monkeypatch)

    async def tool_with_kwargs(a: str, b: int, **kwargs):
        return "result"

    wrapper = auto.make_paid_wrapper(
        func=tool_with_kwargs,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    params = list(inspect.signature(wrapper).parameters.keys())
    # payment_id should come before **kwargs
    assert params == ["a", "b", "payment_id", "kwargs"]


def test_signature_without_var_keyword_params(monkeypatch):
    """Test signature modification when original function has no **kwargs."""
    _make_wrappers(monkeypatch)

    async def tool_without_kwargs(a: str, b: int):
        return "result"

    wrapper = auto.make_paid_wrapper(
        func=tool_without_kwargs,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    params = list(inspect.signature(wrapper).parameters.keys())
    assert params == ["a", "b", "payment_id"]


def test_signature_preserves_parameter_defaults(monkeypatch):
    """Test that original parameter defaults are preserved."""
    _make_wrappers(monkeypatch)

    async def tool_with_defaults(a: str, b: int = 42):
        return "result"

    wrapper = auto.make_paid_wrapper(
        func=tool_with_defaults,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    sig = inspect.signature(wrapper)
    assert sig.parameters["b"].default == 42
    assert sig.parameters["payment_id"].default == ""


def test_signature_inspection_failure_handled_gracefully(monkeypatch):
    """Test that signature inspection failure doesn't crash wrapper creation."""
    _make_wrappers(monkeypatch)

    # Create a callable that causes inspect.signature() to fail
    class BadSignatureCallable:
        __name__ = "bad_sig_tool"
        __doc__ = "Bad signature doc"

        def __call__(self):
            return "result"

        # Make inspect.signature fail by having __wrapped__ point to something invalid
        __wrapped__ = None

    # Patch inspect.signature to raise for this specific object
    original_signature = inspect.signature

    def patched_signature(obj, *args, **kwargs):
        if isinstance(obj, BadSignatureCallable):
            raise ValueError("Cannot inspect signature")
        return original_signature(obj, *args, **kwargs)

    monkeypatch.setattr(inspect, "signature", patched_signature)

    bad_func = BadSignatureCallable()

    # Should not raise, just skip signature override
    wrapper = auto.make_paid_wrapper(
        func=bad_func,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    assert wrapper is not None
    assert callable(wrapper)


# =============================================================================
# Args/Kwargs Passthrough Tests
# =============================================================================


@pytest.mark.asyncio
async def test_auto_passes_positional_args_correctly(monkeypatch):
    """Test that positional args are passed through to the selected flow."""
    received = {}

    async def capture_resubmit(*args, **kwargs):
        received["args"] = args
        received["kwargs"] = kwargs
        return "resubmit"

    _make_wrappers(monkeypatch, resubmit_fn=capture_resubmit)

    async def dummy_tool(a, b, c):
        return "tool"

    ctx = _make_ctx({})
    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    await wrapper("arg1", "arg2", "arg3", ctx=ctx)
    assert received["args"] == ("arg1", "arg2", "arg3")


@pytest.mark.asyncio
async def test_auto_passes_kwargs_correctly(monkeypatch):
    """Test that kwargs are passed through correctly."""
    received = {}

    async def capture_elicitation(*args, **kwargs):
        received["kwargs"] = kwargs
        return "elicitation"

    _make_wrappers(monkeypatch, elicitation_fn=capture_elicitation)

    async def dummy_tool(name: str, count: int):
        return "tool"

    ctx = _make_ctx({"elicitation": True})
    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    await wrapper(name="test", count=5, ctx=ctx)
    assert received["kwargs"]["name"] == "test"
    assert received["kwargs"]["count"] == 5
    # payment_id should be stripped for elicitation
    assert "payment_id" not in received["kwargs"]


# =============================================================================
# Flow Switching Consistency Tests
# =============================================================================


@pytest.mark.asyncio
async def test_auto_same_wrapper_routes_differently_per_call(monkeypatch):
    """Test that the same wrapper can route to different flows on different calls."""
    call_count = {"elicitation": 0, "resubmit": 0}

    async def count_elicitation(*args, **kwargs):
        call_count["elicitation"] += 1
        return "elicitation"

    async def count_resubmit(*args, **kwargs):
        call_count["resubmit"] += 1
        return "resubmit"

    _make_wrappers(monkeypatch, elicitation_fn=count_elicitation, resubmit_fn=count_resubmit)

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    # First call with elicitation
    ctx_with_elicitation = _make_ctx({"elicitation": True})
    await wrapper(ctx=ctx_with_elicitation)

    # Second call without elicitation
    ctx_without = _make_ctx({})
    await wrapper(ctx=ctx_without)

    # Third call with elicitation again
    await wrapper(ctx=ctx_with_elicitation)

    assert call_count["elicitation"] == 2
    assert call_count["resubmit"] == 1


@pytest.mark.asyncio
async def test_auto_payment_id_stripped_only_for_elicitation(monkeypatch):
    """Test that payment_id is stripped for x402/elicitation but kept for resubmit."""
    elicitation_received = {}
    x402_received = {}
    resubmit_received = {}

    async def capture_elicitation(*args, **kwargs):
        elicitation_received.update(kwargs)
        return "elicitation"

    async def capture_resubmit(*args, **kwargs):
        resubmit_received.update(kwargs)
        return "resubmit"

    async def capture_x402(*args, **kwargs):
        x402_received.update(kwargs)
        return "x402"

    _make_wrappers(
        monkeypatch,
        elicitation_fn=capture_elicitation,
        resubmit_fn=capture_resubmit,
        x402_fn=capture_x402,
    )

    async def dummy_tool(**_kwargs):
        return "tool"

    wrapper = auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=object(),
        providers={"mock": object()},
        price_info={"price": 1, "currency": "USD"},
    )

    # Call with elicitation - payment_id should be stripped
    ctx_elicitation = _make_ctx({"elicitation": True})
    await wrapper(ctx=ctx_elicitation, payment_id="pid123")
    assert "payment_id" not in elicitation_received

    # Call with x402 - payment_id should be stripped
    ctx_x402 = _make_ctx({"x402": True})
    await wrapper(ctx=ctx_x402, payment_id="pid789")
    assert "payment_id" not in x402_received

    # Call without elicitation - payment_id should be kept
    ctx_resubmit = _make_ctx({})
    await wrapper(ctx=ctx_resubmit, payment_id="pid456")
    assert resubmit_received["payment_id"] == "pid456"


# =============================================================================
# Wrapper Factory Parameter Tests
# =============================================================================


def test_wrapper_receives_all_parameters(monkeypatch):
    """Test that wrapper factories receive all parameters."""
    received_params = {}

    def capture_elicitation_factory(**kwargs):
        received_params["elicitation"] = kwargs
        return _async_return("elicitation")

    def capture_resubmit_factory(**kwargs):
        received_params["resubmit"] = kwargs
        return _async_return("resubmit")

    def capture_x402_factory(**kwargs):
        received_params["x402"] = kwargs
        return _async_return("x402")

    monkeypatch.setattr(auto, "make_elicitation_wrapper", capture_elicitation_factory)
    monkeypatch.setattr(auto, "make_resubmit_wrapper", capture_resubmit_factory)
    monkeypatch.setattr(auto, "make_x402_wrapper", capture_x402_factory)

    async def dummy_tool():
        return "tool"

    mock_mcp = object()
    mock_provider = object()
    mock_state_store = object()
    mock_config = {"key": "value"}
    price_info = {"price": 1, "currency": "USD"}

    auto.make_paid_wrapper(
        func=dummy_tool,
        mcp=mock_mcp,
        providers={"mock": mock_provider},
        price_info=price_info,
        state_store=mock_state_store,
        config=mock_config,
    )

    # All factories should receive all parameters
    for flow_type in ["elicitation", "resubmit", "x402"]:
        params = received_params[flow_type]
        assert params["func"] is dummy_tool
        assert params["mcp"] is mock_mcp
        assert params["providers"] == {"mock": mock_provider}
        assert params["price_info"] is price_info
        assert params["state_store"] is mock_state_store
        assert params["config"] is mock_config
