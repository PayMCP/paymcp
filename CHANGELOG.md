# Changelog

## 0.2.1
### Fixed
- **Multi-user session isolation** in LIST_CHANGE flow: Fixed per-session tool visibility to properly isolate concurrent users
  - Each user session now maintains independent HIDDEN_TOOLS state
  - Uses MCP SDK's `request_ctx.session` for session tracking with UUID fallback
  - Prevents tool visibility interference between concurrent users
  - Verified with multi-user isolation test scenarios (100% pass rate)
- **Session context propagation**: Ensured proper session context wrapping for all payment flows
- **ELICITATION flow**: Fixed crash when handling JSONRPCResponse messages in MCP SDK patch
  - Added proper type checking before accessing `.method` attribute
  - Handles all message types (JSONRPCRequest, JSONRPCNotification, JSONRPCResponse)

### Changed
- Improved session ID fallback mechanism for better multi-user isolation when server doesn't support session tracking

## 0.2.0
### Added
- Extensible provider system. Providers can now be supplied in multiple ways:
  - As config mapping `{name: {kwargs}}` (existing behavior).
  - As ready-made instances: `{"stripe": StripeProvider(...), "custom": MyProvider(...)}`
  - As a list of instances: `[WalleotProvider(...), MyProvider(...)]`

## 0.1.0
### Added
- WebView checkout for the MCP STDIO transport (local/desktop clients). When a priced tool triggers a payment, PayMCP opens a native in‑app webview to the provider's `payment_url` so the user can complete checkout.
- Scope: applies only to STDIO connections on the user's machine
- Install: `pip install paymcp[webview]` or `pdm add paymcp[webview]`
