# paymcp/payment/flows/elicitation.py
import functools
import time
import os
from ...utils.messages import open_link_message, opened_webview_message
from ..webview import open_payment_webview_if_available
import logging
from ...utils.elicitation import run_elicitation_loop
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

# Environment variable to control strict client matching
# Set PAYMCP_STRICT_CLIENT_MATCH=true to enforce client isolation
STRICT_CLIENT_MATCH = os.getenv("PAYMCP_STRICT_CLIENT_MATCH", "false").lower() == "true"


def make_paid_wrapper(func, mcp, provider, price_info):
    """
    Single-step payment flow using elicitation during execution.
    Uses elicitation to handle payment confirmation without adding tools.
    Session storage provides recovery mechanism for timeouts.
    Automatically detects client type for better session management.
    """

    # No tool registration here - pure elicitation flow

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            ctx = kwargs.get("ctx", None)
            logger.debug(f"[make_paid_wrapper] Starting tool: {func.__name__}")

            # Extract both MCP session ID and stable client ID
            mcp_session_id = None
            stable_client_id = None
            
            if ctx:
                try:
                    mcp_session_id = extract_session_id(ctx)
                    logger.debug(f"Extracted MCP session ID: {mcp_session_id}")
                except Exception as e:
                    logger.debug(f"Could not extract session ID: {e}")
                
                # Get stable client ID (proxy auth for Inspector, session for Desktop)
                if USE_CLIENT_DETECTION:
                    try:
                        stable_client_id = get_stable_client_id(ctx)
                        if stable_client_id:
                            client_type = stable_client_id.split(":")[0] if stable_client_id else "unknown"
                            logger.debug(f"Detected client type: {client_type}")
                    except Exception as e:
                        logger.debug(f"Could not detect client: {e}")

            # Check if there's a payment_id in kwargs (retry scenario)
            # Extract and remove payment_id to avoid exposing it
            retry_payment_id = kwargs.pop("payment_id", kwargs.pop("_payment_id", None))
            
            # If no payment_id provided, check for recent pending payment for this tool
            # This enables auto-recovery after MCP timeout
            if not retry_payment_id:
                if USE_CLIENT_DETECTION and hasattr(PendingPaymentTracker, 'get_most_recent_pending_for_tool'):
                    # Enhanced tracker with client filtering
                    recent = PendingPaymentTracker.get_most_recent_pending_for_tool(
                        func.__name__, 
                        provider.get_name(),
                        client_id=stable_client_id,
                        strict_client_match=STRICT_CLIENT_MATCH
                    )
                else:
                    # Original tracker without client filtering
                    recent = PendingPaymentTracker.get_most_recent_pending_for_tool(
                        func.__name__, provider.get_name()
                    )
                
                if recent:
                    retry_payment_id, payment_url = recent
                    logger.info(
                        f"[make_paid_wrapper] Auto-recovering recent pending payment {retry_payment_id} for {func.__name__}"
                    )

            # If payment_id is provided (manually or auto-discovered), validate it
            if retry_payment_id:
                if USE_CLIENT_DETECTION and hasattr(PendingPaymentTracker, 'get_pending_by_payment_id'):
                    # Enhanced tracker with client filtering
                    pending = PendingPaymentTracker.get_pending_by_payment_id(
                        provider.get_name(), 
                        str(retry_payment_id),
                        client_id=stable_client_id,
                        strict_client_match=STRICT_CLIENT_MATCH
                    )
                else:
                    # Original tracker without client filtering
                    pending = PendingPaymentTracker.get_pending_by_payment_id(
                        provider.get_name(), str(retry_payment_id)
                    )
                
                if not pending:
                    # Payment ID not found - could be expired or invalid
                    logger.warning(
                        f"[make_paid_wrapper] Payment ID {retry_payment_id} not found or expired"
                    )
                    # Don't raise error, just continue with new payment
                    retry_payment_id = None
                else:
                    tool_name, payment_url = pending
                    if tool_name != func.__name__:
                        logger.warning(
                            f"[make_paid_wrapper] Payment ID {retry_payment_id} is for tool {tool_name}, not {func.__name__}"
                        )
                        # Don't raise error, just continue with new payment
                        retry_payment_id = None
                    else:
                        logger.info(f"[make_paid_wrapper] Recovering payment {retry_payment_id} for {func.__name__}")
                    
            if retry_payment_id:
                logger.debug(
                    f"[make_paid_wrapper] Retry detected for payment_id={retry_payment_id}"
                )
                # Check payment status for retry
                try:
                    status = provider.get_payment_status(retry_payment_id)
                    if status == "paid":
                        logger.info(
                            f"[make_paid_wrapper] Payment {retry_payment_id} already paid, executing tool"
                        )
                        # Remove payment_id from kwargs before calling original function
                        clean_kwargs = {
                            k: v
                            for k, v in kwargs.items()
                            if k not in ["_payment_id", "payment_id"]
                        }
                        return await func(*args, **clean_kwargs)
                    elif status == "canceled":
                        logger.info(
                            f"[make_paid_wrapper] Payment {retry_payment_id} was canceled"
                        )
                        return {
                            "status": "canceled",
                            "message": "Previous payment was canceled",
                        }
                except Exception as e:
                    logger.warning(
                        f"[make_paid_wrapper] Could not check retry payment status: {e}"
                    )
                    # Continue with new payment

            # 1. Initiate payment
            payment_id, payment_url = provider.create_payment(
                amount=price_info["price"],
                currency=price_info["currency"],
                description=f"{func.__name__}() execution fee",
            )
            logger.debug(f"[make_paid_wrapper] Created payment with ID: {payment_id}")

            # Store as pending payment for automatic recovery (with client ID if available)
            if USE_CLIENT_DETECTION and hasattr(PendingPaymentTracker, 'store_pending'):
                # Enhanced tracker with client ID
                PendingPaymentTracker.store_pending(
                    func.__name__, 
                    provider.get_name(), 
                    str(payment_id), 
                    payment_url,
                    client_id=stable_client_id
                )
            else:
                # Original tracker without client ID
                PendingPaymentTracker.store_pending(
                    func.__name__, provider.get_name(), str(payment_id), payment_url
                )

            # Store session for recovery (if client needs to retry after timeout)
            # But NOT for a confirmation tool - just for potential retry
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
                    "client_id": stable_client_id,  # Store client ID in metadata
                    "client_type": stable_client_id.split(":")[0] if stable_client_id else "unknown"
                },
            )
            await session_storage.set(
                session_key, session_data, ttl_seconds=300
            )  # 5 minute TTL for retries
            logger.debug(
                f"[make_paid_wrapper] Stored session for potential retry of payment_id={payment_id}"
            )

            if open_payment_webview_if_available(payment_url):
                message = opened_webview_message(
                    payment_url, price_info["price"], price_info["currency"], str(payment_id)
                )
            else:
                message = open_link_message(
                    payment_url, price_info["price"], price_info["currency"], str(payment_id)
                )

            # 2. Ask the user to confirm payment
            # Note: We track payment via PendingPaymentTracker for recovery
            logger.debug(f"[make_paid_wrapper] Calling elicitation for payment: {payment_id}")

            try:
                payment_status = await run_elicitation_loop(
                    ctx, func, message, provider, payment_id
                )
            except Exception as e:
                # Check if this is a user cancellation
                error_msg = str(e).lower()
                if "canceled by user" in error_msg or "cancelled by user" in error_msg:
                    logger.info(f"[make_paid_wrapper] User canceled payment")
                    # Clear pending payment on cancellation
                    PendingPaymentTracker.clear_pending(provider.get_name(), str(payment_id))
                    # Clean up session on cancellation
                    await session_storage.delete(session_key)
                    return {"status": "canceled", "message": "Payment canceled by user"}
                
                logger.warning(f"[make_paid_wrapper] Payment confirmation failed: {e}")
                raise

            if payment_status == "paid":
                logger.info(
                    f"[make_paid_wrapper] Payment confirmed, calling {func.__name__}"
                )
                # Clear pending payment after success
                PendingPaymentTracker.clear_pending(provider.get_name(), str(payment_id))
                # Clean up session after successful payment
                await session_storage.delete(session_key)
                return await func(*args, **kwargs)  # calling original function

            if payment_status == "canceled":
                logger.info(f"[make_paid_wrapper] Payment canceled")
                # Clear pending payment on cancellation
                PendingPaymentTracker.clear_pending(provider.get_name(), str(payment_id))
                # Clean up session on cancellation
                await session_storage.delete(session_key)
                return {"status": "canceled", "message": "Payment canceled by user"}
            else:
                logger.info(f"[make_paid_wrapper] Payment not received after retries")
                # Return pending status with clear instructions
                # Include payment URL so user can complete payment externally
                return {
                    "status": "pending",
                    "message": (
                        f"Payment pending. Please complete payment at: {payment_url}\n"
                        f"After completing payment, retry the '{func.__name__}' tool.\n"
                        f"The system will automatically recover your payment."
                    ),
                    "payment_url": payment_url,
                    # Don't expose payment_id to avoid UI confusion
                }
        
        except Exception as e:
            # Catch any errors including timeout errors
            logger.warning(f"[make_paid_wrapper] Error in wrapper: {e}")
            
            # Check if we have a recent pending payment to recover
            if USE_CLIENT_DETECTION and hasattr(PendingPaymentTracker, 'get_most_recent_pending_for_tool'):
                recent = PendingPaymentTracker.get_most_recent_pending_for_tool(
                    func.__name__, 
                    provider.get_name(),
                    client_id=stable_client_id if 'stable_client_id' in locals() else None,
                    strict_client_match=STRICT_CLIENT_MATCH
                )
            else:
                recent = PendingPaymentTracker.get_most_recent_pending_for_tool(
                    func.__name__, provider.get_name()
                )
            
            if recent:
                payment_id, payment_url = recent
                logger.info(f"[make_paid_wrapper] Found pending payment {payment_id} during error recovery")
                
                # Check if payment was completed
                try:
                    status = provider.get_payment_status(payment_id)
                    if status == "paid":
                        logger.info(f"[make_paid_wrapper] Payment {payment_id} was paid, executing tool despite error")
                        # Try to execute the original function
                        clean_kwargs = {
                            k: v for k, v in kwargs.items() 
                            if k not in ["_payment_id", "payment_id"]
                        }
                        return await func(*args, **clean_kwargs)
                    elif status == "pending":
                        return {
                            "status": "pending",
                            "message": (
                                f"Payment in progress. Please complete payment at: {payment_url}\n"
                                f"After completing payment, retry the '{func.__name__}' tool."
                            ),
                            "payment_url": payment_url
                        }
                except Exception as status_error:
                    logger.debug(f"Could not check payment status during error recovery: {status_error}")
            
            # If we can't recover, provide helpful message
            error_msg = str(e).lower()
            if "timeout" in error_msg or "timed out" in error_msg:
                return {
                    "status": "error", 
                    "message": f"Request timed out. Please retry the '{func.__name__}' tool to continue.",
                    "recoverable": True
                }
            
            # Re-raise other errors
            raise

    return wrapper