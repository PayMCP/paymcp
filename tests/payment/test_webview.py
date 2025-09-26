"""Tests for webview payment functionality."""

import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from paymcp.payment.webview import open_payment_webview_if_available, _open_payment_webview


class TestWebviewPayment:
    """Test webview payment functionality."""

    def test_open_payment_webview_if_available_webview_not_installed(self):
        """Test when webview module is not available."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec:
            mock_find_spec.return_value = None

            result = open_payment_webview_if_available("https://payment.url")

            assert result is False
            mock_find_spec.assert_called_once_with("webview")

    @patch("paymcp.payment.webview.sys.platform", "darwin")
    def test_open_payment_webview_if_available_macos(self):
        """Test webview opening on macOS platform."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.multiprocessing") as mock_multiprocessing:

            mock_find_spec.return_value = Mock()  # webview is available

            # Setup multiprocessing mocks
            mock_ctx = Mock()
            mock_process = Mock()
            mock_ctx.Process.return_value = mock_process
            mock_multiprocessing.get_context.return_value = mock_ctx

            result = open_payment_webview_if_available("https://payment.url")

            assert result is True
            mock_multiprocessing.get_context.assert_called_once_with("spawn")
            mock_ctx.Process.assert_called_once_with(
                target=_open_payment_webview,
                args=("https://payment.url",),
                daemon=True
            )
            mock_process.start.assert_called_once()

    @patch("paymcp.payment.webview.sys.platform", "linux")
    def test_open_payment_webview_if_available_non_macos(self):
        """Test webview opening on non-macOS platform."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.threading") as mock_threading:

            mock_find_spec.return_value = Mock()  # webview is available

            # Setup threading mocks
            mock_thread = Mock()
            mock_threading.Thread.return_value = mock_thread

            result = open_payment_webview_if_available("https://payment.url")

            assert result is True
            mock_threading.Thread.assert_called_once_with(
                target=_open_payment_webview,
                args=("https://payment.url",),
                daemon=True
            )
            mock_thread.start.assert_called_once()

    @patch("paymcp.payment.webview.sys.platform", "darwin")
    def test_open_payment_webview_if_available_exception_fallback_to_browser(self):
        """Test fallback to browser when webview fails."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.multiprocessing") as mock_multiprocessing, \
             patch("paymcp.payment.webview.webbrowser") as mock_webbrowser:

            mock_find_spec.return_value = Mock()  # webview is available
            mock_multiprocessing.get_context.side_effect = Exception("Process failed")

            result = open_payment_webview_if_available("https://payment.url")

            assert result is True
            mock_webbrowser.open.assert_called_once_with("https://payment.url")

    @patch("paymcp.payment.webview.sys.platform", "darwin")
    def test_open_payment_webview_if_available_both_webview_and_browser_fail(self):
        """Test when both webview and browser fail."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.multiprocessing") as mock_multiprocessing, \
             patch("paymcp.payment.webview.webbrowser") as mock_webbrowser:

            mock_find_spec.return_value = Mock()  # webview is available
            mock_multiprocessing.get_context.side_effect = Exception("Process failed")
            mock_webbrowser.open.side_effect = Exception("Browser failed")

            result = open_payment_webview_if_available("https://payment.url")

            assert result is False

    def test_open_payment_webview_webview_available(self):
        """Test _open_payment_webview when webview module is available."""
        # Mock the webview module at the import level
        mock_webview = Mock()
        mock_webview.create_window = Mock()
        mock_webview.start = Mock()

        with patch.dict('sys.modules', {'webview': mock_webview}):
            _open_payment_webview("https://payment.url")

            mock_webview.create_window.assert_called_once_with(
                "Complete your payment", "https://payment.url"
            )
            mock_webview.start.assert_called_once()

    def test_open_payment_webview_import_exception(self):
        """Test _open_payment_webview when webview import fails."""
        with patch("paymcp.payment.webview.logger") as mock_logger:
            # Ensure webview is not in sys.modules to trigger ImportError
            with patch.dict('sys.modules', {'webview': None}):
                _open_payment_webview("https://payment.url")

            # Verify debug logging occurred
            mock_logger.debug.assert_called_once_with(
                "pywebview not available; skipping webview window"
            )

    def test_open_payment_webview_webview_exception(self):
        """Test _open_payment_webview when webview operations fail."""
        mock_webview = Mock()
        mock_webview.create_window.side_effect = Exception("Webview creation failed")

        with patch.dict('sys.modules', {'webview': mock_webview}), \
             patch("paymcp.payment.webview.logger") as mock_logger:

            _open_payment_webview("https://payment.url")

            # Verify exception logging occurred
            mock_logger.exception.assert_called_once_with("Failed to open payment webview")

    def test_open_payment_webview_start_exception(self):
        """Test _open_payment_webview when webview.start() fails."""
        mock_webview = Mock()
        mock_webview.create_window = Mock()
        mock_webview.start.side_effect = Exception("Webview start failed")

        with patch.dict('sys.modules', {'webview': mock_webview}), \
             patch("paymcp.payment.webview.logger") as mock_logger:

            _open_payment_webview("https://payment.url")

            # Verify create_window was called but exception was logged
            mock_webview.create_window.assert_called_once()
            mock_logger.exception.assert_called_once_with("Failed to open payment webview")

    @patch("paymcp.payment.webview.sys.platform", "win32")
    def test_open_payment_webview_if_available_windows(self):
        """Test webview opening on Windows platform."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.threading") as mock_threading:

            mock_find_spec.return_value = Mock()  # webview is available

            # Setup threading mocks
            mock_thread = Mock()
            mock_threading.Thread.return_value = mock_thread

            result = open_payment_webview_if_available("https://payment.url")

            assert result is True
            # Should use threading for non-macOS platforms
            mock_threading.Thread.assert_called_once()

    def test_open_payment_webview_logging_with_debug(self):
        """Test that proper logging occurs during webview operations."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.multiprocessing") as mock_multiprocessing, \
             patch("paymcp.payment.webview.logger") as mock_logger, \
             patch("paymcp.payment.webview.sys.platform", "darwin"):

            mock_find_spec.return_value = Mock()
            mock_ctx = Mock()
            mock_process = Mock()
            mock_ctx.Process.return_value = mock_process
            mock_multiprocessing.get_context.return_value = mock_ctx

            open_payment_webview_if_available("https://payment.url")

            # Verify info logging occurred
            mock_logger.info.assert_called_once_with(
                "[initiate] Started pywebview subprocess for payment url"
            )

    @patch("paymcp.payment.webview.sys.platform", "linux")
    def test_open_payment_webview_logging_non_macos(self):
        """Test logging for non-macOS platforms."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.threading") as mock_threading, \
             patch("paymcp.payment.webview.logger") as mock_logger:

            mock_find_spec.return_value = Mock()
            mock_thread = Mock()
            mock_threading.Thread.return_value = mock_thread

            open_payment_webview_if_available("https://payment.url")

            # Verify info logging occurred for thread-based approach
            mock_logger.info.assert_called_once_with(
                "[initiate] Opened pywebview thread for payment url"
            )

    def test_open_payment_webview_browser_fallback_logging(self):
        """Test logging when falling back to browser."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.multiprocessing") as mock_multiprocessing, \
             patch("paymcp.payment.webview.webbrowser") as mock_webbrowser, \
             patch("paymcp.payment.webview.logger") as mock_logger, \
             patch("paymcp.payment.webview.sys.platform", "darwin"):

            mock_find_spec.return_value = Mock()
            mock_multiprocessing.get_context.side_effect = Exception("Process failed")

            open_payment_webview_if_available("https://payment.url")

            # Verify exception and info logging occurred
            mock_logger.exception.assert_called_once_with(
                "[initiate] Failed to launch pywebview; falling back to browser"
            )
            mock_logger.info.assert_called_once_with(
                "[initiate] Opened default browser for payment url"
            )

    def test_open_payment_webview_browser_fail_logging(self):
        """Test logging when browser also fails."""
        with patch("paymcp.payment.webview.find_spec") as mock_find_spec, \
             patch("paymcp.payment.webview.multiprocessing") as mock_multiprocessing, \
             patch("paymcp.payment.webview.webbrowser") as mock_webbrowser, \
             patch("paymcp.payment.webview.logger") as mock_logger, \
             patch("paymcp.payment.webview.sys.platform", "darwin"):

            mock_find_spec.return_value = Mock()
            mock_multiprocessing.get_context.side_effect = Exception("Process failed")
            mock_webbrowser.open.side_effect = Exception("Browser failed")

            open_payment_webview_if_available("https://payment.url")

            # Verify warning logging occurred
            mock_logger.warning.assert_called_once_with(
                "[initiate] Could not open default browser"
            )