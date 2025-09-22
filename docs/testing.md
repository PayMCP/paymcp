# Testing

## Running Tests

Run all tests:
```bash
pytest
```

Run with verbose output:
```bash
pytest -v
```

Run with coverage report:
```bash
pytest --cov=src/paymcp
```

Run a specific test file:
```bash
pytest tests/test_core.py
```

Run a specific test class:
```bash
pytest tests/test_core.py::TestPayMCP
```

Run a specific test method:
```bash
pytest tests/test_core.py::TestPayMCP::test_initialization_default_flow
```

## Test Structure

```
tests/
├── payment/
│   ├── flows/          # Payment flow tests
│   └── test_webview.py # Webview functionality tests
├── providers/          # Provider implementation tests
├── session/            # Session management tests
├── utils/              # Utility function tests
├── test_core.py        # Core functionality tests
├── test_decorators.py  # Price decorator tests
├── test_edge_cases.py  # Edge case tests
└── test_integration.py # Integration tests
```

## Writing Tests

Tests use pytest and unittest.mock for mocking:

```python
import pytest
from unittest.mock import Mock, patch
from paymcp import PayMCP, price

def test_example():
    mock_mcp = Mock()
    paymcp = PayMCP(mock_mcp, providers={"stripe": {"apiKey": "test"}})

    @paymcp.mcp.tool()
    @price(amount=10, currency="USD")
    def my_tool():
        return "result"

    assert paymcp is not None
```

## Coverage

Current test coverage is ~98%. Run coverage report:
```bash
pytest --cov=src/paymcp --cov-report=html
open htmlcov/index.html  # View HTML coverage report
```

## Continuous Integration

Tests run automatically on push/PR via GitHub Actions. See `.github/workflows/` for CI configuration.