"""Ingest knowledge-base documents into Pinecone for RAG retrieval.

Supports two document formats:

*   ``.kb`` — structured chunks with rich metadata (KB_ID, TYPE, TITLE, TAGS,
    SOURCE, VERSION, PARENT_ID).  Preferred format.
*   ``.md`` — plain markdown files chunked automatically at ~500 tokens with
    50-token overlap (legacy fallback).

Run as a standalone script::

    python -m knowledge_base.ingest
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

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

# ---------------------------------------------------------------------------
# Structured .kb parser
# ---------------------------------------------------------------------------

_CHUNK_DELIMITER = "--- KB_CHUNK_END ---"


def _parse_kb_file(text: str) -> List[Dict[str, str]]:
    """Parse a structured ``.kb`` file into a list of chunk dicts.

    Each chunk dict contains keys: kb_id, type, title, tags, source, version,
    parent_id, text.
    """
    raw_chunks = text.split(_CHUNK_DELIMITER)
    parsed: List[Dict[str, str]] = []

    for raw in raw_chunks:
        raw = raw.strip()
        if not raw:
            continue

        chunk: Dict[str, str] = {}
        # Extract header fields (KEY: value)
        field_pattern = re.compile(
            r"^(KB_ID|TYPE|TITLE|TAGS|SOURCE|VERSION|PARENT_ID):\s*(.+)$",
            re.MULTILINE,
        )
        for match in field_pattern.finditer(raw):
            key = match.group(1).lower()
            chunk[key] = match.group(2).strip()

        # Extract TEXT: block — everything after "TEXT:\n"
        text_match = re.search(r"^TEXT:\s*\n(.*)", raw, re.DOTALL | re.MULTILINE)
        if text_match:
            chunk["text"] = text_match.group(1).strip()

        # Only include if we have at least kb_id and text
        if chunk.get("kb_id") and chunk.get("text"):
            parsed.append(chunk)

    return parsed


# ---------------------------------------------------------------------------
# Legacy .md chunker
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def _stable_id(source: str, index: int) -> str:
    """Generate a deterministic vector ID for a legacy markdown chunk."""
    return hashlib.sha256(f"{source}::{index}".encode()).hexdigest()[:16]


def _kb_vector_id(kb_id: str) -> str:
    """Generate a deterministic vector ID from a structured KB_ID.

    Uses the KB_ID directly (truncated hash) so the same KB_ID always maps to
    the same vector — enabling **upsert-overwrites** on re-ingestion.
    """
    return hashlib.sha256(kb_id.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Ingestion pipeline
# ---------------------------------------------------------------------------


def _prepare_kb_vectors(
    client: openai.OpenAI, filepath: Path
) -> List[Tuple[str, List[float], Dict[str, Any]]]:
    """Prepare vectors from a structured .kb file."""
    text = filepath.read_text(encoding="utf-8")
    chunks = _parse_kb_file(text)
    logger.info("📄 %s — %d structured chunks", filepath.name, len(chunks))

    if not chunks:
        return []

    # Embed: prepend title + tags to text for richer embeddings
    embed_texts = []
    for c in chunks:
        title = c.get("title", "")
        tags = c.get("tags", "")
        body = c.get("text", "")
        embed_texts.append(f"{title}. {tags}. {body}")

    embeddings = _embed_batch(client, embed_texts)

    vectors: List[Tuple[str, List[float], Dict[str, Any]]] = []
    for chunk, embedding in zip(chunks, embeddings):
        vec_id = _kb_vector_id(chunk["kb_id"])
        metadata: Dict[str, Any] = {
            "text": chunk["text"],
            "kb_id": chunk["kb_id"],
            "type": chunk.get("type", ""),
            "title": chunk.get("title", ""),
            "tags": chunk.get("tags", ""),
            "source": chunk.get("source", filepath.name),
            "version": chunk.get("version", ""),
            "parent_id": chunk.get("parent_id", "none"),
        }
        vectors.append((vec_id, embedding, metadata))

    return vectors


def _prepare_md_vectors(
    client: openai.OpenAI, filepath: Path
) -> List[Tuple[str, List[float], Dict[str, Any]]]:
    """Prepare vectors from a legacy .md file (auto-chunked)."""
    text = filepath.read_text(encoding="utf-8")
    chunks = _chunk_text(text)
    source = filepath.name
    logger.info("📄 %s — %d auto-chunks (legacy)", source, len(chunks))

    if not chunks:
        return []

    embeddings = _embed_batch(client, chunks)

    vectors: List[Tuple[str, List[float], Dict[str, Any]]] = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        vec_id = _stable_id(source, i)
        metadata: Dict[str, Any] = {
            "text": chunk,
            "source": source,
            "chunk_index": i,
            "type": "",
            "title": "",
            "tags": "",
            "kb_id": "",
            "version": "",
            "parent_id": "none",
        }
        vectors.append((vec_id, embedding, metadata))

    return vectors


def ingest() -> None:
    """Run the full ingestion pipeline: read → chunk → embed → upsert."""
    if not OPENAI_API_KEY or not PINECONE_API_KEY:
        logger.error("OPENAI_API_KEY and PINECONE_API_KEY must be set.")
        sys.exit(1)

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX)

    # Prefer .kb files; fall back to .md if no .kb equivalent exists
    kb_files = sorted(DOCUMENTS_DIR.glob("*.kb"))
    md_files = sorted(DOCUMENTS_DIR.glob("*.md"))

    # Build set of basenames that have a .kb version
    kb_basenames = {f.stem for f in kb_files}

    all_vectors: List[Tuple[str, List[float], Dict[str, Any]]] = []

    # Process structured .kb files first
    for filepath in kb_files:
        all_vectors.extend(_prepare_kb_vectors(client, filepath))

    # Process .md files only if there is no .kb equivalent
    for filepath in md_files:
        if filepath.stem in kb_basenames:
            logger.info("⏭️  %s — skipping (structured .kb version exists)", filepath.name)
            continue
        all_vectors.extend(_prepare_md_vectors(client, filepath))

    if not all_vectors:
        logger.warning("No documents found in %s", DOCUMENTS_DIR)
        return

    # Upsert in batches of 100
    # Pinecone upsert is idempotent — same vector ID overwrites the old record.
    batch_size = 100
    for i in range(0, len(all_vectors), batch_size):
        batch = all_vectors[i : i + batch_size]
        vectors = [
            {"id": vid, "values": emb, "metadata": meta}
            for vid, emb, meta in batch
        ]
        index.upsert(vectors=vectors, namespace=NS_FAQS)
        logger.info("Upserted batch %d–%d", i, i + len(batch))

    logger.info(
        "✅ Ingestion complete — %d vectors upserted to '%s'",
        len(all_vectors),
        NS_FAQS,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ingest()
