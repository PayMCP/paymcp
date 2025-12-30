from paymcp.providers.x402 import X402Provider


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
