import functools
from importlib import import_module
from typing import Optional
from ...state import StateStore

def make_flow(name, state_store: Optional[StateStore] = None):
    """
    Create a payment flow wrapper factory.

    Args:
        name: Flow name (e.g., 'two_step', 'elicitation', 'progress')
        state_store: Optional StateStore for flows that need persistent state (e.g., TWO_STEP)

    Returns:
        Wrapper factory function
    """
    try:
        mod = import_module(f".{name}", __package__)
        make_paid_wrapper = mod.make_paid_wrapper

        def wrapper_factory(func, mcp, provider, price_info):
            # Check if flow supports state_store parameter
            import inspect
            sig = inspect.signature(make_paid_wrapper)
            if 'state_store' in sig.parameters:
                return make_paid_wrapper(
                    func=func,
                    mcp=mcp,
                    provider=provider,
                    price_info=price_info,
                    state_store=state_store,
                )
            else:
                # Flow doesn't support state_store (e.g., ELICITATION, PROGRESS)
                return make_paid_wrapper(
                    func=func,
                    mcp=mcp,
                    provider=provider,
                    price_info=price_info,
                )

        return wrapper_factory

    except ModuleNotFoundError:
        raise ValueError(f"Unknown payment flow: {name}")