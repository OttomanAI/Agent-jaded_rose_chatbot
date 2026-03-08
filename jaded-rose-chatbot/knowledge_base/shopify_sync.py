"""Sync the Shopify product catalogue into Pinecone for product search.

Fetches every product from the Shopify Admin API, builds a text
representation for each one, embeds it, and upserts into the
``products`` namespace in Pinecone.

Run as a standalone script::

    python -m knowledge_base.shopify_sync
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from typing import Any, Dict, List, Tuple

import httpx
import openai
from pinecone import Pinecone

logger = logging.getLogger(__name__)

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
PINECONE_API_KEY: str = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX: str = os.getenv("PINECONE_INDEX", "jaded-rose")
SHOPIFY_STORE_URL: str = os.getenv("SHOPIFY_STORE_URL", "")
SHOPIFY_ADMIN_API_KEY: str = os.getenv("SHOPIFY_ADMIN_API_KEY", "")
NS_PRODUCTS: str = "products"


def _product_to_text(product: Dict[str, Any]) -> str:
    """Convert a Shopify product dict into a searchable text block.

    Combines the title, description, tags and variant information so that
    semantic search can match on any of these fields.

    Args:
        product: A Shopify product dict.

    Returns:
        A plain-text representation of the product.
    """
    parts = [
        product.get("title", ""),
        product.get("body_html", "").replace("<br>", " ").replace("<br/>", " "),
        f"Tags: {product.get('tags', '')}",
        f"Product type: {product.get('product_type', '')}",
        f"Vendor: {product.get('vendor', '')}",
    ]

    variants = product.get("variants", [])
    if variants:
        variant_lines: list[str] = []
        for v in variants:
            size = v.get("title", "")
            price = v.get("price", "")
            available = "available" if v.get("inventory_quantity", 0) > 0 else "out of stock"
            variant_lines.append(f"  {size} — £{price} ({available})")
        parts.append("Variants:\n" + "\n".join(variant_lines))

    return "\n".join(parts)


def _product_metadata(product: Dict[str, Any]) -> Dict[str, Any]:
    """Extract Pinecone metadata fields from a Shopify product.

    Args:
        product: A Shopify product dict.

    Returns:
        A flat metadata dict suitable for Pinecone.
    """
    variants = product.get("variants", [])
    total_inventory = sum(v.get("inventory_quantity", 0) for v in variants)
    first_price = variants[0].get("price", "0") if variants else "0"
    handle = product.get("handle", "")
    store = SHOPIFY_STORE_URL.rstrip("/")
    url = f"{store}/products/{handle}" if handle else ""

    return {
        "product_id": str(product.get("id", "")),
        "title": product.get("title", ""),
        "price": first_price,
        "url": url,
        "in_stock": total_inventory > 0,
        "text": _product_to_text(product)[:1000],  # Pinecone metadata limit
    }


def _fetch_all_products() -> List[Dict[str, Any]]:
    """Fetch every product from the Shopify Admin API (paginated).

    Returns:
        A list of Shopify product dicts.
    """
    products: List[Dict[str, Any]] = []
    base_url = f"{SHOPIFY_STORE_URL.rstrip('/')}/admin/api/2024-01/products.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_ADMIN_API_KEY}
    params: dict = {"limit": 250}

    with httpx.Client(timeout=30) as client:
        url = base_url
        while url:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            products.extend(data.get("products", []))

            # Shopify pagination via Link header
            link_header = resp.headers.get("Link", "")
            url = ""
            params = {}
            if 'rel="next"' in link_header:
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        url = part.split("<")[1].split(">")[0]
                        break

    return products


def _stable_id(product_id: str) -> str:
    """Generate a deterministic vector ID for a product.

    Args:
        product_id: The Shopify product ID.

    Returns:
        A hex digest string.
    """
    return hashlib.sha256(f"product::{product_id}".encode()).hexdigest()[:16]


def sync() -> None:
    """Run the full Shopify → Pinecone product sync."""
    if not all([OPENAI_API_KEY, PINECONE_API_KEY, SHOPIFY_STORE_URL, SHOPIFY_ADMIN_API_KEY]):
        logger.error("Required environment variables are not all set.")
        sys.exit(1)

    oai = openai.OpenAI(api_key=OPENAI_API_KEY)
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX)

    logger.info("Fetching products from Shopify...")
    products = _fetch_all_products()
    logger.info("Fetched %d products.", len(products))

    all_vectors: List[Tuple[str, List[float], dict]] = []

    # Embed in batches of 50
    batch_size = 50
    for i in range(0, len(products), batch_size):
        batch = products[i : i + batch_size]
        texts = [_product_to_text(p) for p in batch]

        response = oai.embeddings.create(model="text-embedding-3-small", input=texts)
        embeddings = [item.embedding for item in response.data]

        for product, embedding in zip(batch, embeddings):
            pid = str(product.get("id", ""))
            vec_id = _stable_id(pid)
            metadata = _product_metadata(product)
            all_vectors.append((vec_id, embedding, metadata))

        logger.info("Embedded products %d–%d", i, i + len(batch))

    # Upsert in batches of 100
    upsert_batch = 100
    for i in range(0, len(all_vectors), upsert_batch):
        batch = all_vectors[i : i + upsert_batch]
        vectors = [
            {"id": vid, "values": emb, "metadata": meta}
            for vid, emb, meta in batch
        ]
        index.upsert(vectors=vectors, namespace=NS_PRODUCTS)

    logger.info(
        "✅ Sync complete — %d products upserted to '%s'",
        len(all_vectors),
        NS_PRODUCTS,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sync()
