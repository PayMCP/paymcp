"""Tests for paymcp/__init__.py conditional imports."""

import pytest
from unittest.mock import patch
import sys


def test_paymcp_basic_imports():
    """Test that basic imports work without redis."""
    # This test runs in environment where redis may or may not be installed
    from paymcp import (
        PayMCP,
        price,
        PaymentFlow,
        StateStore,
        InMemoryStateStore,
        __version__
    )

    assert PayMCP is not None
    assert price is not None
    assert PaymentFlow is not None
    assert StateStore is not None
    assert InMemoryStateStore is not None
    assert __version__ is not None


def test_paymcp_redis_import_when_available():
    """Test RedisStateStore import when redis is available."""
    try:
        from paymcp import RedisStateStore
        # If redis is installed, this should succeed
        assert RedisStateStore is not None
    except ImportError:
        # If redis is not installed, this is expected
        pytest.skip("redis package not installed")


def test_paymcp_all_exports():
    """Test __all__ exports include expected symbols."""
    import paymcp

    # Basic exports should always be present
    assert 'PayMCP' in paymcp.__all__
    assert 'price' in paymcp.__all__
    assert 'PaymentFlow' in paymcp.__all__
    assert 'StateStore' in paymcp.__all__
    assert 'InMemoryStateStore' in paymcp.__all__
    assert '__version__' in paymcp.__all__

    # RedisStateStore may or may not be present depending on redis installation
    # We just verify __all__ is a list
    assert isinstance(paymcp.__all__, list)
