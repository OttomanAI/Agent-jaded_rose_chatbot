"""Tests for the OrderAgent — order number extraction and response flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.order_agent import OrderAgent


@pytest.fixture
def agent() -> OrderAgent:
    """Return an OrderAgent with mocked tracking dependencies."""
    a = OrderAgent()
    a._fulfillment = MagicMock()
    a._tracker = MagicMock()
    return a


class TestOrderNumberExtraction:
    """Test the regex-based order number extraction."""

    def test_hash_prefix(self) -> None:
        """Should extract from '#JR-4821' format."""
        agent = OrderAgent()
        assert agent._extract_order_number("Where is #JR-4821?") == "JR-4821"

    def test_no_hash(self) -> None:
        """Should extract from 'JR-4821' without hash."""
        agent = OrderAgent()
        assert agent._extract_order_number("Track JR-4821 please") == "JR-4821"

    def test_order_number_keyword(self) -> None:
        """Should extract from 'order number 4821'."""
        agent = OrderAgent()
        result = agent._extract_order_number("Can you check order number 4821")
        assert result == "JR-4821"

    def test_bare_number(self) -> None:
        """Should extract a bare 4-6 digit number as fallback."""
        agent = OrderAgent()
        result = agent._extract_order_number("my order is 12345")
        assert result == "JR-12345"

    def test_no_match(self) -> None:
        """Should return None when no order number is found."""
        agent = OrderAgent()
        assert agent._extract_order_number("Hello, I need help") is None

    def test_case_insensitive(self) -> None:
        """Should handle lowercase 'jr-' prefix."""
        agent = OrderAgent()
        assert agent._extract_order_number("jr-5500") == "JR-5500"


@pytest.mark.asyncio
async def test_asks_for_order_number_when_missing(agent: OrderAgent) -> None:
    """When no order number is in the message or history, prompt the customer."""
    response = await agent.handle("Where is my order?", history=[])
    assert "order number" in response.lower()


@pytest.mark.asyncio
async def test_unfulfilled_order(agent: OrderAgent) -> None:
    """Unfulfilled orders should tell the customer it hasn't shipped yet."""
    agent._fulfillment.get_tracking_from_order = AsyncMock(
        return_value={
            "tracking_number": "",
            "carrier": "",
            "fulfillment_status": "unfulfilled",
        }
    )
    response = await agent.handle("Where is #JR-1001?", history=[])
    assert "hasn't shipped" in response.lower() or "being prepared" in response.lower()


@pytest.mark.asyncio
async def test_fulfilled_order_with_tracking(agent: OrderAgent) -> None:
    """Fulfilled orders should return tracking info from the carrier."""
    agent._fulfillment.get_tracking_from_order = AsyncMock(
        return_value={
            "tracking_number": "AB123456789GB",
            "carrier": "Royal Mail",
            "fulfillment_status": "fulfilled",
        }
    )
    agent._tracker.track = AsyncMock(
        return_value={
            "carrier": "Royal Mail",
            "status": "In Transit",
            "estimated_delivery": "2025-03-10",
            "last_event": "Parcel received at sorting office",
            "tracking_url": "https://royalmail.com/track/AB123456789GB",
            "events": [],
        }
    )

    response = await agent.handle("Track order JR-1002", history=[])
    assert "JR-1002" in response
    assert "In Transit" in response or "Royal Mail" in response


@pytest.mark.asyncio
async def test_order_not_found(agent: OrderAgent) -> None:
    """Unknown order numbers should get a friendly 'not found' message."""
    agent._fulfillment.get_tracking_from_order = AsyncMock(return_value=None)
    response = await agent.handle("Track #JR-9999", history=[])
    assert "couldn't find" in response.lower() or "not found" in response.lower()
