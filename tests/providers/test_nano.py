import logging
from unittest.mock import Mock, patch

import pytest
import requests

from paymcp.providers import build_providers, PROVIDER_MAP
from paymcp.providers.nano import (
    NanoProvider,
    NONCE_MODULUS,
    RAW_PER_XNO,
    DEFAULT_RPC_URL,
    decode_nano_address,
    encode_nano_address,
)

GENESIS = "nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3"
GENESIS_PUBKEY = "e89208dd038fbb269987689621d52292ae9c35941a7484756ecced92a65093ba"
OTHER = encode_nano_address(bytes(range(32)))
BUYER = encode_nano_address(bytes([7] * 32))
SEND_HASH = "A" * 64
RECV_HASH = "B" * 64


class FakeRpc:
    """Dispatches Nano RPC actions to canned responses."""

    def __init__(self, receivable=None, blocks_info=None, history=None, account=GENESIS):
        self.receivable = receivable or {}
        self.blocks_info = blocks_info or {}
        self.history = history or []
        self.account = account
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload)
        action = payload["action"]
        if action == "receivable":
            return {"blocks": self.receivable or ""}
        if action == "blocks_info":
            return {"blocks": {h: self.blocks_info[h] for h in payload["hashes"] if h in self.blocks_info}}
        if action == "account_history":
            return {"account": self.account, "history": self.history}
        raise AssertionError(f"unexpected action {action}")


def send_block(amount, confirmed="true", destination=GENESIS):
    return {
        "block_account": BUYER,
        "amount": str(amount),
        "subtype": "send",
        "confirmed": confirmed,
        "contents": {"type": "state", "link_as_account": destination},
    }


class TestNanoAddress:
    def test_genesis_address_valid(self):
        assert decode_nano_address(GENESIS).hex() == GENESIS_PUBKEY
        assert encode_nano_address(bytes.fromhex(GENESIS_PUBKEY)) == GENESIS

    def test_xrb_prefix_accepted(self):
        assert decode_nano_address("xrb_" + GENESIS[5:]).hex() == GENESIS_PUBKEY

    def test_bad_checksum_rejected(self):
        bad = GENESIS[:-1] + ("4" if GENESIS[-1] != "4" else "5")
        with pytest.raises(ValueError, match="checksum"):
            decode_nano_address(bad)
        with pytest.raises(ValueError, match="checksum"):
            NanoProvider(address=bad)

    @pytest.mark.parametrize(
        "address",
        [
            "",
            "btc_" + GENESIS[5:],
            GENESIS[:-1],
            GENESIS[:10] + "0" + GENESIS[11:],  # '0' not in alphabet
            GENESIS[:10] + "l" + GENESIS[11:],  # 'l' not in alphabet
            "nano_" + "z" + GENESIS[6:],  # first char must be 1 or 3
        ],
    )
    def test_malformed_rejected(self, address):
        with pytest.raises(ValueError):
            NanoProvider(address=address)

    def test_missing_address_rejected(self):
        with pytest.raises(ValueError, match="address"):
            NanoProvider()


class TestNanoRegistration:
    def test_build_providers_nano(self):
        # Fails on main: "Unknown provider: nano".
        providers = build_providers({"nano": {"address": GENESIS}})
        assert isinstance(providers["nano"], NanoProvider)
        assert PROVIDER_MAP["nano"] is NanoProvider
        assert providers["nano"].rpc_url == DEFAULT_RPC_URL


class TestNanoCreatePayment:
    def test_uri_and_unique_raw_amount(self):
        p = NanoProvider(address=GENESIS)
        pid, uri = p.create_payment(0.1, "XNO", "test")
        raw = int(pid[len("xno-"):])
        assert uri == f"nano:{GENESIS}?amount={raw}"
        price = RAW_PER_XNO // 10
        assert price < raw < price + NONCE_MODULUS
        ids = {p.create_payment(0.1, "XNO", "t")[0] for _ in range(50)}
        assert len(ids) > 45

    def test_no_float_rounding(self):
        p = NanoProvider(address=GENESIS)
        pid, _ = p.create_payment(0.3, "XNO", "t")
        raw = int(pid[4:])
        assert raw // NONCE_MODULUS * NONCE_MODULUS == 3 * RAW_PER_XNO // 10

    def test_fiat_needs_configured_price(self):
        p = NanoProvider(address=GENESIS)
        with pytest.raises(ValueError, match="xno_price"):
            p.create_payment(1.0, "USD", "t")
        p = NanoProvider(address=GENESIS, xno_price={"usd": "2"})
        pid, _ = p.create_payment(1.0, "USD", "t")
        assert int(pid[4:]) // NONCE_MODULUS * NONCE_MODULUS == RAW_PER_XNO // 2

    def test_non_positive_amount_rejected(self):
        with pytest.raises(ValueError):
            NanoProvider(address=GENESIS).create_payment(0, "XNO", "t")


class TestNanoPaymentStatus:
    @pytest.fixture
    def provider(self):
        return NanoProvider(address=GENESIS, rpc_url="http://node.test", logger=Mock(spec=logging.Logger))

    @pytest.fixture
    def raw(self):
        return 2 * RAW_PER_XNO + 123456

    def status(self, provider, raw, rpc):
        provider._rpc = rpc
        return provider.get_payment_status(f"xno-{raw}")

    def test_paid_receivable_confirmed_send(self, provider, raw):
        rpc = FakeRpc(
            receivable={SEND_HASH: {"amount": str(raw), "source": BUYER}},
            blocks_info={SEND_HASH: send_block(raw)},
        )
        assert self.status(provider, raw, rpc) == "paid"
        assert rpc.calls[0]["account"] == GENESIS
        assert rpc.calls[0]["threshold"] == str(raw)

    def test_paid_already_received(self, provider, raw):
        rpc = FakeRpc(history=[
            {"type": "receive", "account": BUYER, "amount": str(raw), "hash": RECV_HASH, "confirmed": "true"},
        ])
        assert self.status(provider, raw, rpc) == "paid"

    def test_overpaid_in_high_digits_is_paid(self, provider, raw):
        amount = raw + 5 * RAW_PER_XNO
        rpc = FakeRpc(
            receivable={SEND_HASH: {"amount": str(amount), "source": BUYER}},
            blocks_info={SEND_HASH: send_block(amount)},
        )
        assert self.status(provider, raw, rpc) == "paid"

    def test_underpaid(self, provider, raw):
        low = raw - NONCE_MODULUS  # same nonce digits, one step short
        rpc = FakeRpc(
            receivable={SEND_HASH: {"amount": str(low), "source": BUYER}},
            blocks_info={SEND_HASH: send_block(low)},
            history=[{"type": "receive", "amount": str(low), "hash": RECV_HASH, "confirmed": "true"}],
        )
        assert self.status(provider, raw, rpc) == "pending"

    def test_other_payment_nonce_not_counted(self, provider, raw):
        other = raw + 1
        rpc = FakeRpc(
            receivable={SEND_HASH: {"amount": str(other), "source": BUYER}},
            blocks_info={SEND_HASH: send_block(other)},
        )
        assert self.status(provider, raw, rpc) == "pending"

    def test_unconfirmed_send(self, provider, raw):
        rpc = FakeRpc(
            receivable={SEND_HASH: {"amount": str(raw), "source": BUYER}},
            blocks_info={SEND_HASH: send_block(raw, confirmed="false")},
            history=[{"type": "receive", "amount": str(raw), "hash": RECV_HASH, "confirmed": "false"}],
        )
        assert self.status(provider, raw, rpc) == "pending"

    def test_wrong_destination(self, provider, raw):
        rpc = FakeRpc(
            receivable={SEND_HASH: {"amount": str(raw), "source": BUYER}},
            blocks_info={SEND_HASH: send_block(raw, destination=OTHER)},
        )
        assert self.status(provider, raw, rpc) == "pending"

    def test_history_of_other_account_ignored(self, provider, raw):
        rpc = FakeRpc(
            account=OTHER,
            history=[{"type": "receive", "amount": str(raw), "hash": RECV_HASH, "confirmed": "true"}],
        )
        assert self.status(provider, raw, rpc) == "pending"

    def test_send_in_history_not_counted(self, provider, raw):
        rpc = FakeRpc(history=[{"type": "send", "amount": str(raw), "hash": RECV_HASH, "confirmed": "true"}])
        assert self.status(provider, raw, rpc) == "pending"

    def test_nothing_received(self, provider, raw):
        assert self.status(provider, raw, FakeRpc()) == "pending"

    def test_bad_payment_id(self, provider):
        with pytest.raises(ValueError):
            provider.get_payment_status("pi_123")


class TestNanoRpcTransport:
    def test_posts_json_to_injected_url(self):
        p = NanoProvider(address=GENESIS, rpc_url="http://node.test", api_key="k")
        resp = Mock()
        resp.json.return_value = {"blocks": ""}
        resp.raise_for_status.return_value = None
        with patch("paymcp.providers.nano.requests.post", return_value=resp) as post:
            assert p._rpc({"action": "receivable"}) == {"blocks": ""}
        args, kwargs = post.call_args
        assert args[0] == "http://node.test"
        assert kwargs["json"] == {"action": "receivable"}
        assert kwargs["headers"]["Authorization"] == "Bearer k"

    def test_rpc_error_field_raises(self):
        p = NanoProvider(address=GENESIS)
        resp = Mock()
        resp.json.return_value = {"error": "Account not found"}
        with patch("paymcp.providers.nano.requests.post", return_value=resp):
            with pytest.raises(RuntimeError, match="Account not found"):
                p._rpc({"action": "account_history"})

    def test_network_error_raises(self):
        p = NanoProvider(address=GENESIS)
        with patch("paymcp.providers.nano.requests.post", side_effect=requests.exceptions.ConnectionError("down")):
            with pytest.raises(RuntimeError, match="Nano RPC error"):
                p._rpc({"action": "receivable"})

    def test_end_to_end_with_mocked_http(self):
        p = NanoProvider(address=GENESIS, rpc_url="http://node.test")
        pid, _ = p.create_payment(1, "XNO", "t")
        raw = int(pid[4:])
        fake = FakeRpc(
            receivable={SEND_HASH: {"amount": str(raw), "source": BUYER}},
            blocks_info={SEND_HASH: send_block(raw)},
        )

        def post(url, json=None, headers=None, timeout=None):
            r = Mock()
            r.raise_for_status.return_value = None
            r.json.return_value = fake(json)
            return r

        with patch("paymcp.providers.nano.requests.post", side_effect=post):
            assert p.get_payment_status(pid) == "paid"
