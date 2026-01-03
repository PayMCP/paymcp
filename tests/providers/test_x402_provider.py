import base64
import json

import pytest

from paymcp.providers import x402 as x402_module
from paymcp.providers.x402 import (
    ASSETS_MAP,
    DEFAULT_USDC_MULTIPLIER,
    X402Provider,
)


def test_create_payment_returns_payment_data_v2():
    provider = X402Provider(
        pay_to=[
            {
                "address": "0xabc",
                "network": "eip155:8453",
                "asset": "USDC",
            }
        ]
    )

    payment_id, payment_url, payment_data = provider.create_payment(1.0, "USD", "Test payment")

    assert payment_id
    assert payment_url == ""
    assert payment_data["x402Version"] == 2
    assert payment_data["accepts"][0]["extra"]["challengeId"] == payment_id


def test_create_payment_returns_payment_data_v1():
    provider = X402Provider(
        pay_to=[
            {
                "address": "0xabc",
                "network": "eip155:8453",
                "asset": "USDC",
            }
        ],
        x402_version=1,
    )

    payment_id, payment_url, payment_data = provider.create_payment(1.0, "USD", "Test payment")

    assert payment_id
    assert payment_url == ""
    assert payment_data["x402Version"] == 1
    assert payment_data["accepts"][0]["maxAmountRequired"]


def test_init_normalizes_pay_to_defaults():
    provider = X402Provider(
        pay_to=[{"address": "0xabc"}],
    )
    pay_to = provider.pay_to[0]
    assert pay_to["network"] == "eip155:8453"
    assert pay_to["asset"] == ASSETS_MAP["eip155:8453:USDC"]
    assert pay_to["multiplier"] == DEFAULT_USDC_MULTIPLIER


def test_init_keeps_custom_asset():
    provider = X402Provider(
        pay_to=[{"address": "0xabc", "asset": "MYASSET"}],
    )
    assert provider.pay_to[0]["asset"] == "MYASSET"


def test_init_base_sepolia_domain_name_adjustment():
    provider = X402Provider(
        pay_to=[{"address": "0xabc", "network": "eip155:84532"}],
    )
    assert provider.pay_to[0]["domainName"] == "USDC"


def test_get_payment_requirements_v1_includes_resource_info_and_fee_payer():
    provider = X402Provider(
        pay_to=[{"address": "0xabc", "network": "eip155:8453"}],
        x402_version=1,
        resource_info={"url": "https://example.com", "description": "Paid tool"},
    )
    provider.fee_payer = "fee-payer-1"
    payment_data = provider.get_payment_requirements_v1(1.0)
    accept = payment_data["accepts"][0]
    assert payment_data["x402Version"] == 1
    assert payment_data["resourceInfo"]["url"] == "https://example.com"
    assert accept["extra"]["feePayer"] == "fee-payer-1"


def test_get_payment_requirements_v2_includes_challenge_and_description():
    provider = X402Provider(
        pay_to=[{"address": "0xabc", "network": "eip155:8453"}],
    )
    payment_data = provider.get_payment_requirements_v2("challenge-1", 1.5, "Test")
    accept = payment_data["accepts"][0]
    assert payment_data["x402Version"] == 2
    assert accept["extra"]["challengeId"] == "challenge-1"
    assert accept["extra"]["description"] == "Test"


def test_create_auth_headers_for_cdp(monkeypatch):
    secret = base64.b64encode(b"a" * 32).decode("ascii")

    def fake_generate(**_kwargs):
        return "token-123"

    monkeypatch.setattr(x402_module, "generate_cdp_bearer_jwt", fake_generate)

    provider = X402Provider(
        pay_to=[{"address": "0xabc"}],
        facilitator={"apiKeyId": "id", "apiKeySecret": secret},
    )

    headers = provider._create_auth_headers_for_cdp(
        {"host": "api.cdp.coinbase.com", "method": "POST", "path": "/platform/v2/x402/verify"}
    )
    assert headers == {"Authorization": "Bearer token-123"}


def test_update_facilitator_fee_payer(monkeypatch):
    class DummyResponse:
        ok = True
        text = ""

        def json(self):
            return {
                "kinds": [
                    {
                        "scheme": "exact",
                        "x402Version": 2,
                        "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
                        "extra": {"feePayer": "payer-1"},
                    }
                ]
            }

    monkeypatch.setattr(x402_module.requests, "get", lambda *args, **kwargs: DummyResponse())

    provider = X402Provider(
        pay_to=[{"address": "So1anaAddr", "network": "solana-devnet"}],
        facilitator={"createAuthHeaders": lambda _opts: {"Authorization": "Bearer token"}},
    )

    assert provider.fee_payer == "payer-1"


def _b64_sig(payload):
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


def test_get_payment_status_paid_v2(monkeypatch):
    provider = X402Provider(
        pay_to=[{"address": "0xabc", "network": "eip155:8453", "asset": "USDC"}],
        facilitator={"createAuthHeaders": lambda _opts: {"Authorization": "Bearer token"}},
    )
    sig = {
        "x402Version": 2,
        "accepted": {
            "amount": "100",
            "network": "eip155:8453",
            "asset": "USDC",
            "payTo": "0xabc",
            "extra": {"challengeId": "cid-1", "description": "desc"},
        },
        "payload": {"authorization": {"to": "0xabc", "amount": "100"}},
    }

    class DummyResponse:
        def __init__(self, ok=True, payload=None):
            self.ok = ok
            self._payload = payload or {}
            self.text = "err"

        def json(self):
            return self._payload

    calls = {"verify": 0, "settle": 0}

    def fake_post(url, headers=None, data=None):
        if url.endswith("/verify"):
            calls["verify"] += 1
            return DummyResponse(ok=True, payload={"isValid": True})
        calls["settle"] += 1
        return DummyResponse(ok=True, payload={"success": True})

    monkeypatch.setattr(x402_module.requests, "post", fake_post)

    status = provider.get_payment_status(_b64_sig(sig))
    assert status == "paid"
    assert calls["verify"] == 1
    assert calls["settle"] == 1


def test_get_payment_status_missing_amount_returns_error():
    provider = X402Provider(pay_to=[{"address": "0xabc"}])
    sig = {"x402Version": 2, "accepted": {"network": "eip155:8453"}}
    assert provider.get_payment_status(_b64_sig(sig)) == "error"


def test_get_payment_status_invalid_payto_returns_error():
    provider = X402Provider(pay_to=[{"address": "0xabc", "network": "eip155:8453"}])
    sig = {
        "x402Version": 2,
        "accepted": {
            "amount": "100",
            "network": "eip155:8453",
            "asset": "USDC",
            "payTo": "0xdef",
            "extra": {"challengeId": "cid-1", "description": "desc"},
        },
        "payload": {"authorization": {"to": "0xdef", "amount": "100"}},
    }
    assert provider.get_payment_status(_b64_sig(sig)) == "error"


def test_get_payment_status_verify_failure(monkeypatch):
    provider = X402Provider(pay_to=[{"address": "0xabc", "network": "eip155:8453"}])
    sig = {
        "x402Version": 2,
        "accepted": {
            "amount": "100",
            "network": "eip155:8453",
            "asset": "USDC",
            "payTo": "0xabc",
            "extra": {"challengeId": "cid-1", "description": "desc"},
        },
        "payload": {"authorization": {"to": "0xabc", "amount": "100"}},
    }

    class DummyResponse:
        ok = False
        text = "bad"

        def json(self):
            return {}

    monkeypatch.setattr(x402_module.requests, "post", lambda *args, **kwargs: DummyResponse())

    assert provider.get_payment_status(_b64_sig(sig)) == "error"


def test_get_payment_status_paid_v1(monkeypatch):
    provider = X402Provider(
        pay_to=[{"address": "0xabc", "network": "eip155:8453", "asset": "USDC"}],
        x402_version=1,
    )
    sig = {
        "x402Version": 1,
        "network": "base",
        "payload": {"authorization": {"to": "0xabc", "value": "100"}},
    }

    class DummyResponse:
        def __init__(self, ok=True, payload=None):
            self.ok = ok
            self._payload = payload or {}
            self.text = "err"

        def json(self):
            return self._payload

    def fake_post(url, headers=None, data=None):
        if url.endswith("/verify"):
            return DummyResponse(ok=True, payload={"isValid": True})
        return DummyResponse(ok=True, payload={"success": True})

    monkeypatch.setattr(x402_module.requests, "post", fake_post)

    status = provider.get_payment_status(_b64_sig(sig))
    assert status == "paid"


def test_get_payment_status_settle_failed(monkeypatch):
    provider = X402Provider(
        pay_to=[{"address": "0xabc", "network": "eip155:8453", "asset": "USDC"}],
    )
    sig = {
        "x402Version": 2,
        "accepted": {
            "amount": "100",
            "network": "eip155:8453",
            "asset": "USDC",
            "payTo": "0xabc",
            "extra": {"challengeId": "cid-1", "description": "desc"},
        },
        "payload": {"authorization": {"to": "0xabc", "amount": "100"}},
    }

    class DummyResponse:
        def __init__(self, ok=True, payload=None):
            self.ok = ok
            self._payload = payload or {}
            self.text = "err"

        def json(self):
            return self._payload

    def fake_post(url, headers=None, data=None):
        if url.endswith("/verify"):
            return DummyResponse(ok=True, payload={"isValid": True})
        return DummyResponse(ok=True, payload={"success": False, "errorReason": "failed_to_execute_transfer"})

    monkeypatch.setattr(x402_module.requests, "post", fake_post)

    status = provider.get_payment_status(_b64_sig(sig))
    assert status == "error"
