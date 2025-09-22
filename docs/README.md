# PayMCP Python Documentation

## Quick Start

```python
from mcp.server.fastmcp import FastMCP, Context
from paymcp import PayMCP, price

mcp = FastMCP("My Server")

PayMCP(mcp, providers={
    "stripe": {"apiKey": "sk_test_..."}
})

@mcp.tool()
@price(5.0, "USD")
async def paid_tool(text: str, ctx: Context):
    return f"Result: {text}"

mcp.run()
```

## Guides

- [Installation](installation.md)
- [Payment Flows](payment-flows.md)
- [Providers Setup](providers.md)
- [API Reference](api.md)

## Examples

See `/examples` folder for complete examples.