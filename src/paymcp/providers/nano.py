"""Nano (XNO) payment provider.

Payments go straight to the seller's own Nano account. The provider holds no
private key and never sends funds: it only hands out a ``nano:`` payment URI
with a unique raw amount and then watches the seller's account through a Nano
node RPC until a confirmed send of at least that amount has arrived.
"""

import hashlib
import logging
import secrets
from decimal import Decimal, ROUND_CEILING, InvalidOperation
from typing import Dict, Optional, Tuple

import requests

from .base import BasePaymentProvider

DEFAULT_RPC_URL = "https://rpc.nano.to"

# 1 XNO = 10^30 raw
RAW_PER_XNO = 10 ** 30

NANO_ALPHABET = "13456789abcdefghijkmnopqrstuwxyz"
_ALPHABET_INDEX = {c: i for i, c in enumerate(NANO_ALPHABET)}

# Low-order raw digits reserved for the per-payment nonce. 10^6 raw is
# 10^-24 XNO, far below anything a buyer would notice.
NONCE_MODULUS = 10 ** 6

PAYMENT_ID_PREFIX = "xno-"


def _b32decode(chars: str) -> int:
    value = 0
    for c in chars:
        if c not in _ALPHABET_INDEX:
            raise ValueError(f"Invalid character in Nano address: {c!r}")
        value = (value << 5) | _ALPHABET_INDEX[c]
    return value


def _b32encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(NANO_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def nano_address_checksum(public_key: bytes) -> bytes:
    """5-byte blake2b checksum, byte-reversed, as used in Nano addresses."""
    return hashlib.blake2b(public_key, digest_size=5).digest()[::-1]


def decode_nano_address(address: str) -> bytes:
    """Return the 32-byte public key of a ``nano_``/``xrb_`` address.

    Raises ValueError if the address is malformed or its checksum is wrong.
    """
    if not isinstance(address, str):
        raise ValueError("Nano address must be a string")
    address = address.strip()
    if address.startswith("nano_"):
        body = address[len("nano_"):]
    elif address.startswith("xrb_"):
        body = address[len("xrb_"):]
    else:
        raise ValueError("Nano address must start with 'nano_' or 'xrb_'")
    if len(body) != 60:
        raise ValueError("Nano address must have 60 characters after the prefix")
    if body[0] not in ("1", "3"):
        raise ValueError("Invalid Nano address")

    key_int = _b32decode(body[:52])  # 4 zero pad bits + 256-bit key
    if key_int >> 256:
        raise ValueError("Invalid Nano address")
    public_key = key_int.to_bytes(32, "big")

    checksum = _b32decode(body[52:]).to_bytes(5, "big")
    if checksum != nano_address_checksum(public_key):
        raise ValueError("Invalid Nano address checksum")
    return public_key


def encode_nano_address(public_key: bytes) -> str:
    """Return the canonical ``nano_`` address for a 32-byte public key."""
    if len(public_key) != 32:
        raise ValueError("Nano public key must be 32 bytes")
    key_part = _b32encode(int.from_bytes(public_key, "big"), 52)
    check_part = _b32encode(int.from_bytes(nano_address_checksum(public_key), "big"), 8)
    return f"nano_{key_part}{check_part}"


def _same_account(a: Optional[str], public_key: bytes) -> bool:
    try:
        return decode_nano_address(a) == public_key
    except ValueError:
        return False


def _to_int(value) -> Optional[int]:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class NanoProvider(BasePaymentProvider):
    """Accept Nano (XNO) payments directly to the seller's own account.

    Args:
        address: the seller's checksummed ``nano_`` address that receives funds.
        rpc_url: Nano node RPC endpoint used to watch the account.
        api_key: optional RPC key, sent as a Bearer token if set.
        xno_price: optional fixed prices of 1 XNO in other currencies,
            e.g. ``{"USD": "1.10"}``, used when a tool is priced in something
            other than XNO. There is no price oracle; the seller sets these.
        history_count: how many recent entries of the account to inspect.
    """

    def __init__(
        self,
        address: str = None,
        rpc_url: str = DEFAULT_RPC_URL,
        api_key: str = None,
        apiKey: str = None,
        xno_price: Optional[Dict[str, str]] = None,
        history_count: int = 100,
        timeout: float = 15,
        logger: logging.Logger = None,
    ):
        super().__init__(api_key, apiKey, logger=logger)
        if not address:
            raise ValueError("NanoProvider requires the seller's 'address'")
        self.public_key = decode_nano_address(address)
        self.address = encode_nano_address(self.public_key)
        self.rpc_url = rpc_url
        self.xno_price = {k.upper(): Decimal(str(v)) for k, v in (xno_price or {}).items()}
        self.history_count = int(history_count)
        self.timeout = timeout
        self.logger.debug("Nano provider ready")

    # ------------------------------------------------------------------ RPC
    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _rpc(self, payload: dict) -> dict:
        try:
            resp = requests.post(
                self.rpc_url, json=payload, headers=self._build_headers(), timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Nano RPC request failed: {e}")
            raise RuntimeError(f"Nano RPC error: {e}") from e
        except ValueError as e:
            raise RuntimeError(f"Nano RPC returned invalid JSON: {e}") from e
        if not isinstance(data, dict):
            raise RuntimeError("Nano RPC returned an unexpected response")
        if data.get("error"):
            raise RuntimeError(f"Nano RPC error: {data['error']}")
        return data

    # -------------------------------------------------------------- amounts
    def _to_raw(self, amount, currency: str) -> int:
        try:
            value = Decimal(str(amount))
        except InvalidOperation as e:
            raise ValueError(f"Invalid amount: {amount!r}") from e
        if value <= 0:
            raise ValueError("Amount must be positive")
        cur = (currency or "XNO").upper()
        if cur not in ("XNO", "NANO"):
            rate = self.xno_price.get(cur)
            if not rate or rate <= 0:
                raise ValueError(
                    f"NanoProvider cannot price in {cur}; set xno_price={{'{cur}': ...}} "
                    f"or price the tool in XNO"
                )
            value = value / rate
        return int((value * RAW_PER_XNO).to_integral_value(rounding=ROUND_CEILING))

    @staticmethod
    def _parse_payment_id(payment_id: str) -> int:
        if not isinstance(payment_id, str) or not payment_id.startswith(PAYMENT_ID_PREFIX):
            raise ValueError(f"Not a Nano payment id: {payment_id!r}")
        raw = _to_int(payment_id[len(PAYMENT_ID_PREFIX):])
        if raw is None or raw <= 0:
            raise ValueError(f"Not a Nano payment id: {payment_id!r}")
        return raw

    @staticmethod
    def _amount_matches(amount: Optional[int], raw: int) -> bool:
        return amount is not None and amount >= raw and amount % NONCE_MODULUS == raw % NONCE_MODULUS

    # ------------------------------------------------------------ interface
    def create_payment(self, amount: float, currency: str, description: str) -> Tuple[str, str]:
        """Return (payment_id, ``nano:<address>?amount=<raw>``).

        The raw amount is rounded up to the nonce boundary and a random nonce
        is added in its lowest digits, so concurrent payments of the same
        price are told apart on chain. The payment id carries the raw amount,
        so status checks need no server-side state.
        """
        price_raw = self._to_raw(amount, currency)
        base = -(-price_raw // NONCE_MODULUS) * NONCE_MODULUS
        raw = base + secrets.randbelow(NONCE_MODULUS - 1) + 1
        payment_id = f"{PAYMENT_ID_PREFIX}{raw}"
        uri = f"nano:{self.address}?amount={raw}"
        self.logger.debug(f"Created Nano payment {payment_id} for '{description}'")
        return payment_id, uri

    def get_payment_status(self, payment_id: str) -> str:
        """Return 'paid' once a confirmed send of the amount reached the seller, else 'pending'."""
        raw = self._parse_payment_id(payment_id)

        # 1) Sends to us not yet pocketed (receivable). Verify each candidate
        #    block ourselves: confirmed, a send, addressed to the seller.
        receivable = self._rpc({
            "action": "receivable",
            "account": self.address,
            "count": str(self.history_count),
            "threshold": str(raw),
            "source": "true",
            "include_only_confirmed": "true",
        })
        blocks = receivable.get("blocks") or {}
        candidates = []
        if isinstance(blocks, dict):
            for block_hash, info in blocks.items():
                amount = _to_int(info.get("amount") if isinstance(info, dict) else info)
                if self._amount_matches(amount, raw):
                    candidates.append(block_hash)
        if candidates:
            info = self._rpc({"action": "blocks_info", "hashes": candidates, "json_block": "true"})
            for block_hash, block in (info.get("blocks") or {}).items():
                if not isinstance(block, dict):
                    continue
                contents = block.get("contents") or {}
                if (
                    str(block.get("confirmed")).lower() == "true"
                    and block.get("subtype") == "send"
                    and _same_account(contents.get("link_as_account"), self.public_key)
                    and self._amount_matches(_to_int(block.get("amount")), raw)
                ):
                    self.logger.debug(f"Nano payment {payment_id} paid by send {block_hash}")
                    return "paid"

        # 2) Sends already pocketed: confirmed receive blocks on our own chain.
        history = self._rpc({
            "action": "account_history",
            "account": self.address,
            "count": str(self.history_count),
        })
        if _same_account(history.get("account"), self.public_key):
            for entry in history.get("history") or []:
                if (
                    isinstance(entry, dict)
                    and entry.get("type") == "receive"
                    and str(entry.get("confirmed")).lower() == "true"
                    and self._amount_matches(_to_int(entry.get("amount")), raw)
                ):
                    self.logger.debug(f"Nano payment {payment_id} paid (received {entry.get('hash')})")
                    return "paid"

        return "pending"
