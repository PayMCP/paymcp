# paymcp/payment/flows/resubmit.py
import functools
from ...utils.messages import open_link_message
import logging

logger = logging.getLogger(__name__)

def make_paid_wrapper(func, mcp, provider, price_info, state_store=None):
    """
    Resubmit payment flow (not yet implemented).

    Note: state_store parameter is accepted for signature consistency
    but not used by RESUBMIT flow.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        #ctx = kwargs.get("ctx", None)
        raise RuntimeError("This method is not implemented yet.")

    return wrapper