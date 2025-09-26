import functools
import os
from importlib import import_module


def make_flow(name):
    # Check if async mode is enabled for elicitation flow
    if name == "elicitation" and os.getenv("PAYMCP_ASYNC_MODE", "false").lower() == "true":
        # Try to use async version if available
        try:
            mod = import_module(".elicitation_async", __package__)
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
            # Fall back to regular elicitation if async not available
            pass
    
    # Use async progress flow if available
    if name == "progress":
        try:
            # Try async version first
            mod = import_module(".progress_async", __package__)
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
            # Fall back to regular progress flow
            pass
    
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
