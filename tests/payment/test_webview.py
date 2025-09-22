import pytest
from unittest.mock import Mock, patch, MagicMock, call
import logging
import sys
import threading
import multiprocessing
from paymcp.payment.webview import (
    _open_payment_webview,
    open_payment_webview_if_available,
)


class TestOpenPaymentWebview:
    @pytest.fixture
    def mock_logger(self):
        with patch("paymcp.payment.webview.logger") as mock_log:
            yield mock_log

    def test_open_payment_webview_success(self, mock_logger):
        mock_webview = MagicMock()

        with patch.dict("sys.modules", {"webview": mock_webview}):
            _open_payment_webview("https://test.com/pay")

            mock_webview.create_window.assert_called_once_with(
                "Complete your payment", "https://test.com/pay"
            )
            mock_webview.start.assert_called_once()
            mock_logger.debug.assert_not_called()
            mock_logger.exception.assert_not_called()

    def test_open_payment_webview_import_error(self, mock_logger):
        # Simulate webview not being installed
        with patch.dict("sys.modules", {"webview": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'webview'"),
            ):
                _open_payment_webview("https://test.com/pay")

                mock_logger.debug.assert_called_once_with(
                    "pywebview not available; skipping webview window"
                )

    def test_open_payment_webview_exception_during_import(self, mock_logger):
        with patch("builtins.__import__", side_effect=Exception("Some error")):
            _open_payment_webview("https://test.com/pay")

            mock_logger.debug.assert_called_once_with(
                "pywebview not available; skipping webview window"
            )

    def test_open_payment_webview_exception_during_create_window(self, mock_logger):
        mock_webview = MagicMock()
        mock_webview.create_window.side_effect = Exception("Window creation failed")

        with patch.dict("sys.modules", {"webview": mock_webview}):
            _open_payment_webview("https://test.com/pay")

            mock_logger.exception.assert_called_once_with(
                "Failed to open payment webview"
            )

    def test_open_payment_webview_exception_during_start(self, mock_logger):
        mock_webview = MagicMock()
        mock_webview.start.side_effect = Exception("Start failed")

        with patch.dict("sys.modules", {"webview": mock_webview}):
            _open_payment_webview("https://test.com/pay")

            mock_webview.create_window.assert_called_once()
            mock_logger.exception.assert_called_once_with(
                "Failed to open payment webview"
            )


class TestOpenPaymentWebviewIfAvailable:
    @pytest.fixture
    def mock_logger(self):
        with patch("paymcp.payment.webview.logger") as mock_log:
            yield mock_log

    @patch("paymcp.payment.webview.find_spec")
    def test_webview_not_available(self, mock_find_spec, mock_logger):
        mock_find_spec.return_value = None

        result = open_payment_webview_if_available("https://test.com/pay")

        assert result is False
        mock_find_spec.assert_called_once_with("webview")

    @patch("paymcp.payment.webview.find_spec")
    @patch("sys.platform", "darwin")
    @patch("paymcp.payment.webview.multiprocessing.get_context")
    def test_macos_spawns_process(self, mock_get_context, mock_find_spec, mock_logger):
        mock_find_spec.return_value = MagicMock()  # webview is available
        mock_ctx = MagicMock()
        mock_process = MagicMock()
        mock_ctx.Process.return_value = mock_process
        mock_get_context.return_value = mock_ctx

        result = open_payment_webview_if_available("https://test.com/pay")

        assert result is True
        mock_get_context.assert_called_once_with("spawn")
        mock_ctx.Process.assert_called_once()

        # Check Process arguments
        call_args = mock_ctx.Process.call_args
        assert call_args.kwargs["target"].__name__ == "_open_payment_webview"
        assert call_args.kwargs["args"] == ("https://test.com/pay",)
        assert call_args.kwargs["daemon"] is True

        mock_process.start.assert_called_once()
        mock_logger.info.assert_called_with(
            "[initiate] Started pywebview subprocess for payment url"
        )

    @patch("paymcp.payment.webview.find_spec")
    @patch("sys.platform", "linux")
    @patch("paymcp.payment.webview.threading.Thread")
    def test_non_macos_starts_thread(
        self, mock_thread_class, mock_find_spec, mock_logger
    ):
        mock_find_spec.return_value = MagicMock()  # webview is available
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        result = open_payment_webview_if_available("https://test.com/pay")

        assert result is True
        mock_thread_class.assert_called_once()

        # Check Thread arguments
        call_args = mock_thread_class.call_args
        assert call_args.kwargs["target"].__name__ == "_open_payment_webview"
        assert call_args.kwargs["args"] == ("https://test.com/pay",)
        assert call_args.kwargs["daemon"] is True

        mock_thread.start.assert_called_once()
        mock_logger.info.assert_called_with(
            "[initiate] Opened pywebview thread for payment url"
        )

    @patch("paymcp.payment.webview.find_spec")
    @patch("sys.platform", "win32")
    @patch("paymcp.payment.webview.threading.Thread")
    def test_windows_starts_thread(
        self, mock_thread_class, mock_find_spec, mock_logger
    ):
        mock_find_spec.return_value = MagicMock()  # webview is available
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        result = open_payment_webview_if_available("https://test.com/pay")

        assert result is True
        mock_thread_class.assert_called_once()
        mock_thread.start.assert_called_once()

    @patch("paymcp.payment.webview.find_spec")
    @patch("sys.platform", "darwin")
    @patch("paymcp.payment.webview.multiprocessing.get_context")
    @patch("paymcp.payment.webview.webbrowser.open")
    def test_macos_process_exception_fallback_to_browser(
        self, mock_browser_open, mock_get_context, mock_find_spec, mock_logger
    ):
        mock_find_spec.return_value = MagicMock()  # webview is available
        mock_get_context.side_effect = Exception("Process spawn failed")

        result = open_payment_webview_if_available("https://test.com/pay")

        assert result is True
        mock_logger.exception.assert_called_with(
            "[initiate] Failed to launch pywebview; falling back to browser"
        )
        mock_browser_open.assert_called_once_with("https://test.com/pay")
        mock_logger.info.assert_called_with(
            "[initiate] Opened default browser for payment url"
        )

    @patch("paymcp.payment.webview.find_spec")
    @patch("sys.platform", "linux")
    @patch("paymcp.payment.webview.threading.Thread")
    @patch("paymcp.payment.webview.webbrowser.open")
    def test_thread_exception_fallback_to_browser(
        self, mock_browser_open, mock_thread_class, mock_find_spec, mock_logger
    ):
        mock_find_spec.return_value = MagicMock()  # webview is available
        mock_thread_class.side_effect = Exception("Thread creation failed")

        result = open_payment_webview_if_available("https://test.com/pay")

        assert result is True
        mock_logger.exception.assert_called_with(
            "[initiate] Failed to launch pywebview; falling back to browser"
        )
        mock_browser_open.assert_called_once_with("https://test.com/pay")

    @patch("paymcp.payment.webview.find_spec")
    @patch("sys.platform", "darwin")
    @patch("paymcp.payment.webview.multiprocessing.get_context")
    @patch("paymcp.payment.webview.webbrowser.open")
    def test_browser_fallback_also_fails(
        self, mock_browser_open, mock_get_context, mock_find_spec, mock_logger
    ):
        mock_find_spec.return_value = MagicMock()  # webview is available
        mock_get_context.side_effect = Exception("Process spawn failed")
        mock_browser_open.side_effect = Exception("Browser open failed")

        result = open_payment_webview_if_available("https://test.com/pay")

        assert result is False
        mock_logger.exception.assert_called_with(
            "[initiate] Failed to launch pywebview; falling back to browser"
        )
        mock_logger.warning.assert_called_with(
            "[initiate] Could not open default browser"
        )

    @patch("paymcp.payment.webview.find_spec")
    def test_webview_spec_none(self, mock_find_spec, mock_logger):
        mock_find_spec.return_value = None

        result = open_payment_webview_if_available("https://payment.com")

        assert result is False
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_not_called()
