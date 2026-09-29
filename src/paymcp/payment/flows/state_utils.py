import hashlib
import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def sanitize_state_args(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Remove non-serializable context from args before persistence."""
    if not kwargs:
        return {}

    cleaned = dict(kwargs)
    cleaned.pop("ctx", None)

    nested_args = cleaned.get("args")
    if isinstance(nested_args, dict) and "ctx" in nested_args:
        nested_cleaned = dict(nested_args)
        nested_cleaned.pop("ctx", None)
        cleaned["args"] = nested_cleaned

    return cleaned


# Namespaces for cached results. Flows keyed by a caller-supplied payment id and
# flows keyed by (tool, session) must never be able to address each other's
# entries: the payment id comes from the client, so without this a caller could
# name another flow's state key and be handed its result.
RESULT_NS_PAYMENT = "payment"
RESULT_NS_SESSION = "session"


def _result_key(namespace: str, key: str) -> str:
    return f"paymcp:result:{namespace}:{key}"


def _unfingerprintable() -> str:
    """A call that cannot be described gets a value unique to that call.

    It must not be a constant: a constant would make every such call match
    every other one, and they would be served each other's results.
    """
    return f"unfingerprintable:{uuid.uuid4().hex}"


def call_fingerprint(
    kwargs: Optional[Dict[str, Any]] = None, args: Optional[Any] = None
) -> str:
    """Identify the call a result belongs to.

    Flows keyed by (tool, session) reuse one key across every call the session
    makes to that tool, so a cached result has to be pinned to the arguments it
    was produced for - otherwise the next call, with different arguments, would
    be answered with the previous call's result.

    This runs on every call, including calls that never disconnect, so it never
    raises: an input it cannot describe just fails to match anything.
    """
    payload = {"kwargs": sanitize_state_args(kwargs or {}), "args": list(args or ())}
    try:
        canonical = json.dumps(payload, sort_keys=True, default=repr)
    except Exception:
        try:
            canonical = repr(payload)
        except Exception:
            return _unfingerprintable()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def save_completed_result(
    state_store,
    key: Any,
    result: Any,
    namespace: str,
    tool: str,
    fingerprint: Optional[str] = None,
) -> bool:
    """Persist the result of a paid tool call so a retry can return it.

    Called when the client disconnects after the tool has run: the caller has
    already been charged, so the result must survive until they ask for it
    again. Returns False when there is nothing to store into, or when the store
    cannot hold this result - the caller then keeps its previous behaviour and
    the tool runs again on retry.
    """
    if state_store is None or key is None:
        return False

    payload = {"result": result, "tool": tool, "token": uuid.uuid4().hex}
    if fingerprint is not None:
        payload["fingerprint"] = fingerprint

    try:
        await state_store.set(_result_key(namespace, str(key)), payload)
        return True
    except (TypeError, ValueError):
        # Durable stores persist as JSON; an unserializable result cannot be kept.
        logger.warning(
            "[PayMCP] Tool result for %s cannot be stored and will not be cached; "
            "a retry will execute the tool again.", key
        )
        return False
    except Exception as exc:
        logger.warning("[PayMCP] Failed to cache tool result for %s: %r", key, exc)
        return False


async def peek_completed_result(
    state_store,
    key: Any,
    namespace: str,
    tool: str,
    fingerprint: Optional[str] = None,
) -> Tuple[bool, Any, Optional[str]]:
    """Return (True, result, token) when a completed result is cached for this call.

    The token identifies the stored entry itself, so whoever hands the result
    back can clear exactly what they served and nothing else.

    A payment id identifies a payment, not a tool, and every paid tool reads
    the same namespace - so the tool that produced the result has to match too,
    otherwise one tool would answer with another tool's output.
    """
    if state_store is None or key is None:
        return False, None, None

    try:
        entry = await state_store.get(_result_key(namespace, str(key)))
    except Exception as exc:
        logger.warning("[PayMCP] Failed to read cached tool result for %s: %r", key, exc)
        return False, None, None

    # Only a well-formed entry counts as a cached result: anything else means
    # there is nothing to hand back and the tool still has to run.
    if not isinstance(entry, Mapping):
        return False, None, None

    payload = entry.get("args")
    if not isinstance(payload, Mapping) or "result" not in payload:
        return False, None, None

    if payload.get("tool") != tool:
        logger.debug(
            "[PayMCP] Cached result for %s belongs to another tool; ignoring it.", key
        )
        return False, None, None

    if fingerprint is not None and payload.get("fingerprint") != fingerprint:
        logger.debug(
            "[PayMCP] Cached result for %s belongs to a different call; ignoring it.", key
        )
        return False, None, None

    return True, payload["result"], payload.get("token")


async def clear_completed_result(
    state_store,
    key: Any,
    namespace: str,
    token: Optional[str] = None,
) -> None:
    """Drop the cached result identified by `token`, and only that one.

    Session-keyed flows share one key across every call the session makes to a
    tool, and they hold no lock: between reading a result and clearing it,
    another call can cache its own under the same key - including one for the
    very same arguments. Clearing by key alone would throw away a result
    someone has already paid for, so the entry has to be the same entry.

    The check is read-then-delete, which the stores cannot do atomically: an
    entry written between the two calls is still deleted. That window is one
    round trip, where clearing by key alone left it open across the caller's
    own awaits, but it is narrowed rather than closed.
    """
    if state_store is None or key is None:
        return

    full_key = _result_key(namespace, str(key))

    try:
        entry = await state_store.get(full_key)
        payload = entry.get("args") if isinstance(entry, Mapping) else None
        stored = payload.get("token") if isinstance(payload, Mapping) else None
        if stored != token:
            logger.debug(
                "[PayMCP] Cached result for %s is no longer the one served; keeping it.", key
            )
            return
        await state_store.delete(full_key)
    except Exception as exc:
        logger.warning("[PayMCP] Failed to clear cached tool result for %s: %r", key, exc)


async def discard_spent_state(state_store, key: Any) -> None:
    """Remove state for a payment that has been spent, and carry on if it fails.

    Used only past the point where the caller has been charged - after the paid
    tool has run, or, in the x402 flow, after settlement. A store that cannot
    delete must not turn that into an error: the result would be lost with it,
    and the caller has already paid.

    The cost of carrying on is that the payment record survives, so every call
    until the store expires it runs the tool for free - not only the next one.
    That is still the better of the two outcomes, and worth a warning.
    """
    if state_store is None or key is None:
        return
    try:
        await state_store.delete(key)
    except Exception as exc:
        logger.warning(
            "[PayMCP] Failed to clear spent payment state for %s; a later call may "
            "reuse it: %r", key, exc
        )


async def discard_payment_state(state_store, key: Any, payment_id: Any = None) -> None:
    """Remove a session's payment record, but only the one this call was using.

    Session-keyed flows file every call a session makes to a tool under one
    key, and they hold no lock. A concurrent call can replace the record
    between the moment this one read it and the moment it cleans up, and
    deleting by key alone throws away a payment the caller may already have
    made - leaving them to be asked for a second one.

    `payment_id` is what this call worked with. Passing nothing means the call
    never looked at a payment record, and then there is nothing here it can
    claim to be finished with, so nothing is removed.
    """
    if state_store is None or key is None or payment_id is None:
        return

    try:
        entry = await state_store.get(key)
        # The bundled stores wrap what they were given under "args"; a
        # hand-written one may hand back the payload itself, and `state_store`
        # is an advertised extension point. Accept either rather than silently
        # never matching - which would leave the record behind for ever.
        payload = entry.get("args") if isinstance(entry, Mapping) else None
        if payload is None and isinstance(entry, Mapping) and "args" not in entry:
            # A store that hands back what it was given rather than wrapping it.
            # Only when there is no "args" at all: an envelope that happens to
            # carry a payment_id of its own must not stand in for the payload.
            payload = entry
        current = payload.get("payment_id") if isinstance(payload, Mapping) else None
        if str(current) != str(payment_id):
            logger.debug(
                "[PayMCP] The payment under %s is no longer the one this call used; leaving it.",
                key,
            )
            return
        await state_store.delete(key)
    except Exception as exc:
        logger.warning(
            "[PayMCP] Failed to clear spent payment state for %s; a later call may "
            "reuse it: %r", key, exc
        )
