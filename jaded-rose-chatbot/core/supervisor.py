"""Supervisor — central intent-detection and agent-routing engine.

Every inbound message from any channel passes through the Supervisor.  It
uses GPT-4o to classify the customer's intent, selects the appropriate
specialist agent, and returns a response.  When confidence is low or the
customer explicitly asks for a human, the Escalation Manager takes over.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import openai

from core.memory import ConversationMemory
from core.escalation import EscalationManager

logger = logging.getLogger(__name__)

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# ── Intent constants ────────────────────────────────────────────────────
ORDER_TRACKING = "ORDER_TRACKING"
FAQ = "FAQ"
PRODUCT_QUERY = "PRODUCT_QUERY"
RETURNS = "RETURNS"
COMPLAINT = "COMPLAINT"
ESCALATE = "ESCALATE"
GREETING = "GREETING"
OUT_OF_SCOPE = "OUT_OF_SCOPE"

_INTENT_LIST = [
    ORDER_TRACKING,
    FAQ,
    PRODUCT_QUERY,
    RETURNS,
    COMPLAINT,
    ESCALATE,
    GREETING,
    OUT_OF_SCOPE,
]

_CLASSIFICATION_SYSTEM_PROMPT = """\
You are an intent classifier for Jaded Rose, a UK online clothing store.

Given a customer message and recent conversation history, return JSON with:
- "intent": one of {intents}
- "confidence": float 0.0 – 1.0
- "entities": dict of extracted entities (e.g. order_number, product_name, size)

Rules:
- ORDER_TRACKING: customer asks about order status, delivery, tracking.
- FAQ: general questions about shipping, payments, sizing, care, brand info.
- PRODUCT_QUERY: asking about a specific product, availability, colour, size.
- RETURNS: wants to return, exchange, or has a return-related question.
- COMPLAINT: unhappy customer, damaged item, wrong item, service issue.
- ESCALATE: explicitly asks for a human agent / manager.
- GREETING: simple hello, hi, hey, good morning, etc.
- OUT_OF_SCOPE: unrelated to shopping / the store.

Respond with ONLY the JSON object, no markdown fences.
""".format(intents=", ".join(_INTENT_LIST))

_GREETING_RESPONSES = [
    "Hey there! 👋 Welcome to Jaded Rose. How can I help you today?",
    "Hi! ✨ I'm the Jaded Rose assistant — ask me anything about orders, products, returns or sizing!",
    "Hello! 💬 What can I help you with today?",
]


class Supervisor:
    """Routes customer messages to the correct specialist agent.

    Flow
    ----
    1. Load conversation history from Redis.
    2. Classify the intent with GPT-4o.
    3. Dispatch to the matching agent.
    4. If confidence < 0.7 or intent is ESCALATE/COMPLAINT → escalate.
    5. Persist the exchange in conversation memory.
    """

    def __init__(self) -> None:
        """Initialise the Supervisor with memory, escalation and lazy agents."""
        self._memory = ConversationMemory()
        self._escalation = EscalationManager()
        self._openai = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        self._agents: Dict[str, Any] = {}

    def _get_agent(self, intent: str):
        """Lazily import and cache the agent for a given intent.

        Args:
            intent: The classified intent string.

        Returns:
            An agent instance with a ``handle`` or ``answer`` method.
        """
        if intent not in self._agents:
            if intent == ORDER_TRACKING:
                from agents.order_agent import OrderAgent
                self._agents[intent] = OrderAgent()
            elif intent == FAQ:
                from agents.faq_agent import FAQAgent
                self._agents[intent] = FAQAgent()
            elif intent == PRODUCT_QUERY:
                from agents.product_agent import ProductAgent
                self._agents[intent] = ProductAgent()
            elif intent == RETURNS:
                from agents.returns_agent import ReturnsAgent
                self._agents[intent] = ReturnsAgent()
        return self._agents.get(intent)

    async def _classify_intent(
        self, message: str, history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Use GPT-4o to classify the customer's intent.

        Args:
            message: The latest customer message.
            history: Recent conversation messages.

        Returns:
            Dict with keys ``intent``, ``confidence``, ``entities``.
        """
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in history[-6:]
        )
        user_prompt = (
            f"Conversation history:\n{history_text}\n\nLatest message:\n{message}"
        )

        try:
            response = await self._openai.chat.completions.create(
                model="gpt-4o",
                temperature=0.0,
                messages=[
                    {"role": "system", "content": _CLASSIFICATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = response.choices[0].message.content or "{}"
            result = json.loads(raw)
            return {
                "intent": result.get("intent", OUT_OF_SCOPE),
                "confidence": float(result.get("confidence", 0.0)),
                "entities": result.get("entities", {}),
            }
        except (json.JSONDecodeError, KeyError, IndexError):
            logger.exception("Intent classification failed — defaulting to FAQ")
            return {"intent": FAQ, "confidence": 0.5, "entities": {}}

    async def process(
        self, message: str, session_id: str, channel: str
    ) -> str:
        """Process a customer message end-to-end and return a reply.

        Args:
            message: The customer's message text.
            session_id: Unique session identifier (channel-specific).
            channel: The originating channel (telegram, whatsapp, gmail, web).

        Returns:
            The response text to send back to the customer.
        """
        # 1. Load history and append the new message
        history = await self._memory.get_history(session_id)
        await self._memory.add_message(session_id, "user", message)

        # 2. Classify intent
        classification = await self._classify_intent(message, history)
        intent = classification["intent"]
        confidence = classification["confidence"]
        entities = classification["entities"]

        logger.info(
            "Session %s | intent=%s confidence=%.2f entities=%s",
            session_id, intent, confidence, entities,
        )

        # 3. Low-confidence or explicit escalation
        if confidence < 0.7 or intent in (ESCALATE, COMPLAINT):
            response = await self._escalation.escalate(
                session_id=session_id,
                channel=channel,
                reason=f"intent={intent} confidence={confidence:.2f}",
                conversation_history=history,
            )
            await self._memory.add_message(session_id, "assistant", response)
            return response

        # 4. Greeting
        if intent == GREETING:
            import random
            response = random.choice(_GREETING_RESPONSES)
            await self._memory.add_message(session_id, "assistant", response)
            return response

        # 5. Out of scope
        if intent == OUT_OF_SCOPE:
            response = (
                "That's a bit outside my area! I'm best at helping with orders, "
                "products, sizing and returns for Jaded Rose. "
                "Is there something along those lines I can help with? 😊"
            )
            await self._memory.add_message(session_id, "assistant", response)
            return response

        # 6. Route to specialist agent
        agent = self._get_agent(intent)
        if agent is None:
            response = (
                "I'm not quite sure how to help with that — let me connect you "
                "with someone from our team."
            )
            await self._escalation.escalate(
                session_id=session_id,
                channel=channel,
                reason=f"No agent for intent={intent}",
                conversation_history=history,
            )
            await self._memory.add_message(session_id, "assistant", response)
            return response

        try:
            if hasattr(agent, "answer"):
                response = await agent.answer(query=message, history=history)
            else:
                response = await agent.handle(message=message, history=history)
        except Exception:
            logger.exception("Agent error for intent %s, session %s", intent, session_id)
            response = (
                "Sorry, I ran into an issue looking that up. "
                "Let me connect you with our team so they can help directly."
            )
            await self._escalation.escalate(
                session_id=session_id,
                channel=channel,
                reason=f"Agent exception for intent={intent}",
                conversation_history=history,
            )

        await self._memory.add_message(session_id, "assistant", response)
        return response
