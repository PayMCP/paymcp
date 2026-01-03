from typing import Any, Dict


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
