# Quick Start Guide

Get PayMCP running in 5 minutes!

## 1. Install

```bash
pip install paymcp mcp fastmcp
```

## 2. Basic Setup

Create a simple MCP server with paid tools:

```python
from mcp.server.fastmcp import FastMCP, Context
from paymcp import PayMCP, price

# Create MCP server
mcp = FastMCP("My Paid Server")

# Add payment support
PayMCP(mcp, providers={
    "stripe": {
        "apiKey": "sk_test_51...",  # Your Stripe test key
    }
})

# Free tool
@mcp.tool()
async def free_tool(text: str, ctx: Context):
    return f"Free result: {text}"

# Paid tool
@mcp.tool()
@price(5.0, "USD")
async def premium_tool(text: str, ctx: Context):
    return f"Premium result: {text}"

# Run the server
if __name__ == "__main__":
    mcp.run()
```

## 3. Test It

Save as `server.py` and run:

```bash
python server.py
```

Your MCP server is now running with payment support!

## 4. How It Works

### Default Two-Step Flow

1. **Call paid tool** → Get payment link
2. **Complete payment** → Get payment ID
3. **Confirm payment** → Tool executes

**Example conversation:**
```
User: premium_tool("hello world")
Bot: Please pay $5.00 at: https://checkout.stripe.com/c/pay_xyz...
     After payment, call: confirm_premium_tool(payment_id="your_payment_id")

User: [completes payment and gets ID: cs_xyz123]
User: confirm_premium_tool(payment_id="cs_xyz123")
Bot: Premium result: hello world
```

## 5. Provider Options

### Stripe (Recommended)
```python
"stripe": {
    "apiKey": "sk_test_...",
}
```
- Get test keys from [Stripe Dashboard](https://dashboard.stripe.com/test/apikeys)
- Test card: `4242 4242 4242 4242`

### Walleot (Great for micro-payments)
```python
"walleot": {
    "apiKey": "..."
}
```
- Best for amounts under $2
- No minimum amount restrictions

### PayPal
```python
"paypal": {
    "client_id": "...",
    "client_secret": "...",
    "sandbox": True
}
```

## 6. Multiple Tools

```python
@mcp.tool()
@price(1.0, "USD")
async def cheap_tool(ctx: Context):
    return "Cheap result"

@mcp.tool()
@price(10.0, "USD")
async def expensive_tool(ctx: Context):
    return "Expensive result"

@mcp.tool()
async def free_tool(ctx: Context):
    return "Free result"
```

## 7. Environment Variables

For production, use environment variables:

```python
import os
from dotenv import load_dotenv

load_dotenv()

PayMCP(mcp, providers={
    "stripe": {
        "apiKey": os.getenv("STRIPE_SECRET_KEY")
    }
})
```

Create `.env` file:
```bash
STRIPE_SECRET_KEY=sk_test_...
```

## Next Steps

- [Read about Payment Flows](payment-flows.md) to choose the right flow
- [Set up additional Providers](providers.md)
- [View the full API Reference](api.md)
- [Run tests](testing.md) to verify your setup

## Need Help?

Common issues:
- **Missing Context**: All priced tools need `ctx: Context` parameter
- **Provider errors**: Check your API keys and test with sandbox/test modes
- **Import errors**: Make sure you installed both `paymcp` and `mcp`