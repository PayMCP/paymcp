# Provider Setup

## Stripe

```python
"stripe": {
    "apiKey": "sk_test_...",
    "success_url": "https://example.com/success?session_id={CHECKOUT_SESSION_ID}",
    "cancel_url": "https://example.com/cancel"
}
```

**Configuration:**
- `apiKey`: Stripe secret key (required)
- `success_url`: URL to redirect after successful payment (optional)
- `cancel_url`: URL to redirect after cancelled payment (optional)

**Test card:** `4242 4242 4242 4242`

## PayPal

```python
"paypal": {
    "client_id": "...",
    "client_secret": "...",
    "sandbox": True,
    "success_url": "https://example.com/success",
    "cancel_url": "https://example.com/cancel"
}
```

**Configuration:**
- `client_id`: PayPal client ID (required)
- `client_secret`: PayPal client secret (required)
- `sandbox`: Use sandbox environment (default: True)
- `success_url`: Success redirect URL (optional)
- `cancel_url`: Cancel redirect URL (optional)

## Walleot

```python
"walleot": {
    "apiKey": "..."
}
```

**Configuration:**
- `apiKey`: Walleot API key (required)

**Best for:** Micro-payments and amounts under $2.

## Adyen

```python
"adyen": {
    "apiKey": "...",
    "merchant_account": "...",
    "return_url": "https://example.com/return",
    "sandbox": True
}
```

**Configuration:**
- `apiKey`: Adyen API key (required)
- `merchant_account`: Adyen merchant account (required)
- `return_url`: Return URL after payment (optional)
- `sandbox`: Use test environment (default: False)

## Square

```python
"square": {
    "access_token": "...",
    "location_id": "...",
    "environment": "sandbox"
}
```

**Configuration:**
- `access_token`: Square access token (required)
- `location_id`: Square location ID (required)
- `environment`: "sandbox" or "production" (default: "sandbox")

## Coinbase

```python
"coinbase": {
    "apiKey": "..."
}
```

**Configuration:**
- `apiKey`: Coinbase Commerce API key (required)

## Environment Variables

Use `.env` file for secure configuration:
```bash
STRIPE_SECRET_KEY=sk_test_...
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
WALLEOT_API_KEY=...
ADYEN_API_KEY=...
SQUARE_ACCESS_TOKEN=...
COINBASE_API_KEY=...
```

Load in code:
```python
import os
from dotenv import load_dotenv

load_dotenv()

providers = {
    "stripe": {
        "apiKey": os.getenv("STRIPE_SECRET_KEY")
    },
    "paypal": {
        "client_id": os.getenv("PAYPAL_CLIENT_ID"),
        "client_secret": os.getenv("PAYPAL_CLIENT_SECRET"),
        "sandbox": True
    },
    "walleot": {
        "apiKey": os.getenv("WALLEOT_API_KEY")
    }
}
```

## Multiple Providers

You can configure multiple providers and PayMCP will use the first one:

```python
providers = {
    "stripe": {"apiKey": "sk_test_..."},
    "walleot": {"apiKey": "..."}  # Fallback
}
```

## Provider Selection

Currently, PayMCP uses the first configured provider. Future versions will support:
- Provider selection per tool
- Automatic provider selection based on amount
- Customer preference