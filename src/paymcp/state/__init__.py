# paymcp/state/__init__.py
"""State store implementations for payment flow state management."""

from .base import StateStore
from .in_memory import InMemoryStateStore

__all__ = [
    'StateStore',
    'InMemoryStateStore',
]

# Conditionally export RedisStateStore if redis is available
try:
    from .redis import RedisStateStore
    __all__.append('RedisStateStore')
except ImportError:  # pragma: no cover
    # redis package not installed, skip RedisStateStore
    pass
