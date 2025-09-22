# Provider Setup

## Stripe

```python
"stripe": {
    "apiKey": "sk_test_...",
    "successUrl": "https://example.com/success",
    "cancelUrl": "https://example.com/cancel"
}
```

Test card: `4242 4242 4242 4242`

## PayPal

```python
"paypal": {
    "clientId": "...",
    "clientSecret": "...",
    "sandbox": True
}
```

## Walleot

```python
"walleot": {
    "apiKey": "..."
}
```

Best for amounts under $2.

## Square

```python
"square": {
    "accessToken": "...",
    "locationId": "...",
    "environment": "sandbox"
}
```

## Environment Variables

Use `.env` file:
```bash
STRIPE_SECRET_KEY=sk_test_...
PAYPAL_CLIENT_ID=...
WALLEOT_API_KEY=...
```

Load in code:
```python
import os
from dotenv import load_dotenv

load_dotenv()

providers = {
    "stripe": {
        "apiKey": os.getenv("STRIPE_SECRET_KEY")
    }
}
```