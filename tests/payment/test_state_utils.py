from paymcp.payment.flows.state_utils import sanitize_state_args


def test_sanitize_state_args_removes_ctx():
    data = {"a": 1, "ctx": object()}
    cleaned = sanitize_state_args(data)
    assert "ctx" not in cleaned
    assert cleaned["a"] == 1


def test_sanitize_state_args_removes_nested_ctx():
    data = {"args": {"x": 1, "ctx": object()}}
    cleaned = sanitize_state_args(data)
    assert "ctx" not in cleaned["args"]
    assert cleaned["args"]["x"] == 1


def test_sanitize_state_args_empty():
    assert sanitize_state_args({}) == {}
