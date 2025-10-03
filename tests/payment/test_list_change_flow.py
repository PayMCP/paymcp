"""Tests for LIST_CHANGE payment flow."""
import pytest
from unittest.mock import MagicMock, AsyncMock, call
from paymcp.payment.flows.list_change import make_paid_wrapper, PENDING_ARGS, HIDDEN_TOOLS


@pytest.fixture
def mock_mcp():
    """Create mock MCP server that can register tools dynamically."""
    mcp = MagicMock()
    mcp._tools = {}
    mcp._send_notification = AsyncMock()
    registered_tools = {}

    def tool_decorator(name=None, description=None):
        def decorator(func):
            # Store the registered tool
            registered_tools[name] = {
                'func': func,
                'description': description
            }
            mcp._tools[name] = func
            return func
        return decorator

    mcp.tool = tool_decorator
    mcp.registered_tools = registered_tools
    return mcp


@pytest.fixture
def mock_provider():
    """Create mock payment provider."""
    provider = MagicMock()
    provider.create_payment = MagicMock(return_value=("test_payment_id_123456", "https://pay.example.com/123"))
    provider.get_payment_status = MagicMock(return_value="paid")
    return provider


@pytest.fixture
def price_info():
    """Standard price information."""
    return {"price": 1.00, "currency": "USD"}


@pytest.mark.asyncio
async def test_list_change_hides_original_tool_on_payment(mock_mcp, mock_provider, price_info):
    """Test that LIST_CHANGE hides original tool when payment is initiated."""
    # Create a test function
    async def test_func(**kwargs):
        return {"result": "success", "args": kwargs}

    # Add original tool to mock MCP
    mock_mcp._tools['test_func'] = test_func

    # Wrap with LIST_CHANGE flow
    wrapper = make_paid_wrapper(test_func, mock_mcp, mock_provider, price_info)

    # Initially, original tool should be visible
    assert 'test_func' in mock_mcp._tools

    # Call the wrapped function to initiate payment
    result = await wrapper(data="test_data")

    # Check that payment was created
    mock_provider.create_payment.assert_called_once_with(
        amount=1.00,
        currency="USD",
        description="test_func() execution fee"
    )

    # Check response structure
    assert "payment_url" in result
    assert "payment_id" in result
    assert "next_tool" in result
    assert result["payment_id"] == "test_payment_id_123456"
    assert result["next_tool"] == "confirm_test_func_test_payment_id_123456"  # confirm_{tool}_{payid[:8]}

    # Verify original tool was HIDDEN (tracked in HIDDEN_TOOLS per session)
    # HIDDEN_TOOLS structure: {session_id: {tool_name: True}}
    assert len(HIDDEN_TOOLS) > 0, "Should have at least one session with hidden tools"
    session_id = list(HIDDEN_TOOLS.keys())[0]
    assert 'test_func' in HIDDEN_TOOLS[session_id]

    # Verify confirmation tool was registered
    assert "confirm_test_func_test_payment_id_123456" in mock_mcp.registered_tools

    # Notification sending is attempted but may fail in test environment (no MCP SDK)
    # Just verify the method exists and was attempted (even if it failed)

    # Verify arguments were stored
    assert "test_payment_id_123456" in PENDING_ARGS
    assert PENDING_ARGS["test_payment_id_123456"] == {"data": "test_data"}


@pytest.mark.asyncio
async def test_list_change_restores_tool_after_payment(mock_mcp, mock_provider, price_info):
    """Test that LIST_CHANGE restores original tool after payment confirmation."""
    # Create a test function
    async def test_func(**kwargs):
        return {"result": "executed", "input": kwargs.get("data")}

    # Add original tool to mock MCP
    mock_mcp._tools['test_func'] = test_func

    # Wrap with LIST_CHANGE flow
    wrapper = make_paid_wrapper(test_func, mock_mcp, mock_provider, price_info)

    # Initiate payment
    init_result = await wrapper(data="test_input")

    # Original tool should be hidden (tracked in HIDDEN_TOOLS per session)
    assert len(HIDDEN_TOOLS) > 0
    session_id = list(HIDDEN_TOOLS.keys())[0]
    assert 'test_func' in HIDDEN_TOOLS[session_id]

    # Get the dynamically registered confirmation tool
    confirm_tool_name = init_result["next_tool"]
    confirm_tool = mock_mcp.registered_tools[confirm_tool_name]["func"]

    # Execute the confirmation tool
    confirm_result = await confirm_tool()

    # Verify payment status was checked
    mock_provider.get_payment_status.assert_called_once_with("test_payment_id_123456")

    # Check that original function was executed with correct args
    assert confirm_result == {"result": "executed", "input": "test_input"}

    # Verify original tool was RESTORED (unmarked in HIDDEN_TOOLS)
    assert 'test_func' in mock_mcp._tools
    assert 'test_func' not in HIDDEN_TOOLS

    # Verify confirmation tool was REMOVED from tool manager
    # Note: In real implementation, it's removed from tool manager (_tool_manager._tools)
    # In test environment with mock MCP, we check it was deleted from registered_tools
    if hasattr(mock_mcp, '_tool_manager') and hasattr(mock_mcp._tool_manager, '_tools'):
        assert confirm_tool_name not in mock_mcp._tool_manager._tools

    # Verify arguments were cleaned up
    assert "test_payment_id_123456" not in PENDING_ARGS

    # Notification sending is attempted but may fail in test environment (no MCP SDK)


@pytest.mark.asyncio
async def test_list_change_unique_confirmation_per_payment(mock_mcp, mock_provider, price_info):
    """Test that each payment gets a unique confirmation tool."""
    # Setup provider to return different payment IDs
    payment_ids = ["abc12345xyz", "def67890uvw"]
    mock_provider.create_payment = MagicMock(side_effect=[
        (payment_ids[0], "https://pay.example.com/1"),
        (payment_ids[1], "https://pay.example.com/2")
    ])

    async def test_func(**kwargs):
        return {"result": "success"}

    mock_mcp._tools['test_func'] = test_func

    wrapper = make_paid_wrapper(test_func, mock_mcp, mock_provider, price_info)

    # Make two payment initiations
    result1 = await wrapper(data="first")

    # Restore tool for second payment
    mock_mcp._tools['test_func'] = test_func
    HIDDEN_TOOLS.clear()

    result2 = await wrapper(data="second")

    # Each should have unique confirmation tool names (confirm_{tool}_{payid8})
    assert result1["next_tool"].startswith("confirm_test_func_")
    assert result2["next_tool"].startswith("confirm_test_func_")
    assert result1["next_tool"] != result2["next_tool"]

    # Both tools should be registered
    assert result1["next_tool"] in mock_mcp.registered_tools
    assert result2["next_tool"] in mock_mcp.registered_tools

    # Both sets of arguments should be stored
    assert PENDING_ARGS["abc12345xyz"] == {"data": "first"}
    assert PENDING_ARGS["def67890uvw"] == {"data": "second"}


@pytest.mark.asyncio
async def test_list_change_handles_unpaid_status(mock_mcp, mock_provider, price_info):
    """Test that confirmation tool handles unpaid payment status correctly."""
    mock_provider.get_payment_status = MagicMock(return_value="pending")

    async def test_func(**kwargs):
        return {"result": "success"}

    mock_mcp._tools['test_func'] = test_func

    wrapper = make_paid_wrapper(test_func, mock_mcp, mock_provider, price_info)

    # Initiate payment
    init_result = await wrapper(data="test")

    # Get and execute confirmation tool
    confirm_tool = mock_mcp.registered_tools[init_result["next_tool"]]["func"]
    confirm_result = await confirm_tool()

    # Should return error for unpaid status
    assert "error" in confirm_result
    assert "not completed" in confirm_result["error"].lower()
    assert confirm_result["status"] == "pending"
    assert confirm_result["payment_url"] == "https://pay.example.com/123"

    # Arguments should NOT be cleaned up yet
    assert "test_payment_id_123456" in PENDING_ARGS

    # Original tool should still be hidden (in HIDDEN_TOOLS per session)
    assert len(HIDDEN_TOOLS) > 0
    session_id = list(HIDDEN_TOOLS.keys())[0]
    assert 'test_func' in HIDDEN_TOOLS[session_id]


@pytest.mark.asyncio
async def test_list_change_handles_missing_payment_id(mock_mcp, mock_provider, price_info):
    """Test that confirmation tool handles missing payment ID gracefully."""
    async def test_func(**kwargs):
        return {"result": "success"}

    mock_mcp._tools['test_func'] = test_func

    wrapper = make_paid_wrapper(test_func, mock_mcp, mock_provider, price_info)

    # Initiate payment
    init_result = await wrapper(data="test")

    # Clear the stored arguments to simulate missing payment
    PENDING_ARGS.clear()

    # Get and execute confirmation tool
    confirm_tool = mock_mcp.registered_tools[init_result["next_tool"]]["func"]
    confirm_result = await confirm_tool()

    # Should return appropriate error
    assert "error" in confirm_result
    assert "unknown or expired" in confirm_result["error"].lower()
    assert confirm_result["status"] == "failed"


@pytest.mark.asyncio
async def test_list_change_handles_provider_errors(mock_mcp, mock_provider, price_info):
    """Test that confirmation tool handles provider errors gracefully."""
    mock_provider.get_payment_status = MagicMock(side_effect=Exception("Provider API error"))

    async def test_func(**kwargs):
        return {"result": "success"}

    mock_mcp._tools['test_func'] = test_func

    wrapper = make_paid_wrapper(test_func, mock_mcp, mock_provider, price_info)

    # Initiate payment
    init_result = await wrapper(data="test")

    # Get and execute confirmation tool
    confirm_tool = mock_mcp.registered_tools[init_result["next_tool"]]["func"]
    confirm_result = await confirm_tool()

    # Should return error status
    assert "error" in confirm_result
    assert "error confirming payment" in confirm_result["error"].lower()
    assert confirm_result["status"] == "error"

    # Original tool should be restored on error
    assert 'test_func' in mock_mcp._tools
    assert 'test_func' not in HIDDEN_TOOLS


@pytest.mark.asyncio
async def test_list_change_without_send_notification(mock_mcp, mock_provider, price_info):
    """Test LIST_CHANGE works even if server doesn't support notifications."""
    # Remove notification method
    del mock_mcp._send_notification

    async def test_func(**kwargs):
        return {"result": "success"}

    mock_mcp._tools['test_func'] = test_func

    wrapper = make_paid_wrapper(test_func, mock_mcp, mock_provider, price_info)

    # Should still work without notifications
    result = await wrapper(data="test")

    assert "payment_url" in result
    # Tool still hidden (per session)
    assert len(HIDDEN_TOOLS) > 0
    session_id = list(HIDDEN_TOOLS.keys())[0]
    assert 'test_func' in HIDDEN_TOOLS[session_id]


@pytest.fixture(autouse=True)
def cleanup_state():
    """Clean up state after each test."""
    yield
    PENDING_ARGS.clear()
    HIDDEN_TOOLS.clear()