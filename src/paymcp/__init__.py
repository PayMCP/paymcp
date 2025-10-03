# paymcp/__init__.py

from .core import PayMCP, PaymentFlow, __version__
from .decorators import price
from .payment.payment_flow import PaymentFlow
from .state import StateStore, InMemoryStateStore

__all__ = [
    "PayMCP",
    "price",
    "PaymentFlow",
    "__version__",
    "StateStore",
    "InMemoryStateStore",
]

# Conditionally export RedisStateStore if available
try:
    from .state import RedisStateStore
    __all__.append("RedisStateStore")
except ImportError:  # pragma: no cover
    pass