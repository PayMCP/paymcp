# Payment Flows

PayMCP supports different payment flows to match your use case and client capabilities.

## Two-Step Flow (Default)

The most secure flow with explicit user confirmation.

```python
PayMCP(mcp, providers=config, payment_flow=PaymentFlow.TWO_STEP)
```

**How it works:**
1. User calls priced tool → Gets payment link and confirmation method
2. User completes payment → Gets payment ID
3. User calls confirmation method with payment ID → Tool executes

**Pros:**
- Works with all MCP clients
- Explicit user consent
- Secure for high-value transactions
- Easy to implement

**Cons:**
- Requires two separate tool calls
- More friction for users

**Example flow:**
```
User: Call @price(5.0) translate_text()
Bot: Please pay $5.00 at https://checkout.stripe.com/...
     Then call confirm_translate_text(payment_id="pay_123")
User: [pays and gets payment ID]
User: Call confirm_translate_text(payment_id="pay_123")
Bot: [executes translation]
```

## Elicitation Flow

Automatic payment with compatible clients.

```python
PayMCP(mcp, providers=config, payment_flow=PaymentFlow.ELICITATION)
```

**How it works:**
1. User calls priced tool → Payment UI appears immediately
2. User completes payment → Tool auto-executes
3. Result returned automatically

**Pros:**
- Single tool call
- Better user experience
- Faster workflow

**Cons:**
- Requires client support for elicitation
- Less explicit consent
- May not work with all clients

**Client Requirements:**
- Must support MCP elicitation messages
- Must handle payment UI display
- Must automatically retry tool after payment

## Progress Flow

Background payment monitoring with progress indicators.

```python
PayMCP(mcp, providers=config, payment_flow=PaymentFlow.PROGRESS)
```

**How it works:**
1. User calls priced tool → Gets payment link
2. System monitors payment status in background
3. Tool auto-executes when payment confirmed
4. Progress updates shown to user

**Pros:**
- No second tool call needed
- Real-time payment monitoring
- Good user experience

**Cons:**
- More complex implementation
- Requires background processing
- Client must support progress indicators

## OOB (Out-of-Band) Flow

Payment handled outside the MCP conversation.

```python
PayMCP(mcp, providers=config, payment_flow=PaymentFlow.OOB)
```

**Status:** Planned for future release

**How it would work:**
1. User pre-pays or has subscription
2. Tool checks payment status externally
3. Tool executes if user has credit

## Choosing the Right Flow

| Use Case | Recommended Flow | Reason |
|----------|------------------|---------|
| Production systems | TWO_STEP | Maximum security and compatibility |
| Consumer apps | ELICITATION | Better UX if client supports it |
| Real-time apps | PROGRESS | Background processing |
| High-value transactions | TWO_STEP | Explicit consent required |
| Micro-payments | ELICITATION | Reduce friction |
| API integrations | TWO_STEP | Predictable behavior |

## Client Compatibility

| Flow | Claude Desktop | Custom Clients | Web Clients |
|------|----------------|----------------|-------------|
| TWO_STEP | ✅ | ✅ | ✅ |
| ELICITATION | ⚠️ Depends | ⚠️ Must implement | ⚠️ Must implement |
| PROGRESS | ⚠️ Depends | ⚠️ Must implement | ⚠️ Must implement |
| OOB | ❌ Not yet | ❌ Not yet | ❌ Not yet |

**Recommendation:** Start with `TWO_STEP` and migrate to other flows as needed.