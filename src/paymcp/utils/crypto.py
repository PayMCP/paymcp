import base64
import json
import secrets
import time
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_json(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _b64url(raw)


def random_nonce_hex(bytes_len: int = 16) -> str:
    return secrets.token_hex(bytes_len)


def ed25519_key_from_base64_secret(secret_b64: str) -> Ed25519PrivateKey:
    seed = base64.b64decode(secret_b64.strip())
    return Ed25519PrivateKey.from_private_bytes(seed)


def generate_cdp_bearer_jwt(
    *,
    api_key_id: str,
    api_key_secret: str,
    ttl_seconds: Optional[int] = None,
    request_host: Optional[str] = None,
    request_path: Optional[str] = None,
    request_method: Optional[str] = None,
) -> str:
    ttl = min(ttl_seconds or 120, 120)
    now = int(time.time())

    request_host = (request_host or "api.cdp.coinbase.com").replace("https://", "")
    if not request_path:
        raise ValueError(
            "request_path is required (e.g. /platform/v2/x402/verify or /platform/v2/x402/settle)"
        )
    request_method = (request_method or "POST").upper()
    uri_entry = f"{request_method} {request_host}{request_path}"

    header = {
        "alg": "EdDSA",
        "kid": api_key_id,
        "typ": "JWT",
        "nonce": random_nonce_hex(),
    }
    payload = {
        "sub": api_key_id,
        "iss": "cdp",
        "uris": [uri_entry],
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
    }

    signing_input = f"{_b64url_json(header)}.{_b64url_json(payload)}".encode("utf-8")
    key = ed25519_key_from_base64_secret(api_key_secret)
    signature = key.sign(signing_input)
    return f"{signing_input.decode('utf-8')}.{_b64url(signature)}"
