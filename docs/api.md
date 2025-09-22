# API Reference

## Main Classes

### PayMCP

```python
PayMCP(
    mcp_instance,
    providers: dict,
    payment_flow: PaymentFlow = PaymentFlow.TWO_STEP
)
```

**Parameters:**
- `mcp_instance`: The MCP server instance (e.g., FastMCP)
- `providers`: Dictionary of payment provider configurations
- `payment_flow`: How payments are handled (default: TWO_STEP)

### @price Decorator

```python
@price(price: float, currency: str = "USD")
```

**Parameters:**
- `price`: The cost for using this tool
- `currency`: Currency code (default: "USD")

**Example:**
```python
@mcp.tool()
@price(5.0, "USD")
async def premium_tool(text: str, ctx: Context):
    return f"Processed: {text}"
```

### PaymentFlow Enum

```python
PaymentFlow.TWO_STEP      # Default - explicit confirmation required
PaymentFlow.ELICITATION   # Auto-payment with compatible clients
PaymentFlow.PROGRESS      # Background payment with progress indicator
PaymentFlow.OOB          # Out-of-band payments
```

## Available Providers

- **Stripe**: `stripe`
- **PayPal**: `paypal`
- **Walleot**: `walleot`
- **Adyen**: `adyen`
- **Square**: `square`
- **Coinbase**: `coinbase`

## Custom Provider

```python
from paymcp.providers.base import BasePaymentProvider
from typing import Tuple

class CustomProvider(BasePaymentProvider):
    def get_name(self) -> str:
        return "custom"

    def create_payment(self, amount: float, currency: str, description: str) -> Tuple[str, str]:
        # Implementation here
        # Return (payment_id, payment_url)
        return "pay_123", "https://pay.example.com"

    def get_payment_status(self, payment_id: str) -> str:
        # Return "paid", "pending", or "failed"
        return "paid"
```

## Custom Session Storage

```python
from paymcp.session.types import ISessionStorage, SessionKey, SessionData
from typing import Optional

class CustomStorage(ISessionStorage):
    async def set(self, key: SessionKey, data: SessionData, ttl_seconds: Optional[int] = None) -> None:
        pass

    async def get(self, key: SessionKey) -> Optional[SessionData]:
        pass

    async def delete(self, key: SessionKey) -> None:
        pass

    async def has(self, key: SessionKey) -> bool:
        pass

    async def clear(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass
```

## Context Parameter

**Required for all priced tools:**

```python
from mcp.server.fastmcp import Context

@mcp.tool()
@price(10.0, "USD")
async def tool(arg: str, ctx: Context):  # ctx parameter is required!
    return f"Result: {arg}"
```

The `Context` parameter is automatically injected by the MCP framework and contains request metadata.