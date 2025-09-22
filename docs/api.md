# API Reference

## Main Classes

### PayMCP

```python
PayMCP(
    mcp_server,
    providers: dict,
    payment_flow: PaymentFlow = PaymentFlow.TWO_STEP
)
```

### @price Decorator

```python
@price(amount: float, currency: str)
```

### PaymentFlow Enum

```python
PaymentFlow.TWO_STEP      # Default
PaymentFlow.ELICITATION
PaymentFlow.PROGRESS      # Coming soon
PaymentFlow.OOB          # Planned
```

## Custom Provider

```python
from paymcp.providers.base import BasePaymentProvider

class CustomProvider(BasePaymentProvider):
    def get_name(self) -> str:
        return "custom"

    async def create_payment(self, amount, currency, description):
        # Return (payment_id, payment_url)
        return "pay_123", "https://pay.example.com"

    async def get_payment_status(self, payment_id):
        # Return "paid", "pending", or "failed"
        return "paid"
```

## Custom Storage

```python
from paymcp.session import SessionStorage

class RedisStorage(SessionStorage):
    async def get(self, key): ...
    async def set(self, key, value, ttl_seconds=900): ...
    async def delete(self, key): ...
    async def has(self, key): ...
```

## Context Parameter

Required for all priced tools:

```python
@mcp.tool()
@price(10.0, "USD")
async def tool(arg: str, ctx: Context):  # ctx is required!
    return result
```