# paymcp/payment/flows/x402.py
import base64
import functools
import json
import logging
from typing import Any, Dict, Optional
from ...utils.context import get_ctx_from_server, capture_client_from_ctx



logger = logging.getLogger(__name__)


def _get_headers(ctx: Any) -> Dict[str, str]:
    """Return HTTP headers as a plain dict.

    Works with Starlette `Headers` (mapping-like) and plain dict.
    """
    request_context = getattr(ctx, "request_context", None) if ctx is not None else None
    req = getattr(request_context, "request", None) if request_context is not None else None
    headers = getattr(req, "headers", None) if req is not None else None

    if headers is None:
        return {}

    if isinstance(headers, dict):
        # Ensure string keys/values
        return {str(k): str(v) for k, v in headers.items()}

    # Starlette Headers / mapping-like
    try:
        return {str(k): str(v) for k, v in dict(headers).items()}
    except Exception:
        pass

    get = getattr(headers, "get", None)
    if callable(get):
        # Best-effort fall back to mapping interface
        try:
            return {str(k): str(headers.get(k)) for k in headers.keys()}  # type: ignore[attr-defined]
        except Exception:
            return {}

    return {}


def _get_meta(ctx: Any) -> Dict[str, Any]:
    """Return request meta as a dict.

    In FastMCP, meta typically lives on `ctx.request_context.meta` and is often a
    Pydantic model (so it's not a plain dict).
    """
    request_context = getattr(ctx, "request_context", None) if ctx is not None else None
    meta = getattr(request_context, "meta", None) if request_context is not None else None

    if meta is None:
        # Fallbacks for other runtimes
        meta = getattr(ctx, "meta", None) if ctx is not None else None

    if meta is None:
        return {}

    if isinstance(meta, dict):
        return meta

    # Pydantic v2
    dump = getattr(meta, "model_dump", None)
    if callable(dump):
        try:
            data = dump()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # Pydantic v1
    dump = getattr(meta, "dict", None)
    if callable(dump):
        try:
            data = dump()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # Generic object
    try:
        return vars(meta)
    except Exception:
        return {}


def _get_header(headers: Any, name: str) -> Optional[str]:
    if not headers:
        return None
    if isinstance(headers, dict):
        return headers.get(name) or headers.get(name.lower()) or headers.get(name.upper())
    try:
        return headers.get(name)
    except Exception:
        return None


def _get_payment_fields_for_v1(sig: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "amount": sig.get("payload", {}).get("authorization", {}).get("value"),
        "network": sig.get("network"),
        "payTo": sig.get("payload", {}).get("authorization", {}).get("to"),
    }


def make_paid_wrapper(func, mcp, providers, price_info, state_store=None, config=None):
    """
    x402 RESUBMIT flow.
    """
    provider = next(iter(providers.values()), None)
    if provider is None:
        raise RuntimeError("[PayMCP] No payment provider configured")

    if state_store is None:
        raise RuntimeError(
            f"StateStore is required for RESUBMIT x402 flow but not provided for tool {func.__name__}"
        )

    if not price_info or "price" not in price_info:
        raise RuntimeError(f"Invalid price info for tool {func.__name__}")

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        ctx = kwargs.get("ctx", None)
        if ctx is None and mcp is not None:
            try:
                ctx = get_ctx_from_server(mcp)
            except Exception:
                ctx = None

        log = getattr(provider, "logger", logger)
        log.debug(
            "[PayMCP:x402] wrapper invoked for tool=%s argsLen=%d",
            func.__name__,
            len(args) + len(kwargs),
        )

        headers = _get_headers(ctx)
        payment_sig_b64 = _get_header(headers, "payment-signature") or _get_header(headers, "x-payment")

        if not payment_sig_b64:
            meta = _get_meta(ctx)
            meta_payment = meta.get("x402/payment")
            if meta_payment is not None:
                payment_sig_b64 = base64.b64encode(
                    json.dumps(meta_payment).encode("utf-8")
                ).decode("utf-8")

        client_info = capture_client_from_ctx(ctx)
        session_id = client_info.get("sessionId")

        if not payment_sig_b64:
            payment_result = provider.create_payment(
                amount=price_info["price"],
                currency=price_info["currency"],
                description=f"{func.__name__}() execution fee",
            )
            payment_id, _, payment_data = (
                payment_result[0],
                payment_result[1],
                payment_result[2] if len(payment_result) > 2 else None,
            )

            if not payment_data:
                raise RuntimeError("Payment provider did not return payment requirements")

            challenge_id = ""
            if payment_data.get("x402Version") == 1:
                if not session_id:
                    raise RuntimeError("Session ID is not found")
                challenge_id = f"{session_id}-{func.__name__}"
            else:
                accepts = payment_data.get("accepts") or []
                if accepts:
                    challenge_id = accepts[0].get("extra", {}).get("challengeId", "")

            if not challenge_id:
                raise RuntimeError("Payment provider did not return challengeId in payment requirements")

            await state_store.set(str(challenge_id), {"paymentData": payment_data})

            #according to x402 github - payment request can be sent in JSON-RPC response as
            # {
            # "jsonrpc": "2.0",
            # "id": REQ_ID,
            # "error": {
            #   "code": 402,
            #   "message": "Payment required",
            #   "data": ...
            # }
            #  https://github.com/coinbase/x402/blob/main/specs/transports-v2/mcp.md


            return {"error": {"message": "Payment required", "code": 402, "data": payment_data}}


        sig = json.loads(base64.b64decode(payment_sig_b64).decode("utf-8"))

        challenge_id = sig.get("accepted", {}).get("extra", {}).get("challengeId") or (
            f"{session_id}-{func.__name__}" if session_id else ""
        )

        stored = await state_store.get(str(challenge_id)) if challenge_id else None
        stored_args = stored.get("args") if stored else None
        payment_data = stored_args.get("paymentData") if isinstance(stored_args, dict) else None
        if not payment_data:
            raise RuntimeError("Unknown challenge ID")

        x402v = sig.get("x402Version")
        network_str = sig.get("network") if x402v == 1 else sig.get("accepted", {}).get("network")
        is_solana = isinstance(network_str, str) and network_str.startswith("solana")
        pay_to_address = (
            sig.get("payload", {}).get("authorization", {}).get("to")
            if x402v == 1
            else (
                sig.get("accepted", {}).get("payTo")
                if is_solana
                else sig.get("payload", {}).get("authorization", {}).get("to")
            )
        )

        def norm_addr(value: Any) -> str:
            return value.lower() if isinstance(value, str) else ""

        expected = None
        for pt in payment_data.get("accepts", []):
            if pt.get("network") == network_str and norm_addr(pt.get("payTo")) == norm_addr(pay_to_address):
                expected = pt
                break

        if not expected:
            log.debug("[PayMCP] %s %s %s", payment_data.get("accepts"), network_str, pay_to_address)
            raise RuntimeError("Cannot locate accepted payment mehtod")

        got = _get_payment_fields_for_v1(sig) if x402v == 1 else sig.get("accepted")
        if not expected or not got:
            raise RuntimeError("Invalid payment data for signature verification")

        mismatch = []
        if str(expected.get("amount") or expected.get("maxAmountRequired")) != str(got.get("amount")):
            mismatch.append("amount")
        if str(expected.get("network")) != str(got.get("network")):
            mismatch.append("network")
        if x402v != 1 and norm_addr(expected.get("asset")) != norm_addr(got.get("asset")):
            mismatch.append("asset")
        if norm_addr(expected.get("payTo")) != norm_addr(got.get("payTo")):
            mismatch.append("payTo")
        if x402v != 1 and str(expected.get("extra", {}).get("challengeId")) != str(
            got.get("extra", {}).get("challengeId")
        ):
            mismatch.append("challengeId")

        if mismatch:
            log.warning("[PayMCP] Incorrect signature %s", {"mismatch": mismatch, "expected": expected, "got": got})
            raise RuntimeError("Incorrect signature")

        payment_status = provider.get_payment_status(payment_sig_b64)
        if payment_status == "error":
            await state_store.delete(str(challenge_id))
            raise RuntimeError("Payment failed")

        if payment_status == "paid":
            await state_store.delete(str(challenge_id))
            return await func(*args, **kwargs)

        raise RuntimeError(
            "Payment is not confirmed yet.\nAsk user to complete payment and retry.\n"
            f"Payment ID: {challenge_id}"
        )

    return wrapper
