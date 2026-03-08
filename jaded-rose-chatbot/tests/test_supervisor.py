"""Tests for the Supervisor intent-classification and routing logic."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.supervisor import Supervisor, ORDER_TRACKING, FAQ, GREETING, ESCALATE


@pytest.fixture
def supervisor() -> Supervisor:
    """Return a Supervisor with mocked dependencies."""
    sup = Supervisor()
    sup._memory = MagicMock()
    sup._memory.get_history = AsyncMock(return_value=[])
    sup._memory.add_message = AsyncMock()
    sup._escalation = MagicMock()
    sup._escalation.escalate = AsyncMock(
        return_value="I'm connecting you with our customer experience team."
    )
    return sup


@pytest.mark.asyncio
async def test_greeting_intent(supervisor: Supervisor) -> None:
    """Greetings should return a welcome message without calling an agent."""
    classification = {"intent": GREETING, "confidence": 0.95, "entities": {}}
    with patch.object(supervisor, "_classify_intent", new=AsyncMock(return_value=classification)):
        response = await supervisor.process("Hey!", session_id="test-1", channel="web")

    assert response  # non-empty
    assert "Jaded Rose" in response or "help" in response.lower()
    supervisor._memory.add_message.assert_called()


@pytest.mark.asyncio
async def test_escalation_on_low_confidence(supervisor: Supervisor) -> None:
    """Low-confidence intents should trigger escalation."""
    classification = {"intent": FAQ, "confidence": 0.4, "entities": {}}
    with patch.object(supervisor, "_classify_intent", new=AsyncMock(return_value=classification)):
        response = await supervisor.process("blah blah", session_id="test-2", channel="telegram")

    supervisor._escalation.escalate.assert_awaited_once()
    assert "team" in response.lower() or "connecting" in response.lower()


@pytest.mark.asyncio
async def test_explicit_escalation_intent(supervisor: Supervisor) -> None:
    """Intent=ESCALATE should always escalate regardless of confidence."""
    classification = {"intent": ESCALATE, "confidence": 0.99, "entities": {}}
    with patch.object(supervisor, "_classify_intent", new=AsyncMock(return_value=classification)):
        response = await supervisor.process(
            "I want to speak to a human", session_id="test-3", channel="whatsapp"
        )

    supervisor._escalation.escalate.assert_awaited_once()


@pytest.mark.asyncio
async def test_order_tracking_routes_to_agent(supervisor: Supervisor) -> None:
    """ORDER_TRACKING intent should route to the OrderAgent."""
    classification = {"intent": ORDER_TRACKING, "confidence": 0.92, "entities": {"order_number": "JR-4821"}}
    mock_agent = MagicMock()
    mock_agent.handle = AsyncMock(return_value="Your order JR-4821 is on its way!")

    with patch.object(supervisor, "_classify_intent", new=AsyncMock(return_value=classification)):
        with patch.object(supervisor, "_get_agent", return_value=mock_agent):
            response = await supervisor.process(
                "Where is order #JR-4821?", session_id="test-4", channel="web"
            )

    mock_agent.handle.assert_awaited_once()
    assert "JR-4821" in response


@pytest.mark.asyncio
async def test_out_of_scope(supervisor: Supervisor) -> None:
    """OUT_OF_SCOPE should return a polite deflection without escalation."""
    classification = {"intent": "OUT_OF_SCOPE", "confidence": 0.88, "entities": {}}
    with patch.object(supervisor, "_classify_intent", new=AsyncMock(return_value=classification)):
        response = await supervisor.process(
            "What is the meaning of life?", session_id="test-5", channel="web"
        )

    assert "outside" in response.lower() or "area" in response.lower()
    supervisor._escalation.escalate.assert_not_awaited()
