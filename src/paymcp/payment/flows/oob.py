#waiting for PR #887 of modelcontext protocol - https://github.com/modelcontextprotocol/modelcontextprotocol/pull/887 , https://github.com/modelcontextprotocol/modelcontextprotocol/pull/475


# paymcp/payment/flows/oob.py
import functools
from ...utils.messages import open_link_message
import logging
from ...utils.elicitation import run_elicitation_loop

logger = logging.getLogger(__name__)

def make_paid_wrapper(func, mcp, provider, price_info, state_store=None, config=None):
    """
    Out-of-band payment flow (not yet implemented).

    Note: state_store parameter is accepted for signature consistency
    but not used by OOB flow.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        #ctx = kwargs.get("ctx", None)
        raise RuntimeError("This method is not implemented yet.")

    return wrapper