"""
Tracks pending payments using provider:payment_id as key to enable seamless recovery after MCP timeout.
Designed for multi-user support with strict payment ID validation.
"""
import time
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class PendingPaymentTracker:
    """Tracks pending payments by provider:payment_id key for multi-user support."""

    # In-memory storage: {"provider:payment_id": (tool_name, payment_url, timestamp)}
    _pending_payments: Dict[str, Tuple[str, str, float]] = {}

    # Timeout for pending payments (5 minutes)
    TIMEOUT_SECONDS = 300

    @classmethod
    def store_pending(cls, tool_name: str, provider: str, payment_id: str, payment_url: str):
        """Store a pending payment with provider:payment_id as key."""
        key = f"{provider}:{payment_id}"
        cls._pending_payments[key] = (tool_name, payment_url, time.time())
        logger.debug(f"Stored pending payment {key} for tool {tool_name}")
        cls._cleanup_expired()

    @classmethod
    def get_pending_by_payment_id(cls, provider: str, payment_id: str) -> Optional[Tuple[str, str]]:
        """Get pending payment by exact provider and payment_id.
        
        Returns:
            Optional tuple of (tool_name, payment_url) if found and not expired.
            None if not found or expired.
        """
        cls._cleanup_expired()
        
        key = f"{provider}:{payment_id}"
        if key in cls._pending_payments:
            tool_name, payment_url, timestamp = cls._pending_payments[key]
            if time.time() - timestamp < cls.TIMEOUT_SECONDS:
                logger.debug(f"Found pending payment {key} for tool {tool_name}")
                return tool_name, payment_url
            else:
                logger.debug(f"Payment {key} expired")
        else:
            logger.debug(f"Payment {key} not found in pending tracker")

        return None
    
    @classmethod
    def get_most_recent_pending_for_tool(cls, tool_name: str, provider: str) -> Optional[Tuple[str, str]]:
        """Get the most recent pending payment for a specific tool.
        
        This helps with auto-recovery after MCP timeout when user doesn't have payment_id.
        
        Returns:
            Optional tuple of (payment_id, payment_url) if found.
            None if no pending payments for this tool.
        """
        cls._cleanup_expired()
        
        current_time = time.time()
        most_recent = None
        most_recent_time = 0
        
        for key, (stored_tool, url, timestamp) in cls._pending_payments.items():
            if stored_tool == tool_name and key.startswith(f"{provider}:"):
                if current_time - timestamp < cls.TIMEOUT_SECONDS:
                    if timestamp > most_recent_time:
                        most_recent_time = timestamp
                        payment_id = key.split(":", 1)[1]
                        most_recent = (payment_id, url)
        
        if most_recent:
            logger.debug(f"Found recent pending payment for tool {tool_name}: {most_recent[0]}")
        else:
            logger.debug(f"No recent pending payments found for tool {tool_name}")
            
        return most_recent

    @classmethod
    def clear_pending(cls, provider: str, payment_id: str):
        """Clear a pending payment after it's been completed or canceled."""
        key = f"{provider}:{payment_id}"
        if key in cls._pending_payments:
            tool_name = cls._pending_payments[key][0]
            del cls._pending_payments[key]
            logger.debug(f"Cleared pending payment {key} for tool {tool_name}")

    @classmethod
    def _cleanup_expired(cls):
        """Remove expired pending payments."""
        current_time = time.time()
        expired = []

        for key, (tool_name, _, timestamp) in cls._pending_payments.items():
            if current_time - timestamp >= cls.TIMEOUT_SECONDS:
                expired.append(key)
                logger.debug(f"Expiring pending payment {key} for tool {tool_name}")

        for key in expired:
            del cls._pending_payments[key]