# paymcp/state/in_memory.py
"""In-memory state store implementation."""

from typing import Dict, Any, Optional
import time
import logging

logger = logging.getLogger(__name__)


class InMemoryStateStore:
    """In-memory state store using a dictionary.

    Suitable for development and single-process deployments.
    Data is lost when the process restarts.

    Thread-safe for async operations within a single process.
    """

    def __init__(self):
        """Initialize the in-memory state store."""
        self._store: Dict[str, Dict[str, Any]] = {}
        logger.debug("InMemoryStateStore initialized")

    async def set(self, key: str, args: Dict[str, Any]) -> None:
        """Store arguments in memory.

        Args:
            key: Unique payment identifier
            args: Dictionary of tool arguments to store
        """
        self._store[key] = {
            'args': args,
            'ts': time.time()
        }
        logger.debug(f"Stored args for payment {key}")

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve arguments from memory.

        Args:
            key: Unique payment identifier

        Returns:
            Dictionary with 'args' and 'ts' keys if found, None otherwise
        """
        result = self._store.get(key)
        if result:
            logger.debug(f"Retrieved args for payment {key}")
        else:
            logger.debug(f"No args found for payment {key}")
        return result

    async def delete(self, key: str) -> None:
        """Delete arguments from memory.

        Args:
            key: Unique payment identifier
        """
        if key in self._store:
            del self._store[key]
            logger.debug(f"Deleted args for payment {key}")
        else:
            logger.debug(f"No args to delete for payment {key}")

    def clear(self) -> None:
        """Clear all stored data. Useful for testing."""
        self._store.clear()
        logger.debug("Cleared all stored data")

    def size(self) -> int:
        """Return the number of stored payments."""
        return len(self._store)
