"""Tests for providers initialization and factory functionality."""

import pytest
from unittest.mock import Mock, patch
from paymcp.providers import (
    register_provider,
    build_providers,
    _resolve_class,
    _key_for_instance,
    PROVIDER_MAP
)
from paymcp.providers.base import BasePaymentProvider


class MockProvider(BasePaymentProvider):
    """Mock provider for testing."""

    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.slug = "mock"

    def create_payment(self, amount, currency, description):
        return "mock_payment_id", "https://mock.payment.url"

    def get_payment_status(self, payment_id):
        return "paid"


class TestProviderRegistration:
    """Test provider registration functionality."""

    def test_register_provider_valid(self):
        """Test registering a valid provider."""
        register_provider("test_provider", MockProvider)
        assert "test_provider" in PROVIDER_MAP
        assert PROVIDER_MAP["test_provider"] == MockProvider

    def test_register_provider_case_insensitive(self):
        """Test that provider registration is case insensitive."""
        register_provider("TEST_PROVIDER", MockProvider)
        assert "test_provider" in PROVIDER_MAP

    def test_register_provider_empty_name(self):
        """Test registering provider with empty name raises error."""
        with pytest.raises(ValueError, match="name must be a non-empty string"):
            register_provider("", MockProvider)

    def test_register_provider_none_name(self):
        """Test registering provider with None name raises error."""
        with pytest.raises(ValueError, match="name must be a non-empty string"):
            register_provider(None, MockProvider)

    def test_register_provider_non_string_name(self):
        """Test registering provider with non-string name raises error."""
        with pytest.raises(ValueError, match="name must be a non-empty string"):
            register_provider(123, MockProvider)


class TestResolveClass:
    """Test class resolution functionality."""

    def test_resolve_class_with_colon(self):
        """Test resolving class with colon syntax."""
        with patch("paymcp.providers.importlib.import_module") as mock_import:
            mock_module = Mock()
            mock_class = Mock()
            mock_module.MockClass = mock_class
            mock_import.return_value = mock_module

            result = _resolve_class("test.module:MockClass")

            mock_import.assert_called_once_with("test.module")
            assert result == mock_class

    def test_resolve_class_with_dot(self):
        """Test resolving class with dot syntax."""
        with patch("paymcp.providers.importlib.import_module") as mock_import:
            mock_module = Mock()
            mock_class = Mock()
            mock_module.MockClass = mock_class
            mock_import.return_value = mock_module

            result = _resolve_class("test.module.MockClass")

            mock_import.assert_called_once_with("test.module")
            assert result == mock_class

    def test_resolve_class_attribute_error(self):
        """Test resolving non-existent class attribute."""
        with patch("paymcp.providers.importlib.import_module") as mock_import:
            mock_module = Mock()
            del mock_module.NonExistentClass  # Ensure attribute doesn't exist
            mock_import.return_value = mock_module

            with pytest.raises(AttributeError):
                _resolve_class("test.module:NonExistentClass")


class TestKeyForInstance:
    """Test instance key derivation."""

    def test_key_for_instance_with_slug(self):
        """Test key derivation when instance has slug attribute."""
        mock_instance = Mock()
        mock_instance.slug = "custom_slug"
        mock_instance.name = "should_not_use_this"

        result = _key_for_instance(mock_instance)
        assert result == "custom_slug"

    def test_key_for_instance_with_name(self):
        """Test key derivation when instance has name but no slug."""
        mock_instance = Mock()
        mock_instance.slug = None
        mock_instance.name = "provider_name"

        result = _key_for_instance(mock_instance)
        assert result == "provider_name"

    def test_key_for_instance_with_fallback(self):
        """Test key derivation with fallback value."""
        mock_instance = Mock()
        mock_instance.slug = None
        mock_instance.name = None

        result = _key_for_instance(mock_instance, fallback="fallback_name")
        assert result == "fallback_name"

    def test_key_for_instance_with_class_name(self):
        """Test key derivation falling back to class name."""
        mock_instance = Mock()
        mock_instance.slug = None
        mock_instance.name = None
        mock_instance.__class__.__name__ = "MockClass"

        result = _key_for_instance(mock_instance)
        assert result == "mockclass"

    def test_key_for_instance_case_conversion(self):
        """Test that key is converted to lowercase."""
        mock_instance = Mock()
        mock_instance.slug = "UPPER_CASE_SLUG"

        result = _key_for_instance(mock_instance)
        assert result == "upper_case_slug"


class TestBuildProviders:
    """Test provider building functionality."""

    def test_build_providers_mapping_with_kwargs(self):
        """Test building providers from mapping with kwargs."""
        config = {
            "mock": {"api_key": "test_key"}
        }

        # Register mock provider
        register_provider("mock", MockProvider)

        result = build_providers(config)

        assert "mock" in result
        assert isinstance(result["mock"], MockProvider)
        assert result["mock"].api_key == "test_key"

    def test_build_providers_mapping_with_instances(self):
        """Test building providers from mapping with instances."""
        mock_instance = MockProvider(api_key="test")
        config = {
            "mock": mock_instance
        }

        result = build_providers(config)

        assert "mock" in result
        assert result["mock"] == mock_instance

    def test_build_providers_mapping_with_custom_class(self):
        """Test building providers with custom class path."""
        config = {
            "custom": {
                "class": "tests.test_providers_init:MockProvider",
                "api_key": "custom_key"
            }
        }

        with patch("paymcp.providers._resolve_class") as mock_resolve:
            mock_resolve.return_value = MockProvider

            result = build_providers(config)

            assert "custom" in result
            assert isinstance(result["custom"], MockProvider)
            mock_resolve.assert_called_once_with("tests.test_providers_init:MockProvider")

    def test_build_providers_iterable_of_instances(self):
        """Test building providers from iterable of instances."""
        mock1 = MockProvider()
        mock1.slug = "provider1"
        mock2 = MockProvider()
        mock2.slug = "provider2"

        result = build_providers([mock1, mock2])

        assert "provider1" in result
        assert "provider2" in result
        assert result["provider1"] == mock1
        assert result["provider2"] == mock2

    def test_build_providers_unknown_provider(self):
        """Test building providers with unknown provider name."""
        config = {"unknown": {"api_key": "test"}}

        with pytest.raises(ValueError, match="Unknown provider: unknown"):
            build_providers(config)

    def test_build_providers_invalid_instance_type(self):
        """Test building providers with invalid instance type in mapping."""
        config = {"test": "not_a_provider_instance"}

        with pytest.raises(TypeError, match="must be an instance of BasePaymentProvider"):
            build_providers(config)

    def test_build_providers_invalid_class_type(self):
        """Test building providers with class that doesn't subclass BasePaymentProvider."""
        config = {
            "invalid": {
                "class": "builtins:str"
            }
        }

        with patch("paymcp.providers._resolve_class") as mock_resolve:
            mock_resolve.return_value = str  # str doesn't subclass BasePaymentProvider

            with pytest.raises(TypeError, match="must subclass BasePaymentProvider"):
                build_providers(config)

    def test_build_providers_constructed_instance_wrong_type(self):
        """Test when constructed instance is not BasePaymentProvider."""
        class BadProvider:
            def __init__(self, **kwargs):
                pass

        config = {"bad": {"api_key": "test"}}
        register_provider("bad", BadProvider)

        with pytest.raises(TypeError, match="Provider 'bad' must subclass BasePaymentProvider"):
            build_providers(config)

    def test_build_providers_isinstance_check_fails(self):
        """Test line 113: isinstance check after construction."""
        # Create a class that passes issubclass check but fails isinstance check
        # This is tricky - we need to mock the constructor to return wrong type

        class TrickyProvider(BasePaymentProvider):
            def __new__(cls, **kwargs):
                # Return a plain object instead of TrickyProvider instance
                return object()

            def create_payment(self, amount, currency, description):
                return "id", "url"

            def get_payment_status(self, payment_id):
                return "paid"

        config = {"tricky": {"api_key": "test"}}
        register_provider("tricky", TrickyProvider)

        # Should fail on line 113 isinstance check
        with pytest.raises(TypeError, match="Constructed provider for 'tricky' is not a BasePaymentProvider"):
            build_providers(config)

    def test_build_providers_iterable_invalid_type(self):
        """Test building providers from iterable with invalid types."""
        with pytest.raises(TypeError, match="contains non-provider instance"):
            build_providers(["not_a_provider", MockProvider()])

    def test_build_providers_invalid_input_type(self):
        """Test building providers with invalid input type."""
        with pytest.raises(TypeError, match="build_providers expects a mapping or an iterable"):
            build_providers(123)  # Use non-string, non-iterable type

    def test_build_providers_with_cls_key(self):
        """Test building providers using 'cls' key instead of 'class'."""
        config = {
            "custom": {
                "cls": "tests.test_providers_init:MockProvider",
                "api_key": "test_key"
            }
        }

        with patch("paymcp.providers._resolve_class") as mock_resolve:
            mock_resolve.return_value = MockProvider

            result = build_providers(config)

            assert "custom" in result
            mock_resolve.assert_called_once_with("tests.test_providers_init:MockProvider")

    def test_build_providers_empty_mapping(self):
        """Test building providers with empty mapping."""
        result = build_providers({})
        assert result == {}

    def test_build_providers_empty_iterable(self):
        """Test building providers with empty iterable."""
        result = build_providers([])
        assert result == {}

    def test_build_providers_mapping_none_name_with_instance(self):
        """Test building providers with None name in mapping but valid instance."""
        mock_instance = MockProvider()
        mock_instance.slug = "derived_name"
        config = {None: mock_instance}

        result = build_providers(config)

        assert "derived_name" in result
        assert result["derived_name"] == mock_instance

    def test_build_providers_case_insensitive_provider_lookup(self):
        """Test that provider lookup is case insensitive."""
        register_provider("TEST_PROVIDER", MockProvider)
        config = {"test_provider": {"api_key": "test"}}

        result = build_providers(config)

        assert "test_provider" in result
        assert isinstance(result["test_provider"], MockProvider)

    def test_build_providers_kwargs_shallow_copy(self):
        """Test that kwargs are shallow copied before modification."""
        original_config = {"api_key": "test"}
        config = {"provider": original_config}

        register_provider("provider", MockProvider)

        # This should not modify the original config
        result = build_providers(config)

        # Original config should not be modified
        assert "api_key" in original_config
        assert len(original_config) == 1  # Should still only have api_key

    # Note: Line 110 coverage is difficult to test due to isinstance complexity
    # The line is: raise TypeError(f"Constructed provider for '{name}' is not a BasePaymentProvider (got {type(obj).__name__})")
    # This would only be reached if an object passes issubclass check but fails isinstance check after construction
    # This is an extremely rare edge case that's difficult to reproduce in practice

    def test_build_providers_exactly_line_123(self):
        """Test exactly line 123 for complete coverage."""
        # Line 123 should be triggered by non-mapping, non-iterable input
        # Using a custom object that's neither
        class NotIterableNotMapping:
            pass

        obj = NotIterableNotMapping()

        with pytest.raises(TypeError, match="build_providers expects a mapping or an iterable"):
            build_providers(obj)