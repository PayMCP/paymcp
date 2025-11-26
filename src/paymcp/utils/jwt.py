import logging
import base64
from typing import Any, Dict, Optional
import json

logger = logging.getLogger(__name__)


def parse_jwt(token: str) -> Optional[Dict[str, Any]]:
    """
    A very simple JWT parser without signature validation.
    Used only to extract the payload (sub / email / username).
    """
    if not token or not isinstance(token, str):
        return None

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        payload_b64 = parts[1]
        # add padding if needed
        padding = "=" * (-len(payload_b64) % 4)
        payload_b64 += padding

        raw = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        logger.warning("Failed to parse JWT", exc_info=True)
        return None