"""Tests for session manager."""

import pytest
from unittest.mock import MagicMock, patch

from paymcp.session.manager import SessionManager
from paymcp.session.memory import InMemorySessionStorage
from paymcp.session.types import SessionStorageConfig, ISessionStorage


class TestSessionManager:
    """Test suite for SessionManager."""

    def teardown_method(self):
        """Reset manager after each test."""
        SessionManager.reset()

    def test_get_storage_singleton(self):
        """Test that get_storage returns singleton instance."""
        storage1 = SessionManager.get_storage()
        storage2 = SessionManager.get_storage()

        assert storage1 is storage2
        assert isinstance(storage1, InMemorySessionStorage)

    def test_get_storage_with_config(self):
        """Test get_storage with explicit config."""
        config = SessionStorageConfig(type="memory")
        storage = SessionManager.get_storage(config)

        assert isinstance(storage, InMemorySessionStorage)

    def test_create_memory_storage(self):
        """Test creating memory storage."""
        config = SessionStorageConfig(type="memory")
        storage = SessionManager.create_storage(config)

        assert isinstance(storage, InMemorySessionStorage)

    def test_create_redis_storage_not_implemented(self):
        """Test that Redis storage raises NotImplementedError."""
        config = SessionStorageConfig(type="redis")

        with pytest.raises(NotImplementedError) as exc:
            SessionManager.create_storage(config)

        assert "Redis storage not yet implemented" in str(exc.value)

    def test_create_custom_storage(self):
        """Test creating custom storage implementation."""
        mock_storage = MagicMock(spec=ISessionStorage)
        config = SessionStorageConfig(
            type="custom", options={"implementation": mock_storage}
        )

        storage = SessionManager.create_storage(config)

        assert storage is mock_storage

    def test_create_custom_storage_missing_implementation(self):
        """Test custom storage without implementation raises error."""
        config = SessionStorageConfig(type="custom", options={})

        with pytest.raises(ValueError) as exc:
            SessionManager.create_storage(config)

        assert "Custom storage requires an implementation" in str(exc.value)

    def test_create_custom_storage_no_options(self):
        """Test custom storage without options raises error."""
        config = SessionStorageConfig(type="custom")

        with pytest.raises(ValueError) as exc:
            SessionManager.create_storage(config)

        assert "Custom storage requires an implementation" in str(exc.value)

    def test_create_unknown_storage_type(self):
        """Test unknown storage type raises error."""
        config = SessionStorageConfig(type="unknown")  # type: ignore

        with pytest.raises(ValueError) as exc:
            SessionManager.create_storage(config)

        assert "Unknown storage type: unknown" in str(exc.value)

    def test_reset(self):
        """Test resetting the manager."""
        storage1 = SessionManager.get_storage()
        SessionManager.reset()
        storage2 = SessionManager.get_storage()

        assert storage1 is not storage2

    def test_reset_with_destroyable_instance(self):
        """Test reset calls destroy on existing instance."""
        storage = SessionManager.get_storage()
        assert hasattr(storage, "destroy")

        # Mock the destroy method
        with patch.object(storage, "destroy") as mock_destroy:
            SessionManager.reset()
            mock_destroy.assert_called_once()

    def test_reset_without_instance(self):
        """Test reset when no instance exists."""
        # Should not raise
        SessionManager.reset()
        SessionManager.reset()  # Double reset

    def test_default_config(self):
        """Test that default config creates memory storage."""
        storage = SessionManager.create_storage()
        assert isinstance(storage, InMemorySessionStorage)

    def test_get_storage_preserves_singleton_with_config(self):
        """Test that providing config to existing singleton doesn't recreate."""
        storage1 = SessionManager.get_storage()
        config = SessionStorageConfig(type="memory")
        storage2 = SessionManager.get_storage(config)

        # Should still be the same instance
        assert storage1 is storage2

    def test_custom_storage_implementation_interface(self):
        """Test that custom storage must implement ISessionStorage methods."""
        # Create a mock that implements the interface
        mock_storage = MagicMock()
        mock_storage.set = MagicMock()
        mock_storage.get = MagicMock()
        mock_storage.delete = MagicMock()
        mock_storage.has = MagicMock()
        mock_storage.clear = MagicMock()
        mock_storage.cleanup = MagicMock()

        config = SessionStorageConfig(
            type="custom", options={"implementation": mock_storage}
        )

        storage = SessionManager.create_storage(config)

        # Verify it has all required methods
        assert hasattr(storage, "set")
        assert hasattr(storage, "get")
        assert hasattr(storage, "delete")
        assert hasattr(storage, "has")
        assert hasattr(storage, "clear")
        assert hasattr(storage, "cleanup")
