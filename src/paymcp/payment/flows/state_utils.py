import json
import logging
from collections.abc import Mapping
from typing import Any, Dict, Tuple

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


RESULT_KEY_SUFFIX = ":result"


def result_state_key(key: str) -> str:
    """State key holding the result of an already-executed paid tool call."""
    return f"{key}{RESULT_KEY_SUFFIX}"


def _is_persistable(result: Any) -> bool:
    """Results are persisted as JSON, so non-JSON results cannot be cached."""
    try:
        json.dumps(result)
        return True
    except (TypeError, ValueError):
        return False


async def save_completed_result(state_store, key: Any, result: Any) -> bool:
    """Persist the result of a paid tool call so a retry can return it.

    Called when the client disconnects after the tool has run: the caller has
    already been charged, so the result must survive until they ask for it
    again. Returns False when there is nothing to store into, or when the
    result is not JSON-serializable - the caller then keeps its previous
    behaviour and the tool runs again on retry.
    """
    if state_store is None or key is None:
        return False

    if not _is_persistable(result):
        logger.warning(
            "[PayMCP] Tool result for %s is not JSON-serializable and cannot be "
            "cached; a retry will execute the tool again.", key
        )
        return False

    try:
        await state_store.set(result_state_key(str(key)), {"result": result})
        return True
    except Exception:
        logger.exception("[PayMCP] Failed to cache tool result for %s", key)
        return False


async def peek_completed_result(state_store, key: Any) -> Tuple[bool, Any]:
    """Return (True, result) when a completed result is cached for this key."""
    if state_store is None or key is None:
        return False, None

    try:
        entry = await state_store.get(result_state_key(str(key)))
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

    return True, payload["result"]


async def clear_completed_result(state_store, key: Any) -> None:
    """Drop a cached result once it has been handed back to the caller."""
    if state_store is None or key is None:
        return
    try:
        await state_store.delete(result_state_key(str(key)))
    except Exception:
        logger.exception("[PayMCP] Failed to clear cached tool result for %s", key)
