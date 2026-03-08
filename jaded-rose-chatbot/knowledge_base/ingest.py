"""Ingest markdown documents into Pinecone for RAG retrieval.

Reads every ``.md`` file in ``knowledge_base/documents/``, chunks the text
at ~500 tokens with 50-token overlap, embeds each chunk with OpenAI
``text-embedding-3-small``, and upserts into the ``faqs`` namespace.

Run as a standalone script::

    python -m knowledge_base.ingest
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import List, Tuple

import openai
from pinecone import Pinecone

logger = logging.getLogger(__name__)

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
PINECONE_API_KEY: str = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX: str = os.getenv("PINECONE_INDEX", "jaded-rose")
NS_FAQS: str = "faqs"

DOCUMENTS_DIR = Path(__file__).parent / "documents"
CHUNK_SIZE = 500       # approximate tokens (using ~4 chars/token heuristic)
CHUNK_OVERLAP = 50     # overlap in tokens
CHARS_PER_TOKEN = 4    # rough estimate for English text


def _chunk_text(text: str) -> List[str]:
    """Split text into overlapping chunks of approximately CHUNK_SIZE tokens.

    Args:
        text: The full document text.

    Returns:
        A list of text chunks.
    """
    chunk_chars = CHUNK_SIZE * CHARS_PER_TOKEN
    overlap_chars = CHUNK_OVERLAP * CHARS_PER_TOKEN

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_chars
        chunk = text[start:end]

        # Try to break at a paragraph or sentence boundary
        if end < len(text):
            last_para = chunk.rfind("\n\n")
            if last_para > overlap_chars:
                end = start + last_para
                chunk = text[start:end]

        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap_chars
        if start < 0:
            start = 0

    return chunks


def _embed_batch(client: openai.OpenAI, texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts with OpenAI.

    Args:
        client: An OpenAI client.
        texts: A list of strings to embed.

    Returns:
        A list of embedding vectors.
    """
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]


def _stable_id(source: str, index: int) -> str:
    """Generate a deterministic vector ID for a chunk.

    Args:
        source: The source filename.
        index: The chunk index within the file.

    Returns:
        A hex digest string.
    """
    return hashlib.sha256(f"{source}::{index}".encode()).hexdigest()[:16]


def ingest() -> None:
    """Run the full ingestion pipeline: read → chunk → embed → upsert."""
    if not OPENAI_API_KEY or not PINECONE_API_KEY:
        logger.error("OPENAI_API_KEY and PINECONE_API_KEY must be set.")
        sys.exit(1)

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX)

    md_files = sorted(DOCUMENTS_DIR.glob("*.md"))
    if not md_files:
        logger.warning("No .md files found in %s", DOCUMENTS_DIR)
        return

    all_vectors: List[Tuple[str, List[float], dict]] = []

    for filepath in md_files:
        source = filepath.name
        text = filepath.read_text(encoding="utf-8")
        chunks = _chunk_text(text)
        logger.info("📄 %s — %d chunks", source, len(chunks))

        embeddings = _embed_batch(client, chunks)

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            vec_id = _stable_id(source, i)
            metadata = {
                "text": chunk,
                "source": source,
                "chunk_index": i,
            }
            all_vectors.append((vec_id, embedding, metadata))

    # Upsert in batches of 100
    batch_size = 100
    for i in range(0, len(all_vectors), batch_size):
        batch = all_vectors[i : i + batch_size]
        vectors = [
            {"id": vid, "values": emb, "metadata": meta}
            for vid, emb, meta in batch
        ]
        index.upsert(vectors=vectors, namespace=NS_FAQS)
        logger.info("Upserted batch %d–%d", i, i + len(batch))

    logger.info("✅ Ingestion complete — %d vectors upserted to '%s'", len(all_vectors), NS_FAQS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ingest()
