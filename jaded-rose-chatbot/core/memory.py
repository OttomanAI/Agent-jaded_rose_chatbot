"""Conversation memory backed by Redis.

Stores the last N messages per session so the Supervisor and agents have
context when generating replies.  Each session expires after a configurable
TTL to keep Redis tidy.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_MESSAGES: int = 10
SESSION_TTL_SECONDS: int = 86400  # 24 hours


class ConversationMemory:
    """Per-session conversation memory stored in Redis lists.

    Each session is keyed as ``chat:{session_id}`` and contains up to
    ``MAX_MESSAGES`` serialised message dicts (``{role, content}``).
    """

    def __init__(self, redis_url: str | None = None) -> None:
        """Initialise the memory store.

        Args:
            redis_url: Redis connection string.  Falls back to the
                       ``REDIS_URL`` environment variable.
        """
        self._redis_url = redis_url or REDIS_URL
        self._pool: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        """Return a Redis connection, creating the pool lazily.

        Returns:
            An async Redis client.
        """
        if self._pool is None:
            self._pool = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
            )
        return self._pool

    def _key(self, session_id: str) -> str:
        """Build the Redis key for a given session.

        Args:
            session_id: Unique session identifier.

        Returns:
            The namespaced Redis key.
        """
        return f"chat:{session_id}"

    async def add_message(
        self, session_id: str, role: str, content: str
    ) -> None:
        """Append a message to the session history.

        Trims the list so that only the most recent ``MAX_MESSAGES``
        entries are kept, and resets the TTL.

        Args:
            session_id: Unique session identifier.
            role: ``"user"`` or ``"assistant"``.
            content: The message text.
        """
        r = await self._get_redis()
        key = self._key(session_id)
        payload = json.dumps({"role": role, "content": content})

        pipe = r.pipeline()
        pipe.rpush(key, payload)
        pipe.ltrim(key, -MAX_MESSAGES, -1)
        pipe.expire(key, SESSION_TTL_SECONDS)
        await pipe.execute()

        logger.debug("Memory add [%s] %s: %s", session_id, role, content[:80])

    async def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Retrieve the conversation history for a session.

        Args:
            session_id: Unique session identifier.

        Returns:
            A list of message dicts with ``role`` and ``content`` keys,
            ordered oldest → newest.
        """
        r = await self._get_redis()
        key = self._key(session_id)
        items = await r.lrange(key, 0, -1)
        history: List[Dict[str, str]] = []
        for raw in items:
            try:
                history.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("Corrupt memory entry in %s — skipping", key)
        return history

    async def clear(self, session_id: str) -> None:
        """Delete all messages for a session.

        Args:
            session_id: Unique session identifier.
        """
        r = await self._get_redis()
        await r.delete(self._key(session_id))
        logger.info("Memory cleared for session %s", session_id)
