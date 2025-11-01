import functools
from importlib import import_module

def make_flow(name):
    """
    Factory function to create a payment flow wrapper.

    All flows accept the same signature for consistency:
    - func: The tool function to wrap
    - mcp: MCP server instance
    - provider: Payment provider instance
    - price_info: Price configuration dict
    - state_store: Optional state storage (used by TWO_STEP, ignored by others)

    Returns:
        wrapper_factory function that creates payment-gated tool wrappers
    """
    try:
        mod = import_module(f".{name}", __package__)
        make_paid_wrapper = mod.make_paid_wrapper

        def wrapper_factory(func, mcp, provider, price_info, state_store=None, config=None):
            # All flows have uniform signature - pass all parameters
            return make_paid_wrapper(
                func=func,
                mcp=mcp,
                provider=provider,
                price_info=price_info,
                state_store=state_store,
                config=config,
            )

        return wrapper_factory

    except ModuleNotFoundError:
        raise ValueError(f"Unknown payment flow: {name}")