"""Tests for paymcp/state/__init__.py conditional imports."""

import pytest


def test_state_basic_imports():
    """Test that basic state imports work without redis."""
    from paymcp.state import StateStore, InMemoryStateStore

    assert StateStore is not None
    assert InMemoryStateStore is not None


def test_state_redis_import_when_available():
    """Test RedisStateStore import when redis is available."""
    try:
        from paymcp.state import RedisStateStore
        # If redis is installed, this should succeed
        assert RedisStateStore is not None
    except ImportError:
        # If redis is not installed, this is expected
        pytest.skip("redis package not installed")


def test_state_all_exports():
    """Test __all__ exports include expected symbols."""
    from paymcp import state

    # Basic exports should always be present
    assert 'StateStore' in state.__all__
    assert 'InMemoryStateStore' in state.__all__

    # RedisStateStore may or may not be present depending on redis installation
    assert isinstance(state.__all__, list)
