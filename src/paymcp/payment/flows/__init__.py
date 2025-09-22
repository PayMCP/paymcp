import functools
from importlib import import_module


def make_flow(name):
    try:
        mod = import_module(f".{name}", __package__)
        make_paid_wrapper = mod.make_paid_wrapper

        def wrapper_factory(func, mcp, provider, price_info):
            return make_paid_wrapper(
                func=func,
                mcp=mcp,
                provider=provider,
                price_info=price_info,
            )

        return wrapper_factory

    except ModuleNotFoundError:
        raise ValueError(f"Unknown payment flow: {name}")
