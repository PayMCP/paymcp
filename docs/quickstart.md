# Quick Start

## Install

```bash
pip install paymcp mcp
```

## Basic Usage

```python
from mcp.server.fastmcp import FastMCP, Context
from paymcp import PayMCP, PaymentFlow, price

# Create server
mcp = FastMCP("My Server")

# Add payments
PayMCP(mcp, providers={
    "stripe": {
        "apiKey": "sk_test_...",
        "successUrl": "https://example.com/success",
        "cancelUrl": "https://example.com/cancel"
    }
})

# Paid tool ($5)
@mcp.tool()
@price(5.0, "USD")
async def premium_tool(text: str, ctx: Context):
    return f"Processed: {text}"

# Run server
mcp.run()
```

## Payment Flow

1. User calls tool → Gets payment link
2. User pays → Gets payment ID
3. User confirms payment → Tool runs

## Providers

### Stripe
```python
"stripe": {
    "apiKey": "sk_test_...",
    "successUrl": "...",
    "cancelUrl": "..."
}
```

### PayPal
```python
"paypal": {
    "clientId": "...",
    "clientSecret": "...",
    "sandbox": True
}
```

### Walleot
```python
"walleot": {
    "apiKey": "..."
}
```

## Test

Use test API keys and test cards (Stripe: 4242 4242 4242 4242).