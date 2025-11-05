# PayMCP

**Provider-agnostic payment layer for MCP (Model Context Protocol) tools and agents.**

`paymcp` is a lightweight SDK that helps you add monetization to your MCP‑based tools, servers, or agents. It supports multiple payment providers and integrates seamlessly with MCP's tool/resource interface.

See the [full documentation](https://paymcp.info).

---

## 🔧 Features

- ✅ Add `@price(...)` decorators to your MCP tools to enable payments
- 🔁 Choose between different  modes (two_step, resubmit, elicit, progress, dynamic_tools, etc.)
- 🔌 Built-in support for major providers ([see list](#supported-providers)) — plus a pluggable interface for custom providers.
- ⚙️ Easy integration with `FastMCP` or other MCP servers


## 🚀 Quickstart

Install the SDK from PyPI:
```bash
pip install mcp paymcp
```

Initialize `PayMCP`:

```python
import os
from mcp.server.fastmcp import FastMCP, Context
from paymcp import Mode, price
from paymcp.providers import StripeProvider

mcp = FastMCP("AI agent name")

PayMCP(
    mcp,
    providers=[
        StripeProvider(api_key=os.getenv("STRIPE_API_KEY")),
    ],
    mode=Mode.TWO_STEP # optional, TWO_STEP (default) / RESUBMIT / ELICITATION / PROGRESS / DYNAMIC_TOOLS
)

```

Use the `@price` decorator on any tool:

```python
@mcp.tool()
@price(amount=0.99, currency="USD")
def add(a: int, b: int, ctx: Context) -> int: # `ctx` is required by the PayMCP tool signature — include it even if unused
    """Adds two numbers and returns the result."""
    return a + b
```

> **Demo server:** For a complete setup, see the example repo: [python-paymcp-server-demo](https://github.com/blustAI/python-paymcp-server-demo).


## 🧭 Modes (formerly Payment Flows)

In version 0.4.2, the `paymentFlow` parameter was renamed to `mode`, which better reflects its purpose. The old name remains supported for backward compatibility.

The `mode` parameter controls how the user is guided through the payment process. Choose the strategy that fits your use case:

 - **`Mode.TWO_STEP`** (default)  
  Splits the tool into two separate MCP methods.  
  The first step returns a `payment_url` and a `next_step` method for confirmation.  
  The second method (e.g. `confirm_add_payment`) verifies payment and runs the original logic.  
  Supported in most clients.

 - **`Mode.RESUBMIT`**
  Adds an optional `payment_id` to the original tool signature.
    - **First call**: the tool is invoked without `payment_id` → PayMCP returns a `payment_url` + `payment_id` and instructs a retry after payment.
    - **Second call**: the same tool is invoked again with the returned `payment_id` → PayMCP verifies payment server‑side and, if paid, executes the original tool logic.

  Similar compatibility to TWO_STEP, but with a simpler surface

- **`Mode.ELICITATION`** 
  Sends the user a payment link when the tool is invoked. If the client supports it, a payment UI is displayed immediately. Once the user completes payment, the tool proceeds.


- **`Mode.PROGRESS`**  
  Shows payment link and a progress indicator while the system waits for payment confirmation in the background. The result is returned automatically once payment is completed. 


- **`Mode.DYNAMIC_TOOLS`** 
Steer the client and the LLM by changing the visible tool set at specific points in the flow (e.g., temporarily expose `confirm_payment_*`), thereby guiding the next valid action. 


All modes require the MCP client to support the corresponding interaction pattern. When in doubt, start with `TWO_STEP`.


---

## 🗄️ State Storage 

By default, when using the `TWO_STEP` payment flow, PayMCP stores pending tool arguments (for confirming payment) **in memory** using a process-local `Map`. This is **not durable** and will not work across server restarts or multiple server instances (no horizontal scaling).

To enable durable and scalable state storage, you can provide a custom `StateStore` implementation. PayMCP includes a built-in `RedisStateStore`, which works with any Redis-compatible client.

```python
from redis.asyncio import from_url
from paymcp import PayMCP, RedisStateStore

redis = await from_url("redis://localhost:6379")
PayMCP(
    mcp,
    providers=[
        StripeProvider(api_key=os.getenv("STRIPE_API_KEY")),
    ],
    state_store=RedisStateStore(redis)
)
```

---

## 🧩 Supported Providers

Built-in support is available for the following providers. You can also [write a custom provider](#writing-a-custom-provider).

- ✅ [Adyen](https://www.adyen.com)
- ✅ [Coinbase Commerce](https://commerce.coinbase.com)
- ✅ [PayPal](https://paypal.com)
- ✅ [Stripe](https://stripe.com)
- ✅ [Square](https://squareup.com)
- ✅ [Walleot](https://walleot.com/developers)

- 🔜 More providers welcome! Open an issue or PR.


## 🔌 Writing a Custom Provider

Any provider must subclass `BasePaymentProvider` and implement `create_payment(...)` and `get_payment_status(...)`.

```python
from paymcp.providers import BasePaymentProvider

class MyProvider(BasePaymentProvider):

    def create_payment(self, amount: float, currency: str, description: str):
        # Return (payment_id, payment_url)
        return "unique-payment-id", "https://example.com/pay"

    def get_payment_status(self, payment_id: str) -> str:
        return "paid"

PayMCP(mcp, providers=[MyProvider(api_key="...")])
```


---

## 📄 License

[MIT License](./LICENSE)
