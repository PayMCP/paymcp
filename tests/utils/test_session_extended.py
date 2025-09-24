"""Extended tests for session utilities to cover edge cases."""
import pytest
from unittest.mock import Mock, patch
from paymcp.utils.session import extract_session_id


class TestExtractSessionIdExtended:
    """Extended test cases for extract_session_id function."""

    def test_headers_not_dict_no_get_method(self):
        """Test when headers is neither dict nor has get method."""
        ctx = Mock()
        # Headers is some other type without get method
        ctx.headers = []  # List has no get method

        # Should skip to checking request.headers
        ctx.request = Mock(spec=['headers'])
        ctx.request.headers = {"Mcp-Session-Id": "from-request"}

        result = extract_session_id(ctx)
        assert result == "from-request"

    def test_request_headers_not_dict_no_get_method(self):
        """Test when request.headers is neither dict nor has get method."""
        ctx = Mock(spec=['request'])
        ctx.request = Mock(spec=['headers'])
        # Headers is some other type without get method
        ctx.request.headers = []  # List has no get method

        # Should continue to check session_id
        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        assert result is None
        # Should still warn about HTTP context
        mock_logger.warning.assert_called_once()

    def test_no_headers_but_has_session_id(self):
        """Test when there's no headers but has session_id attribute."""
        ctx = Mock(spec=['session_id'])
        ctx.session_id = "direct-session"

        result = extract_session_id(ctx)
        assert result == "direct-session"

    def test_ctx_request_headers_get_returns_falsy_but_not_none(self):
        """Test when headers.get returns a falsy value (not None)."""
        ctx = Mock(spec=['headers'])
        # First check headers directly
        headers_mock = Mock()
        # Return empty string for the 'Mcp-Session-Id' key
        # Empty string is falsy, so it won't be returned
        headers_mock.get = Mock(side_effect=lambda k: "" if k == "Mcp-Session-Id" else None)
        ctx.headers = headers_mock

        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        # Empty string is falsy, so we continue searching and get None
        assert result is None
        # Should warn about missing session ID in HTTP context
        mock_logger.warning.assert_called_once()

    def test_headers_dict_empty_continue_search(self):
        """Test that search continues when headers dict is empty."""
        ctx = Mock()
        ctx.headers = {}  # Empty headers dict
        ctx.request = Mock(spec=['headers'])
        ctx.request.headers = {"Mcp-Session-Id": "from-request-headers"}

        with patch("paymcp.utils.session.logger"):
            result = extract_session_id(ctx)

        # Should have continued to request.headers
        assert result == "from-request-headers"

    def test_request_with_headers_dict_empty(self):
        """Test warning when request.headers dict exists but is empty."""
        ctx = Mock(spec=['request'])
        ctx.request = Mock(spec=['headers'])
        ctx.request.headers = {}

        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        assert result is None
        # Should warn about missing session ID in HTTP context
        mock_logger.warning.assert_called_once()

    def test_all_paths_no_session_id_found(self):
        """Test when all paths are searched but no session ID found."""
        ctx = Mock(spec=['headers', 'request'])
        ctx.headers = []  # Not a dict, no get method
        ctx.request = Mock(spec=['headers'])
        ctx.request.headers = []  # Not a dict, no get method
        # No session_id or _session_id attributes

        with patch("paymcp.utils.session.logger") as mock_logger:
            result = extract_session_id(ctx)

        assert result is None
        # Should warn about HTTP context
        mock_logger.warning.assert_called_once()