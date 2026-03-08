"""Product Agent — answers product queries using the Pinecone product index.

Searches the NS_PRODUCTS namespace for matching products and returns
availability, pricing and sizing information.  When a product is out of
stock it suggests alternatives.
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
NS_PRODUCTS: str = "products"

_SYSTEM_PROMPT = """\
You are the Jaded Rose product advisor — stylish, knowledgeable, friendly.
You help customers find products from the Jaded Rose catalogue.

Use ONLY the product data provided below.  Never invent products.

PRODUCT DATA:
{products}

GUIDELINES:
- State the product name, price, and availability clearly.
- If a specific size is asked about, check the variants.
- If the product is out of stock, suggest similar alternatives from the data.
- Include the product URL when available so the customer can view it.
- Keep replies concise — 2-4 sentences unless more detail is needed.
- Use a warm, on-brand tone.  Light emoji usage is fine.
"""


class ProductAgent:
    """Specialist agent for product queries, availability and recommendations."""

    def __init__(self) -> None:
        """Initialise the product agent."""
        self._openai = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        pc = Pinecone(api_key=PINECONE_API_KEY)
        self._index = pc.Index(PINECONE_INDEX)

    async def _embed(self, text: str) -> List[float]:
        """Generate an embedding for search.

        Args:
            text: The query text.

        Returns:
            Embedding vector as a list of floats.
        """
        response = await self._openai.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding

    async def _search_products(self, query: str, top_k: int = 5) -> str:
        """Search Pinecone for matching products.

        Args:
            query: The customer's product query.
            top_k: Maximum number of results.

        Returns:
            Formatted product data string for the LLM context.
        """
        embedding = await self._embed(query)
        results = self._index.query(
            vector=embedding,
            top_k=top_k,
            namespace=NS_PRODUCTS,
            include_metadata=True,
        )

        products: list[str] = []
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            score = match.get("score", 0)
            if score < 0.3:
                continue

            title = meta.get("title", "Unknown")
            price = meta.get("price", "N/A")
            in_stock = meta.get("in_stock", False)
            url = meta.get("url", "")
            text = meta.get("text", "")

            stock_str = "In stock ✅" if in_stock else "Out of stock ❌"
            entry = f"• {title} — £{price} — {stock_str}"
            if url:
                entry += f"\n  Link: {url}"
            if text:
                entry += f"\n  Details: {text[:200]}"
            products.append(entry)

        return "\n\n".join(products) if products else ""

    async def handle(self, message: str, history: List[Dict[str, str]]) -> str:
        """Handle a product query.

        Args:
            message: The customer's message.
            history: Recent conversation history.

        Returns:
            A response with product details, availability, or suggestions.
        """
        product_data = await self._search_products(message)

        if not product_data:
            return (
                "I couldn't find any matching products in our catalogue. 🤔\n\n"
                "Could you try describing what you're looking for in a different way? "
                "For example: \"black midi dress\" or \"oversized hoodie in size M\"."
            )

        system_prompt = _SYSTEM_PROMPT.format(products=product_data)

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in history[-4:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        response = await self._openai.chat.completions.create(
            model="gpt-4o",
            temperature=0.3,
            messages=messages,
        )

        return response.choices[0].message.content or (
            "I found some products but had trouble formatting the details. "
            "Try asking again or browse our site at jadedrose.com! ✨"
        )
