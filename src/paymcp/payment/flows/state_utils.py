import hashlib
import json
import logging
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


def call_fingerprint(kwargs: Optional[Dict[str, Any]]) -> str:
    """Identify the call a result belongs to.

    Flows keyed by (tool, session) reuse one key across every call the session
    makes to that tool, so a cached result has to be pinned to the arguments it
    was produced for - otherwise the next call, with different arguments, would
    be answered with the previous call's result.
    """
    try:
        canonical = json.dumps(
            sanitize_state_args(kwargs or {}), sort_keys=True, default=repr
        )
    except Exception:
        canonical = repr(sorted((kwargs or {}).items(), key=lambda kv: kv[0]))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def save_completed_result(
    state_store,
    key: Any,
    result: Any,
    namespace: str,
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

    payload = {"result": result}
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
    except Exception:
        logger.exception("[PayMCP] Failed to cache tool result for %s", key)
        return False


async def peek_completed_result(
    state_store,
    key: Any,
    namespace: str,
    fingerprint: Optional[str] = None,
) -> Tuple[bool, Any]:
    """Return (True, result) when a completed result is cached for this call."""
    if state_store is None or key is None:
        return False, None

    try:
        entry = await state_store.get(_result_key(namespace, str(key)))
    except Exception:
        logger.exception("[PayMCP] Failed to read cached tool result for %s", key)
        return False, None

    # Only a well-formed entry counts as a cached result: anything else means
    # there is nothing to hand back and the tool still has to run.
    if not isinstance(entry, Mapping):
        return False, None

    payload = entry.get("args")
    if not isinstance(payload, Mapping) or "result" not in payload:
        return False, None

    if fingerprint is not None and payload.get("fingerprint") != fingerprint:
        logger.debug(
            "[PayMCP] Cached result for %s belongs to a different call; ignoring it.", key
        )
        return False, None

    return True, payload["result"]


async def clear_completed_result(state_store, key: Any, namespace: str) -> None:
    """Drop a cached result."""
    if state_store is None or key is None:
        return
    try:
        await state_store.delete(_result_key(namespace, str(key)))
    except Exception:
        logger.exception("[PayMCP] Failed to clear cached tool result for %s", key)
