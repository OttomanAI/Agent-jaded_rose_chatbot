"""FAQ Agent — answers general questions using RAG over the knowledge base.

Embeds the customer query, retrieves the most relevant FAQ chunks from
Pinecone, and uses GPT-4o to generate a grounded, on-brand response.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List

import openai
from pinecone import Pinecone

logger = logging.getLogger(__name__)

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
PINECONE_API_KEY: str = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX: str = os.getenv("PINECONE_INDEX", "jaded-rose")
NS_FAQS: str = "faqs"

_SYSTEM_PROMPT = """\
You are the Jaded Rose AI assistant — warm, helpful and concise.
You work for a UK online clothing store called Jaded Rose.

Answer the customer's question using ONLY the context provided below.
If the context does not contain enough information to answer confidently,
say so honestly and offer to connect them with the team.

Keep replies short (2-4 sentences) unless the customer needs step-by-step
instructions.  Use a friendly, professional tone.  Emoji are fine sparingly.

CONTEXT:
{context}
"""


class FAQAgent:
    """Retrieval-augmented FAQ answering agent."""

    def __init__(self) -> None:
        """Initialise OpenAI and Pinecone clients."""
        self._openai = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        pc = Pinecone(api_key=PINECONE_API_KEY)
        self._index = pc.Index(PINECONE_INDEX)

    async def _embed(self, text: str) -> List[float]:
        """Generate an embedding for the given text.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        response = await self._openai.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding

    async def _retrieve(self, query: str, top_k: int = 5) -> str:
        """Query Pinecone for the most relevant FAQ chunks.

        Args:
            query: The customer's question.
            top_k: Number of results to return.

        Returns:
            Concatenated text of the top matching chunks.
        """
        embedding = await self._embed(query)
        results = self._index.query(
            vector=embedding,
            top_k=top_k,
            namespace=NS_FAQS,
            include_metadata=True,
        )

        chunks: list[str] = []
        for match in results.get("matches", []):
            text = match.get("metadata", {}).get("text", "")
            score = match.get("score", 0)
            if text and score > 0.3:
                chunks.append(text)

        return "\n---\n".join(chunks) if chunks else ""

    async def answer(self, query: str, history: List[Dict[str, str]]) -> str:
        """Answer a customer FAQ using retrieval-augmented generation.

        Args:
            query: The customer's question.
            history: Recent conversation history.

        Returns:
            The generated answer, or an escalation-flagging message.
        """
        context = await self._retrieve(query)

        if not context:
            return (
                "I couldn't find specific information about that in our knowledge base. "
                "Let me connect you with our team so they can give you an accurate answer! 💬"
            )

        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT.format(context=context)},
        ]
        # Include recent history for conversational continuity
        for msg in history[-4:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})

        response = await self._openai.chat.completions.create(
            model="gpt-4o",
            temperature=0.2,
            messages=messages,
        )

        return response.choices[0].message.content or (
            "Sorry, I wasn't able to generate a response. "
            "Please try rephrasing your question!"
        )
