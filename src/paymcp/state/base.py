# paymcp/state/base.py
"""Base state store protocol for payment flow state management."""

from typing import Protocol, Any, Dict, Optional
from datetime import datetime


class StateStore(Protocol):
    """Protocol for state storage backends used in payment flows.

    State stores are used to persist pending payment arguments between
    payment initiation and confirmation steps in TWO_STEP flow.

    Implementations must be thread-safe and support async operations.
    """

    async def set(self, key: str, args: Dict[str, Any]) -> None:
        """Store arguments for a payment.

        Args:
            key: Unique payment identifier
            args: Dictionary of tool arguments to store

        Raises:
            Exception: If storage operation fails
        """
        ...

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored arguments for a payment.

        Args:
            key: Unique payment identifier

        Returns:
            Dictionary with 'args' and 'ts' keys if found, None otherwise
            'args' contains the original tool arguments
            'ts' contains the timestamp when the data was stored

        Raises:
            Exception: If retrieval operation fails
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete stored arguments for a payment.

        Args:
            key: Unique payment identifier

        Raises:
            Exception: If deletion operation fails
        """
        ...
