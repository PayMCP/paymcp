# PayMCP

**Provider-agnostic payment layer for MCP (Model Context Protocol) tools and agents.**

`paymcp` is a lightweight SDK that helps you add monetization to your MCP-based tools, servers, or agents. It supports multiple payment providers and integrates seamlessly with MCP's tool/resource interface.

---

## 🔧 Features

- ✅ Add `@price(...)` decorators to your MCP tools to enable payments
- 🔁 Choose between different payment flows (elicit, confirm, etc.)
- 🔌 Pluggable support for providers like Walleot, Stripe, and more
- ⚙️ Easy integration with `FastMCP` or other MCP servers

---

## 🧭 Payment Flows

The `payment_flow` parameter controls how the user is guided through the payment process. Choose the strategy that fits your use case:

 - **`PaymentFlow.TWO_STEP`** (default)  
  Splits the tool into two separate MCP methods.  
  The first step returns a `payment_url` and a `next_step` method for confirmation.  
  The second method (e.g. `confirm_add_payment`) verifies payment and runs the original logic.  
  Supported in most clients.

- **`PaymentFlow.ELICITATION`** 
  Sends the user a payment link when the tool is invoked. If the client supports it, a payment UI is displayed immediately. Once the user completes payment, the tool proceeds.


- **`PaymentFlow.PROGRESS`**  
  Shows payment link and a progress indicator while the system waits for payment confirmation in the background. The result is returned automatically once payment is completed. 

- **`PaymentFlow.OOB`** *(Out-of-Band)*  
Not yet implemented.

All flows require the MCP client to support the corresponding interaction pattern. When in doubt, start with `TWO_STEP`.

---

## 🚀 Quickstart

Install the SDK from PyPI:
```bash
pip install mcp paymcp
```

Initialize `PayMCP`:

```python
from mcp.server.fastmcp import FastMCP, Context
from paymcp import PayMCP, price, PaymentFlow
import os

mcp = FastMCP("AI agent name")
PayMCP(
    mcp,  # your FastMCP instance
    providers={
        "stripe": {"apiKey": os.getenv("STRIPE_API_KEY")},
    },
    payment_flow=PaymentFlow.TWO_STEP #or ELICITATION / PROGRESS
)
```

### Providers: alternative styles (optional)

**Instances instead of config (advanced):**
```python
import os
from paymcp.providers import WalleotProvider, StripeProvider

PayMCP(
    mcp,
    providers=[
        WalleotProvider(api_key=os.getenv("WALLEOT_API_KEY")),
        CoinbaseProvider(api_key=os.getenv("COINBASE_API_KEY")),
    ],
)
# Note: right now the first configured provider is used.
```

**Custom provider (minimal):**  
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

Use the `@price` decorator on any tool:

```python
@mcp.tool()
@price(amount=0.19, currency="USD")
def add(a: int, b: int, ctx: Context) -> int:
    # `ctx` is required by the PayMCP tool signature — include it even if unused
    return a + b
```

> **Demo server:** For a complete setup, see the example repo: [python-paymcp-server-demo](https://github.com/blustAI/python-paymcp-server-demo).


---

## 🪟 Optional: WebView (STDIO)

Open the payment link in a native window when your MCP server is connected via the stdio transport (typical for local/desktop installs).

- Install: `pip install paymcp[webview]` (or `pdm add paymcp[webview]`).
- What it does: when a priced tool is invoked, PayMCP opens a lightweight in-app webview to the provider's `payment_url` so the user can complete checkout without leaving the client.
- Scope: applies only to stdio connections on the user's machine.
- Notes: requires a desktop environment.



---

## 🧩 Supported Providers
- ✅ [Adyen](https://www.adyen.com)
- ✅ [Coinbase Commerce](https://commerce.coinbase.com)
- ✅ [PayPal](https://paypal.com)
- ✅ [Stripe](https://stripe.com)
- ✅ [Square](https://squareup.com)
- ✅ [Walleot](https://walleot.com/developers)
- 🔜 Want another provider? Open an issue or submit a pull request!

---

## 📄 License

MIT License
