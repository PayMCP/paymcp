# Changelog

# 0.7.0
### Breaking Changes
- Default `mode` is now `AUTO`.
  - Clients relying on implicit defaults may observe different execution paths.

### Added
- Introduced `AUTO` mode that automatically selects between ELICITATION and RESUBMIT based on client capabilities.


# 0.6.1
### Added
- Session recovery for ELICITATION and PROGRESS modes after client timeouts/disconnects (reuse pending payment and continue).
- `is_disconnected` to capture aborts and preserve payment info when the connection drops before sending the result.


# 0.5.3
### Added
- Stripe provider now sets an `Idempotency-Key` when creating customers to prevent duplicate customer records for the same user.

# 0.5.1
### Added
- Added subscription support in addition to the existing pay-per-request model.

# 0.4.4
### Changed
- In RESUBMIT mode, the tool now uses the most recently provided arguments instead of those from the initial call.

# 0.4.3
### Added
- Added protection against reusing `payment_id` in RESUBMIT mode (single-use enforcement).

## 0.4.2
### Changed
- `mode` is now the recommended parameter instead of `paymentFlow`, as it better reflects the intended behavior.
  - `paymentFlow` remains supported for backward compatibility, but `mode` takes precedence in new implementations.
  - Future updates may deprecate `paymentFlow`.

## 0.4.1
### Added
- payment flow `RESUBMIT`.
- Introduced `mode` parameter (will replace `paymentFlow` in future versions).

## 0.3.3
### Changed
- Kept original tool UI in ChatGPT Apps by removing `_meta` from the initial tool and applying it only to confirmation tools in TWO_STEP payment flow. 

## 0.3.1
### Added
- Experimental payment flow `DYNAMIC_TOOLS` for dynamic tool visibility control

## 0.2.1
### Added
- Pluggable state storage for TWO_STEP flow
  - `InMemoryStateStore`: Default in-memory storage (backward compatible, process-local)
  - `RedisStateStore`: Production-ready distributed state storage using Redis
  - Custom state stores supported via duck typing

## 0.2.0
### Added
- Extensible provider system. Providers can now be supplied in multiple ways:
  - As config mapping `{name: {kwargs}}` (existing behavior).
  - As ready-made instances: `{"stripe": StripeProvider(...), "custom": MyProvider(...)}`
  - As a list of instances: `[WalleotProvider(...), MyProvider(...)]`

