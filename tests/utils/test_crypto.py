import base64
import json

import pytest

from paymcp.utils.crypto import (
    ed25519_key_from_base64_secret,
    generate_cdp_bearer_jwt,
)


def _b64decode_segment(segment: str) -> dict:
    padding = "=" * (-len(segment) % 4)
    raw = base64.urlsafe_b64decode(segment + padding)
    return json.loads(raw.decode("utf-8"))


def test_generate_cdp_bearer_jwt_builds_token():
    secret = base64.b64encode(b"a" * 32).decode("ascii")
    token = generate_cdp_bearer_jwt(
        api_key_id="kid-1",
        api_key_secret=secret,
        request_host="api.cdp.coinbase.com",
        request_path="/platform/v2/x402/verify",
        request_method="POST",
    )
    header_b64, payload_b64, signature_b64 = token.split(".")
    header = _b64decode_segment(header_b64)
    payload = _b64decode_segment(payload_b64)

    assert header["kid"] == "kid-1"
    assert header["alg"] == "EdDSA"
    assert "nonce" in header
    assert payload["sub"] == "kid-1"
    assert payload["uris"] == ["POST api.cdp.coinbase.com/platform/v2/x402/verify"]
    assert payload["exp"] >= payload["iat"]
    assert signature_b64


def test_generate_cdp_bearer_jwt_requires_request_path():
    secret = base64.b64encode(b"a" * 32).decode("ascii")
    with pytest.raises(ValueError, match="request_path is required"):
        generate_cdp_bearer_jwt(
            api_key_id="kid-1",
            api_key_secret=secret,
        )


def test_ed25519_key_from_base64_secret_accepts_64_bytes():
    secret = base64.b64encode(b"b" * 64).decode("ascii")
    key = ed25519_key_from_base64_secret(secret)
    assert key is not None


def test_ed25519_key_from_base64_secret_rejects_invalid_length():
    secret = base64.b64encode(b"short").decode("ascii")
    with pytest.raises(ValueError, match="must decode to 32 bytes"):
        ed25519_key_from_base64_secret(secret)
