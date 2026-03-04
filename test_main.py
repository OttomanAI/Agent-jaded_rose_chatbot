"""Tests for the three bug fixes in JadedRoseBot._handle_message."""

from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import Settings
from main import JadedRoseBot


def _make_settings(tmp_path: Path) -> Settings:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "system_message.txt").write_text("You are a helpful assistant.")
    (prompts / "input_guardrail.txt").write_text("Classify: ALLOWED or BLOCKED")
    return Settings(
        openai_api_key="test-key",
        telegram_bot_token="test-token",
        pinecone_api_key="test-pinecone",
        pinecone_index_name="test-index",
        pinecone_namespace="test-ns",
        base_dir=tmp_path,
    )


def _make_bot(tmp_path: Path) -> JadedRoseBot:
    bot = JadedRoseBot(settings=_make_settings(tmp_path))
    bot._client = MagicMock()
    bot._index = MagicMock()
    bot._blocklist = MagicMock()
    bot._blocklist.is_blocked.return_value = False
    return bot


def _openai_response(content: str | None):
    """Build a mock OpenAI chat completion response."""
    msg = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=msg)
    return types.SimpleNamespace(choices=[choice])


# ---------------------------------------------------------------------------
# Bug 1: "from" field (was "sender")
# ---------------------------------------------------------------------------

@patch("main.telegram_send_message")
@patch("main.telegram_send_typing")
def test_sender_field_uses_from(mock_typing, mock_send, tmp_path):
    """The bot should read msg['from'] for the sender, not msg['sender']."""
    bot = _make_bot(tmp_path)

    # Guardrail returns ALLOWED, chat returns an answer
    bot._client.chat.completions.create.side_effect = [
        _openai_response("ALLOWED"),
        _openai_response("Hello!"),
    ]

    msg = {
        "text": "Hi there",
        "chat": {"id": 123},
        "from": {"first_name": "Alice"},
    }

    with patch("main.query_chunks", return_value=[]):
        bot._handle_message(msg)

    # The reply should have been sent (proves no crash)
    mock_send.assert_called_once_with(text="Hello!", chat_id=123)


# ---------------------------------------------------------------------------
# Bug 2: None content guard
# ---------------------------------------------------------------------------

@patch("main.telegram_send_message")
@patch("main.telegram_send_typing")
def test_guardrail_none_content_defaults_to_blocked(mock_typing, mock_send, tmp_path):
    """If the guardrail model returns content=None, treat as BLOCKED."""
    bot = _make_bot(tmp_path)

    bot._client.chat.completions.create.return_value = _openai_response(None)

    msg = {
        "text": "Tell me a joke",
        "chat": {"id": 456},
        "from": {"first_name": "Bob"},
    }

    bot._handle_message(msg)

    # Should get the guardrail-blocked response, NOT crash with AttributeError
    mock_send.assert_called_once_with(
        text="I'm sorry, I can only help with Jaded Rose customer service enquiries.",
        chat_id=456,
    )


@patch("main.telegram_send_message")
@patch("main.telegram_send_typing")
def test_chat_none_content_returns_empty_string(mock_typing, mock_send, tmp_path):
    """If the chat model returns content=None, return '' instead of crashing."""
    bot = _make_bot(tmp_path)

    bot._client.chat.completions.create.side_effect = [
        _openai_response("ALLOWED"),
        _openai_response(None),  # chat model returns None
    ]

    msg = {
        "text": "What are your products?",
        "chat": {"id": 789},
        "from": {"first_name": "Carol"},
    }

    with patch("main.query_chunks", return_value=[]):
        bot._handle_message(msg)

    mock_send.assert_called_once_with(text="", chat_id=789)


# ---------------------------------------------------------------------------
# Bug 3: Memory not saved for blocked/rejected users
# ---------------------------------------------------------------------------

@patch("main.telegram_send_message")
@patch("main.telegram_send_typing")
def test_memory_not_saved_when_user_is_blocked(mock_typing, mock_send, tmp_path):
    """Blocked users' messages should NOT be persisted to memory."""
    bot = _make_bot(tmp_path)
    bot._blocklist.is_blocked.return_value = True

    msg = {
        "text": "Let me in",
        "chat": {"id": 100},
        "from": {"first_name": "Eve"},
    }

    bot._handle_message(msg)

    memory_file = tmp_path / "data" / "memory_100.json"
    if memory_file.exists():
        data = json.loads(memory_file.read_text())
        assert data == [], "Memory file should be empty for blocked users"


@patch("main.telegram_send_message")
@patch("main.telegram_send_typing")
def test_memory_not_saved_when_guardrail_blocks(mock_typing, mock_send, tmp_path):
    """Guardrail-rejected messages should NOT be persisted to memory."""
    bot = _make_bot(tmp_path)

    bot._client.chat.completions.create.return_value = _openai_response("BLOCKED")

    msg = {
        "text": "What is the meaning of life?",
        "chat": {"id": 200},
        "from": {"first_name": "Mallory"},
    }

    bot._handle_message(msg)

    memory_file = tmp_path / "data" / "memory_200.json"
    if memory_file.exists():
        data = json.loads(memory_file.read_text())
        assert data == [], "Memory file should be empty for guardrail-blocked messages"


@patch("main.telegram_send_message")
@patch("main.telegram_send_typing")
def test_memory_saved_for_allowed_messages(mock_typing, mock_send, tmp_path):
    """Allowed messages SHOULD be saved to memory."""
    bot = _make_bot(tmp_path)

    bot._client.chat.completions.create.side_effect = [
        _openai_response("ALLOWED"),
        _openai_response("We have rings and necklaces!"),
    ]

    msg = {
        "text": "What products do you sell?",
        "chat": {"id": 300},
        "from": {"first_name": "Grace"},
    }

    with patch("main.query_chunks", return_value=[]):
        bot._handle_message(msg)

    memory_file = tmp_path / "data" / "memory_300.json"
    assert memory_file.exists(), "Memory file should exist for allowed messages"
    data = json.loads(memory_file.read_text())
    assert len(data) == 2
    assert data[0]["role"] == "user"
    assert data[0]["content"] == "What products do you sell?"
    assert data[1]["role"] == "assistant"
    assert data[1]["content"] == "We have rings and necklaces!"
