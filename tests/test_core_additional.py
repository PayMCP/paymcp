import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from paymcp.core import PayMCP
from paymcp.payment.payment_flow import PaymentFlow


class DummyContent:
    def __init__(self, text):
        self.text = text


def _make_mcp_with_tool_manager(list_tools_result=None, call_tool_result=None):
    mcp = Mock()
    mcp.tool = Mock(return_value=lambda func: func)
    mcp._tool_manager = Mock()
    def list_tools():
        return list_tools_result or []

    async def call_tool(_name, _arguments, context=None, convert_result=False):
        return call_tool_result

    mcp._tool_manager.list_tools = list_tools
    mcp._tool_manager.call_tool = call_tool
    mcp._mcp_server = SimpleNamespace(request_context=Mock())
    return mcp


def test_x402_provider_forces_x402_mode_when_only_provider():
    mcp = _make_mcp_with_tool_manager()
    paymcp = PayMCP(
        mcp,
        providers={"x402": {"pay_to": [{"address": "0xabc"}]}},
        payment_flow=PaymentFlow.TWO_STEP,
    )
    assert paymcp.payment_flow == PaymentFlow.X402


def test_x402_provider_forces_auto_mode_with_multiple_providers():
    mcp = _make_mcp_with_tool_manager()
    paymcp = PayMCP(
        mcp,
        providers={
            "x402": {"pay_to": [{"address": "0xabc"}]},
            "mock": {},
        },
        payment_flow=PaymentFlow.TWO_STEP,
    )
    assert paymcp.payment_flow == PaymentFlow.AUTO


def test_x402_mode_without_x402_provider_falls_back_to_resubmit():
    mcp = _make_mcp_with_tool_manager()
    paymcp = PayMCP(
        mcp,
        providers={"mock": {}},
        payment_flow=PaymentFlow.X402,
    )
    assert paymcp.payment_flow == PaymentFlow.RESUBMIT


@pytest.mark.asyncio
async def test_patch_tool_call_raises_on_x402_error():
    error_text = json.dumps({"error": {"code": 402, "message": "Payment required"}})
    mcp = _make_mcp_with_tool_manager(call_tool_result=[DummyContent(error_text)])
    paymcp = PayMCP(mcp, providers={"mock": {}})
    if not hasattr(mcp._tool_manager.call_tool, "_paymcp_patched"):
        paymcp._patch_tool_call()

    with pytest.raises(RuntimeError):
        await mcp._tool_manager.call_tool("tool", {})


def test_patch_list_tools_strips_payment_id_for_auto(monkeypatch):
    tools = [
        {
            "name": "paid_tool",
            "parameters": {
                "properties": {"payment_id": {"type": "string"}, "x": {"type": "string"}},
                "required": ["payment_id"],
            },
        }
    ]
    mcp = _make_mcp_with_tool_manager(list_tools_result=tools)

    monkeypatch.setattr(
        "paymcp.core.capture_client_from_ctx",
        lambda _ctx: {"capabilities": {"elicitation": True}},
    )

    paymcp = PayMCP(mcp, providers={"mock": {}})
    paymcp.paidtools = {"paid_tool": {"amount": 1, "currency": "USD", "description": "test"}}

    paymcp._patch_list_tool_for_auto()
    patched_tools = mcp._tool_manager.list_tools()
    props = patched_tools[0]["parameters"]["properties"]
    assert "payment_id" not in props
    assert "payment_id" not in patched_tools[0]["parameters"].get("required", [])
