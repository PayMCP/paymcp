# Installation

## Install Package

```bash
pip install paymcp
```

Note: You'll also need an MCP server framework. The most popular option is:

```bash
pip install mcp fastmcp
```

## Development Install

```bash
git clone https://github.com/your-repo/paymcp.git
cd paymcp
pip install -e .
```

## Requirements

- Python 3.10+
- An MCP server framework (recommended: `fastmcp`)

## Optional Dependencies

For webview support (desktop payment flows):
```bash
pip install paymcp[webview]
```

For development (testing, linting, etc.):
```bash
pip install paymcp[dev]
```

For testing only:
```bash
pip install paymcp[test]
```

## Verify Installation

```python
from paymcp import PayMCP, price, PaymentFlow
print("PayMCP installed successfully!")
```