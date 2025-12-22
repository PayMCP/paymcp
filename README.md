# PayMCP

**Provider-agnostic payment layer for MCP (Model Context Protocol) tools and agents.**

`paymcp` is a lightweight SDK that helps you add monetization to your MCP‑based tools, servers, or agents. It supports multiple payment providers and integrates seamlessly with MCP's tool/resource interface.

See the [full documentation](https://paymcp.info).

---

## 🔧 Features

- ✅ Add `@price(...)` decorators to your MCP tools to enable pay‑per‑request billing.
- ✅ Gate tools behind **active subscriptions** (where supported) with the `@subscription(...)` decorator; helper tools included.
- 🔁 Pay‑per‑request flows support multiple **modes** (AUTO / TWO_STEP / RESUBMIT / ELICITATION / PROGRESS / DYNAMIC_TOOLS).
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
    mode=Mode.AUTO # optional, AUTO (default) / TWO_STEP / RESUBMIT / ELICITATION / PROGRESS / DYNAMIC_TOOLS
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

> **Demo MCP servers:**
> - Pay‑per‑request example: [python-paymcp-server-demo](https://github.com/blustAI/python-paymcp-server-demo)
> - Subscription example: [paymcp-subscription-demo-py](https://github.com/PayMCP/paymcp-subscription-demo-py)


## 💰 Choose How to Charge (per tool)

Use **either** `@price` or `@subscription` on a tool (they are mutually exclusive).

### Option A — Pay‑per‑request

```python
@mcp.tool()
@price(amount=0.19, currency="USD")
def summarize(text: str, ctx: Context) -> str:
    return text[:200]
```

### Option B — Subscription‑gated (providers with subscription support, e.g., Stripe)

User authentication is **your** responsibility. PayMCP will resolve identity from `ctx.authInfo` **or** a Bearer token (Authorization header). Make sure your token carries:
- `sub` (treated as `userId`), and ideally
- `email` (highly recommended for provider matching, e.g., Stripe).

PayMCP does **not** validate or verify the token; it only parses it to extract `userId`/`email`.

```python
from paymcp import subscription

@mcp.tool()
@subscription(plan="price_pro_monthly")  # or a list of accepted plan IDs from your provider
async def generate_report(ctx: Context) -> str:
    return "Your report"
```

When you register the first subscription‑protected tool, PayMCP auto‑registers helper tools:

- `list_subscriptions` — current subscriptions + available plans for the user.
- `start_subscription` — accepts `planId` to create (or resume) a subscription.
- `cancel_subscription` — accepts `subscriptionId` to cancel at period end.

---

## 🧩 Supported Providers

Built-in support is available for the following providers. You can also [write a custom provider](#writing-a-custom-provider).

- ✅ [Stripe](https://stripe.com) — pay‑per‑request + subscriptions
- ✅ [Adyen](https://www.adyen.com) — pay‑per‑request
- ✅ [Coinbase Commerce](https://commerce.coinbase.com) — pay‑per‑request
- ✅ [PayPal](https://paypal.com) — pay‑per‑request
- ✅ [Square](https://squareup.com) — pay‑per‑request
- ✅ [Walleot](https://walleot.com/developers) — pay‑per‑request

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

## 🗄️ State Storage 

By default, PayMCP stores payment_id and pending tool arguments **in memory** using a process-local `Map`. This is **not durable** and will not work across server restarts or multiple server instances (no horizontal scaling).

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

## 🧭 Modes (pay‑per‑request only)

In version 0.4.2, `paymentFlow` was renamed to `mode` (old name still works).

The `mode` parameter controls how the user is guided through the pay‑per‑request payment process. Pick what fits your client:

- **`Mode.AUTO`** (default) — Detects client capabilities; uses elicitation when available, otherwise falls back to RESUBMIT.
- **`Mode.TWO_STEP`** — Splits the tool into two MCP methods. First call returns `payment_url` + `next_step`; the confirm method verifies and runs the original logic. Works in most clients.
- **`Mode.RESUBMIT`** — Adds optional `payment_id` to the tool signature. First call returns `payment_url` + `payment_id`; second call with `payment_id` verifies then runs the tool. Similar compatibility to TWO_STEP.
- **`Mode.ELICITATION`** — Sends a payment link via MCP elicitation (if supported). After payment, the tool completes in the same call.
- **`Mode.PROGRESS`** — Keeps the call open, streams progress while polling the provider, and returns automatically once paid.
- **`Mode.DYNAMIC_TOOLS`** — Temporarily exposes additional tools (e.g., `confirm_payment_*`) to steer the client/LLM through the flow.


---

## 🔒 Security Notice

PayMCP is NOT compatible with STDIO mode deployments where end users download and run MCP servers locally. This would expose your payment provider API keys to end users, creating serious security vulnerabilities.

---

## 📄 License

[MIT License](./LICENSE)
