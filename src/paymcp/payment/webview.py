import logging

logger = logging.getLogger(__name__)
from importlib.util import find_spec
import threading
import multiprocessing
import sys
import webbrowser


def _open_payment_webview(url: str):
    """Open the payment URL in an embedded pywebview window,

    Note: On macOS, GUI frameworks must run on the main thread of a process.
    This function is safe to run as the target of a dedicated process or a
    background thread (non-macOS only).
    """
    try:
        import webview  # provided by the optional extra "webview"
    except Exception:
        logger.debug("pywebview not available; skipping webview window")
        return

    try:
        webview.create_window("Complete your payment", url)
        webview.start()
    except Exception:
        logger.exception("Failed to open payment webview")


def open_payment_webview_if_available(url: str) -> bool:
    if find_spec("webview") is not None:
        try:
            if sys.platform == "darwin":
                # On macOS, run pywebview in a separate process so the GUI
                # runs on that process's main thread (Cocoa requirement).
                ctx = multiprocessing.get_context("spawn")
                p = ctx.Process(
                    target=_open_payment_webview,
                    args=(url,),
                    daemon=True,
                )
                p.start()
                logger.info("[initiate] Started pywebview subprocess for payment url")
            else:
                # On non-macOS platforms, running in a background thread is fine.
                threading.Thread(
                    target=_open_payment_webview,
                    args=(url,),
                    daemon=True,
                ).start()
                logger.info("[initiate] Opened pywebview thread for payment url")
            return True
        except Exception:
            logger.exception(
                "[initiate] Failed to launch pywebview; falling back to browser"
            )
            try:
                webbrowser.open(url)
                logger.info("[initiate] Opened default browser for payment url")
                return True
            except Exception:
                logger.warning("[initiate] Could not open default browser")
                return False
    else:
        return False
