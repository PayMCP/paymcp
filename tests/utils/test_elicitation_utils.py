import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import logging
import inspect
from types import SimpleNamespace
from paymcp.utils.elicitation import run_elicitation_loop
from paymcp.utils.responseSchema import SimpleActionSchema


class TestRunElicitationLoop:
    @pytest.fixture
    def mock_logger(self):
        with patch('paymcp.utils.elicitation.logger') as mock_log:
            yield mock_log

    @pytest.fixture
    def mock_provider(self):
        provider = Mock()
        provider.get_payment_status = Mock(return_value="pending")
        return provider

    @pytest.fixture
    def mock_ctx_with_response_type(self):
        ctx = Mock()
        ctx.elicit = AsyncMock()
        # Mock the signature to have response_type parameter
        sig = inspect.signature(lambda message, response_type=None: None)
        with patch.object(inspect, 'signature', return_value=sig):
            yield ctx

    @pytest.fixture
    def mock_ctx_with_schema(self):
        ctx = Mock()
        ctx.elicit = AsyncMock()
        # Mock the signature to NOT have response_type parameter
        sig = inspect.signature(lambda message, schema=None: None)
        with patch.object(inspect, 'signature', return_value=sig):
            yield ctx

    @pytest.mark.asyncio
    async def test_elicitation_loop_accept_action_with_response_type(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.return_value = SimpleNamespace(action="accept")
        mock_provider.get_payment_status.side_effect = ["pending", "paid"]

        result = await run_elicitation_loop(
            mock_ctx_with_response_type,
            Mock(),
            "Test message",
            mock_provider,
            "payment_123"
        )

        assert result == "paid"
        assert mock_ctx_with_response_type.elicit.call_count == 2
        mock_ctx_with_response_type.elicit.assert_called_with(
            message="Test message",
            response_type=None
        )

    @pytest.mark.asyncio
    async def test_elicitation_loop_accept_action_with_schema(
        self, mock_ctx_with_schema, mock_provider, mock_logger
    ):
        mock_ctx_with_schema.elicit.return_value = SimpleNamespace(action="accept")
        mock_provider.get_payment_status.return_value = "paid"

        result = await run_elicitation_loop(
            mock_ctx_with_schema,
            Mock(),
            "Test message",
            mock_provider,
            "payment_456"
        )

        assert result == "paid"
        mock_ctx_with_schema.elicit.assert_called_once_with(
            message="Test message",
            schema=SimpleActionSchema
        )

    @pytest.mark.asyncio
    async def test_elicitation_loop_cancel_action(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.return_value = SimpleNamespace(action="cancel")

        with pytest.raises(RuntimeError, match="Payment canceled by user"):
            await run_elicitation_loop(
                mock_ctx_with_response_type,
                Mock(),
                "Test message",
                mock_provider,
                "payment_789"
            )

        mock_logger.debug.assert_any_call("[run_elicitation_loop] User canceled payment")

    @pytest.mark.asyncio
    async def test_elicitation_loop_decline_action(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.return_value = SimpleNamespace(action="decline")

        with pytest.raises(RuntimeError, match="Payment canceled by user"):
            await run_elicitation_loop(
                mock_ctx_with_response_type,
                Mock(),
                "Test message",
                mock_provider,
                "payment_999"
            )

    @pytest.mark.asyncio
    async def test_elicitation_loop_payment_canceled_status(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.return_value = SimpleNamespace(action="accept")
        mock_provider.get_payment_status.return_value = "canceled"

        result = await run_elicitation_loop(
            mock_ctx_with_response_type,
            Mock(),
            "Test message",
            mock_provider,
            "payment_canceled"
        )

        assert result == "canceled"

    @pytest.mark.asyncio
    async def test_elicitation_loop_max_attempts_reached(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.return_value = SimpleNamespace(action="accept")
        mock_provider.get_payment_status.return_value = "pending"

        result = await run_elicitation_loop(
            mock_ctx_with_response_type,
            Mock(),
            "Test message",
            mock_provider,
            "payment_pending",
            max_attempts=3
        )

        assert result == "pending"
        assert mock_ctx_with_response_type.elicit.call_count == 3

    @pytest.mark.asyncio
    async def test_elicitation_loop_exception_with_accept_keyword(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.side_effect = [
            Exception("unexpected elicitation action: accept"),
            SimpleNamespace(action="accept")
        ]
        mock_provider.get_payment_status.return_value = "paid"

        result = await run_elicitation_loop(
            mock_ctx_with_response_type,
            Mock(),
            "Test message",
            mock_provider,
            "payment_accept_exception"
        )

        assert result == "paid"
        mock_logger.debug.assert_any_call(
            "[run_elicitation_loop] Treating 'accept' action as confirmation"
        )

    @pytest.mark.asyncio
    async def test_elicitation_loop_exception_with_cancel_keyword(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.side_effect = Exception(
            "unexpected elicitation action: cancel"
        )

        with pytest.raises(RuntimeError, match="Payment canceled by user"):
            await run_elicitation_loop(
                mock_ctx_with_response_type,
                Mock(),
                "Test message",
                mock_provider,
                "payment_cancel_exception"
            )

        mock_logger.debug.assert_any_call(
            "[run_elicitation_loop] Treating 'cancel/decline' action as user cancellation"
        )

    @pytest.mark.asyncio
    async def test_elicitation_loop_exception_with_decline_keyword(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.side_effect = Exception(
            "unexpected elicitation action: decline"
        )

        with pytest.raises(RuntimeError, match="Payment canceled by user"):
            await run_elicitation_loop(
                mock_ctx_with_response_type,
                Mock(),
                "Test message",
                mock_provider,
                "payment_decline_exception"
            )

    @pytest.mark.asyncio
    async def test_elicitation_loop_unexpected_elicitation_other_action(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.side_effect = Exception(
            "unexpected elicitation action: unknown"
        )

        with pytest.raises(RuntimeError, match="Elicitation failed during confirmation loop"):
            await run_elicitation_loop(
                mock_ctx_with_response_type,
                Mock(),
                "Test message",
                mock_provider,
                "payment_unknown_action"
            )

    @pytest.mark.asyncio
    async def test_elicitation_loop_general_exception(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.side_effect = Exception("General error")

        with pytest.raises(RuntimeError, match="Elicitation failed during confirmation loop"):
            await run_elicitation_loop(
                mock_ctx_with_response_type,
                Mock(),
                "Test message",
                mock_provider,
                "payment_general_error"
            )

        mock_logger.warning.assert_called_with(
            "[run_elicitation_loop] Elicitation failed: General error"
        )

    @pytest.mark.asyncio
    async def test_elicitation_loop_custom_max_attempts(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.return_value = SimpleNamespace(action="accept")
        mock_provider.get_payment_status.return_value = "pending"

        result = await run_elicitation_loop(
            mock_ctx_with_response_type,
            Mock(),
            "Test message",
            mock_provider,
            "payment_custom",
            max_attempts=2
        )

        assert result == "pending"
        assert mock_ctx_with_response_type.elicit.call_count == 2

    @pytest.mark.asyncio
    async def test_elicitation_loop_payment_becomes_paid(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.return_value = SimpleNamespace(action="accept")
        mock_provider.get_payment_status.side_effect = ["pending", "pending", "paid"]

        result = await run_elicitation_loop(
            mock_ctx_with_response_type,
            Mock(),
            "Test message",
            mock_provider,
            "payment_eventual_success"
        )

        assert result == "paid"
        assert mock_provider.get_payment_status.call_count == 3

    @pytest.mark.asyncio
    async def test_elicitation_loop_logging(
        self, mock_ctx_with_response_type, mock_provider, mock_logger
    ):
        mock_ctx_with_response_type.elicit.return_value = SimpleNamespace(action="accept")
        mock_provider.get_payment_status.return_value = "paid"

        await run_elicitation_loop(
            mock_ctx_with_response_type,
            Mock(),
            "Test message",
            mock_provider,
            "payment_logging"
        )

        # Check logging calls
        mock_logger.debug.assert_any_call("[run_elicitation_loop] Attempt 1,")
        mock_logger.debug.assert_any_call(
            "[run_elicitation_loop] Elicitation response: namespace(action='accept')"
        )
        mock_logger.debug.assert_any_call(
            "[run_elicitation_loop]: payment status = paid"
        )