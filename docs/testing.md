# Testing

## Quick Start

Install test dependencies:
```bash
pip install paymcp[test]
# or
pip install pytest pytest-asyncio pytest-cov
```

Run all tests:
```bash
pytest
```

## Test Commands

### Basic Testing
```bash
# Run all tests
pytest

# Verbose output
pytest -v

# Run specific file
pytest tests/test_core.py

# Run specific test
pytest tests/test_core.py::TestPayMCP::test_initialization_default_flow
```

### Coverage Reports
```bash
# Basic coverage
pytest --cov=src/paymcp

# HTML coverage report
pytest --cov=src/paymcp --cov-report=html
open htmlcov/index.html

# Coverage with missing lines
pytest --cov=src/paymcp --cov-report=term-missing
```

### Development
```bash
# Watch mode (requires pytest-watch)
pip install pytest-watch
pytest --watch

# Run tests matching pattern
pytest -k "test_stripe"

# Run failed tests only
pytest --lf

# Stop after first failure
pytest -x
```

## Test Structure

```
tests/
├── __init__.py
├── test_core.py           # Core PayMCP functionality
├── test_core_extended.py  # Extended core tests
├── test_decorators.py     # @price decorator tests
├── test_edge_cases.py     # Edge cases and error handling
├── test_integration.py    # Integration tests
├── test_session_persistence.py # Session management
├── payment/               # Payment flow tests
│   ├── flows/
│   │   ├── test_two_step.py
│   │   ├── test_elicitation.py
│   │   └── test_progress.py
│   └── test_webview.py    # Webview functionality
├── providers/             # Provider tests
│   ├── test_stripe.py
│   ├── test_paypal.py
│   ├── test_walleot.py
│   ├── test_adyen.py
│   ├── test_square.py
│   └── test_coinbase.py
├── session/               # Session storage tests
│   ├── test_manager.py
│   └── test_memory.py
└── utils/                 # Utility tests
    ├── test_messages.py
    └── test_payment.py
```

## Writing Tests

### Basic Test Example
```python
import pytest
from unittest.mock import Mock
from paymcp import PayMCP, price

def test_paymcp_initialization():
    mock_mcp = Mock()
    paymcp = PayMCP(mock_mcp, providers={
        "stripe": {"apiKey": "sk_test_123"}
    })
    assert paymcp.providers["stripe"].get_name() == "stripe"
```

### Testing Paid Tools
```python
import pytest
from unittest.mock import Mock, AsyncMock
from mcp.server.fastmcp import Context
from paymcp import PayMCP, price

@pytest.mark.asyncio
async def test_paid_tool():
    mock_mcp = Mock()
    paymcp = PayMCP(mock_mcp, providers={
        "stripe": {"apiKey": "sk_test_123"}
    })

    @price(5.0, "USD")
    async def test_tool(text: str, ctx: Context):
        return f"Result: {text}"

    # Mock the provider
    mock_provider = Mock()
    mock_provider.create_payment.return_value = ("pay_123", "https://pay.url")
    paymcp.providers["stripe"] = mock_provider

    # Test the wrapped function
    wrapper = paymcp._wrapper_factory(test_tool, mock_mcp, mock_provider, {"price": 5.0, "currency": "USD"})

    mock_ctx = Mock(spec=Context)
    result = await wrapper("hello", mock_ctx)

    assert "payment_url" in result
```

### Testing Providers
```python
import pytest
from unittest.mock import patch, Mock
from paymcp.providers.stripe import StripeProvider

def test_stripe_create_payment():
    provider = StripeProvider(apiKey="sk_test_123")

    with patch.object(provider, '_request') as mock_request:
        mock_request.return_value = {
            "id": "cs_123",
            "url": "https://checkout.stripe.com/pay/cs_123"
        }

        payment_id, payment_url = provider.create_payment(10.0, "USD", "Test payment")

        assert payment_id == "cs_123"
        assert "checkout.stripe.com" in payment_url
        mock_request.assert_called_once()
```

## Mocking Strategies

### Mock HTTP Requests
```python
import pytest
from unittest.mock import patch
import requests

@patch('requests.post')
def test_provider_request(mock_post):
    mock_response = Mock()
    mock_response.json.return_value = {"id": "123"}
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    # Your test code here
```

### Mock Async Functions
```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_async_function():
    mock_session = AsyncMock()
    mock_session.get.return_value = {"key": "value"}

    # Your async test code here
```

## Coverage Goals

Current coverage: **~98%**

### Coverage by Module
- `core.py`: 99%
- `decorators.py`: 100%
- `providers/`: 95%+
- `payment/flows/`: 90%+
- `session/`: 95%+

### Running Coverage
```bash
# Generate coverage report
pytest --cov=src/paymcp --cov-report=html --cov-report=term

# Check coverage threshold
pytest --cov=src/paymcp --cov-fail-under=95

# Generate badge (if coverage-badge installed)
coverage-badge -o coverage.svg
```

## Continuous Integration

Tests run automatically on:
- Pull requests
- Pushes to main branch
- Scheduled nightly runs

### GitHub Actions Workflow
```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.10, 3.11, 3.12, 3.13]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dependencies
        run: |
          pip install -e .[test]
      - name: Run tests
        run: pytest --cov=src/paymcp
```

## Test Data

### Test Provider Credentials
```python
# tests/conftest.py
TEST_PROVIDERS = {
    "stripe": {"apiKey": "sk_test_fake123"},
    "paypal": {
        "client_id": "test_client",
        "client_secret": "test_secret",
        "sandbox": True
    },
    "walleot": {"apiKey": "test_walleot_key"}
}
```

### Test Cards (Stripe)
- Success: `4242 4242 4242 4242`
- Decline: `4000 0000 0000 0002`
- Authentication required: `4000 0025 0000 3155`

## Debugging Tests

### Run with debugging
```bash
# Print statements
pytest -s

# Enter debugger on failure
pytest --pdb

# Drop into debugger immediately
pytest --pdb-trace

# Verbose output with tracebacks
pytest -vvv --tb=long
```

### Common Issues
1. **Missing Context parameter**: All priced tools need `ctx: Context`
2. **Async/await**: Use `@pytest.mark.asyncio` for async tests
3. **Mock setup**: Ensure mocks match actual function signatures
4. **Provider API keys**: Use test keys, never production keys