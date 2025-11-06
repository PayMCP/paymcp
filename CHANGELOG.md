# Changelog

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

## 0.1.0
- Add WebView checkout for the MCP STDIO transport (local/desktop clients). When a priced tool triggers a payment, PayMCP opens a native in‑app webview to the provider’s `payment_url` so the user can complete checkout.
- Scope: applies only to STDIO connections on the user’s machine; 
- Install: `pip install paymcp[webview]` or `pdm add paymcp[webview]`.
