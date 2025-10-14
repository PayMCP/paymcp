"""
Mock Payment Provider for Testing.

Provides a flexible mock payment provider that generates payment IDs with
embedded status hints, allowing tests to control expected payment behavior
without environment variables or setup configuration.

Key Features:
- Payment IDs include status prefix (e.g., mock_paid_abc123, mock_failed_xyz789)
- Status automatically determined from payment_id prefix
- No environment variables needed for basic testing
- Supports auto-confirm transitions (pending → paid)
- Instant failure/success scenarios for comprehensive testing

Payment ID Format: mock_{status}_{random_hex}[_{delay_ms}]
- Basic: mock_paid_abc123 (immediate "paid" status)
- With delay: mock_paid_abc123_2000 (returns "pending" for 2000ms, then "paid")

Supported statuses: paid, pending, failed, cancelled, expired, timeout
"""

import uuid
import logging
import time
import os
from typing import Tuple, Dict, Any
from .base import BasePaymentProvider


class MockPaymentProvider(BasePaymentProvider):
    """Mock payment provider for testing PayMCP flows.

    Payment IDs are generated with status hints embedded in the ID itself:
    - Format: mock_{status}_{random_hex}[_{delay_ms}]
    - Example: mock_paid_abc123 always returns "paid" status
    - Example: mock_failed_xyz789 always returns "failed" status
    - Example: mock_paid_abc123_2000 returns "pending" for 2 seconds, then "paid"

    This design eliminates the need for environment variable configuration
    in test scenarios, making tests more self-documenting and deterministic.

    Supported payment statuses:
    - paid: Instant success
    - pending: Payment awaiting confirmation
    - failed: Payment failed
    - cancelled: User cancelled payment
    - expired: Payment session expired
    - timeout: Payment processing timed out

    Delay simulation (optional):
    - Append _{milliseconds} to simulate processing time
    - Payment returns "pending" until delay elapses
    - Then automatically transitions to target status

    Configuration (optional, for legacy compatibility):
    - default_status: Status to use when creating payments (default: "paid")
    - auto_confirm: Auto-transition pending → paid after delay (default: False)
    - confirm_delay: Seconds to wait before auto-confirming (default: 0)

    Environment variables (legacy, optional):
    - MOCK_PAYMENT_DEFAULT_STATUS: "paid", "pending", "failed", "cancelled", "expired"
    - MOCK_PAYMENT_AUTO_CONFIRM: "true"/"false"
    - MOCK_PAYMENT_CONFIRM_DELAY: seconds to wait before auto-confirming
    """

    def __init__(self, api_key: str = None, apiKey: str = None, logger: logging.Logger = None, **kwargs):
        """Initialize mock payment provider.

        Args:
            api_key: Not used for mock provider, but kept for interface compatibility
            apiKey: Alternative parameter name for api_key
            logger: Logger instance
            **kwargs: Additional configuration:
                - default_status: Default payment status ("paid", "pending", "failed", "cancelled", "expired")
                - auto_confirm: Whether to auto-confirm payments after delay
                - confirm_delay: Seconds to wait before auto-confirming
        """
        super().__init__(api_key=api_key or apiKey or "mock", logger=logger)

        # Payment storage: {payment_id: {status, created_at, amount, currency, metadata}}
        self._payments: Dict[str, Dict[str, Any]] = {}

        # Configuration
        self.default_status = kwargs.get(
            'default_status',
            os.getenv('MOCK_PAYMENT_DEFAULT_STATUS', 'paid')
        )
        self.auto_confirm = kwargs.get(
            'auto_confirm',
            os.getenv('MOCK_PAYMENT_AUTO_CONFIRM', 'false').lower() == 'true'
        )
        self.confirm_delay = float(kwargs.get(
            'confirm_delay',
            os.getenv('MOCK_PAYMENT_CONFIRM_DELAY', '0')
        ))

        self.logger.info(
            f"MockPaymentProvider initialized: "
            f"default_status={self.default_status}, "
            f"auto_confirm={self.auto_confirm}, "
            f"confirm_delay={self.confirm_delay}"
        )

    def create_payment(
        self, amount: float, currency: str, description: str
    ) -> Tuple[str, str]:
        """Create a mock payment with status hint embedded in payment_id.

        The payment_id format is: mock_{status}_{random_hex}
        This allows tests to control expected status without environment variables.

        Args:
            amount: Payment amount
            currency: Currency code (e.g., "USD")
            description: Payment description

        Returns:
            Tuple of (payment_id, payment_url)

        Examples:
            >>> provider = MockPaymentProvider(default_status="paid")
            >>> payment_id, url = provider.create_payment(1.00, "USD", "test")
            >>> # payment_id will be like: mock_paid_a1b2c3d4e5f6g7h8
        """
        # Determine initial status
        initial_status = "pending" if self.auto_confirm else self.default_status

        # Generate payment ID with status prefix hint
        random_suffix = uuid.uuid4().hex[:16]
        payment_id = f"mock_{initial_status}_{random_suffix}"

        # Store payment data
        self._payments[payment_id] = {
            'status': initial_status,
            'created_at': time.time(),
            'amount': amount,
            'currency': currency,
            'description': description,
            'metadata': {}
        }

        # Generate mock payment URL
        payment_url = f"https://mock-payment.local/pay/{payment_id}"

        self.logger.info(
            f"Created mock payment: {payment_id} "
            f"(${amount} {currency}, status={initial_status})"
        )

        return (payment_id, payment_url)

    def get_payment_status(self, payment_id: str) -> str:
        """Get mock payment status with prefix-based hint detection.

        Priority order:
        1. Internal storage (if payment exists and was manually modified)
        2. Payment ID prefix hint (mock_{status}_{hex})
        3. Unknown payment returns "expired"

        This allows tests to create deterministic payment statuses by controlling
        the payment_id prefix without needing environment variable configuration,
        while still supporting manual status overrides via set_payment_status().

        Args:
            payment_id: Payment identifier (e.g., "mock_paid_abc123" or "mock_abc123")

        Returns:
            Payment status: "paid", "pending", "failed", "cancelled", "expired", "timeout"

        Examples:
            >>> provider.get_payment_status("mock_paid_abc123")  # Returns "paid"
            >>> provider.get_payment_status("mock_failed_xyz789")  # Returns "failed"
            >>> provider.get_payment_status("mock_timeout_slow_response")  # Returns "timeout"
            >>> provider.get_payment_status("mock_unknown_id")  # Returns "expired"
        """
        # If payment exists in storage, use stored status (allows manual overrides)
        if payment_id in self._payments:
            payment = self._payments[payment_id]
            current_status = payment['status']

            # Handle auto-confirm logic
            if self.auto_confirm and current_status == "pending":
                elapsed = time.time() - payment['created_at']
                if elapsed >= self.confirm_delay:
                    # Auto-confirm the payment
                    payment['status'] = "paid"
                    current_status = "paid"
                    self.logger.info(f"Auto-confirmed payment: {payment_id}")

            # Handle delay simulation logic (for payment_id with embedded delay)
            # Check if this is a delay-simulated payment still pending
            if current_status == "pending" and 'metadata' in payment and 'delay' in payment['metadata']:
                elapsed = time.time() - payment['created_at']
                target_delay = payment['metadata']['delay']
                target_status = payment['metadata'].get('target_status', 'paid')

                if elapsed >= target_delay:
                    # Delay has elapsed, transition to target status
                    payment['status'] = target_status
                    current_status = target_status
                    self.logger.debug(f"Delay elapsed for {payment_id}: transitioning to '{target_status}'")

            self.logger.debug(f"Payment status check: {payment_id} = {current_status}")
            return current_status

        # Parse status hint from payment_id prefix (for external/unknown payment IDs)
        # Format: mock_{status}_{random}[_{delay_ms}]
        if payment_id.startswith("mock_"):
            parts = payment_id.split("_")
            if len(parts) >= 3:
                status_hint = parts[1]  # Extract: mock_paid_xxx -> "paid"
                valid_statuses = ["paid", "pending", "failed", "cancelled", "expired", "timeout"]

                if status_hint in valid_statuses:
                    # Check for delay specification in last segment
                    # Format: mock_paid_abc123_1000 (1000ms delay before returning "paid")
                    if len(parts) >= 4 and parts[-1].isdigit():
                        delay_ms = int(parts[-1])
                        delay_seconds = delay_ms / 1000.0

                        # Create temporary payment entry to track timing
                        if payment_id not in self._payments:
                            self._payments[payment_id] = {
                                'status': 'pending',  # Start as pending
                                'created_at': time.time(),
                                'amount': 0,
                                'currency': 'USD',
                                'metadata': {'target_status': status_hint, 'delay': delay_seconds}
                            }
                            self.logger.debug(
                                f"Created delayed payment: {payment_id} -> '{status_hint}' after {delay_ms}ms"
                            )

                        # Check if delay has elapsed
                        payment = self._payments[payment_id]
                        elapsed = time.time() - payment['created_at']

                        if elapsed >= delay_seconds:
                            # Delay elapsed, return target status
                            payment['status'] = status_hint
                            self.logger.debug(
                                f"Delay elapsed for {payment_id}: returning '{status_hint}'"
                            )
                            return status_hint
                        else:
                            # Still waiting, return pending
                            remaining_ms = int((delay_seconds - elapsed) * 1000)
                            self.logger.debug(
                                f"Delay in progress for {payment_id}: {remaining_ms}ms remaining"
                            )
                            return "pending"
                    else:
                        # No delay, return status immediately
                        self.logger.debug(
                            f"Payment status from prefix hint: {payment_id} = {status_hint}"
                        )
                        return status_hint

        # Unknown payment
        self.logger.warning(f"Payment not found: {payment_id}")
        return "expired"  # Unknown payments treated as expired

    def set_payment_status(self, payment_id: str, status: str) -> None:
        """Manually set payment status (for testing).

        Args:
            payment_id: Payment identifier
            status: New status to set
        """
        if payment_id in self._payments:
            self._payments[payment_id]['status'] = status
            self.logger.info(f"Updated payment status: {payment_id} = {status}")
        else:
            self.logger.warning(f"Cannot set status for unknown payment: {payment_id}")

    def get_payment_details(self, payment_id: str) -> Dict[str, Any]:
        """Get full payment details (for testing/debugging).

        Args:
            payment_id: Payment identifier

        Returns:
            Full payment data dictionary
        """
        return self._payments.get(payment_id, {})

    def clear_payments(self) -> None:
        """Clear all stored payments (for testing).
        """
        self._payments.clear()
        self.logger.info("Cleared all mock payments")