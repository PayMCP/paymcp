# PayMCP Documentation

**Provider-agnostic payment layer for MCP (Model Context Protocol) tools and agents.**

## Quick Start

```python
from mcp.server.fastmcp import FastMCP, Context
from paymcp import PayMCP, price, PaymentFlow

mcp = FastMCP("My Server")

PayMCP(mcp, providers={
    "stripe": {"apiKey": "sk_test_..."}
}, payment_flow=PaymentFlow.TWO_STEP)

@mcp.tool()
@price(5.0, "USD")
async def paid_tool(text: str, ctx: Context):
    return f"Result: {text}"

mcp.run()
```

## Features

- ✅ Add `@price(...)` decorators to your MCP tools to enable payments
- 🔁 Choose between different payment flows (two-step, elicitation, progress, OOB)
- 🔌 Support for multiple providers: Stripe, PayPal, Walleot, Adyen, Square, Coinbase
- ⚙️ Easy integration with `FastMCP` or other MCP servers

## Documentation

- [Quick Start Guide](quickstart.md)
- [Installation](installation.md)
- [Payment Flows](payment-flows.md)
- [Provider Setup](providers.md)
- [API Reference](api.md)
- [Testing](testing.md)