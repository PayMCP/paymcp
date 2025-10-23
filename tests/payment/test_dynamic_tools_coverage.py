"""Additional tests for dynamic_tools.py to achieve 95%+ coverage."""
import pytest
from unittest.mock import MagicMock, AsyncMock, Mock, patch
from paymcp.payment.flows.dynamic_tools import (
    make_paid_wrapper,
    PAYMENTS,
    HIDDEN_TOOLS,
    CONFIRMATION_TOOLS,
    _defer_list_tools_patch,
    _patch_list_tools_immediate,
    _patch_list_tools,
    _send_notification
)


def test_defer_list_tools_patch():
    """Test _defer_list_tools_patch() deferred patching mechanism."""
    # Create mock MCP without _tool_manager (simulating pre-tool-registration state)
    mcp = Mock()
    mcp.tool = Mock()
    mcp._tool_manager = None  # Not created yet

    # Apply deferred patching
    _defer_list_tools_patch(mcp)

    # Verify mcp.tool was wrapped
    assert hasattr(mcp.tool, '_paymcp_deferred_patch_applied')
    assert mcp.tool._paymcp_deferred_patch_applied is True

    # Now simulate tool registration by creating _tool_manager
    mcp._tool_manager = Mock()
    mcp._tool_manager.list_tools = Mock(return_value=[])

    # Call the wrapped tool decorator
    wrapped_tool = mcp.tool

    # Create a test decorator call
    test_decorator = wrapped_tool("test_tool", "description")

    # Apply decorator to a test function
    @test_decorator
    async def test_func():
        return {"result": "success"}

    # Verify _patch_list_tools_immediate was called (indirectly via wrapper)
    assert hasattr(mcp._tool_manager.list_tools, '_paymcp_dynamic_tools_patched')


def test_patch_list_tools_immediate_no_tool_manager():
    """Test _patch_list_tools_immediate() returns early if no _tool_manager."""
    # Create mock MCP without _tool_manager
    mcp = Mock(spec=[])

    # Should not raise exception
    _patch_list_tools_immediate(mcp)


def test_patch_list_tools_immediate_already_patched():
    """Test _patch_list_tools_immediate() skips if already patched."""
    # Create mock MCP with already patched list_tools
    mcp = Mock()
    mcp._tool_manager = Mock()
    original_func = Mock(return_value=[])
    original_func._paymcp_dynamic_tools_patched = True
    mcp._tool_manager.list_tools = original_func

    # Apply patching (should skip)
    _patch_list_tools_immediate(mcp)

    # Verify it didn't replace the function
    assert mcp._tool_manager.list_tools == original_func


def test_patch_list_tools_deferred_path():
    """Test _patch_list_tools() deferred patching path when _tool_manager missing."""
    # Create mock MCP without _tool_manager
    mcp = Mock()
    mcp.tool = Mock()
    del mcp._tool_manager  # Ensure attribute doesn't exist

    # Apply patching (should trigger deferred path)
    _patch_list_tools(mcp)

    # Verify deferred patching was applied
    assert hasattr(mcp.tool, '_paymcp_deferred_patch_applied')


def test_patch_list_tools_deferred_path_already_wrapped():
    """Test _patch_list_tools() skips deferred wrapping if already wrapped."""
    # Create mock MCP without _tool_manager but with already wrapped tool
    mcp = Mock()
    mcp.tool = Mock()
    mcp.tool._paymcp_deferred_patch_applied = True
    del mcp._tool_manager

    original_tool = mcp.tool

    # Apply patching (should skip wrapping)
    _patch_list_tools(mcp)

    # Verify tool wasn't re-wrapped
    assert mcp.tool == original_tool


def test_patch_list_tools_immediate_exception_handling():
    """Test filtered_list_tools handles exceptions when retrieving session."""
    # Create mock MCP
    mcp = Mock()
    mcp._mcp_server = Mock()

    # Mock request_context to raise LookupError
    type(mcp._mcp_server).request_context = property(lambda self: (_ for _ in ()).throw(LookupError("No context")))

    # Create tool manager
    mcp._tool_manager = Mock()
    mock_tool1 = Mock()
    mock_tool1.name = "tool1"
    mcp._tool_manager.list_tools = Mock(return_value=[mock_tool1])

    # Apply patching
    _patch_list_tools_immediate(mcp)

    # Get tools (should return all tools since no session context)
    filtered = mcp._tool_manager.list_tools()
    assert len(filtered) == 1
    assert filtered[0].name == "tool1"


def test_patch_list_tools_immediate_general_exception():
    """Test filtered_list_tools handles general exceptions when retrieving session."""
    # Create mock MCP
    mcp = Mock()
    mcp._mcp_server = Mock()

    # Mock request_context to raise generic Exception
    type(mcp._mcp_server).request_context = property(lambda self: (_ for _ in ()).throw(Exception("Generic error")))

    # Create tool manager
    mcp._tool_manager = Mock()
    mock_tool1 = Mock()
    mock_tool1.name = "tool1"
    mcp._tool_manager.list_tools = Mock(return_value=[mock_tool1])

    # Apply patching
    _patch_list_tools_immediate(mcp)

    # Get tools (should return all tools since error occurred)
    filtered = mcp._tool_manager.list_tools()
    assert len(filtered) == 1
    assert filtered[0].name == "tool1"


def test_patch_list_tools_non_deferred_path():
    """Test _patch_list_tools() non-deferred path when _tool_manager exists."""
    # Create mock MCP with _tool_manager already present
    mcp = Mock()
    mcp._mcp_server = Mock()
    mcp._mcp_server.request_context = Mock()
    mock_session = Mock()
    mcp._mcp_server.request_context.session = mock_session

    # Create tool manager
    mcp._tool_manager = Mock()
    mock_tool = Mock()
    mock_tool.name = "tool1"
    mcp._tool_manager.list_tools = Mock(return_value=[mock_tool])

    # Apply patching (should use non-deferred path)
    _patch_list_tools(mcp)

    # Verify patching occurred
    assert hasattr(mcp._tool_manager.list_tools, '_paymcp_dynamic_tools_patched')

    # Test filtered function
    filtered = mcp._tool_manager.list_tools()
    assert len(filtered) == 1


@pytest.fixture(autouse=True)
def cleanup_test_state():
    """Clean up global state after each test."""
    yield
    PAYMENTS.clear()
    HIDDEN_TOOLS.clear()
    CONFIRMATION_TOOLS.clear()
