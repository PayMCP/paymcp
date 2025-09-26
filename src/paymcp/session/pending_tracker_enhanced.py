"""
Enhanced tracker for pending payments with client-specific filtering.
Tracks payments using provider:payment_id and optionally filters by client ID.
"""
import time
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class EnhancedPendingPaymentTracker:
    """Enhanced tracker with client-specific filtering for better isolation."""

    # In-memory storage: {"provider:payment_id": (tool_name, payment_url, timestamp, client_id)}
    _pending_payments: Dict[str, Tuple[str, str, float, Optional[str]]] = {}

    # Timeout for pending payments (5 minutes)
    TIMEOUT_SECONDS = 300

    @classmethod
    def store_pending(
        cls,
        tool_name: str,
        provider: str,
        payment_id: str,
        payment_url: str,
        client_id: Optional[str] = None,
    ):
        """Store a pending payment with provider:payment_id as key.
        
        Args:
            tool_name: Name of the tool that initiated payment
            provider: Payment provider name
            payment_id: Unique payment identifier
            payment_url: URL for completing payment
            client_id: Optional client identifier (e.g., proxy auth for MCP Inspector)
        """
        key = f"{provider}:{payment_id}"
        cls._pending_payments[key] = (tool_name, payment_url, time.time(), client_id)
        logger.debug(
            f"Stored pending payment {key} for tool {tool_name} "
            f"(client: {client_id[:20] if client_id else 'none'}...)"
        )
        cls._cleanup_expired()

    @classmethod
    def get_pending_by_payment_id(
        cls,
        provider: str,
        payment_id: str,
        client_id: Optional[str] = None,
        strict_client_match: bool = False,
    ) -> Optional[Tuple[str, str]]:
        """Get pending payment by exact provider and payment_id.
        
        Args:
            provider: Payment provider name
            payment_id: Payment identifier
            client_id: Optional client identifier for filtering
            strict_client_match: If True, only return payments from same client
        
        Returns:
            Optional tuple of (tool_name, payment_url) if found and not expired.
        """
        cls._cleanup_expired()

        key = f"{provider}:{payment_id}"
        if key in cls._pending_payments:
            tool_name, payment_url, timestamp, stored_client_id = cls._pending_payments[key]

            # Check client match if strict mode is enabled
            if strict_client_match and client_id != stored_client_id:
                logger.debug(
                    f"Payment {key} found but client mismatch "
                    f"(expected: {client_id[:20] if client_id else 'none'}..., "
                    f"got: {stored_client_id[:20] if stored_client_id else 'none'}...)"
                )
                return None

            if time.time() - timestamp < cls.TIMEOUT_SECONDS:
                logger.debug(f"Found pending payment {key} for tool {tool_name}")
                return tool_name, payment_url
            else:
                logger.debug(f"Payment {key} expired")
        else:
            logger.debug(f"Payment {key} not found in pending tracker")

        return None

    @classmethod
    def get_most_recent_pending_for_tool(
        cls,
        tool_name: str,
        provider: str,
        client_id: Optional[str] = None,
        strict_client_match: bool = False,
    ) -> Optional[Tuple[str, str]]:
        """Get the most recent pending payment for a specific tool.
        
        This helps with auto-recovery after MCP timeout.
        
        Args:
            tool_name: Name of the tool
            provider: Payment provider name
            client_id: Optional client identifier for filtering
            strict_client_match: If True, only return payments from same client
        
        Returns:
            Optional tuple of (payment_id, payment_url) if found.
        """
        cls._cleanup_expired()

        current_time = time.time()
        most_recent = None
        most_recent_time = 0

        for key, (stored_tool, url, timestamp, stored_client_id) in cls._pending_payments.items():
            if stored_tool == tool_name and key.startswith(f"{provider}:"):
                # Check client match if strict mode is enabled
                if strict_client_match and client_id != stored_client_id:
                    continue

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

        for key, (tool_name, _, timestamp, _) in cls._pending_payments.items():
            if current_time - timestamp >= cls.TIMEOUT_SECONDS:
                expired.append(key)
                logger.debug(f"Expiring pending payment {key} for tool {tool_name}")

        for key in expired:
            del cls._pending_payments[key]

    @classmethod
    def get_all_pending_for_client(
        cls, client_id: str, provider: Optional[str] = None
    ) -> Dict[str, Tuple[str, str]]:
        """Get all pending payments for a specific client.
        
        Args:
            client_id: Client identifier
            provider: Optional provider filter
        
        Returns:
            Dict of {payment_id: (tool_name, payment_url)}
        """
        cls._cleanup_expired()
        
        result = {}
        current_time = time.time()
        
        for key, (tool_name, url, timestamp, stored_client_id) in cls._pending_payments.items():
            if stored_client_id == client_id:
                if provider and not key.startswith(f"{provider}:"):
                    continue
                    
                if current_time - timestamp < cls.TIMEOUT_SECONDS:
                    payment_id = key.split(":", 1)[1]
                    result[payment_id] = (tool_name, url)
        
        return result