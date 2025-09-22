# Payment Flows

## Two-Step Flow (Default)

Most secure, requires explicit confirmation.

```python
PaymentFlow.TWO_STEP
```

1. Call tool → Get payment link
2. Pay → Get payment ID
3. Confirm → Tool executes

## Elicitation Flow

Automatic with compatible clients.

```python
PaymentFlow.ELICITATION
```

1. Call tool → Payment UI opens
2. Pay → Tool auto-executes

## Choose Based On

- **Two-Step**: Production, high-value, explicit consent needed
- **Elicitation**: Consumer apps, better UX, client must support it