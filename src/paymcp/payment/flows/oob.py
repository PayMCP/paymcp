# waiting for PR #887 of modelcontext protocol - https://github.com/modelcontextprotocol/modelcontextprotocol/pull/887 , https://github.com/modelcontextprotocol/modelcontextprotocol/pull/475


# paymcp/payment/flows/oob.py
import functools
from ...utils.messages import open_link_message
import logging
from ...utils.elicitation import run_elicitation_loop

logger = logging.getLogger(__name__)


def make_paid_wrapper(func, mcp, provider, price_info):

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # ctx = kwargs.get("ctx", None)
        raise RuntimeError("This method is not implemented yet.")

    return wrapper
