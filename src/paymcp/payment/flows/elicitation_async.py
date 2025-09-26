# paymcp/payment/flows/elicitation_async.py
"""
Asynchronous payment flow that returns immediately and processes payment in background.
This prevents MCP timeouts while still providing results as soon as payment is complete.
"""
import functools
import time
import os
import asyncio
from typing import Dict, Any, Optional, Tuple
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
import logging
from ...session import SessionManager, SessionKey, SessionData
from ...utils.session import extract_session_id

# Try to use enhanced tracker with client detection if available
try:
    from ...utils.client_detection import get_stable_client_id
    from ...session.pending_tracker_enhanced import EnhancedPendingPaymentTracker as PendingPaymentTracker
    USE_CLIENT_DETECTION = True
except ImportError:
    from ...session.pending_tracker import PendingPaymentTracker
    USE_CLIENT_DETECTION = False
    
    def get_stable_client_id(ctx):
        """Fallback when client detection not available."""
        return None

logger = logging.getLogger(__name__)

# Session storage for payment args
session_storage = SessionManager.get_storage()

# Store for completed async results
ASYNC_RESULTS: Dict[str, Any] = {}
RESULT_TTL = 300  # 5 minutes

# Environment variable to control strict client matching
STRICT_CLIENT_MATCH = os.getenv("PAYMCP_STRICT_CLIENT_MATCH", "false").lower() == "true"

# Enable async mode
ASYNC_MODE = os.getenv("PAYMCP_ASYNC_MODE", "false").lower() == "true"


async def process_payment_async(func, args, kwargs, provider, payment_id, payment_url):
    """Background task to poll payment status and execute tool when paid."""
    max_polls = 60  # Poll for up to 60 seconds
    poll_interval = 1  # Check every second
    
    for i in range(max_polls):
        try:
            status = provider.get_payment_status(payment_id)
            if status == "paid":
                logger.info(f"[async] Payment {payment_id} confirmed, executing {func.__name__}")
                # Execute the original function
                result = await func(*args, **kwargs)
                # Store result for retrieval
                ASYNC_RESULTS[payment_id] = {
                    "status": "completed",
                    "result": result,
                    "timestamp": time.time()
                }
                # Clear pending payment
                PendingPaymentTracker.clear_pending(provider.get_name(), str(payment_id))
                return result
            elif status == "canceled":
                logger.info(f"[async] Payment {payment_id} canceled")
                ASYNC_RESULTS[payment_id] = {
                    "status": "canceled",
                    "message": "Payment was canceled",
                    "timestamp": time.time()
                }
                PendingPaymentTracker.clear_pending(provider.get_name(), str(payment_id))
                return None
        except Exception as e:
            logger.debug(f"[async] Error checking payment status: {e}")
        
        await asyncio.sleep(poll_interval)
    
    # Timeout - payment still pending
    logger.info(f"[async] Payment {payment_id} still pending after timeout")
    ASYNC_RESULTS[payment_id] = {
        "status": "timeout",
        "message": "Payment verification timed out. Please retry the tool.",
        "payment_url": payment_url,
        "timestamp": time.time()
    }


def cleanup_old_results():
    """Remove old results from memory."""
    current_time = time.time()
    expired = []
    for payment_id, data in ASYNC_RESULTS.items():
        if current_time - data.get("timestamp", 0) > RESULT_TTL:
            expired.append(payment_id)
    for payment_id in expired:
        del ASYNC_RESULTS[payment_id]


def make_paid_wrapper_async(func, mcp, provider, price_info):
    """
    Asynchronous payment flow that returns immediately to prevent timeouts.
    Processes payment and executes tool in background, storing result for retrieval.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            ctx = kwargs.get("ctx", None)
            logger.debug(f"[async wrapper] Starting tool: {func.__name__}")
            
            # Clean up old results
            cleanup_old_results()

            # Extract session info
            mcp_session_id = None
            stable_client_id = None
            
            if ctx:
                try:
                    mcp_session_id = extract_session_id(ctx)
                    logger.debug(f"Extracted MCP session ID: {mcp_session_id}")
                except Exception as e:
                    logger.debug(f"Could not extract session ID: {e}")
                
                if USE_CLIENT_DETECTION:
                    try:
                        stable_client_id = get_stable_client_id(ctx)
                        if stable_client_id:
                            client_type = stable_client_id.split(":")[0] if stable_client_id else "unknown"
                            logger.debug(f"Detected client type: {client_type}")
                    except Exception as e:
                        logger.debug(f"Could not detect client: {e}")

            # Check for retry with payment_id
            retry_payment_id = kwargs.pop("payment_id", kwargs.pop("_payment_id", None))
            
            # Check for async result retrieval
            if retry_payment_id and retry_payment_id in ASYNC_RESULTS:
                result_data = ASYNC_RESULTS[retry_payment_id]
                if result_data["status"] == "completed":
                    logger.info(f"[async wrapper] Returning cached result for {retry_payment_id}")
                    # Remove from cache after retrieval
                    del ASYNC_RESULTS[retry_payment_id]
                    return result_data["result"]
                elif result_data["status"] == "canceled":
                    del ASYNC_RESULTS[retry_payment_id]
                    return {"status": "canceled", "message": result_data["message"]}
                elif result_data["status"] == "timeout":
                    # Don't delete, let it expire naturally
                    return {
                        "status": "pending",
                        "message": result_data["message"],
                        "payment_url": result_data.get("payment_url")
                    }
            
            # Check for recent pending payment
            if not retry_payment_id:
                if USE_CLIENT_DETECTION and hasattr(PendingPaymentTracker, 'get_most_recent_pending_for_tool'):
                    recent = PendingPaymentTracker.get_most_recent_pending_for_tool(
                        func.__name__, 
                        provider.get_name(),
                        client_id=stable_client_id,
                        strict_client_match=STRICT_CLIENT_MATCH
                    )
                else:
                    recent = PendingPaymentTracker.get_most_recent_pending_for_tool(
                        func.__name__, provider.get_name()
                    )
                
                if recent:
                    retry_payment_id, payment_url = recent
                    logger.info(f"[async wrapper] Found pending payment {retry_payment_id}")
                    
                    # Quick check if already paid
                    try:
                        status = provider.get_payment_status(retry_payment_id)
                        if status == "paid":
                            logger.info(f"[async wrapper] Payment {retry_payment_id} already paid, executing")
                            PendingPaymentTracker.clear_pending(provider.get_name(), str(retry_payment_id))
                            clean_kwargs = {
                                k: v for k, v in kwargs.items() 
                                if k not in ["_payment_id", "payment_id"]
                            }
                            return await func(*args, **clean_kwargs)
                    except Exception as e:
                        logger.debug(f"Could not check payment status: {e}")

            # If we have a payment_id, check its status
            if retry_payment_id:
                try:
                    status = provider.get_payment_status(retry_payment_id)
                    if status == "paid":
                        logger.info(f"[async wrapper] Payment {retry_payment_id} already paid")
                        clean_kwargs = {
                            k: v for k, v in kwargs.items() 
                            if k not in ["_payment_id", "payment_id"]
                        }
                        return await func(*args, **clean_kwargs)
                    elif status == "canceled":
                        return {
                            "status": "canceled",
                            "message": "Previous payment was canceled"
                        }
                except Exception as e:
                    logger.warning(f"Could not check retry payment status: {e}")

            # Create new payment
            payment_id, payment_url = provider.create_payment(
                amount=price_info["price"],
                currency=price_info["currency"],
                description=f"{func.__name__}() execution fee",
            )
            logger.debug(f"[async wrapper] Created payment with ID: {payment_id}")

            # Store as pending payment
            if USE_CLIENT_DETECTION and hasattr(PendingPaymentTracker, 'store_pending'):
                PendingPaymentTracker.store_pending(
                    func.__name__, 
                    provider.get_name(), 
                    str(payment_id), 
                    payment_url,
                    client_id=stable_client_id
                )
            else:
                PendingPaymentTracker.store_pending(
                    func.__name__, provider.get_name(), str(payment_id), payment_url
                )

            # Store session for recovery
            provider_name = provider.get_name()
            session_key = SessionKey(
                provider=provider_name,
                payment_id=str(payment_id),
                mcp_session_id=mcp_session_id,
            )
            session_data = SessionData(
                args={"args": args, "kwargs": kwargs},
                ts=int(time.time() * 1000),
                provider_name=provider_name,
                metadata={
                    "tool_name": func.__name__, 
                    "for_retry": True,
                    "client_id": stable_client_id,
                    "client_type": stable_client_id.split(":")[0] if stable_client_id else "unknown"
                },
            )
            await session_storage.set(
                session_key, session_data, ttl_seconds=300
            )

            # Open payment window if available
            if open_payment_webview_if_available(payment_url):
                message = opened_webview_message(
                    payment_url, price_info["price"], price_info["currency"], str(payment_id)
                )
            else:
                message = open_link_message(
                    payment_url, price_info["price"], price_info["currency"], str(payment_id)
                )

            # Start async payment processing
            asyncio.create_task(
                process_payment_async(func, args, kwargs, provider, payment_id, payment_url)
            )

            # Return immediately with pending status
            return {
                "status": "payment_required",
                "message": (
                    f"Payment initiated. {message}\n"
                    f"Once payment is complete, retry the '{func.__name__}' tool to get your result.\n"
                    f"Payment ID: {payment_id}"
                ),
                "payment_url": payment_url,
                "payment_id": str(payment_id),
                "retry_instruction": f"Call '{func.__name__}' again after completing payment"
            }
            
        except Exception as e:
            logger.error(f"[async wrapper] Error: {e}")
            raise

    return wrapper


# Export the async wrapper as the main wrapper if async mode is enabled
def make_paid_wrapper(func, mcp, provider, price_info):
    """Main entry point that selects sync or async mode based on environment."""
    if ASYNC_MODE:
        logger.info(f"Using async payment flow for {func.__name__}")
        return make_paid_wrapper_async(func, mcp, provider, price_info)
    else:
        # Import the original sync wrapper
        from .elicitation import make_paid_wrapper as make_paid_wrapper_sync
        return make_paid_wrapper_sync(func, mcp, provider, price_info)