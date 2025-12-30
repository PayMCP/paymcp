import base64
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

import requests

from .base import BasePaymentProvider
from ..utils.crypto import generate_cdp_bearer_jwt

DEFAULT_USDC_MULTIPLIER = 1_000_000
DEFAULT_ASSET = "USDC"
DEFAULT_NETWORK = "eip155:8453"
DEFAULT_DOMAIN_NAME = "USD Coin"
DEFAULT_DOMAIN_VERSION = "2"
FACILITATOR_BASE = "https://api.cdp.coinbase.com/platform/v2/x402"

ASSETS_MAP = {
    "eip155:8453:USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "eip155:84532:USDC": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
}

V1_NETWORK_MAP = {
    "eip155:8453": "base",
    "eip155:84532": "base-sepolia",
    "base": "base",
    "base-sepolia": "base-sepolia",
    "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1": "solana-devnet",
    "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "solana-mainnet",
    "solana-devnet": "solana-devnet",
    "solana-mainnet": "solana-mainnet",
}

V2_NETWORK_MAP = {
    "eip155:8453": "eip155:8453",
    "eip155:84532": "eip155:84532",
    "base": "eip155:8453",
    "base-sepolia": "eip155:84532",
    "solana-devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
    "solana-mainnet": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
    "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
    "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
}


class X402Provider(BasePaymentProvider):
    def __init__(
        self,
        pay_to: List[Dict[str, Any]],
        logger: logging.Logger = None,
        resource_info: Optional[Dict[str, Any]] = None,
        facilitator: Optional[Dict[str, Any]] = None,
        x402_version: Optional[int] = None,
        gas_limit: Optional[str] = None,
    ):
        super().__init__(api_key=None, apiKey=None, logger=logger)
        self.pay_to = []
        self.resource_info = resource_info
        self.x402_version = x402_version or 2
        self.facilitator: Dict[str, Any] = {"url": FACILITATOR_BASE}
        self.fee_payer: Optional[str] = None

        for pay in pay_to:
            network = pay.get("network") or DEFAULT_NETWORK
            asset_key = f"{network}:{pay.get('asset') or DEFAULT_ASSET}"
            asset = ASSETS_MAP.get(asset_key, pay.get("asset"))
            norm = {
                "address": pay.get("address"),
                "network": network,
                "asset": asset,
                "multiplier": pay.get("multiplier", DEFAULT_USDC_MULTIPLIER),
                "domainName": pay.get("domainName", DEFAULT_DOMAIN_NAME),
                "domainVersion": pay.get("domainVersion", DEFAULT_DOMAIN_VERSION),
                "gasLimit": pay.get("gasLimit") or gas_limit,
            }
            if network == "eip155:84532" and norm["domainName"] == "USD Coin":
                norm["domainName"] = "USDC"
            self.pay_to.append(norm)

        if facilitator:
            if facilitator.get("url"):
                self.facilitator["url"] = facilitator["url"]
            if facilitator.get("createAuthHeaders"):
                self.facilitator["createAuthHeaders"] = facilitator["createAuthHeaders"]
            elif facilitator.get("apiKeyId") and facilitator.get("apiKeySecret"):
                self.facilitator["apiKeyId"] = facilitator["apiKeyId"]
                self.facilitator["apiKeySecret"] = facilitator["apiKeySecret"]
                self.facilitator["createAuthHeaders"] = self._create_auth_headers_for_cdp

        fee_payer_required = [p for p in self.pay_to if str(p.get("network", "")).startswith("solana")]
        if fee_payer_required:
            self._update_facilitator_fee_payer(fee_payer_required[0]["network"])

        self.logger.debug("[X402Provider] ready")

    def _update_facilitator_fee_payer(self, network: str) -> None:
        headers = {"Content-Type": "application/json"}
        auth_headers = self._create_auth_headers("GET", "/platform/v2/x402/supported")
        if auth_headers:
            headers.update(auth_headers)

        try:
            response = requests.get(f"{self.facilitator['url']}/supported", headers=headers)
        except requests.RequestException as exc:
            self.logger.error("[PayMCP] x402 get facilitator feePayer failed: %s", exc)
            return

        if not response.ok:
            self.logger.error("[PayMCP] x402 get facilitator feePayer failed for: %s", response.text)
            return

        supported_json = response.json()
        mapped_network = (
            V1_NETWORK_MAP.get(network, network)
            if self.x402_version == 1
            else V2_NETWORK_MAP.get(network, network)
        )

        kind = None
        for entry in supported_json.get("kinds", []):
            if (
                entry.get("scheme") == "exact"
                and entry.get("x402Version") == self.x402_version
                and entry.get("network") == mapped_network
                and entry.get("extra", {}).get("feePayer")
            ):
                kind = entry
                break

        if kind:
            self.fee_payer = kind.get("extra", {}).get("feePayer")
            self.logger.debug("[PayMCP] FeePayer for Solana %s", self.fee_payer)

    def _create_auth_headers(self, method: str, path: str) -> Optional[Dict[str, str]]:
        create_auth_headers: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, str]]]] = self.facilitator.get(
            "createAuthHeaders"
        )
        if not create_auth_headers:
            return None
        host = requests.utils.urlparse(self.facilitator["url"]).netloc
        return create_auth_headers({"host": host, "method": method, "path": path})

    def _create_auth_headers_for_cdp(self, opts: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, str]]:
        api_key_id = self.facilitator.get("apiKeyId")
        api_key_secret = self.facilitator.get("apiKeySecret")
        if not api_key_id or not api_key_secret:
            return None
        try:
            token = generate_cdp_bearer_jwt(
                api_key_id=api_key_id,
                api_key_secret=api_key_secret,
                request_host=opts.get("host") if opts else None,
                request_method=opts.get("method") if opts else None,
                request_path=opts.get("path") if opts else None,
            )
            return {"Authorization": f"Bearer {token}"}
        except Exception as exc:
            self.logger.error("[PayMCP] Can't generate CDP token. Proceeding without authentication. %s", exc)
            return None

    def create_payment(self, amount: float, _currency: str, description: str) -> Tuple[str, str, Any]:
        challenge_id = str(uuid4())
        payment_required = (
            self.get_payment_requirements_v1(amount)
            if self.x402_version == 1
            else self.get_payment_requirements_v2(challenge_id, amount, description)
        )
        self.logger.debug("[X402Provider] createPayment %s", challenge_id)
        return challenge_id, "", payment_required

    def get_payment_requirements_v1(self, amount: float) -> Dict[str, Any]:
        accepts = []
        for pay in self.pay_to:
            amount_str = _to_base_units(amount, pay["multiplier"])
            extra = {"name": pay["domainName"], "version": pay["domainVersion"]}
            if self.fee_payer:
                extra["feePayer"] = self.fee_payer
            if pay.get("gasLimit"):
                extra["gasLimit"] = pay["gasLimit"]

            accepts.append(
                {
                    "scheme": "exact",
                    "network": V1_NETWORK_MAP.get(pay["network"], pay["network"]),
                    "asset": pay["asset"],
                    "payTo": pay["address"],
                    "maxTimeoutSeconds": 900,
                    "maxAmountRequired": amount_str,
                    "resource": (self.resource_info or {}).get("url", "https://paymcp.info"),
                    "description": (self.resource_info or {}).get("description", "Premium processing fee"),
                    "mimeType": (self.resource_info or {}).get("mimeType", "application/json"),
                    "extra": extra,
                }
            )

        response = {"x402Version": 1, "accepts": accepts}
        if self.resource_info:
            response["resourceInfo"] = self.resource_info
        return response

    def get_payment_requirements_v2(self, challenge_id: str, amount: float, description: str) -> Dict[str, Any]:
        accepts = []
        for pay in self.pay_to:
            amount_str = _to_base_units(amount, pay["multiplier"])
            extra = {
                "name": pay["domainName"],
                "version": pay["domainVersion"],
                "challengeId": challenge_id,
                "description": description,
            }
            if self.fee_payer:
                extra["feePayer"] = self.fee_payer
            if pay.get("gasLimit"):
                extra["gasLimit"] = pay["gasLimit"]

            accepts.append(
                {
                    "scheme": "exact",
                    "x402Version": self.x402_version,
                    "network": V2_NETWORK_MAP.get(pay["network"], pay["network"]),
                    "amount": amount_str,
                    "asset": pay["asset"],
                    "payTo": pay["address"],
                    "maxTimeoutSeconds": 900,
                    "extra": extra,
                }
            )

        response = {"x402Version": self.x402_version, "error": "Payment required", "accepts": accepts}
        if self.resource_info:
            response["resourceInfo"] = self.resource_info
        return response

    def get_payment_status(self, payment_signature_b64: str) -> str:
        sig = json.loads(base64.b64decode(payment_signature_b64).decode("utf-8"))
        amount_str = (
            sig.get("accepted", {}).get("amount")
            or sig.get("payload", {}).get("authorization", {}).get("value")
            or sig.get("payload", {}).get("authorization", {}).get("amount")
        )
        if not amount_str:
            self.logger.error("[PayMCP] Missing amount in payment signature payload")
            return "error"

        network_str = sig.get("network") if sig.get("x402Version") == 1 else sig.get("accepted", {}).get("network")
        is_solana = isinstance(network_str, str) and network_str.startswith("solana")
        pay_to_address = (
            sig.get("payload", {}).get("authorization", {}).get("to")
            if sig.get("x402Version") == 1
            else (
                sig.get("accepted", {}).get("payTo")
                if is_solana
                else sig.get("payload", {}).get("authorization", {}).get("to")
            )
        )

        chosen_pay_to = None
        for pay in self.pay_to:
            mapped_network = (
                V1_NETWORK_MAP.get(pay["network"], pay["network"])
                if sig.get("x402Version") == 1
                else V2_NETWORK_MAP.get(pay["network"], pay["network"])
            )
            if network_str == mapped_network and pay_to_address == pay["address"]:
                chosen_pay_to = pay
                break

        if not chosen_pay_to:
            self.logger.warning("[X402Provider] getPaymentStatus invalid payTo")
            return "error"

        headers = {"Content-Type": "application/json"}
        auth_headers = self._create_auth_headers("POST", "/platform/v2/x402/verify")
        if auth_headers:
            headers.update(auth_headers)

        payment_requirements_all = (
            self.get_payment_requirements_v1(0).get("accepts")
            if sig.get("x402Version") == 1
            else self.get_payment_requirements_v2(
                sig.get("accepted", {}).get("extra", {}).get("challengeId"),
                0,
                sig.get("accepted", {}).get("extra", {}).get("description"),
            ).get("accepts")
        )
        payment_requirements = None
        for requirement in payment_requirements_all or []:
            mapped_network = (
                V1_NETWORK_MAP.get(requirement.get("network"), requirement.get("network"))
                if sig.get("x402Version") == 1
                else requirement.get("network")
            )
            if network_str == mapped_network:
                payment_requirements = requirement
                break

        if not payment_requirements:
            self.logger.warning("[PayMCP X402Provider] error locating requirements")
            return "error"

        if sig.get("x402Version") == 1:
            payment_requirements["maxAmountRequired"] = amount_str
        else:
            payment_requirements["amount"] = amount_str

        body = {
            "x402Version": sig.get("x402Version"),
            "paymentPayload": sig,
            "paymentRequirements": payment_requirements,
        }

        verify_res = requests.post(
            f"{self.facilitator['url']}/verify",
            headers=headers,
            data=json.dumps(body),
        )
        if not verify_res.ok:
            self.logger.error("[PayMCP] x402 verify failed: %s", verify_res.text)
            return "error"

        verify_json = verify_res.json()
        self.logger.debug("[PayMCP] verify result %s", verify_json)
        if not verify_json.get("isValid"):
            self.logger.error("[PayMCP] x402 verification failed: %s", verify_json.get("invalidReason"))
            return "error"

        auth_headers = self._create_auth_headers("POST", "/platform/v2/x402/settle")
        if auth_headers:
            headers.update(auth_headers)
        settle_res = requests.post(
            f"{self.facilitator['url']}/settle",
            headers=headers,
            data=json.dumps(body),
        )
        if not settle_res.ok:
            self.logger.error("[PayMCP] x402 settle failed: %s", settle_res.text)
            return "error"

        settle_json = settle_res.json()
        self.logger.debug("[PayMCP] settle result %s", settle_json)
        if not settle_json.get("success"):
            self.logger.error("[PayMCP] x402 settle failed: %s", settle_json.get("errorReason"))
            if settle_json.get("errorReason") == "failed_to_execute_transfer":
                self.logger.warning("[PayMCP] Make sure purchaser has enough gas to sign the transaction")
            return "error"

        return "paid"


def _to_base_units(amount: float, multiplier: int) -> str:
    return str(int(round(amount * multiplier)))
