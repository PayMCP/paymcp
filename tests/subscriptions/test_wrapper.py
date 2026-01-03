"""Tests for the paymcp.subscriptions.wrapper module."""

import pytest
import logging
import json
import base64
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from paymcp.subscriptions.wrapper import (
    _safe_get,
    _normalize_email,
    _get_bearer_token_from_ctx,
    _extract_auth_identity,
    ensure_subscription_allowed,
    make_subscription_wrapper,
    register_subscription_tools,
)


class TestSafeGet:
    """Test the _safe_get utility function."""

    def test_safe_get_from_dict(self):
        """Test getting value from dict."""
        obj = {"userId": "user123", "email": "test@example.com"}
        assert _safe_get(obj, "userId") == "user123"
        assert _safe_get(obj, "email") == "test@example.com"

    def test_safe_get_from_object_attribute(self):
        """Test getting value from object attribute."""
        obj = Mock()
        obj.userId = "user456"
        obj.email = "obj@example.com"
        assert _safe_get(obj, "userId") == "user456"
        assert _safe_get(obj, "email") == "obj@example.com"

    def test_safe_get_multiple_keys(self):
        """Test getting value with multiple key options."""
        obj = {"user_id": "user789"}
        # First key not found, second key found
        assert _safe_get(obj, "userId", "user_id") == "user789"

    def test_safe_get_none_obj(self):
        """Test with None object."""
        assert _safe_get(None, "key") is None

    def test_safe_get_missing_key(self):
        """Test with missing key."""
        obj = {"other": "value"}
        assert _safe_get(obj, "userId") is None

    def test_safe_get_none_value(self):
        """Test with None value returns None and continues."""
        obj = {"userId": None, "user_id": "fallback"}
        assert _safe_get(obj, "userId", "user_id") == "fallback"


class TestGetBearerTokenFromCtx:
    """Test the _get_bearer_token_from_ctx function."""

    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    def test_extract_bearer_token_success(self, mock_logger):
        """Test successful Bearer token extraction."""
        ctx = Mock()
        ctx.request_context = Mock()
        ctx.request_context.request = Mock()
        ctx.request_context.request.headers = {"authorization": "Bearer test_token_123"}

        result = _get_bearer_token_from_ctx(ctx, mock_logger)

        assert result == "test_token_123"
        mock_logger.info.assert_called()

    def test_extract_bearer_token_none_ctx(self, mock_logger):
        """Test with None context."""
        assert _get_bearer_token_from_ctx(None, mock_logger) is None

    def test_extract_bearer_token_no_request_context(self, mock_logger):
        """Test with missing request_context."""
        ctx = Mock(spec=[])  # Empty spec means no attributes
        assert _get_bearer_token_from_ctx(ctx, mock_logger) is None

    def test_extract_bearer_token_no_authorization(self, mock_logger):
        """Test with missing authorization header."""
        ctx = Mock()
        ctx.request_context = Mock()
        ctx.request_context.request = Mock()
        ctx.request_context.request.headers = {}

        assert _get_bearer_token_from_ctx(ctx, mock_logger) is None

    def test_extract_bearer_token_not_bearer(self, mock_logger):
        """Test with non-Bearer authorization."""
        ctx = Mock()
        ctx.request_context = Mock()
        ctx.request_context.request = Mock()
        ctx.request_context.request.headers = {"authorization": "Basic abc123"}

        assert _get_bearer_token_from_ctx(ctx, mock_logger) is None

    def test_extract_bearer_token_bytes(self, mock_logger):
        """Test with bytes authorization header."""
        ctx = Mock()
        ctx.request_context = Mock()
        ctx.request_context.request = Mock()
        ctx.request_context.request.headers = {"authorization": b"Bearer byte_token"}

        result = _get_bearer_token_from_ctx(ctx, mock_logger)

        assert result == "byte_token"

    def test_extract_bearer_token_headers_none(self, mock_logger):
        ctx = Mock()
        ctx.request_context = Mock()
        ctx.request_context.request = Mock()
        ctx.request_context.request.headers = None
        assert _get_bearer_token_from_ctx(ctx, mock_logger) is None

    def test_extract_bearer_token_headers_get_raises(self, mock_logger):
        class BadHeaders:
            def get(self, _name):
                raise RuntimeError("boom")

        ctx = Mock()
        ctx.request_context = Mock()
        ctx.request_context.request = Mock()
        ctx.request_context.request.headers = BadHeaders()
        assert _get_bearer_token_from_ctx(ctx, mock_logger) is None

    def test_extract_bearer_token_empty_value(self, mock_logger):
        ctx = Mock()
        ctx.request_context = Mock()
        ctx.request_context.request = Mock()
        ctx.request_context.request.headers = {"authorization": "Bearer "}
        assert _get_bearer_token_from_ctx(ctx, mock_logger) is None


class TestExtractAuthIdentity:
    """Test the _extract_auth_identity function."""

    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    def test_extract_from_authinfo_directly(self, mock_logger):
        """Test extracting identity from authInfo on context."""
        ctx = Mock()
        ctx.authInfo = {"userId": "user123", "email": "test@example.com"}
        ctx.request_context = None  # Prevent Mock from returning more Mocks

        user_id, email = _extract_auth_identity(ctx, "test_tool", mock_logger)

        assert user_id == "user123"
        assert email == "test@example.com"

    def test_extract_from_dict_context(self, mock_logger):
        """Test extracting identity from dict context."""
        ctx = {"authInfo": {"userId": "user456", "email": "dict@example.com"}}

        user_id, email = _extract_auth_identity(ctx, "test_tool", mock_logger)

        assert user_id == "user456"
        assert email == "dict@example.com"

    def test_extract_from_jwt_fallback(self, mock_logger):
        """Test extracting identity from JWT token as fallback."""
        # Create a valid JWT payload
        payload = {"sub": "jwt_user", "email": "jwt@example.com"}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        jwt_token = f"header.{payload_b64}.signature"

        ctx = Mock()
        ctx.authInfo = {"token": jwt_token}  # No userId, but has token

        user_id, email = _extract_auth_identity(ctx, "test_tool", mock_logger)

        assert user_id == "jwt_user"
        assert email == "jwt@example.com"

    def test_extract_raises_when_no_user_id(self, mock_logger):
        """Test raises error when no userId found."""
        ctx = Mock()
        ctx.authInfo = {"email": "no_user@example.com"}  # No userId
        ctx.request_context = None  # Prevent Mock from returning more Mocks

        with pytest.raises(RuntimeError, match="Not authorized"):
            _extract_auth_identity(ctx, "test_tool", mock_logger)

    def test_extract_from_request_context_meta(self, mock_logger):
        """Test extracting from request_context.meta."""
        ctx = Mock(spec=[])  # Empty spec to prevent auto-Mock attributes
        ctx.authInfo = None
        ctx.auth_info = None
        ctx.AuthInfo = None
        ctx.request_context = Mock(spec=[])
        ctx.request_context.authInfo = None
        ctx.request_context.auth_info = None
        ctx.request_context.AuthInfo = None
        ctx.request_context.request = None
        ctx.request_context.meta = {"authInfo": {"userId": "meta_user", "email": "meta@example.com"}}

        user_id, email = _extract_auth_identity(ctx, "test_tool", mock_logger)

        assert user_id == "meta_user"
        assert email == "meta@example.com"

    def test_invalid_email_returns_none(self, mock_logger):
        """Email with invalid format should be normalized to None."""
        ctx = Mock()
        ctx.authInfo = {"userId": "user123", "email": "not-an-email"}
        ctx.request_context = None

        user_id, email = _extract_auth_identity(ctx, "test_tool", mock_logger)

        assert user_id == "user123"
        assert email is None

    def test_extract_from_request_context_dict(self, mock_logger):
        ctx = SimpleNamespace(
            authInfo=None,
            request_context={"authInfo": {"userId": "ctx_user", "email": "ctx@example.com"}},
        )
        user_id, email = _extract_auth_identity(ctx, "test_tool", mock_logger)
        assert user_id == "ctx_user"
        assert email == "ctx@example.com"

    def test_extract_from_meta_object(self, mock_logger):
        meta = SimpleNamespace(authInfo={"userId": "meta_user", "email": "meta@example.com"})
        ctx = SimpleNamespace(
            authInfo=None,
            request_context=SimpleNamespace(meta=meta),
        )
        user_id, email = _extract_auth_identity(ctx, "test_tool", mock_logger)
        assert user_id == "meta_user"
        assert email == "meta@example.com"


class TestNormalizeEmail:
    def test_normalize_email_empty(self):
        assert _normalize_email("") is None


class TestEnsureSubscriptionAllowed:
    """Test the ensure_subscription_allowed function."""

    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def mock_provider(self):
        provider = Mock()
        provider.get_subscriptions = Mock(return_value={
            "current_subscriptions": [
                {"planId": "price_pro", "status": "active"}
            ],
            "available_subscriptions": []
        })
        return provider

    @pytest.mark.asyncio
    async def test_allows_when_has_required_subscription(self, mock_provider, mock_logger):
        """Test allows access when user has required subscription."""
        subscription_info = {"plan": "price_pro"}

        # Should not raise
        await ensure_subscription_allowed(
            mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
        )

    @pytest.mark.asyncio
    async def test_denies_when_missing_subscription(self, mock_provider, mock_logger):
        """Test denies access when user doesn't have required subscription."""
        mock_provider.get_subscriptions.return_value = {
            "current_subscriptions": [],
            "available_subscriptions": [{"planId": "price_pro"}]
        }
        subscription_info = {"plan": "price_pro"}

        with pytest.raises(RuntimeError) as exc_info:
            await ensure_subscription_allowed(
                mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
            )

        error_data = json.loads(str(exc_info.value))
        assert error_data["error"] == "subscription_required"

    @pytest.mark.asyncio
    async def test_allows_with_multiple_valid_plans(self, mock_provider, mock_logger):
        """Test allows access when user has one of multiple valid plans."""
        mock_provider.get_subscriptions.return_value = {
            "current_subscriptions": [{"planId": "price_enterprise", "status": "active"}],
            "available_subscriptions": []
        }
        subscription_info = {"plan": ["price_pro", "price_enterprise"]}

        # Should not raise
        await ensure_subscription_allowed(
            mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
        )

    @pytest.mark.asyncio
    async def test_allows_with_trialing_status(self, mock_provider, mock_logger):
        """Test allows access when subscription is in trialing status."""
        mock_provider.get_subscriptions.return_value = {
            "current_subscriptions": [{"planId": "price_pro", "status": "trialing"}],
            "available_subscriptions": []
        }
        subscription_info = {"plan": "price_pro"}

        # Should not raise
        await ensure_subscription_allowed(
            mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
        )

    @pytest.mark.asyncio
    async def test_skips_when_no_subscription_info(self, mock_provider, mock_logger):
        """Test skips check when no subscription_info provided."""
        # Should not raise and not call provider
        await ensure_subscription_allowed(
            mock_provider, None, "user123", "test@example.com", "test_tool", mock_logger
        )
        mock_provider.get_subscriptions.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_provider_not_supporting_subscriptions(self, mock_logger):
        """Test handles provider not supporting subscriptions."""
        mock_provider = Mock()
        mock_provider.get_subscriptions.side_effect = RuntimeError(
            "Subscriptions are not supported for this payment provider"
        )
        subscription_info = {"plan": "price_pro"}

        with pytest.raises(RuntimeError, match="Subscriptions are required"):
            await ensure_subscription_allowed(
                mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
            )

    @pytest.mark.asyncio
    async def test_plan_object_with_empty_list(self, mock_provider, mock_logger):
        class SubInfo:
            plan = []

        await ensure_subscription_allowed(
            mock_provider, SubInfo(), "user123", "test@example.com", "test_tool", mock_logger
        )
        mock_provider.get_subscriptions.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_error_is_raised(self, mock_logger):
        mock_provider = Mock()
        mock_provider.get_subscriptions.side_effect = RuntimeError("boom")
        subscription_info = {"plan": "price_pro"}

        with pytest.raises(RuntimeError, match="boom"):
            await ensure_subscription_allowed(
                mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
            )

    @pytest.mark.asyncio
    async def test_current_subscriptions_alternate_key(self, mock_logger):
        mock_provider = Mock()
        mock_provider.get_subscriptions.return_value = {
            "currentSubscriptions": [{"planId": "price_pro", "status": "active"}],
            "availableSubscriptions": [],
        }
        subscription_info = {"plan": "price_pro"}
        await ensure_subscription_allowed(
            mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
        )

    @pytest.mark.asyncio
    async def test_current_subscriptions_non_list_and_available_not_list(self, mock_logger):
        mock_provider = Mock()
        mock_provider.get_subscriptions.return_value = {
            "current_subscriptions": "not-a-list",
            "availableSubscriptions": "bad",
        }
        subscription_info = {"plan": "price_pro"}
        with pytest.raises(RuntimeError):
            await ensure_subscription_allowed(
                mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
            )

    @pytest.mark.asyncio
    async def test_skips_non_dict_subscriptions(self, mock_logger):
        mock_provider = Mock()
        mock_provider.get_subscriptions.return_value = {
            "current_subscriptions": ["bad", {"planId": "price_pro", "status": "active"}],
            "available_subscriptions": [],
        }
        subscription_info = {"plan": "price_pro"}
        await ensure_subscription_allowed(
            mock_provider, subscription_info, "user123", "test@example.com", "test_tool", mock_logger
        )


class TestMakeSubscriptionWrapper:
    """Test the make_subscription_wrapper function."""

    @pytest.fixture
    def mock_logger(self):
        return Mock(spec=logging.Logger)

    @pytest.fixture
    def mock_provider(self):
        provider = Mock()
        provider.logger = Mock(spec=logging.Logger)
        provider.get_subscriptions = Mock(return_value={
            "current_subscriptions": [{"planId": "price_pro", "status": "active"}],
            "available_subscriptions": []
        })
        return provider

    @pytest.fixture
    def mock_mcp(self):
        return Mock()

    @pytest.mark.asyncio
    async def test_wrapper_calls_original_function_when_subscription_valid(self, mock_provider, mock_mcp):
        """Test wrapper calls original function when subscription is valid."""
        async def original_func(data: str, ctx=None) -> str:
            return f"processed: {data}"

        ctx = Mock(spec=[])  # Empty spec to prevent auto-Mock
        ctx.authInfo = {"userId": "user123", "email": "test@example.com"}
        ctx.auth_info = None
        ctx.AuthInfo = None
        ctx.request_context = None

        wrapper = make_subscription_wrapper(
            original_func, mock_mcp, {"mock": mock_provider}, {"plan": "price_pro"}, "test_tool"
        )

        result = await wrapper(data="test_data", ctx=ctx)

        assert result == "processed: test_data"

    @pytest.mark.asyncio
    async def test_wrapper_raises_when_no_context(self, mock_provider, mock_mcp):
        """Test wrapper raises error when no context provided."""
        async def original_func() -> str:
            return "result"

        # Mock mcp.get_context to return None
        mock_mcp.get_context = Mock(return_value=None)

        wrapper = make_subscription_wrapper(
            original_func, mock_mcp, {"mock": mock_provider}, {"plan": "price_pro"}, "test_tool"
        )

        with pytest.raises(RuntimeError, match="Context.*required"):
            await wrapper()

    @pytest.mark.asyncio
    async def test_wrapper_checks_subscription_before_calling(self, mock_provider, mock_mcp):
        """Test wrapper checks subscription before calling original function."""
        call_count = {"value": 0}

        async def original_func(ctx=None) -> str:
            call_count["value"] += 1
            return "result"

        # No valid subscription
        mock_provider.get_subscriptions.return_value = {
            "current_subscriptions": [],
            "available_subscriptions": []
        }

        ctx = Mock(spec=[])  # Empty spec to prevent auto-Mock
        ctx.authInfo = {"userId": "user123"}
        ctx.auth_info = None
        ctx.AuthInfo = None
        ctx.request_context = None

        wrapper = make_subscription_wrapper(
            original_func, mock_mcp, {"mock": mock_provider}, {"plan": "price_pro"}, "test_tool"
        )

        with pytest.raises(RuntimeError):
            await wrapper(ctx=ctx)

        # Original function should not have been called
        assert call_count["value"] == 0

    @pytest.mark.asyncio
    async def test_wrapper_preserves_function_signature(self, mock_provider, mock_mcp):
        """Test wrapper preserves original function signature."""
        async def original_func(a: int, b: str, ctx=None) -> str:
            return f"{a}-{b}"

        wrapper = make_subscription_wrapper(
            original_func, mock_mcp, {"mock": mock_provider}, {"plan": "price_pro"}, "test_tool"
        )

        import inspect
        sig = inspect.signature(wrapper)
        params = list(sig.parameters.keys())
        assert "a" in params
        assert "b" in params

    def test_wrapper_raises_without_provider(self, mock_mcp):
        async def original_func():
            return "result"

        with pytest.raises(RuntimeError, match="No payment provider configured"):
            make_subscription_wrapper(original_func, mock_mcp, {}, {"plan": "price_pro"}, "test_tool")

    @pytest.mark.asyncio
    async def test_wrapper_accepts_ctx_positional(self, mock_provider, mock_mcp):
        async def original_func(*_args, ctx=None):
            return "ok"

        ctx = Mock(spec=[])
        ctx.authInfo = {"userId": "user123", "email": "test@example.com"}
        ctx.request_context = None

        wrapper = make_subscription_wrapper(
            original_func, mock_mcp, {"mock": mock_provider}, {"plan": "price_pro"}, "test_tool"
        )

        result = await wrapper("arg1", ctx)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_wrapper_handles_get_ctx_exception(self, mock_provider, mock_mcp, monkeypatch):
        async def original_func(ctx=None):
            return "ok"

        monkeypatch.setattr(
            "paymcp.subscriptions.wrapper.get_ctx_from_server",
            lambda _mcp: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        wrapper = make_subscription_wrapper(
            original_func, mock_mcp, {"mock": mock_provider}, {"plan": "price_pro"}, "test_tool"
        )

        with pytest.raises(RuntimeError, match="Context"):
            await wrapper()

    def test_signature_preservation_failure_is_ignored(self, mock_provider, mock_mcp, monkeypatch):
        async def original_func(ctx=None):
            return "ok"

        monkeypatch.setattr("inspect.signature", lambda _fn: (_ for _ in ()).throw(TypeError("bad sig")))
        wrapper = make_subscription_wrapper(
            original_func, mock_mcp, {"mock": mock_provider}, {"plan": "price_pro"}, "test_tool"
        )
        assert callable(wrapper)


class TestRegisterSubscriptionTools:
    @pytest.fixture
    def mock_provider(self):
        provider = Mock()
        provider.get_subscriptions = Mock(return_value={"current_subscriptions": []})
        provider.start_subscription = Mock(return_value={"ok": True})
        provider.cancel_subscription = Mock(return_value={"ok": True})
        return provider

    def test_register_subscription_tools_with_input_schema(self, mock_provider):
        class DummyServer:
            def __init__(self):
                self.registered = {}
                self.schemas = {}
                self._ctx = None

            def get_context(self):
                return self._ctx

            def tool(self, name: str, description: str, input_schema=None):
                self.schemas[name] = input_schema

                def decorator(fn):
                    self.registered[name] = fn
                    return fn

                return decorator

        server = DummyServer()
        ctx = SimpleNamespace(authInfo={"userId": "user123", "email": "test@example.com"})
        server._ctx = ctx

        register_subscription_tools(server, {"mock": mock_provider})

        assert server.schemas["start_subscription"] is not None
        assert server.schemas["cancel_subscription"] is not None

    @pytest.mark.asyncio
    async def test_subscription_tool_handlers(self, mock_provider):
        class DummyServer:
            def __init__(self):
                self.registered = {}
                self._ctx = None

            def get_context(self):
                return self._ctx

            def tool(self, name: str, description: str, input_schema=None):
                def decorator(fn):
                    self.registered[name] = fn
                    return fn

                return decorator

        server = DummyServer()
        ctx = SimpleNamespace(authInfo={"userId": "user123", "email": "test@example.com"})
        server._ctx = ctx

        register_subscription_tools(server, {"mock": mock_provider})

        result = await server.registered["list_subscriptions"]()
        assert result["content"][0]["type"] == "text"

        result = await server.registered["start_subscription"]("plan-1")
        assert json.loads(result["content"][0]["text"])["ok"] is True

        result = await server.registered["cancel_subscription"]("sub-1")
        assert json.loads(result["content"][0]["text"])["ok"] is True

        with pytest.raises(RuntimeError, match="planId is required"):
            await server.registered["start_subscription"]("")

        with pytest.raises(RuntimeError, match="subscriptionId is required"):
            await server.registered["cancel_subscription"]("")
