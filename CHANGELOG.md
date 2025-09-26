# Changelog

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
