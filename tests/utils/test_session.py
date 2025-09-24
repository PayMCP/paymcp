"""Tests for session utilities."""
import pytest
from unittest.mock import Mock, MagicMock, patch
from paymcp.utils.session import extract_session_id


class TestExtractSessionId:
    """Test extract_session_id function."""

    def test_none_context(self):
        """Test with None context."""
        result = extract_session_id(None)
        assert result is None

    def test_direct_headers_dict_with_session_id(self):
        """Test with headers as dict containing Mcp-Session-Id."""
        ctx = Mock()
        ctx.headers = {"Mcp-Session-Id": "session-123"}
        result = extract_session_id(ctx)
        assert result == "session-123"

    def test_direct_headers_dict_case_insensitive(self):
        """Test with headers dict containing lowercase mcp-session-id."""
        ctx = Mock()
        ctx.headers = {"mcp-session-id": "session-456"}
        result = extract_session_id(ctx)
        assert result == "session-456"

    def test_direct_headers_dict_mixed_case(self):
        """Test with headers dict containing mixed case."""
        ctx = Mock()
        ctx.headers = {"MCP-SESSION-ID": "session-789"}
        result = extract_session_id(ctx)
        assert result == "session-789"

    def test_headers_object_with_get_method(self):
        """Test with headers object that has get method."""
        ctx = Mock()
        headers_mock = Mock()
        headers_mock.get = Mock(side_effect=lambda k: "session-abc" if k == "Mcp-Session-Id" else None)
        ctx.headers = headers_mock
        result = extract_session_id(ctx)
        assert result == "session-abc"

    def test_headers_object_get_lowercase(self):
        """Test with headers object get method using lowercase."""
        ctx = Mock()
        headers_mock = Mock()
        headers_mock.get = Mock(side_effect=lambda k: "session-def" if k == "mcp-session-id" else None)
        ctx.headers = headers_mock
        result = extract_session_id(ctx)
        assert result == "session-def"

    def test_request_headers_dict(self):
        """Test with request.headers as dict."""
        ctx = Mock(spec=['request'])
        ctx.request = Mock()
        ctx.request.headers = {"Mcp-Session-Id": "session-req-123"}
        result = extract_session_id(ctx)
        assert result == "session-req-123"

    def test_request_headers_dict_case_insensitive(self):
        """Test with request.headers dict lowercase."""
        ctx = Mock(spec=['request'])
        ctx.request = Mock()
        ctx.request.headers = {"mcp-session-id": "session-req-456"}
        result = extract_session_id(ctx)
        assert result == "session-req-456"

    def test_request_headers_object_with_get(self):
        """Test with request.headers object that has get method."""
        ctx = Mock(spec=['request'])
        ctx.request = Mock()
        headers_mock = Mock()
        headers_mock.get = Mock(side_effect=lambda k: "session-req-obj" if k == "Mcp-Session-Id" else None)
        ctx.request.headers = headers_mock
        result = extract_session_id(ctx)
        assert result == "session-req-obj"

    def test_ctx_session_id_attribute(self):
        """Test with direct session_id attribute."""
        ctx = Mock(spec=['session_id'])
        ctx.session_id = "direct-session-id"
        result = extract_session_id(ctx)
        assert result == "direct-session-id"

    def test_ctx_private_session_id_attribute(self):
        """Test with _session_id private attribute."""
        ctx = Mock(spec=['_session_id'])
        ctx._session_id = "private-session-id"
        result = extract_session_id(ctx)
        assert result == "private-session-id"

    def test_http_context_no_session_id_warning(self):
        """Test warning when HTTP context has no session ID."""
        ctx = Mock(spec=['headers'])
        ctx.headers = {}  # Empty headers

        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        assert result is None
        mock_logger.warning.assert_called_with(
            "MCP session ID not found in HTTP context. "
            "This may cause issues with multi-client scenarios. "
            "Ensure your MCP server provides Mcp-Session-Id header."
        )

    def test_request_headers_no_session_id_warning(self):
        """Test warning when request.headers has no session ID."""
        ctx = Mock(spec=['request'])
        ctx.request = Mock(spec=['headers'])
        ctx.request.headers = {}

        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        assert result is None
        mock_logger.warning.assert_called_with(
            "MCP session ID not found in HTTP context. "
            "This may cause issues with multi-client scenarios. "
            "Ensure your MCP server provides Mcp-Session-Id header."
        )

    def test_meta_headers_triggers_warning(self):
        """Test warning when _meta.headers exists but no session ID."""
        ctx = Mock(spec=['_meta'])
        ctx._meta = Mock(spec=['headers'])
        ctx._meta.headers = {}

        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        assert result is None
        mock_logger.warning.assert_called_with(
            "MCP session ID not found in HTTP context. "
            "This may cause issues with multi-client scenarios. "
            "Ensure your MCP server provides Mcp-Session-Id header."
        )

    def test_stdio_transport_no_warning(self):
        """Test no warning for STDIO transport (no headers)."""
        ctx = Mock(spec=[])

        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        assert result is None
        mock_logger.debug.assert_called_with("No MCP session ID found (STDIO transport)")
        mock_logger.warning.assert_not_called()

    def test_priority_headers_over_request(self):
        """Test that direct headers take priority over request.headers."""
        ctx = Mock()
        ctx.headers = {"Mcp-Session-Id": "priority-1"}
        ctx.request = Mock()
        ctx.request.headers = {"Mcp-Session-Id": "priority-2"}

        result = extract_session_id(ctx)
        assert result == "priority-1"

    def test_priority_request_over_session_id(self):
        """Test that request.headers takes priority over session_id attribute."""
        ctx = Mock(spec=['request', 'session_id'])
        ctx.request = Mock()
        ctx.request.headers = {"Mcp-Session-Id": "priority-req"}
        ctx.session_id = "priority-attr"

        result = extract_session_id(ctx)
        assert result == "priority-req"

    def test_empty_string_session_id(self):
        """Test with empty string session ID."""
        ctx = Mock()
        ctx.headers = {"Mcp-Session-Id": ""}

        result = extract_session_id(ctx)
        # Empty string is returned as-is (not None)
        assert result == ""

    def test_headers_get_returns_none(self):
        """Test when headers.get returns None for both cases."""
        ctx = Mock(spec=['headers'])
        headers_mock = Mock()
        headers_mock.get = Mock(return_value=None)
        ctx.headers = headers_mock

        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        assert result is None
        mock_logger.warning.assert_called_with(
            "MCP session ID not found in HTTP context. "
            "This may cause issues with multi-client scenarios. "
            "Ensure your MCP server provides Mcp-Session-Id header."
        )