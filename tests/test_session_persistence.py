#!/usr/bin/env python3
"""
Comprehensive test suite for SessionManager integration across all payment flows.
Tests session persistence, timeout handling, and payment confirmation for all flows.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from paymcp import PayMCP, PaymentFlow
from paymcp.payment.flows import two_step, elicitation, progress
from paymcp.providers.base import BasePaymentProvider
from paymcp.session import SessionManager, SessionKey, SessionData


# Test data
PRICE_INFO = {"price": 0.05, "currency": "USD"}
PAYMENT_ID = "test_payment_123"
PAYMENT_URL = "https://pay.example.com/123"


class MockProvider(BasePaymentProvider):
    """Mock provider for testing with configurable behavior"""

    def __init__(self, name="mock", **config):
        super().__init__()
        self.name = name
        self.config = config
        self.payments = {}
        self.payment_delay = config.get("payment_delay", 0)

    def get_name(self):
        return self.name

    def create_payment(self, amount, currency, description="Payment"):
        payment_id = f"{self.name}_{PAYMENT_ID}"
        payment_url = f"https://{self.name}.example.com/pay/123"
        self.payments[payment_id] = {
            "status": "pending",
            "amount": amount,
            "currency": currency,
            "created_at": asyncio.get_event_loop().time(),
        }
        return payment_id, payment_url

    def get_payment_status(self, payment_id):
        if payment_id not in self.payments:
            return "unknown"

        payment = self.payments[payment_id]

        # Simulate delayed payment confirmation
        if self.payment_delay > 0:
            elapsed = asyncio.get_event_loop().time() - payment["created_at"]
            if elapsed >= self.payment_delay:
                payment["status"] = "paid"

        return payment["status"]

    def set_payment_status(self, payment_id, status):
        """Helper method for testing"""
        if payment_id in self.payments:
            self.payments[payment_id]["status"] = status


@pytest.fixture
def mock_mcp():
    """Mock MCP server instance"""
    mcp = Mock()
    registered_tools = {}

    def mock_tool_decorator(name=None, description=None):
        def decorator(f):
            tool_name = name if name else f.__name__
            registered_tools[tool_name] = f
            return f

        # Handle both @mcp.tool() and @mcp.tool cases
        if callable(name):
            # Direct decoration without parentheses
            func = name
            tool_name = func.__name__
            registered_tools[tool_name] = func
            return func
        return decorator

    mcp.tool = mock_tool_decorator
    mcp.registered_tools = registered_tools
    return mcp


@pytest.fixture
async def mock_func():
    """Mock function to be wrapped with payment"""
    func = AsyncMock()
    func.__name__ = "test_function"
    func.return_value = {"result": "success", "data": "test_data"}
    return func


@pytest.fixture
def mock_ctx():
    """Mock context with progress reporting"""
    ctx = Mock()
    ctx.report_progress = AsyncMock()
    return ctx


class TestSessionPersistenceAllFlows:
    """Test session persistence across all payment flows"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "flow", [PaymentFlow.TWO_STEP, PaymentFlow.ELICITATION, PaymentFlow.PROGRESS]
    )
    async def test_session_storage_on_timeout(
        self, flow, mock_mcp, mock_func, mock_ctx
    ):
        """Test that session is properly stored when payment times out"""
        provider = MockProvider(name="test_provider")

        # Get the appropriate wrapper based on flow
        if flow == PaymentFlow.TWO_STEP:
            wrapper = two_step.make_paid_wrapper(
                mock_func, mock_mcp, provider, PRICE_INFO
            )
            # For TWO_STEP, the wrapper IS the initiate tool
            result = await wrapper()
            payment_id = result["payment_id"]

        elif flow == PaymentFlow.ELICITATION:
            with patch(
                "paymcp.payment.flows.elicitation.run_elicitation_loop"
            ) as mock_elicitation:
                mock_elicitation.return_value = "timeout"
                wrapper = elicitation.make_paid_wrapper(
                    mock_func, mock_mcp, provider, PRICE_INFO
                )
                result = await wrapper("arg1", "arg2", ctx=mock_ctx, key="value")
                payment_id = result["payment_id"]

        elif flow == PaymentFlow.PROGRESS:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch("paymcp.payment.flows.progress.MAX_WAIT_SECONDS", 0.1):
                    with patch(
                        "paymcp.payment.flows.progress.DEFAULT_POLL_SECONDS", 0.01
                    ):
                        wrapper = progress.make_paid_wrapper(
                            mock_func, mock_mcp, provider, PRICE_INFO
                        )
                        result = await wrapper(
                            "arg1", "arg2", ctx=mock_ctx, key="value"
                        )
                        payment_id = result["payment_id"]

        # Verify response contains pending status and payment details
        assert result["status"] == "pending"
        assert "payment_id" in result
        assert "payment_url" in result

        # TWO_STEP flow still has next_step (confirmation tool)
        # ELICITATION and PROGRESS flows no longer have next_step
        if flow == PaymentFlow.TWO_STEP:
            assert "next_step" in result
            assert result["next_step"] == f"confirm_{mock_func.__name__}_payment"
        else:
            # ELICITATION and PROGRESS don't add confirmation tools anymore
            assert "next_step" not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "flow", [PaymentFlow.TWO_STEP]  # Only TWO_STEP has confirmation tools now
    )
    async def test_confirmation_tool_with_session(
        self, flow, mock_mcp, mock_func, mock_ctx
    ):
        """Test that confirmation tool correctly retrieves and uses stored session"""
        provider = MockProvider(name="test_provider")

        # Get wrapper and confirmation tool (only for TWO_STEP)
        wrapper = two_step.make_paid_wrapper(mock_func, mock_mcp, provider, PRICE_INFO)

        # Only TWO_STEP has confirmation tools now
        if flow == PaymentFlow.TWO_STEP:
            confirm_tool = mock_mcp.registered_tools.get(
                f"confirm_{mock_func.__name__}_payment"
            )
            assert confirm_tool is not None
        else:
            # ELICITATION and PROGRESS don't have confirmation tools
            confirm_tool = None

        # Create payment and mark as paid
        payment_id = f"{provider.name}_{PAYMENT_ID}"
        provider.payments[payment_id] = {
            "status": "paid",
            "amount": 0.05,
            "currency": "USD",
        }

        # Mock session storage
        module_name = {
            PaymentFlow.TWO_STEP: "paymcp.payment.flows.two_step",
            PaymentFlow.ELICITATION: "paymcp.payment.flows.elicitation",
            PaymentFlow.PROGRESS: "paymcp.payment.flows.progress",
        }[flow]

        with patch(f"{module_name}.session_storage") as mock_storage:
            mock_storage.get = AsyncMock(
                return_value=SessionData(
                    args={
                        "args": ("arg1", "arg2"),
                        "kwargs": {"key": "value", "ctx": mock_ctx},
                    },
                    ts=int(time.time() * 1000),
                )
            )
            mock_storage.delete = AsyncMock()

            # Call confirmation tool (only exists for TWO_STEP)
            result = await confirm_tool(payment_id=payment_id)

            # Verify function was called with stored args
            mock_func.assert_called_once_with("arg1", "arg2", key="value", ctx=mock_ctx)
            assert result == {"result": "success", "data": "test_data"}

            # Verify session was cleaned up
            mock_storage.delete.assert_called_once()
            session_key = mock_storage.delete.call_args[0][0]
            assert session_key.provider == provider.name
            assert session_key.payment_id == payment_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flow", [PaymentFlow.ELICITATION, PaymentFlow.PROGRESS])
    async def test_retry_with_payment_id(self, flow, mock_mcp, mock_func, mock_ctx):
        """Test that ELICITATION and PROGRESS flows support retry with payment_id"""
        provider = MockProvider(name="test_provider")

        # Pre-create a paid payment
        payment_id = f"{provider.name}_{PAYMENT_ID}"
        provider.payments[payment_id] = {
            "status": "paid",
            "amount": 0.05,
            "currency": "USD",
        }

        # Get wrapper based on flow
        if flow == PaymentFlow.ELICITATION:
            wrapper = elicitation.make_paid_wrapper(
                mock_func, mock_mcp, provider, PRICE_INFO
            )
        elif flow == PaymentFlow.PROGRESS:
            wrapper = progress.make_paid_wrapper(
                mock_func, mock_mcp, provider, PRICE_INFO
            )

        # Call wrapper with payment_id to trigger retry logic
        result = await wrapper(ctx=mock_ctx, payment_id=payment_id)

        # Verify function was called directly (payment already paid)
        mock_func.assert_called_once()
        assert result == {"result": "success", "data": "test_data"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flow", [PaymentFlow.ELICITATION, PaymentFlow.PROGRESS])
    async def test_session_cleanup_on_success(
        self, flow, mock_mcp, mock_func, mock_ctx
    ):
        """Test that session is cleaned up after successful payment"""
        provider = MockProvider(name="test_provider")

        # Pre-create a paid payment
        payment_id = f"{provider.name}_{PAYMENT_ID}"
        provider.payments[payment_id] = {
            "status": "paid",
            "amount": 0.05,
            "currency": "USD",
        }

        module_name = {
            PaymentFlow.ELICITATION: "paymcp.payment.flows.elicitation",
            PaymentFlow.PROGRESS: "paymcp.payment.flows.progress",
        }[flow]

        with patch(f"{module_name}.session_storage") as mock_storage:
            mock_storage.set = AsyncMock()
            mock_storage.delete = AsyncMock()

            if flow == PaymentFlow.ELICITATION:
                with patch(
                    "paymcp.payment.flows.elicitation.run_elicitation_loop"
                ) as mock_elicitation:
                    mock_elicitation.return_value = "paid"
                    wrapper = elicitation.make_paid_wrapper(
                        mock_func, mock_mcp, provider, PRICE_INFO
                    )

                    # Mock provider to return paid immediately
                    provider.get_payment_status = Mock(return_value="paid")

                    result = await wrapper("arg1", ctx=mock_ctx)

                    # Verify function was called
                    mock_func.assert_called_once()
                    # Verify session was cleaned up
                    mock_storage.delete.assert_called_once()

            elif flow == PaymentFlow.PROGRESS:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    wrapper = progress.make_paid_wrapper(
                        mock_func, mock_mcp, provider, PRICE_INFO
                    )

                    # Mock provider to return paid immediately
                    provider.get_payment_status = Mock(return_value="paid")

                    result = await wrapper("arg1", ctx=mock_ctx)

                    # Verify function was called
                    mock_func.assert_called_once()
                    # Verify session was cleaned up
                    mock_storage.delete.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flow", [PaymentFlow.ELICITATION, PaymentFlow.PROGRESS])
    async def test_session_cleanup_on_cancellation(
        self, flow, mock_mcp, mock_func, mock_ctx
    ):
        """Test that session is cleaned up when payment is canceled"""
        provider = MockProvider(name="test_provider")

        module_name = {
            PaymentFlow.ELICITATION: "paymcp.payment.flows.elicitation",
            PaymentFlow.PROGRESS: "paymcp.payment.flows.progress",
        }[flow]

        with patch(f"{module_name}.session_storage") as mock_storage:
            mock_storage.set = AsyncMock()
            mock_storage.delete = AsyncMock()

            if flow == PaymentFlow.ELICITATION:
                with patch(
                    "paymcp.payment.flows.elicitation.run_elicitation_loop"
                ) as mock_elicitation:
                    mock_elicitation.return_value = "canceled"
                    wrapper = elicitation.make_paid_wrapper(
                        mock_func, mock_mcp, provider, PRICE_INFO
                    )

                    result = await wrapper("arg1", ctx=mock_ctx)

                    # Verify cancellation response
                    assert result["status"] == "canceled"
                    assert "canceled" in result["message"].lower()

                    # Verify function was NOT called
                    mock_func.assert_not_called()

                    # Verify session was cleaned up
                    mock_storage.delete.assert_called_once()

            elif flow == PaymentFlow.PROGRESS:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    wrapper = progress.make_paid_wrapper(
                        mock_func, mock_mcp, provider, PRICE_INFO
                    )

                    # Mock provider to return canceled after first check
                    provider.get_payment_status = Mock(
                        side_effect=["pending", "canceled"]
                    )

                    result = await wrapper("arg1", ctx=mock_ctx)

                    # Verify cancellation response
                    assert result["status"] == "canceled"

                    # Verify function was NOT called
                    mock_func.assert_not_called()

                    # Verify session was cleaned up
                    mock_storage.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_payment_id_error(self, mock_mcp, mock_func):
        """Test that unknown payment ID raises appropriate error"""
        provider = MockProvider(name="test_provider")

        # Test for each flow
        for flow in [
            PaymentFlow.TWO_STEP,
            PaymentFlow.ELICITATION,
            PaymentFlow.PROGRESS,
        ]:
            if flow == PaymentFlow.TWO_STEP:
                wrapper = two_step.make_paid_wrapper(
                    mock_func, mock_mcp, provider, PRICE_INFO
                )
            elif flow == PaymentFlow.ELICITATION:
                wrapper = elicitation.make_paid_wrapper(
                    mock_func, mock_mcp, provider, PRICE_INFO
                )
            elif flow == PaymentFlow.PROGRESS:
                wrapper = progress.make_paid_wrapper(
                    mock_func, mock_mcp, provider, PRICE_INFO
                )

            confirm_tool = mock_mcp.registered_tools.get(
                f"confirm_{mock_func.__name__}_payment"
            )

            module_name = {
                PaymentFlow.TWO_STEP: "paymcp.payment.flows.two_step",
                PaymentFlow.ELICITATION: "paymcp.payment.flows.elicitation",
                PaymentFlow.PROGRESS: "paymcp.payment.flows.progress",
            }[flow]

            with patch(f"{module_name}.session_storage") as mock_storage:
                mock_storage.get = AsyncMock(return_value=None)

                # Should raise error for unknown payment ID
                with pytest.raises(RuntimeError, match="Unknown or expired payment_id"):
                    await confirm_tool(payment_id="unknown_payment_id")

    @pytest.mark.asyncio
    async def test_unpaid_confirmation_error(self, mock_mcp, mock_func):
        """Test that confirming unpaid payment raises appropriate error"""
        provider = MockProvider(name="test_provider")

        # Create unpaid payment
        payment_id = f"{provider.name}_{PAYMENT_ID}"
        provider.payments[payment_id] = {
            "status": "pending",
            "amount": 0.05,
            "currency": "USD",
        }

        # Test for each flow
        for flow in [
            PaymentFlow.TWO_STEP,
            PaymentFlow.ELICITATION,
            PaymentFlow.PROGRESS,
        ]:
            if flow == PaymentFlow.TWO_STEP:
                wrapper = two_step.make_paid_wrapper(
                    mock_func, mock_mcp, provider, PRICE_INFO
                )
            elif flow == PaymentFlow.ELICITATION:
                wrapper = elicitation.make_paid_wrapper(
                    mock_func, mock_mcp, provider, PRICE_INFO
                )
            elif flow == PaymentFlow.PROGRESS:
                wrapper = progress.make_paid_wrapper(
                    mock_func, mock_mcp, provider, PRICE_INFO
                )

            confirm_tool = mock_mcp.registered_tools.get(
                f"confirm_{mock_func.__name__}_payment"
            )

            module_name = {
                PaymentFlow.TWO_STEP: "paymcp.payment.flows.two_step",
                PaymentFlow.ELICITATION: "paymcp.payment.flows.elicitation",
                PaymentFlow.PROGRESS: "paymcp.payment.flows.progress",
            }[flow]

            with patch(f"{module_name}.session_storage") as mock_storage:
                mock_storage.get = AsyncMock(
                    return_value=SessionData(
                        args={"args": (), "kwargs": {}}, ts=int(time.time() * 1000)
                    )
                )

                # Should raise error for unpaid payment
                with pytest.raises(RuntimeError, match="Payment status is pending"):
                    await confirm_tool(payment_id=payment_id)


class TestProviderIntegration:
    """Test SessionManager with different payment providers"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "provider_name, flow",
        [
            ("stripe", PaymentFlow.TWO_STEP),
            ("paypal", PaymentFlow.TWO_STEP),
            ("square", PaymentFlow.TWO_STEP),
            ("walleot", PaymentFlow.TWO_STEP),
        ],
    )
    async def test_provider_with_session(
        self, provider_name, flow, mock_mcp, mock_func, mock_ctx
    ):
        """Test SessionManager works with all providers and flows"""
        provider = MockProvider(name=provider_name)

        # Get wrapper
        if flow == PaymentFlow.TWO_STEP:
            wrapper = two_step.make_paid_wrapper(
                mock_func, mock_mcp, provider, PRICE_INFO
            )
        elif flow == PaymentFlow.ELICITATION:
            wrapper = elicitation.make_paid_wrapper(
                mock_func, mock_mcp, provider, PRICE_INFO
            )
        elif flow == PaymentFlow.PROGRESS:
            wrapper = progress.make_paid_wrapper(
                mock_func, mock_mcp, provider, PRICE_INFO
            )

        # Verify confirmation tool is registered
        # Only TWO_STEP has confirmation tools now
        if flow == PaymentFlow.TWO_STEP:
            confirm_tool = mock_mcp.registered_tools.get(
                f"confirm_{mock_func.__name__}_payment"
            )
            assert confirm_tool is not None
        else:
            # ELICITATION and PROGRESS don't have confirmation tools
            confirm_tool = None

        # Create and mark payment as paid
        payment_id = f"{provider_name}_{PAYMENT_ID}"
        provider.payments[payment_id] = {
            "status": "paid",
            "amount": 0.05,
            "currency": "USD",
        }

        module_name = {
            PaymentFlow.TWO_STEP: "paymcp.payment.flows.two_step",
            PaymentFlow.ELICITATION: "paymcp.payment.flows.elicitation",
            PaymentFlow.PROGRESS: "paymcp.payment.flows.progress",
        }[flow]

        with patch(f"{module_name}.session_storage") as mock_storage:
            mock_storage.get = AsyncMock(
                return_value=SessionData(
                    args={"args": ("test_arg",), "kwargs": {"test_key": "test_value"}},
                    ts=int(time.time() * 1000),
                )
            )
            mock_storage.delete = AsyncMock()

            # Confirm payment
            result = await confirm_tool(payment_id=payment_id)

            # Verify provider name is in session key
            delete_call = mock_storage.delete.call_args[0][0]
            assert delete_call.provider == provider_name
            assert delete_call.payment_id == payment_id


class TestDelayedPayment:
    """Test delayed payment scenarios"""

    @pytest.mark.asyncio
    async def test_delayed_payment_with_confirmation(
        self, mock_mcp, mock_func, mock_ctx
    ):
        """Test that delayed payments can be confirmed after timeout"""
        provider = MockProvider(
            name="test_provider", payment_delay=10
        )  # 10 second delay

        # Test TWO_STEP flow with delayed payment
        wrapper = two_step.make_paid_wrapper(mock_func, mock_mcp, provider, PRICE_INFO)

        # First call - initiate payment
        result = await wrapper("delayed_arg", ctx=mock_ctx)
        assert result["status"] == "pending"
        payment_id = result["payment_id"]

        # Simulate time passing and payment completing
        provider.payments[payment_id]["created_at"] -= 20  # Simulate 20 seconds passed

        # Now confirm payment
        confirm_tool = mock_mcp.registered_tools.get(
            f"confirm_{mock_func.__name__}_payment"
        )
        assert confirm_tool is not None

        with patch("paymcp.payment.flows.two_step.session_storage") as mock_storage:
            mock_storage.get = AsyncMock(
                return_value=SessionData(
                    args={
                        "args": ("delayed_arg",),
                        "kwargs": {"ctx": mock_ctx},
                    },
                    ts=int(time.time() * 1000),
                )
            )
            mock_storage.delete = AsyncMock()

            # Payment should now be marked as paid
            assert provider.get_payment_status(payment_id) == "paid"

            # Confirm payment
            result = await confirm_tool(payment_id=payment_id)

            # Verify function was called with original args
            mock_func.assert_called_once_with("delayed_arg", ctx=mock_ctx)
            assert result == {"result": "success", "data": "test_data"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
