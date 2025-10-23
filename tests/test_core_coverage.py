"""Additional tests for core.py to achieve 95%+ coverage."""
import pytest
from unittest.mock import Mock, MagicMock
from paymcp import PayMCP, PaymentFlow
from paymcp.providers import MockPaymentProvider


def test_paymcp_dynamic_tools_deferred_patching():
    """Test PayMCP DYNAMIC_TOOLS flow applies deferred patching after tool registration."""
    from paymcp.decorators import price

    # Create mock MCP server
    mcp = Mock()
    mcp._mcp_server = Mock()
    registered_tools = {}

    # Simulate FastMCP-style lazy _tool_manager initialization
    # Initially, no _tool_manager
    if hasattr(mcp, '_tool_manager'):
        delattr(mcp, '_tool_manager')

    def tool_decorator(*args, **kwargs):
        def decorator(func):
            # On first tool registration, create _tool_manager
            if not hasattr(mcp, '_tool_manager'):
                mcp._tool_manager = Mock()
                mcp._tool_manager.list_tools = Mock(return_value=[])
                mcp._tool_manager._tools = {}

            # Register the tool
            tool_name = kwargs.get('name', func.__name__)
            registered_tools[tool_name] = func
            mcp._tool_manager._tools[tool_name] = func

            return func
        return decorator

    mcp.tool = tool_decorator

    # Initialize PayMCP with DYNAMIC_TOOLS flow
    paymcp = PayMCP(
        mcp,
        providers={"mock": MockPaymentProvider()},
        payment_flow=PaymentFlow.DYNAMIC_TOOLS
    )

    # Create and register a priced tool
    @price(price=1.00, currency="USD")
    async def test_tool():
        return {"result": "success"}

    # Register the tool (this should trigger deferred patching)
    @paymcp.mcp.tool(name="test_tool")
    async def wrapped_test_tool():
        return await test_tool()

    # Verify tool was registered
    assert "test_tool" in registered_tools

    # Verify deferred patching was applied (_patch_list_tools_immediate should have been called)
    # The patching is triggered in core.py lines 64-67
    if hasattr(mcp, '_tool_manager'):
        # Patching should have been applied
        assert hasattr(mcp._tool_manager.list_tools, '_paymcp_dynamic_tools_patched')


def test_paymcp_dynamic_tools_setup_flow_called():
    """Test PayMCP calls setup_flow for DYNAMIC_TOOLS flow."""
    from unittest.mock import patch

    # Create mock MCP server
    mcp = Mock()
    mcp._mcp_server = Mock()
    mcp._mcp_server.create_initialization_options = Mock(return_value={})
    mcp.tool = Mock()

    # Patch setup_flow to verify it gets called
    with patch('paymcp.payment.flows.dynamic_tools.setup_flow') as mock_setup_flow:
        # Initialize PayMCP with DYNAMIC_TOOLS flow
        paymcp = PayMCP(
            mcp,
            providers={"mock": MockPaymentProvider()},
            payment_flow=PaymentFlow.DYNAMIC_TOOLS
        )

        # Verify setup_flow was called (covers lines 34-35 in core.py)
        mock_setup_flow.assert_called_once_with(mcp, paymcp, PaymentFlow.DYNAMIC_TOOLS)


def test_paymcp_dynamic_tools_skip_patching_if_already_patched():
    """Test PayMCP skips deferred patching if list_tools already patched."""
    from paymcp.decorators import price

    # Create mock MCP server with _tool_manager already having patched list_tools
    mcp = Mock()
    mcp._mcp_server = Mock()
    mcp._tool_manager = Mock()
    patched_list_tools = Mock(return_value=[])
    patched_list_tools._paymcp_dynamic_tools_patched = True
    mcp._tool_manager.list_tools = patched_list_tools

    registered_tools = {}

    def tool_decorator(*args, **kwargs):
        def decorator(func):
            tool_name = kwargs.get('name', func.__name__)
            registered_tools[tool_name] = func
            return func
        return decorator

    mcp.tool = tool_decorator

    # Initialize PayMCP with DYNAMIC_TOOLS flow
    paymcp = PayMCP(
        mcp,
        providers={"mock": MockPaymentProvider()},
        payment_flow=PaymentFlow.DYNAMIC_TOOLS
    )

    # Create and register a priced tool
    @price(price=1.00, currency="USD")
    async def test_tool():
        return {"result": "success"}

    original_list_tools = mcp._tool_manager.list_tools

    # Register the tool
    @paymcp.mcp.tool(name="test_tool")
    async def wrapped_test_tool():
        return await test_tool()

    # Verify patching was skipped (list_tools should still be the same object)
    assert mcp._tool_manager.list_tools == original_list_tools


def test_paymcp_dynamic_tools_no_tool_manager():
    """Test PayMCP handles case where _tool_manager doesn't exist during tool registration."""
    from paymcp.decorators import price

    # Create mock MCP server without _tool_manager
    mcp = Mock(spec=['tool', '_mcp_server'])
    mcp._mcp_server = Mock()
    mcp._mcp_server.create_initialization_options = Mock(return_value={})

    registered_tools = {}

    def tool_decorator(*args, **kwargs):
        def decorator(func):
            tool_name = kwargs.get('name', func.__name__)
            registered_tools[tool_name] = func
            return func
        return decorator

    mcp.tool = tool_decorator

    # Initialize PayMCP with DYNAMIC_TOOLS flow
    paymcp = PayMCP(
        mcp,
        providers={"mock": MockPaymentProvider()},
        payment_flow=PaymentFlow.DYNAMIC_TOOLS
    )

    # Create and register a priced tool (should not crash even without _tool_manager)
    @price(price=1.00, currency="USD")
    async def test_tool():
        return {"result": "success"}

    # Register the tool (core.py line 64 checks hasattr(_tool_manager))
    @paymcp.mcp.tool(name="test_tool")
    async def wrapped_test_tool():
        return await test_tool()

    # Should complete without error
    assert "test_tool" in registered_tools
