"""Returns Agent — walks customers through the returns & exchange process.

Retrieves the Jaded Rose returns policy from Pinecone for grounding, then
uses GPT-4o to guide the customer step-by-step through initiating a return.
Collects the order number, item details and reason, and generates a unique
returns reference.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Dict, List

import openai
from pinecone import Pinecone

logger = logging.getLogger(__name__)

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
PINECONE_API_KEY: str = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX: str = os.getenv("PINECONE_INDEX", "jaded-rose")
NS_FAQS: str = "faqs"

_SYSTEM_PROMPT = """\
You are the Jaded Rose returns assistant — helpful, empathetic and efficient.
You help customers return or exchange items purchased from Jaded Rose (UK clothing store).

Use the RETURNS POLICY below as your single source of truth.  Never invent policy details.

RETURNS POLICY:
{policy}

YOUR TASK:
Guide the customer through the return process step by step:
1. Confirm which order and item they want to return.
2. Check the reason (wrong size, changed mind, faulty, etc.).
3. Confirm the item meets the policy requirements (30 days, unworn, tags on).
4. Provide their returns reference number: {returns_ref}
5. Give clear next-step instructions.

If the return is outside policy, explain kindly and suggest alternatives (exchange, store credit).
Keep replies concise and warm.
"""


class ReturnsAgent:
    """Specialist agent for returns and exchanges."""

    def __init__(self) -> None:
        """Initialise the returns agent."""
        self._openai = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        pc = Pinecone(api_key=PINECONE_API_KEY)
        self._index = pc.Index(PINECONE_INDEX)

    async def _embed(self, text: str) -> List[float]:
        """Generate an embedding vector.

        Args:
            text: Input text.

        Returns:
            Embedding as a list of floats.
        """
        response = await self._openai.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding

    async def _get_returns_policy(self) -> str:
        """Retrieve the returns policy from Pinecone.

        Returns:
            The policy text, or a sensible fallback.
        """
        query = "returns policy refund exchange"
        embedding = await self._embed(query)
        results = self._index.query(
            vector=embedding,
            top_k=5,
            namespace=NS_FAQS,
            include_metadata=True,
        )

        chunks: list[str] = []
        for match in results.get("matches", []):
            text = match.get("metadata", {}).get("text", "")
            if text:
                chunks.append(text)

        if chunks:
            return "\n---\n".join(chunks)

        # Fallback policy summary
        return (
            "30-day return window from delivery date. Items must be unworn, "
            "unwashed, with original tags attached. Refunds processed within "
            "5-10 business days of receiving the return. Customer covers return "
            "shipping unless the item is faulty."
        )

    def _generate_returns_ref(self) -> str:
        """Generate a short unique returns reference number.

        Returns:
            A reference string like ``RET-A1B2C3``.
        """
        short_id = uuid.uuid4().hex[:6].upper()
        return f"RET-{short_id}"

    async def handle(self, message: str, history: List[Dict[str, str]]) -> str:
        """Handle a returns or exchange query.

        Args:
            message: The customer's message.
            history: Recent conversation history.

        Returns:
            A helpful reply guiding the customer through the return process.
        """
        policy = await self._get_returns_policy()
        returns_ref = self._generate_returns_ref()

        system_prompt = _SYSTEM_PROMPT.format(
            policy=policy,
            returns_ref=returns_ref,
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        response = await self._openai.chat.completions.create(
            model="gpt-4o",
            temperature=0.2,
            messages=messages,
        )

        return response.choices[0].message.content or (
            "I'd be happy to help with your return! Could you share your order "
            "number and which item you'd like to return? 🔄"
        )
