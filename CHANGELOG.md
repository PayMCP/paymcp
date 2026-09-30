# Changelog

# 0.9.1
### Fixed
- Declare the `mcp` dependency, bounded to `>=1,<2`. It was not declared at all, and `pip install mcp paymcp` now resolves mcp 2.x, where `mcp.server.fastmcp` no longer exists - so a new install stopped working before it ran a line of its own code. PayMCP is written against the 1.x SDK.
- A paid tool no longer runs twice when the client disconnects before receiving the result. The result is stored on disconnect and returned on the retry, and only to the call that paid for it. In RESUBMIT and TWO_STEP a further retry with the same payment id returns that result again until the store expires it, where it previously reported the payment as unknown.
- A state store that fails to delete no longer costs the caller the result they paid for: the failure is logged and the result returned. The payment record then stays reusable until it expires.
- The in-memory per-payment lock is now actually exclusive. It discarded its registry entry as soon as the holder finished, so a caller arriving after that ran alongside one still queued - which is the race RESUBMIT relies on it to prevent.
- DYNAMIC_TOOLS now hides the paid tool from the session paying for it and offers the confirm tool, which is what it always intended: the two sides resolved the session differently, so the listing was the opposite.
- ELICITATION and PROGRESS delete a session's payment record only when it is still the one that call was using, so a concurrent call no longer loses a payment the user may already have made.
- DYNAMIC_TOOLS sweeps payments nobody came back for, together with the tool registries that hang off them, instead of holding them for the lifetime of the process.
- Reading the caller's identity from a context with no active request no longer fails the tool call. `Context.request_context`, `session` and `client_id` raise there, and `getattr` with a default does not cover it.

# 0.9.0
### Breaking Changes
- x402 v2 challenges now carry the resource description under `resource`, the field name the v2 `PaymentRequired` schema defines. It was previously emitted as `resourceInfo`, which is not an x402 field, so v2 clients never found it. Anyone reading the old key must switch.

### Fixed
- `resource` is required by the v2 schema but was omitted unless `resource_info` was configured. Every v2 challenge PayMCP sends now carries it, defaulting to `mcp://tool/<tool_name>` — the form used by the x402 MCP transport spec. The name is the registered one, so `@mcp.tool("other_name")` advertises `mcp://tool/other_name` rather than the implementation function's name.
- Note that a `resource_info` with a `url` still wins, and it is a single value shared by every tool: operators who configured it for v1 (where it fills the `resource` string inside `accepts`) will not see the per-tool default. Leave `url` unset to get it.

x402 v1 challenges are unchanged, including their non-standard top-level `resourceInfo`, which is left alone deliberately: in v1 the fields the facilitator verifies live inside `accepts`.

# 0.8.4
### Security
- Fixed session-isolation vulnerability: payment/session state no longer uses Python object IDs (`id(session)`) as keys in ELICITATION, PROGRESS, and DYNAMIC_TOOLS flows.
- Replaced `id(session)` keying with stable per-session identifiers to prevent cross-session state reuse when CPython reuses object addresses.

# 0.8.3
### Changed
- Default x402 facilitator is now https://facilitator.paymcp.info

# 0.8.2
### Changed
- Price/subscription settings can now be configured in tool `meta` (decorators still work too)
- Removed auto-adding pricing hints to tool descriptions, since price is now available in tool meta


# 0.8.1
### Added
- Mode.AUTO now supports configuring both a traditional provider and an X402 provider, automatically selecting X402 when the client has an X402 wallet.

# 0.8.0
### Added
- Introduced `Mode.X402`.

### Changed
- In `AUTO` mode, the server now detects client support for `X402` and automatically selects `Mode.X402` when available.

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

