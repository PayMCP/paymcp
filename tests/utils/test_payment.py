"""Tests for payment utilities."""

import pytest
from paymcp.utils.payment import normalize_status


class TestNormalizeStatus:
    """Test suite for normalize_status function."""

    def test_normalize_paid_statuses(self):
        """Test normalization of paid statuses."""
        paid_statuses = [
            "paid",
            "PAID",
            "complete",
            "completed",
            "COMPLETED",
            "succeeded",
            "success",
            "captured",
            "CAPTURED",
            "confirmed",
            "CONFIRMED",
            "approved",
            "APPROVED",
        ]

        for status in paid_statuses:
            assert normalize_status(status) == "paid", f"Failed for {status}"

    def test_normalize_canceled_statuses(self):
        """Test normalization of canceled statuses."""
        canceled_statuses = [
            "canceled",
            "cancelled",
            "CANCELLED",
            "failed",
            "FAILED",
            "expired",
            "EXPIRED",
            "error",
            "ERROR",
            "refused",
            "REFUSED",
            "rejected",
            "REJECTED",
            "voided",
            "VOIDED",
        ]

        for status in canceled_statuses:
            assert normalize_status(status) == "canceled", f"Failed for {status}"

    def test_normalize_pending_statuses(self):
        """Test normalization of pending statuses."""
        pending_statuses = [
            "pending",
            "PENDING",
            "processing",
            "PROCESSING",
            "waiting",
            "WAITING",
            "initiated",
            "INITIATED",
            "unknown",
            "some-random-status",
            "",
        ]

        for status in pending_statuses:
            assert normalize_status(status) == "pending", f"Failed for {status}"

    def test_handle_none(self):
        """Test handling of None value."""
        assert normalize_status(None) == "pending"

    def test_handle_non_string(self):
        """Test handling of non-string values."""
        assert normalize_status(123) == "pending"
        assert normalize_status([]) == "pending"
        assert normalize_status({}) == "pending"
        assert normalize_status(True) == "pending"

    def test_case_insensitive(self):
        """Test that normalization is case-insensitive."""
        assert normalize_status("PaId") == "paid"
        assert normalize_status("CaNcElEd") == "canceled"
        assert normalize_status("PeNdInG") == "pending"

    def test_whitespace_handling(self):
        """Test handling of whitespace in status strings."""
        assert normalize_status("  paid  ") == "paid"
        assert normalize_status("\tcanceled\n") == "canceled"
        assert normalize_status(" pending ") == "pending"

    def test_object_without_str_method(self):
        """Test with object that raises exception when converting to string."""

        class BadObject:
            def __str__(self):
                raise Exception("Cannot convert to string")

        result = normalize_status(BadObject())
        assert result == "pending"
