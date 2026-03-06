"""
Jaded Rose Telegram Chatbot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

RAG-powered customer service bot with input guardrails,
Pinecone vector search, and per-chat conversation memory.

    User prompt
         |
         v
    INPUT GUARDRAIL (OpenAI) -- fail --> rejection reply --> Telegram
         |
         | pass
         v
    OpenAI Embeddings --> Pinecone query --> matched chunks
         |                                       |
         v                                       v
    OpenAI Chat (system prompt + chunks + memory + user prompt)
         |
         v
    Save to memory --> Telegram reply
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import Any

from openai import OpenAI

from agent_tools import Blocklist, Memory
from agent_tools.pinecone import get_index, query_chunks
from comms.telegram import (
    telegram_send_message,
    telegram_send_typing,
    trigger as telegram_trigger,
)
from config import ConfigError, Settings

log = logging.getLogger("jaded-rose-bot")


class JadedRoseBot:
    """RAG chatbot that runs on Telegram with OpenAI + Pinecone.

    Parameters
    ----------
    settings:
        A fully-validated ``Settings`` instance.  When omitted the bot
        builds one from environment variables via ``Settings.from_env()``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._cfg = settings or Settings.from_env()

        self._system_message = (self._cfg.prompts_dir / "system_message.txt").read_text()
        self._guardrail_prompt = (self._cfg.prompts_dir / "input_guardrail.txt").read_text()

        self._running = False
        self._client: OpenAI | None = None
        self._index: Any = None
        self._blocklist: Blocklist | None = None
        self._last_update_id: int | None = None

    # -- lifecycle ------------------------------------------------------------

    def _connect(self) -> None:
        self._client = OpenAI(api_key=self._cfg.openai_api_key)
        self._index = get_index(
            index_name=self._cfg.pinecone_index_name,
            api_key=self._cfg.pinecone_api_key,
        )
        log.info("Pinecone index '%s' connected", self._cfg.pinecone_index_name)
        self._blocklist = Blocklist(
            path=self._cfg.data_dir / "blocklist.json",
            max_violations_per_day=self._cfg.max_violations_per_day,
        )

    def _shutdown(self, signum: int, frame: Any) -> None:
        log.info("Shutdown signal received — finishing current cycle")
        self._running = False

    # -- pipeline steps -------------------------------------------------------

    def _run_guardrail(self, prompt: str) -> str:
        """Return ``'ALLOWED'`` or ``'BLOCKED'``."""
        response = self._client.chat.completions.create(
            model=self._cfg.guardrail_model,
            messages=[
                {"role": "system", "content": self._guardrail_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip().upper()

    def _retrieve_context(self, prompt: str) -> list[dict]:
        return query_chunks(
            index=self._index,
            prompt=prompt,
            namespace=self._cfg.pinecone_namespace,
        )

    def _generate_answer(self, prompt: str, chunks: list[dict], memory: Memory) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_message},
            {"role": "system", "content": "Retrieved context:\n\n" + "\n\n".join(c["text"] for c in chunks)},
        ]
        for entry in memory.history:
            messages.append({"role": entry["role"], "content": entry["content"]})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self._cfg.chat_model,
            messages=messages,
        )
        return response.choices[0].message.content

    # -- typing indicator ------------------------------------------------------

    def _start_typing(self, chat_id: int) -> threading.Event:
        """Send typing action every 4s until the returned event is set."""
        stop = threading.Event()

        def _loop() -> None:
            while not stop.is_set():
                try:
                    telegram_send_typing(chat_id)
                except Exception:
                    pass
                stop.wait(4.0)

        threading.Thread(target=_loop, daemon=True).start()
        return stop

    # -- message handling -----------------------------------------------------

    def _handle_message(self, msg: dict) -> None:
        prompt = msg.get("text", "")
        if not prompt:
            return

        chat_id: int = msg["chat"]["id"]
        sender = msg.get("sender", {})
        log.info("Message from %s (chat %s): %s", sender.get("first_name", "?"), chat_id, prompt[:80])

        typing_stop = self._start_typing(chat_id)

        memory = Memory(
            path=self._cfg.data_dir / f"memory_{chat_id}.json",
            max_entries=self._cfg.max_memory_entries,
        )

        if self._blocklist.is_blocked(chat_id):
            answer = "Your access has been restricted. Please contact hello@jadedrose.co.uk for assistance."
        else:
            verdict = self._run_guardrail(prompt)
            log.info("Guardrail verdict: %s", verdict)

            if verdict == "BLOCKED":
                self._blocklist.record_violation(chat_id)
                answer = "I'm sorry, I can only help with Jaded Rose customer service enquiries."
            else:
                chunks = self._retrieve_context(prompt)
                log.info("Retrieved %d chunks (top score: %.3f)", len(chunks), chunks[0]["score"] if chunks else 0)
                answer = self._generate_answer(prompt, chunks, memory)

        typing_stop.set()

        memory.save("user", prompt)
        memory.save("assistant", answer)

        telegram_send_message(text=answer, chat_id=chat_id)
        log.info("Reply sent to chat %s", chat_id)

    # -- main loop ------------------------------------------------------------

    def run(self) -> None:
        """Connect to external services and start the Telegram polling loop."""
        log.info("Starting Jaded Rose bot  [guardrail=%s  chat=%s]", self._cfg.guardrail_model, self._cfg.chat_model)
        self._connect()

        self._running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        while self._running:
            log.info("Waiting for message (timeout %ds)…", self._cfg.poll_timeout_seconds)
            trigger_cfg: dict[str, Any] = {
                "bot_token": self._cfg.telegram_bot_token,
                "include_existing": False,
                "timeout_seconds": self._cfg.poll_timeout_seconds,
                "baseline_update_id": self._last_update_id,
            }
            # Pass offset so Telegram confirms/discards already-processed
            # updates server-side.  Without this the getUpdates buffer fills
            # up and new messages are silently dropped.
            if self._last_update_id is not None:
                trigger_cfg["offset"] = self._last_update_id + 1

            msg = telegram_trigger(trigger_cfg)

            if msg is None:
                continue

            self._last_update_id = msg.get("update_id", self._last_update_id)

            try:
                self._handle_message(msg)
            except Exception:
                log.exception("Error handling message")

        log.info("Bot stopped")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        bot = JadedRoseBot()
    except ConfigError as exc:
        log.critical("Configuration error: %s", exc)
        sys.exit(1)

    bot.run()


if __name__ == "__main__":
    main()
