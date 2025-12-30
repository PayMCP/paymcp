from .stripe import StripeProvider
from .walleot import WalleotProvider
from .adyen import AdyenProvider
from .paypal import PayPalProvider
from .square import SquareProvider
from .coinbase import CoinbaseProvider
from .mock import MockPaymentProvider
from .x402 import X402Provider
from .base import BasePaymentProvider

__all__ = [
    "StripeProvider",
    "WalleotProvider",
    "AdyenProvider",
    "PayPalProvider",
    "SquareProvider",
    "CoinbaseProvider",
    "MockPaymentProvider",
    "X402Provider",
]

from typing import Any, Iterable, Mapping, Type, Dict, Optional
import importlib

PROVIDER_MAP = {
    "stripe": StripeProvider,
    "walleot": WalleotProvider,
    "paypal": PayPalProvider,
    "adyen": AdyenProvider,
    "square": SquareProvider,
    "coinbase": CoinbaseProvider,
    "mock": MockPaymentProvider,
    "x402": X402Provider,
}


def register_provider(name: str, cls: Type) -> None:
    """
    Register a provider class under a name. 

    Example:
        register_provider("my-gateway", MyProvider)
    """
    if not name or not isinstance(name, str):
        raise ValueError("name must be a non-empty string")
    PROVIDER_MAP[name.lower()] = cls

def _resolve_class(path: str) -> Type:
    """
    Resolve fully-qualified class path like 'pkg.module:Class' or 'pkg.module.Class' to a class.
    """
    if ":" in path:
        module_path, cls_name = path.split(":", 1)
    else:
        module_path, cls_name = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)

def _key_for_instance(inst: Any, fallback: Optional[str] = None) -> str:
    """
    Derive a key for the instance from its attributes or fallback.
    """
    name = getattr(inst, "slug", None) or getattr(inst, "name", None) or fallback or inst.__class__.__name__
    return str(name).lower()

def build_providers(config_or_instances: Any):
    """
    Normalize providers into a dict[name -> instance].

    Accepted inputs:
    1) Mapping[str, dict] where dict are kwargs:
        {"stripe": {"apiKey": "..."}, "walleot": {"apiKey": "..."}}

    2) Mapping[str, instance] where the values are already constructed providers:
        {"stripe": StripeProvider(...), "custom": MyProvider(...)}

    3) Iterable[instance], in which case keys will be derived from .slug/.name/ClassName:
        [StripeProvider(...), MyProvider(...)]

    Also supports custom classes via a special 'class' key:
        {"custom": {"class": "my_pkg.providers:MyProvider", "apiKey": "..."}}

    To pre-register classes programmatically use register_provider("custom", MyProvider).
    """
    instances: dict[str, Any] = {}

    # Case 1/2: mapping
    if isinstance(config_or_instances, Mapping):
        for name, value in config_or_instances.items():
            # Instance passed directly
            if not isinstance(value, dict):
                inst = value
                if not isinstance(inst, BasePaymentProvider):
                    raise TypeError(f"Provider '{name or _key_for_instance(inst)}' must be an instance of BasePaymentProvider; got {type(inst).__name__}")
                key = name or _key_for_instance(inst)
                instances[key] = inst
                continue

            # dict of kwargs (may contain a 'class')
            kwargs = dict(value)  # shallow copy
            cls = PROVIDER_MAP.get((name or "").lower())

            class_path = kwargs.pop("class", None) or kwargs.pop("cls", None)
            if class_path is not None:
                cls = _resolve_class(class_path)

            if not cls:
                raise ValueError(f"Unknown provider: {name}. "
                                 f"Either register it via register_provider('{name}', YourClass) "
                                 f"or provide a fully-qualified 'class' path in the config.")

            if not issubclass(cls, BasePaymentProvider):
                raise TypeError(f"Provider '{name}' must subclass BasePaymentProvider (got {cls.__name__})")
            obj = cls(**kwargs)
            if not isinstance(obj, BasePaymentProvider):
                raise TypeError(f"Constructed provider for '{name}' is not a BasePaymentProvider (got {type(obj).__name__})")
            instances[name] = obj
        return instances

    # Case 3: iterable of instances
    if isinstance(config_or_instances, Iterable):
        for inst in config_or_instances:
            if not isinstance(inst, BasePaymentProvider):
                raise TypeError(f"Iterable contains non-provider instance of type {type(inst).__name__}; expected BasePaymentProvider")
            key = _key_for_instance(inst)
            instances[key] = inst
        return instances

    raise TypeError("build_providers expects a mapping or an iterable of provider instances")
