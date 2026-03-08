"""Tests for the OrderTracker carrier auto-detection logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tracking.tracker import OrderTracker


@pytest.fixture
def tracker() -> OrderTracker:
    """Return an OrderTracker with mocked carrier instances."""
    t = OrderTracker()
    t._royal_mail = MagicMock()
    t._dhl = MagicMock()
    t._evri = MagicMock()
    t._dpd = MagicMock()
    return t


class TestCarrierDetection:
    """Test that tracking numbers are mapped to the correct carrier."""

    def test_royal_mail_format(self) -> None:
        """Royal Mail: 2 letters + 9 digits + 2 letters."""
        tracker = OrderTracker()
        assert tracker._detect_carrier("AB123456789GB") == "royal_mail"

    def test_dhl_jd_format(self) -> None:
        """DHL: starts with JD followed by digits."""
        tracker = OrderTracker()
        assert tracker._detect_carrier("JD0123456789") == "dhl"

    def test_dhl_10_digit(self) -> None:
        """DHL: plain 10-digit number."""
        tracker = OrderTracker()
        assert tracker._detect_carrier("1234567890") == "dhl"

    def test_dpd_14_digit(self) -> None:
        """DPD: exactly 14 digits."""
        tracker = OrderTracker()
        assert tracker._detect_carrier("12345678901234") == "dpd"

    def test_evri_15_char(self) -> None:
        """Evri: 15 alphanumeric characters."""
        tracker = OrderTracker()
        assert tracker._detect_carrier("ABCDEF123456789") == "evri"

    def test_evri_16_char(self) -> None:
        """Evri: 16 alphanumeric characters."""
        tracker = OrderTracker()
        assert tracker._detect_carrier("ABCDEF1234567890") == "evri"

    def test_unknown_format(self) -> None:
        """Unrecognised formats should return None."""
        tracker = OrderTracker()
        assert tracker._detect_carrier("XYZ") is None

    def test_case_insensitive(self) -> None:
        """Detection should be case-insensitive."""
        tracker = OrderTracker()
        assert tracker._detect_carrier("ab123456789gb") == "royal_mail"


@pytest.mark.asyncio
async def test_routes_to_royal_mail(tracker: OrderTracker) -> None:
    """Royal Mail tracking numbers should call the Royal Mail tracker."""
    tracker._royal_mail.track = AsyncMock(
        return_value={
            "carrier": "Royal Mail",
            "status": "Delivered",
            "estimated_delivery": "",
            "last_event": "Delivered to letterbox",
            "tracking_url": "https://royalmail.com/track/AB123456789GB",
            "events": [],
        }
    )

    result = await tracker.track("AB123456789GB")
    assert result["carrier"] == "Royal Mail"
    assert result["status"] == "Delivered"
    tracker._royal_mail.track.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_on_unknown_format(tracker: OrderTracker) -> None:
    """Unknown formats should try all carriers in sequence."""
    tracker._royal_mail.track = AsyncMock(
        return_value={"status": "not_found"}
    )
    tracker._dhl.track = AsyncMock(
        return_value={
            "carrier": "DHL",
            "status": "In Transit",
            "estimated_delivery": "2025-03-12",
            "last_event": "Package in transit",
            "tracking_url": "https://dhl.com/track",
            "events": [],
        }
    )

    result = await tracker.track("UNKNOWNFORMAT")
    assert result["carrier"] == "DHL"
    assert result["status"] == "In Transit"


@pytest.mark.asyncio
async def test_all_carriers_fail(tracker: OrderTracker) -> None:
    """When every carrier fails, return a not_found result."""
    for carrier in [tracker._royal_mail, tracker._dhl, tracker._evri, tracker._dpd]:
        carrier.track = AsyncMock(return_value={"status": "not_found"})

    result = await tracker.track("UNKNOWNFORMAT")
    assert result["status"] == "not_found"
    assert result["carrier"] == "Unknown"
