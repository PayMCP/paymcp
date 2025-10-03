"""Tests for MockPaymentProvider."""

import pytest
import time
from paymcp.providers.mock import MockPaymentProvider


def test_mock_provider_initialization():
    """Test basic initialization of MockPaymentProvider."""
    provider = MockPaymentProvider()
    assert provider.api_key == "mock"
    assert provider.default_status == "paid"
    assert provider.auto_confirm is False
    assert provider.confirm_delay == 0


def test_mock_provider_with_custom_config():
    """Test MockPaymentProvider with custom configuration."""
    provider = MockPaymentProvider(
        api_key="custom_mock",
        default_status="pending",
        auto_confirm=True,
        confirm_delay=2.0
    )
    assert provider.api_key == "custom_mock"
    assert provider.default_status == "pending"
    assert provider.auto_confirm is True
    assert provider.confirm_delay == 2.0


def test_create_payment():
    """Test payment creation with status prefix."""
    provider = MockPaymentProvider()
    payment_id, payment_url = provider.create_payment(
        amount=10.50,
        currency="USD",
        description="Test payment"
    )

    # Verify payment ID format: mock_{status}_{16_hex_chars}
    assert payment_id.startswith("mock_paid_")  # default_status is "paid"
    parts = payment_id.split("_")
    assert len(parts) == 3  # ["mock", "paid", "hex"]
    assert len(parts[2]) == 16  # hex part is 16 chars

    # Verify payment URL format
    assert payment_url == f"https://mock-payment.local/pay/{payment_id}"

    # Verify payment is stored
    details = provider.get_payment_details(payment_id)
    assert details is not None
    assert details['amount'] == 10.50
    assert details['currency'] == "USD"
    assert details['description'] == "Test payment"
    assert details['status'] == "paid"  # default_status


def test_get_payment_status_paid():
    """Test getting payment status for paid payment."""
    provider = MockPaymentProvider(default_status="paid")
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    status = provider.get_payment_status(payment_id)
    assert status == "paid"


def test_get_payment_status_pending():
    """Test getting payment status for pending payment."""
    provider = MockPaymentProvider(default_status="pending")
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    status = provider.get_payment_status(payment_id)
    assert status == "pending"


def test_get_payment_status_failed():
    """Test getting payment status for failed payment."""
    provider = MockPaymentProvider(default_status="failed")
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    status = provider.get_payment_status(payment_id)
    assert status == "failed"


def test_get_payment_status_not_found():
    """Test getting status for non-existent payment returns expired."""
    provider = MockPaymentProvider()
    status = provider.get_payment_status("nonexistent_payment_id")
    assert status == "expired"  # Unknown payments treated as expired


def test_set_payment_status():
    """Test manually setting payment status."""
    provider = MockPaymentProvider(default_status="pending")
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    # Verify initial status
    assert provider.get_payment_status(payment_id) == "pending"

    # Change status to paid
    provider.set_payment_status(payment_id, "paid")
    assert provider.get_payment_status(payment_id) == "paid"

    # Change status to failed
    provider.set_payment_status(payment_id, "failed")
    assert provider.get_payment_status(payment_id) == "failed"


def test_set_payment_status_invalid_payment():
    """Test setting status for non-existent payment."""
    provider = MockPaymentProvider()
    # Should not raise error, just log warning
    provider.set_payment_status("nonexistent_id", "paid")


def test_auto_confirm_disabled():
    """Test that auto_confirm=False keeps status as set."""
    provider = MockPaymentProvider(default_status="pending", auto_confirm=False)
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    # Check immediately
    assert provider.get_payment_status(payment_id) == "pending"

    # Check after delay
    time.sleep(0.5)
    assert provider.get_payment_status(payment_id) == "pending"


def test_auto_confirm_instant():
    """Test auto_confirm with zero delay."""
    provider = MockPaymentProvider(
        default_status="paid",
        auto_confirm=True,
        confirm_delay=0
    )
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    # Payment should be pending initially
    details = provider.get_payment_details(payment_id)
    assert details['status'] == "pending"

    # Should immediately become paid on first check
    assert provider.get_payment_status(payment_id) == "paid"

    # Verify status was updated in storage
    details = provider.get_payment_details(payment_id)
    assert details['status'] == "paid"


def test_auto_confirm_with_delay():
    """Test auto_confirm with delay."""
    provider = MockPaymentProvider(
        default_status="paid",
        auto_confirm=True,
        confirm_delay=0.5
    )
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    # Should be pending before delay
    assert provider.get_payment_status(payment_id) == "pending"

    # Wait for delay to pass
    time.sleep(0.6)

    # Should now be paid
    assert provider.get_payment_status(payment_id) == "paid"


def test_get_payment_details():
    """Test getting full payment details."""
    provider = MockPaymentProvider()
    payment_id, _ = provider.create_payment(25.99, "EUR", "Premium service")

    details = provider.get_payment_details(payment_id)
    assert details['amount'] == 25.99
    assert details['currency'] == "EUR"
    assert details['description'] == "Premium service"
    assert details['status'] == "paid"
    assert 'created_at' in details
    assert 'metadata' in details


def test_get_payment_details_not_found():
    """Test getting details for non-existent payment."""
    provider = MockPaymentProvider()
    details = provider.get_payment_details("nonexistent_id")
    assert details == {}


def test_clear_payments():
    """Test clearing all payments."""
    provider = MockPaymentProvider()

    # Create multiple payments
    id1, _ = provider.create_payment(1.00, "USD", "Test 1")
    id2, _ = provider.create_payment(2.00, "USD", "Test 2")

    # Verify payments exist
    assert provider.get_payment_details(id1) != {}
    assert provider.get_payment_details(id2) != {}

    # Clear all payments
    provider.clear_payments()

    # Verify payments are gone
    assert provider.get_payment_details(id1) == {}
    assert provider.get_payment_details(id2) == {}


def test_multiple_payments_independent():
    """Test that multiple payments have independent states."""
    provider = MockPaymentProvider(default_status="pending")

    id1, _ = provider.create_payment(1.00, "USD", "Payment 1")
    id2, _ = provider.create_payment(2.00, "USD", "Payment 2")

    # Set different statuses
    provider.set_payment_status(id1, "paid")
    provider.set_payment_status(id2, "failed")

    # Verify independent states
    assert provider.get_payment_status(id1) == "paid"
    assert provider.get_payment_status(id2) == "failed"


def test_auto_confirm_only_affects_pending():
    """Test that auto_confirm only changes pending payments."""
    provider = MockPaymentProvider(
        default_status="failed",
        auto_confirm=True,
        confirm_delay=0
    )
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    # Manually set to failed (not pending)
    provider.set_payment_status(payment_id, "failed")

    # Auto-confirm should not change non-pending status
    assert provider.get_payment_status(payment_id) == "failed"


def test_payment_id_uniqueness():
    """Test that generated payment IDs are unique."""
    provider = MockPaymentProvider()

    ids = set()
    for _ in range(100):
        payment_id, _ = provider.create_payment(1.00, "USD", "Test")
        ids.add(payment_id)

    # All IDs should be unique
    assert len(ids) == 100


def test_payment_id_prefix_hint_paid():
    """Test that payment_id prefix determines status (paid)."""
    provider = MockPaymentProvider()

    # Query with a payment_id that has "paid" prefix (not in storage)
    status = provider.get_payment_status("mock_paid_abc123def456")
    assert status == "paid"


def test_payment_id_prefix_hint_failed():
    """Test that payment_id prefix determines status (failed)."""
    provider = MockPaymentProvider()

    # Query with a payment_id that has "failed" prefix (not in storage)
    status = provider.get_payment_status("mock_failed_xyz789abc123")
    assert status == "failed"


def test_payment_id_prefix_hint_pending():
    """Test that payment_id prefix determines status (pending)."""
    provider = MockPaymentProvider()

    # Query with a payment_id that has "pending" prefix (not in storage)
    status = provider.get_payment_status("mock_pending_111222333444")
    assert status == "pending"


def test_payment_id_prefix_hint_cancelled():
    """Test that payment_id prefix determines status (cancelled)."""
    provider = MockPaymentProvider()

    # Query with a payment_id that has "cancelled" prefix (not in storage)
    status = provider.get_payment_status("mock_cancelled_aabbccddee")
    assert status == "cancelled"


def test_payment_id_prefix_hint_expired():
    """Test that payment_id prefix determines status (expired)."""
    provider = MockPaymentProvider()

    # Query with a payment_id that has "expired" prefix (not in storage)
    status = provider.get_payment_status("mock_expired_ffeeddccbbaa")
    assert status == "expired"


def test_payment_id_prefix_with_different_default():
    """Test that created payment IDs use configured default_status."""
    provider = MockPaymentProvider(default_status="failed")

    payment_id, _ = provider.create_payment(1.00, "USD", "Test")

    # Payment ID should have "failed" prefix
    assert payment_id.startswith("mock_failed_")

    # Status query should return "failed"
    assert provider.get_payment_status(payment_id) == "failed"


def test_storage_overrides_prefix_hint():
    """Test that stored status takes precedence over prefix hint."""
    provider = MockPaymentProvider(default_status="pending")

    # Create payment with "pending" prefix
    payment_id, _ = provider.create_payment(1.00, "USD", "Test")
    assert payment_id.startswith("mock_pending_")
    assert provider.get_payment_status(payment_id) == "pending"

    # Manually change status to "paid"
    provider.set_payment_status(payment_id, "paid")

    # Stored status should override prefix hint
    assert provider.get_payment_status(payment_id) == "paid"


def test_prefix_hint_invalid_status():
    """Test that invalid status prefixes fall back to expired."""
    provider = MockPaymentProvider()

    # Query with invalid status prefix
    status = provider.get_payment_status("mock_invalid_abc123")
    assert status == "expired"


def test_prefix_hint_no_status_part():
    """Test that payment_id without status part returns expired."""
    provider = MockPaymentProvider()

    # Query with only "mock_" prefix (no status part)
    status = provider.get_payment_status("mock_abc123")
    assert status == "expired"